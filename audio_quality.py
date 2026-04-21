"""
audio_quality.py
─────────────────────────────────────────────────────────────────────────────
음성 품질 측정 유틸리티 (MOS / PESQ / ViSQOL).

analyze_hybrid.py 에서 분리된 모듈.
"""
from __future__ import annotations

import os
import concurrent.futures

import numpy as np

from audio_lib.consts import SR

# ── 옵션 라이브러리 ────────────────────────────────────
try:
    from pesq import pesq as _pesq_fn
    _PESQ_AVAILABLE = True
except ImportError:
    _PESQ_AVAILABLE = False

try:
    import visqol_lib_py as _visqol
    _VISQOL_AVAILABLE = True
    _VISQOL_SPEECH_MODEL = os.path.join(
        os.path.dirname(__file__), 'visqol-3.3.3', 'model',
        'lattice_tcditugenmeetpackhref_ls2_nl60_lr12_bs2048_learn.005_ep2400_train1_7_raw.tflite'
    )
except ImportError:
    _VISQOL_AVAILABLE = False
    _VISQOL_SPEECH_MODEL = None


# ─────────────────────────────────────────────────────────────────────────────
# 신호 전처리
# ─────────────────────────────────────────────────────────────────────────────

def _snr_db(ref: np.ndarray, deg: np.ndarray) -> float:
    """정답지(ref) 대비 녹음(deg)의 SNR (dB).

    noise = deg - gain_matched_ref 방식.
    ref와 deg는 이미 시간 정렬(_align_signals)된 상태여야 합니다.
    """
    # 게인 매칭: ref를 deg 레벨에 맞춤 (전송 경로 게인 차이 제거)
    ref_pow = float(np.mean(ref ** 2))
    deg_pow = float(np.mean(deg ** 2))
    if ref_pow < 1e-18:
        return 99.0
    gain = np.sqrt(deg_pow / ref_pow)
    ref_scaled = ref * gain

    noise = deg - ref_scaled
    noise_pow = float(np.mean(noise ** 2))
    if noise_pow < 1e-18:
        return 99.0
    return float(10 * np.log10(deg_pow / noise_pow))


def _remove_dc(y: np.ndarray) -> np.ndarray:
    """Line In 녹음의 DC 오프셋 제거."""
    return (y - np.mean(y)).astype(np.float32)


def _normalize_level(y: np.ndarray, target_rms: float = 0.05012) -> np.ndarray:
    """RMS 레벨을 -26 dBov(ITU-T P.56)로 정규화. 묵음 파일은 그대로 반환."""
    rms = float(np.sqrt(np.mean(y ** 2)))
    if rms < 1e-9:
        return y
    return (y * (target_rms / rms)).astype(np.float32)


def _align_signals(ref: np.ndarray, deg: np.ndarray, sr: int) -> tuple:
    """Cross-correlation으로 VoIP 지연(최대 ±3초)을 보정 → (ref, deg, lag_ms)."""
    max_lag = int(sr * 3.0)
    win = min(len(ref), len(deg), sr * 10)
    r = np.correlate(
        deg[:win] - deg[:win].mean(),
        ref[:win] - ref[:win].mean(),
        mode='full',
    )
    lag = int(np.argmax(np.abs(r))) - (win - 1)
    lag = max(-max_lag, min(max_lag, lag))

    if lag > 0:
        deg = deg[lag:]
    elif lag < 0:
        ref = ref[-lag:]

    n = min(len(ref), len(deg))
    lag_ms = round(lag / sr * 1000, 1)
    return ref[:n].copy(), deg[:n].copy(), lag_ms


# ─────────────────────────────────────────────────────────────────────────────
# ViSQOL NSIM ↔ MOS 변환 (speech_similarity_to_quality_mapper.cc 기반)
# ─────────────────────────────────────────────────────────────────────────────
# ViSQOL 내부 매핑 함수:
#   MOS_raw = A + exp(B * (NSIM - X0))          (ExponentialFromFit)
#   MOS     = clamp(MOS_raw * scale, 1, 5)       (scale=1.245063 if scale_to_max_mos)
#
# 역함수 (NSIM → from MOS):
#   NSIM = X0 + ln(MOS/scale - A) / B
#
# 이 값이 '지각 선형 공간'에서의 평균 대상.
# MOS-LQO 직접 산술평균은 비선형 지각 도메인 왜곡 발생.

_VISQOL_A      = -262.847869
_VISQOL_B      =    0.0154302525
_VISQOL_X0     = -361.063949
_VISQOL_SCALE  =    1.245063   # scale_to_max_mos=True 시 적용 (Python API 기본값)


def visqol_mos_to_nsim(mos: float, scaled: bool = True) -> float:
    """ViSQOL MOS-LQO → 내부 NSIM 역산.

    scaled=True: Python API (Init(..., scale_to_max_mos=True)) 기본값.
    역산 불가능(MOS ≤ A*scale)이면 0.0 반환.
    """
    import math
    mos_unscaled = mos / _VISQOL_SCALE if scaled else mos
    inner = mos_unscaled - _VISQOL_A
    if inner <= 0:
        return 0.0
    return _VISQOL_X0 + math.log(inner) / _VISQOL_B


def visqol_nsim_to_mos(nsim: float, scaled: bool = True) -> float:
    """ViSQOL 내부 NSIM → MOS-LQO 순방향 변환."""
    import math
    mos_raw = _VISQOL_A + math.exp(_VISQOL_B * (nsim - _VISQOL_X0))
    if scaled:
        mos_raw *= _VISQOL_SCALE
    return float(min(max(mos_raw, 1.0), 5.0))


def visqol_mos_mean(mos_scores: list[float], scaled: bool = True) -> float:
    """ViSQOL MOS-LQO 점수 리스트 → NSIM 공간에서 평균 후 MOS 재변환.

    단순 산술평균(직접 평균) 대신 비선형 도메인 왜곡을 방지하기 위해
    NSIM 선형 공간으로 역산 → 평균 → 다시 MOS 변환.
    """
    if not mos_scores:
        return 0.0
    nsim_values = [visqol_mos_to_nsim(m, scaled) for m in mos_scores]
    nsim_mean = sum(nsim_values) / len(nsim_values)
    return round(visqol_nsim_to_mos(nsim_mean, scaled), 3)


# ─────────────────────────────────────────────────────────────────────────────
# MOS 계산
# ─────────────────────────────────────────────────────────────────────────────

def compute_mos_pesq(
    ref_y: np.ndarray,
    ios_y: np.ndarray,
    and_y: np.ndarray,
    ref_android_y: np.ndarray | None = None,
    sr: int = SR,
) -> dict:
    """정답지(ref) 기준 Android/iOS 각각의 ViSQOL MOS-LQO 계산.

    ref_y          : iOS 수신 녹음용 정답지 (S1 재생 음원)
    ref_android_y  : Android 수신 녹음용 정답지 (S2 재생 음원). None이면 ref_y와 동일.
    ios_y          : iOS 수신 녹음
    and_y          : Android 수신 녹음
    """
    if ref_android_y is None or len(ref_android_y) == 0:
        ref_android_y = ref_y
    result: dict = {
        'android_visqol_mos': None,
        'ios_visqol_mos':     None,
        'ios_snr_db':         None,
        'android_snr_db':     None,
        'ios_rms_mean':       None,
        'android_rms_mean':   None,
        'android_lag_ms':     None,
        'ios_lag_ms':         None,
        'lag_ms':             None,   # 하위 호환 (Android lag 대표값)
        'visqol_error':       None,
    }

    _has_ios = len(ios_y) > 0
    _has_and = len(and_y) > 0

    try:
        if _has_ios:
            result['ios_rms_mean']     = round(float(np.sqrt(np.mean(ios_y ** 2))), 5)
        if _has_and:
            result['android_rms_mean'] = round(float(np.sqrt(np.mean(and_y ** 2))), 5)
    except Exception as e:
        result['visqol_error'] = f'신호 통계 계산 실패: {e}'

    if len(ref_y) == 0 and len(ref_android_y) == 0:
        result['visqol_error'] = '정답지 오디오 비어 있음'
        return result

    ref_dc = _remove_dc(ref_y) if len(ref_y) > 0 else np.zeros(0, dtype=np.float32)
    ref_android_dc = _remove_dc(ref_android_y) if len(ref_android_y) > 0 else ref_dc

    # 정답지 ↔ Android 정렬 + 정규화 (S2 정답지 사용)
    and_ref_norm = and_norm = None
    if _has_and:
        try:
            r, d, lag = _align_signals(ref_android_dc.copy(), _remove_dc(and_y), sr)
            result['android_lag_ms'] = lag
            result['lag_ms'] = lag          # 하위 호환
            result['android_snr_db'] = round(_snr_db(r, d), 1)
            and_ref_norm = _normalize_level(r)
            and_norm     = _normalize_level(d)
        except Exception as e:
            result['visqol_error'] = f'Android 전처리 실패: {e}'

    # 정답지 ↔ iOS 정렬 + 정규화 (S1 정답지 사용)
    ios_ref_norm = ios_norm = None
    if _has_ios:
        try:
            r, d, lag = _align_signals(ref_dc.copy(), _remove_dc(ios_y), sr)
            result['ios_lag_ms'] = lag
            if result['lag_ms'] is None:
                result['lag_ms'] = lag
            result['ios_snr_db'] = round(_snr_db(r, d), 1)
            ios_ref_norm = _normalize_level(r)
            ios_norm     = _normalize_level(d)
        except Exception as e:
            result['visqol_error'] = f'iOS 전처리 실패: {e}'

    if not _VISQOL_AVAILABLE:
        result['visqol_error'] = 'visqol_lib_py 없음'
    elif not os.path.isfile(_VISQOL_SPEECH_MODEL):
        result['visqol_error'] = f'모델 파일 없음: {_VISQOL_SPEECH_MODEL}'
    else:
        try:
            import tempfile
            import soundfile as _sf

            def _run_visqol(ref_path: str, deg_path: str) -> float:
                """독립 VisqolManager 인스턴스로 실행 (스레드 안전)."""
                m = _visqol.VisqolManager()
                m.Init(_visqol.FilePath(_VISQOL_SPEECH_MODEL), True, False, 60, True)
                vr = m.Run(_visqol.FilePath(ref_path), _visqol.FilePath(deg_path))
                return round(float(vr.moslqo), 3)

            # 임시 wav 파일 생성 (각각 정답지 정렬본 + 열화본)
            _tmp_files = []

            def _write_tmp(y, tag):
                p = tempfile.mktemp(suffix=f'_{tag}.wav')
                _sf.write(p, y, sr)
                _tmp_files.append(p)
                return p

            futures = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _pool:
                if and_ref_norm is not None and and_norm is not None:
                    ref_f = _write_tmp(and_ref_norm, 'ref_and')
                    deg_f = _write_tmp(and_norm, 'and')
                    futures['android'] = _pool.submit(_run_visqol, ref_f, deg_f)
                if ios_ref_norm is not None and ios_norm is not None:
                    ref_f = _write_tmp(ios_ref_norm, 'ref_ios')
                    deg_f = _write_tmp(ios_norm, 'ios')
                    futures['ios'] = _pool.submit(_run_visqol, ref_f, deg_f)

                if 'android' in futures:
                    result['android_visqol_mos'] = futures['android'].result()
                if 'ios' in futures:
                    result['ios_visqol_mos'] = futures['ios'].result()

            for _p in _tmp_files:
                try:
                    os.unlink(_p)
                except OSError:
                    pass
        except Exception as e:
            result['visqol_error'] = f'ViSQOL 계산 실패: {e}'

    return result


# ─────────────────────────────────────────────────────────────────────────────
# HTML 생성 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _mos_grade(mos: float) -> tuple[str, str]:
    """MOS 점수 → (등급 라벨, CSS 클래스).

    ITU-T P.800 표준 + VoIP 실무 통합 6단계:
      4.3+ 우수(Excellent)  | 4.0~4.3 좋음(Good)   | 3.6~4.0 양호(Fair~Good)
      3.0~3.6 보통(Fair)     | 2.5~3.0 미흡(Poor)    | <2.5 불량(Bad)
    """
    if mos >= 4.3:
        return ('우수',  'mos-grade-ex')
    elif mos >= 4.0:
        return ('좋음',  'mos-grade-good')
    elif mos >= 3.6:
        return ('양호',  'mos-grade-fair')
    elif mos >= 3.0:
        return ('보통',  'mos-grade-avg')
    elif mos >= 2.5:
        return ('미흡',  'mos-grade-poor')
    else:
        return ('불량',  'mos-grade-bad')


def build_mos_html(mos_rows: list) -> str:
    """MOS 측정 결과 HTML 섹션 생성. mos_rows: [(label, mos_result_dict), ...]"""
    if not mos_rows:
        return ''

    rows_html = ''
    for label, m in mos_rows:
        ios_snr   = f"{m.get('ios_snr_db', '—')} dB"     if m.get('ios_snr_db')  is not None else '—'
        and_snr   = f"{m.get('android_snr_db', '—')} dB" if m.get('android_snr_db') is not None else '—'
        ios_rms   = f"{m.get('ios_rms_mean', '—'):.5f}"    if m.get('ios_rms_mean')  is not None else '—'
        and_rms   = f"{m.get('android_rms_mean', '—'):.5f}" if m.get('android_rms_mean') is not None else '—'
        lag_ms    = m.get('lag_ms')
        lag_label = (
            f'<span title="VoIP 수신 지연 보정량" style="font-size:.78em;color:#8b949e">'
            f'⏱ 정렬 {lag_ms:+.0f} ms</span>'
            if lag_ms is not None else ''
        )

        vmos_and = m.get('android_visqol_mos')
        if vmos_and is not None:
            vgrade_a, vgcls_a = _mos_grade(vmos_and)
            vbar_a = max(0, min(100, int((vmos_and - 1.0) / 3.5 * 100)))
            visqol_and_cell = f"""
              <td>
                <div class="mos-bar-wrap">
                  <div class="mos-bar mos-bar-visqol" style="width:{vbar_a}%"></div>
                </div>
                <span class="mos-score">{vmos_and:.3f}</span>
                <span class="mos-grade {vgcls_a}">{vgrade_a}</span>
                <br>{lag_label}
              </td>"""
        else:
            verr = m.get('visqol_error', '계산 불가')
            visqol_and_cell = f'<td><span style="color:#ff5252;font-size:.82em">⚠️ {verr}</span></td>'

        vmos_ios = m.get('ios_visqol_mos')
        if vmos_ios is not None:
            vgrade_i, vgcls_i = _mos_grade(vmos_ios)
            vbar_i = max(0, min(100, int((vmos_ios - 1.0) / 3.5 * 100)))
            visqol_ios_cell = f"""
              <td>
                <div class="mos-bar-wrap">
                  <div class="mos-bar mos-bar-visqol-ios" style="width:{vbar_i}%"></div>
                </div>
                <span class="mos-score">{vmos_ios:.3f}</span>
                <span class="mos-grade {vgcls_i}">{vgrade_i}</span>
              </td>"""
        elif m.get('visqol_error'):
            visqol_ios_cell = (
                f'<td><span style="color:#ff5252;font-size:.82em">'
                f'⚠️ {m["visqol_error"]}</span></td>'
            )
        else:
            visqol_ios_cell = '<td>—</td>'

        rows_html += f"""
        <tr>
          <td class="mos-label">{label}</td>
          <td>
            <span class="mos-os-badge ios-badge">iOS</span>
            SNR {ios_snr} &nbsp;·&nbsp; RMS {ios_rms}
          </td>
          <td>
            <span class="mos-os-badge and-badge">Android</span>
            SNR {and_snr} &nbsp;·&nbsp; RMS {and_rms}
          </td>
          {visqol_ios_cell}
          {visqol_and_cell}
        </tr>"""

    return f"""
<div class="mos-section">
  <h3>📊 MOS 음질 측정 결과
    <span class="mos-method">ViSQOL v3 — 정답지 TTS 기준 Android/iOS 개별 음질 측정</span>
  </h3>
  <table class="mos-table">
    <thead>
      <tr>
        <th>음원</th>
        <th>iOS 수신 신호품질</th>
        <th>Android 수신 신호품질</th>
        <th><span class="mos-os-badge ios-badge" style="margin-right:4px">iOS</span>\
ViSQOL MOS-LQO <span class="mos-range">(1.0~4.5)</span></th>
        <th><span class="mos-os-badge and-badge" style="margin-right:4px">Android</span>\
ViSQOL MOS-LQO <span class="mos-range">(1.0~4.5)</span></th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p class="mos-note">
    ⓘ &nbsp;ViSQOL v3: Google 음성 전용 딥러닝 MOS 측정 (lattice TFLite speech model)
    &nbsp;|&nbsp; reference = 정답지 TTS 원본
    &nbsp;|&nbsp; degraded = VoIP 수신 녹음 (iOS / Android 각각)
  </p>
</div>"""
