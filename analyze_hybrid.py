#!/usr/bin/env python3
"""
하이브리드 음단절 분석 — 진입점 (main)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
역할 분담:
  Gemini  : 두 음원을 사람처럼 직접 듣고 → 어느 타임스탬프에서 무슨 음절이
            iOS엔 있고 Android엔 없는지 스스로 판단 (Primary Judge)
  librosa : Gemini가 지목한 타임스탬프 주변 파형/에너지를 시각화 (Visualizer)

모듈 구조:
  _hybrid_config.py  — 공유 상수 (경로, TEST_ENV 등)
  app_scanner.py     — 녹음 파일 탐지, API 키 로드, 앱 버전 조회
  audio_quality.py   — MOS/PESQ/ViSQOL 측정
  audio_plots.py     — 파형 시각화, 오디오 클립 생성, 에너지 힌트
  gemini_analysis.py — Gemini API 분석 로직, 프롬프트, JSON 파싱
  html_report.py     — HTML 보고서 생성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import sys
import time

import numpy as np

from audio_lib.io  import load_audio
from audio_lib.dsp import compute_rms

from _hybrid_config  import TEST_ENV, OUTPUT_HTML, VISHING_REF_PATH, VISHING_REF_IOS, VISHING_REF_ANDROID
from app_scanner     import CALLS, get_app_versions, get_device_info
from audio_quality   import compute_mos_pesq, _mos_grade, visqol_mos_mean
from audio_plots     import (
    compute_signal_hints, top_suspicious_windows,
    ms_label, plot_comparison, plot_comparison_android_only, build_marker_list,
    plot_per_platform,
)
from html_report         import build_html, dropout_card_html, sev_class
from script_gap_detector import analyze_by_script, parse_script

def _sev_from_rate(count: int, rate: float) -> str:
    """드롭 건수/비율 → 심각도."""
    if count == 0:
        return "없음"
    if rate < 10:
        return "경미"
    if rate < 30:
        return "보통"
    return "심각"

# ── 테스트 대본 ───────────────────────────────────────────────────────────────
# script_gap_detector.py 의 load_script_reference() 가 이 파일을 regex로 파싱.
# 이 상수는 반드시 이 파일에 유지해야 함.
SCRIPT_REFERENCE = """
=== 테스트 음원 대본 (Ground Truth 참고자료) ===

【음원 1 화자: 박편육(가해자1, 수사관 사칭) + 임채팅(가해자2, 검사 사칭)】

[박편육]
안녕하십니까, 서울중앙지검 첨단범죄수사 1팀의 박편육 수사관입니다.
본인 성함이 김버그 씨 맞으시죠?

[박편육]
다름이 아니라, 최근 저희가 검거한 금융사기단 주범 '최에러' 일당의
소지품에서 귀하의 명의로 개설된 농협, 신한은행 통장 두 개가 발견되었습니다.
본인이 직접 개설하신 적 있습니까?

[박편육]
본인이 안 하셨다면 명의 도용으로 인한 피해자로 보입니다만,
현재 이 계좌들이 범죄 자금 세탁에 이용되어 피해액만 5억 원에 달합니다.
지금 본인이 공범이 아니라는 것을 입증하지 못하면 피의자 신분으로 전환되어
긴급 체포될 수 있는 중대한 상황입니다. 이해하셨습니까?

[박편육]
일단 사건의 엄중함을 고려해 담당 검사님께 연결해 드릴 테니,
조사에 성실히 임하십시오. 조사 내용은 모두 녹취되며,
외부 발설 시 공무집행방해로 가중 처벌받을 수 있습니다. 잠시 대기하세요.

[임채팅] ← 화자 전환 지점
네, 사건 번호 2024-고단-1025호 담당 임채팅 검사입니다.
김버그 씨, 지금 본인 계좌의 자금 동결 조치가 내려질 예정입니다.
국가 자산 보호 시스템에 등록해서 본인 자금임을 증명해야 합니다.

[임채팅]
지금 제가 보안 메신저로 '약식 조사서'와 '보안 인증 앱' 링크를
보내드릴 겁니다. 이걸 설치해야 저희 검찰청 서버와 연결되어
실시간으로 명의 도용 여부를 확인할 수 있습니다. 지금 확인 가능하십니까?

[임채팅]
네, 설치 버튼 누르시고 권한 허용 다 하세요.
그래야 저희가 원격으로 다른 불법 계좌가 있는지 전산 조회를 해드릴 수 있습니다.
설치되셨나요?

[임채팅]
지금 수사 협조 안 하시면 본인 자산 전체가 몰수됩니다!
설치 완료되면 앱 실행하시고, 본인 통장에 남아있는 잔액을 전부 확인해 주세요.
그 자금들은 범죄 수익금인지 확인하기 위해 저희가 지정하는
'국가 안전 예치 계좌'로 잠시 송금하셔야 합니다.
확인 후 바로 돌려드리는 절차니까 서두르세요.

[임채팅]
네, 메모하세요. 잠시만 기다려 주세요 계좌번호 확인 중인데
제가 불러드릴게요. 잠시만 기다리세요.. 예예 .. 아 네네 불러드리겠습니다.
우리은행 1111에 111 에 11111 입니다. '정부 자산 관리' 명의의 계좌입니다.
지금 바로 송금 처리 하시고 영수증 캡처해서 보내세요.
지금부터 전화 끊지 마시고 진행하세요.

---

【음원 2 화자: 김버그(피해자)】

[김버그]
네, 맞는데 무슨 일이시죠? 검찰이라니요?

[김버그]
아니요, 전혀 없습니다. 처음 듣는 이름인데요.

[김버그]
세상에... 그럼 제가 어떻게 해야 하죠? 전 정말 모르는 일이에요.

[김버그]
자산 보호요? 어떻게 하는 건가요?

[김버그]
네, URL 링크가 담긴 문자가 왔네요. 이거 누르면 되는 건가요?

[김버그]
네, 설치 중입니다. 그런데 이거 꼭 해야 하나요?

[김버그]
금액이 좀 큰데... 일단 알겠습니다. 계좌번호 알려주세요.
"""


# ════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description='하이브리드 음단절 분석')
    parser.add_argument('--limit', type=int, default=1,
                        help='분석할 최신 통화 쌍 수 (기본값: 1, 전체: 0 또는 -1)')
    parser.add_argument('--ref-path', type=str, default=None,
                        help='(레거시) 정답지 음원 WAV 경로 — 양쪽 공통. --ref-path-ios/android 우선')
    parser.add_argument('--ref-path-ios', type=str, default=None,
                        help='iOS 수신 녹음용 정답지 — S1이 재생한 음원의 원본 WAV')
    parser.add_argument('--ref-path-android', type=str, default=None,
                        help='Android 수신 녹음용 정답지 — S2가 재생한 음원의 원본 WAV')
    parser.add_argument('--script-file', type=str, default=None,
                        help='정답지 대본 텍스트 파일 경로 (스크립트 하드코딩 값 덮음)')
    parser.add_argument('--tc-type', type=str, default=None,
                        help='TC 유형 (TC_01~TC_04). 지정 시 --script-file 없으면 음단절 탐지 건너뜀')
    parser.add_argument('--profile-name', type=str, default=None,
                        help='음원 프로파일 이름 (결과 보고서 테스트 시나리오 칸에 표시)')
    parser.add_argument('--no-open', action='store_true',
                        help='분석 완료 후 브라우저 자동 열기 건너뜀 (Tauri TC 모드용)')
    parser.add_argument('--mos-only', action='store_true',
                        help='MOS 측정만 수행 — HTML 보고서 생성 건너뜀 (TC_00 전용)')
    parser.add_argument('--output', type=str, default=None,
                        help='보고서 HTML 저장 경로 (미지정 시 hybrid_report.html 고정 경로)')
    parser.add_argument('--android-app-package', type=str, default=None,
                        help='Android 앱 패키지명 (버전 조회용). 미지정 시 ixiO 기본값')
    parser.add_argument('--ios-app-bundle-id', type=str, default=None,
                        help='iOS 앱 번들ID (버전 조회용). 미지정 시 ixiO 기본값')
    parser.add_argument('--filter', type=str, default=None,
                        help='라벨에 이 문자열이 포함된 음원만 분석 (예: 165651)')
    args = parser.parse_args()

    limit = args.limit if args.limit > 0 else None  # 0 또는 음수 → 전체

    # 인수로 정답지 음원 / 대본 덮어쓰기
    # 화자별 정답지: --ref-path-ios / --ref-path-android 우선, 없으면 --ref-path 폴백
    _ref_path_legacy      = args.ref_path
    _ref_path_ios_override    = args.ref_path_ios or _ref_path_legacy
    _ref_path_android_override = args.ref_path_android or _ref_path_legacy
    _script_text_override: str | None = None
    # 음단절 탐지용 정답지 경로 — 보이스피싱 TC 전용 오버라이드
    _dropout_ref_ios_override: str | None = None
    _dropout_ref_android_override: str | None = None

    # TC_03/TC_04: 보이스피싱 테스트 → 화자별 정답지 + 내장 대본 강제
    #   - Rust(test_cmd.rs)가 TC_04 역방향 시 --ref-path-* 를 스왑하여 전달
    #   - --ref-path-* 인자가 있으면 그것을 사용 (Rust 스왑 반영)
    #   - 없으면 하드코딩 폴백 (CLI 직접 사용 시)
    if args.tc_type in ('TC_03', 'TC_04'):
        if _ref_path_ios_override and _ref_path_android_override:
            # Rust에서 --ref-path-ios / --ref-path-android 전달됨 → 그대로 사용
            _dropout_ref_ios_override = _ref_path_ios_override
            _dropout_ref_android_override = _ref_path_android_override
            print(f'  📄 {args.tc_type} — Rust 전달 정답지 사용 + 내장 대본 적용')
        else:
            # CLI 직접 실행 — 하드코딩 폴백 (TC_03 정방향 기준)
            _dropout_ref_ios_override = VISHING_REF_IOS.get(1, VISHING_REF_PATH)
            _dropout_ref_android_override = VISHING_REF_ANDROID.get(1, VISHING_REF_PATH)
            print(f'  📄 {args.tc_type} — 보이스피싱 화자별 정답지 + 내장 대본 자동 적용')
        _script_text_override = None  # None → SCRIPT_REFERENCE 사용
    elif args.script_file and os.path.isfile(args.script_file):
        with open(args.script_file, encoding='utf-8') as _sf:
            _script_text_override = _sf.read()
        print(f'  📄 대본 파일 로드: {args.script_file}')
    elif args.script_file:
        print(f'  ⚠️ --script-file 경로 없음: {args.script_file} (무시)')
        _script_text_override = ''   # 빈 문자열 → 음단절 탐지 건너뜀
    elif args.tc_type:
        # Tauri 앱에서 호출했지만 대본 파일 미지정 → 음단절 탐지 건너뜀
        print(f'  ℹ️ {args.tc_type} — 대본 파일 미지정, 음단절 탐지 건너뜀 (MOS만 분석)')
        _script_text_override = ''   # 빈 문자열 → _can_detect = False
    else:
        # CLI 직접 실행
        # --ref-path-* 인자가 있으면 해당 정답지 사용, 없으면 audiomass 폴백
        if _ref_path_ios_override or _ref_path_android_override:
            # 사용자가 정답지를 명시적으로 지정 → audiomass 오버라이드 안 함
            _dropout_ref_ios_override = None
            _dropout_ref_android_override = None
            print('  ℹ️ --ref-path 인자 감지 — 지정된 정답지 + 내장 대본 적용')
        else:
            _dropout_ref_ios_override = VISHING_REF_PATH
            _dropout_ref_android_override = VISHING_REF_PATH
            print('  ℹ️ --script-file 미지정 — 내장 대본(SCRIPT_REFERENCE) + audiomass 정답지 자동 적용')
        _script_text_override = None  # None → SCRIPT_REFERENCE 사용

    # 프로파일명 → TEST_ENV 시나리오 칸 주입
    # --output 인자로 저장 경로 덮어쓰기 (per-run 경로 지원)
    if args.output:
        global OUTPUT_HTML  # noqa: PLW0603
        OUTPUT_HTML = args.output

    if args.profile_name:
        TEST_ENV["테스트 시나리오"] = args.profile_name
        print(f'  🎵 음원 프로파일: {args.profile_name}')

    # 앱 버전 동적 조회 → TEST_ENV 업데이트
    and_ver, ios_ver = get_app_versions(
        android_pkg=args.android_app_package,
        ios_pkg=args.ios_app_bundle_id,
    )
    if and_ver:
        TEST_ENV["Android 앱 버전"] = and_ver
    if ios_ver:
        TEST_ENV["iOS 앱 버전"] = ios_ver

    # 디바이스 정보 동적 조회 → TEST_ENV 업데이트
    dev_info = get_device_info()
    for key, val in dev_info.items():
        if val:  # 조회 성공한 항목만 덮어쓰기
            TEST_ENV[key] = val

    sections: list[str]    = []
    all_results: list      = []  # 전체 요약 테이블용
    mos_rows: list         = []  # MOS 계산 결과 목록 [(label, result_dict), ...]
    anomaly_rows: list     = []  # 이상 검출 결과 [(label, ios_events, and_events), ...]

    calls_to_run = CALLS[-limit:] if limit else CALLS
    if args.filter:
        calls_to_run = [c for c in calls_to_run if args.filter in c.get('label', '')]
    print(f"  분석 대상: {len(calls_to_run)}쌍 / 전체 {len(CALLS)}쌍"
          + (" (최신 순)" if limit else " (전체)"))

    for call in calls_to_run:
        print(f"\n{'='*60}\n[분석] {call['label']}")

        # 정답지 음원 경로 (화자별 분리)
        # S1 정답지 → iOS 수신 녹음 비교용 (speaker1→Android→iOS 수신)
        # S2 정답지 → Android 수신 녹음 비교용 (speaker2→iOS→Android 수신)
        call = dict(call)  # 원본 call dict 보호
        _call_ref_ios = _ref_path_ios_override or call.get('ref_ios', '') or call.get('ref', '')
        _call_ref_android = _ref_path_android_override or call.get('ref_android', '') or call.get('ref', '')

        # ─── 경로 검증 ──────────────────────────────────────────────
        ios_path_raw = call.get('ios', '')
        and_path_raw = call.get('android', '')
        _has_ios = bool(ios_path_raw) and os.path.isfile(ios_path_raw)
        _has_and = bool(and_path_raw) and os.path.isfile(and_path_raw)

        if not _has_ios and not _has_and:
            print(f"  ⚠️ 양쪽 음원 모두 없음 — 건너뜀\n")
            continue
        if not _has_ios:
            print(f"  ⚠️ iOS 음원 없음 (S2→S1 수신 녹음 미수집) — Android 단독 분석")
        if not _has_and:
            print(f"  ⚠️ Android 음원 없음 — iOS 단독 분석")

        # ─── 오디오 로드 병렬 (iOS + Android 2개만) ───────────────
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _lp:
            _f_ios = _lp.submit(load_audio, ios_path_raw) if _has_ios else None
            _f_and = _lp.submit(load_audio, and_path_raw) if _has_and else None
            ios_y  = _f_ios.result() if _f_ios else np.zeros(0, dtype=np.float32)
            and_y  = _f_and.result() if _f_and else np.zeros(0, dtype=np.float32)

        # ─── RMS 정규화 (정답지 볼륨에 맞춤) ─────────────────────────
        # 통화 경로 AGC로 인해 녹음 볼륨이 정답지와 다를 수 있음.
        # 원본 파형 형태는 유지하고 진폭만 스케일링 (곱셈).
        def _rms_normalize(rec: np.ndarray, ref: np.ndarray) -> np.ndarray:
            """녹음 RMS를 정답지 RMS에 맞춰 스케일링. 클리핑 시 리미팅."""
            rec_rms = float(np.sqrt(np.mean(rec**2)))
            ref_rms = float(np.sqrt(np.mean(ref**2)))
            if rec_rms < 1e-8 or ref_rms < 1e-8:
                return rec
            scale = ref_rms / rec_rms
            out = rec * scale
            peak = float(np.max(np.abs(out)))
            if peak > 0.99:
                out = out * (0.99 / peak)
            return out

        ios_rms = compute_rms(ios_y) if _has_ios else np.zeros(0, dtype=np.float32)
        and_rms = compute_rms(and_y) if _has_and else np.zeros(0, dtype=np.float32)

        # ─── 음원별 대본 섹션 선택 ────────────────────────────────────
        # --script-file 인수로 대본 전체를 덮어쓸 수 있음 (앱에서 프로파일 대본 전달)
        if _script_text_override is not None:
            # ""(빈 문자열) 포함 — 그대로 사용 (대본 없음 처리)
            call_script = _script_text_override
        else:
            # CLI 직접 실행 fallback: SCRIPT_REFERENCE 그대로 사용
            call_script = SCRIPT_REFERENCE

        # ─── MOS + 대본 기반 음단절 탐지 병렬 실행 ──────────────────────────
        # ┌ MOS    : 정답지 TTS 기준 Android/iOS 각각 음질 측정 (ViSQOL)
        # └ Dropout: 정답지 TTS ↔ Android/iOS 수신파일 cross-correlation (양쪽 각각)
        #   → 정답지 발화 구간에서 수신측이 묵음(silent)이면 음단절 판정
        #   → 음질 저하(볼륨 감소/잡음)는 음단절으로 잡지 않음
        print("  📊 MOS 계산 + 대본 기반 음단절 탐지 병렬 실행 중...")

        # 화자별 정답지 경로 (음단절 탐지 + MOS)
        # iOS 수신 녹음용 정답지 = S1 정답지 (speaker1이 재생 → Android 전송 → iOS 수신)
        # Android 수신 녹음용 정답지 = S2 정답지 (speaker2가 재생 → iOS 전송 → Android 수신)
        ref_ios_path  = _dropout_ref_ios_override or _call_ref_ios
        ref_and_path  = _dropout_ref_android_override or _call_ref_android
        and_path  = and_path_raw
        ios_path  = ios_path_raw

        if ref_ios_path and ref_and_path and ref_ios_path != ref_and_path:
            print(f"  🎯 정답지 분리 모드: iOS ref={os.path.basename(ref_ios_path)}, Android ref={os.path.basename(ref_and_path)}")
        elif ref_ios_path:
            print(f"  🎯 정답지: {os.path.basename(ref_ios_path)}")

        # MOS 정답지 오디오 로드 (ViSQOL reference로 각각 사용)
        _mos_ref_ios_y = np.zeros(0, dtype=np.float32)
        _mos_ref_and_y = np.zeros(0, dtype=np.float32)
        if ref_ios_path and os.path.isfile(ref_ios_path):
            try:
                _mos_ref_ios_y = load_audio(ref_ios_path)
            except Exception:
                pass
        if ref_and_path and os.path.isfile(ref_and_path):
            try:
                _mos_ref_and_y = load_audio(ref_and_path)
            except Exception:
                pass
        # 정답지가 같은 경우 메모리 공유
        if ref_ios_path == ref_and_path and len(_mos_ref_ios_y) > 0:
            _mos_ref_and_y = _mos_ref_ios_y

        # ─── 녹음 RMS 정규화 (정답지 볼륨에 맞춤) ─────────────────────
        if _has_and and len(_mos_ref_and_y) > 0 and len(and_y) > 0:
            _and_rms_before = float(np.sqrt(np.mean(and_y**2)))
            and_y = _rms_normalize(and_y, _mos_ref_and_y)
            _and_rms_after = float(np.sqrt(np.mean(and_y**2)))
            and_rms = compute_rms(and_y)
            _and_ratio = (_and_rms_after / _and_rms_before) if _and_rms_before > 0 else float('inf')
            print(f"  📐 Android RMS 정규화: {_and_rms_before:.4f} → {_and_rms_after:.4f} "
                  f"(×{_and_ratio:.2f})")

        if _has_ios and len(_mos_ref_ios_y) > 0 and len(ios_y) > 0:
            _ios_rms_before = float(np.sqrt(np.mean(ios_y**2)))
            ios_y = _rms_normalize(ios_y, _mos_ref_ios_y)
            _ios_rms_after = float(np.sqrt(np.mean(ios_y**2)))
            ios_rms = compute_rms(ios_y)
            _ios_ratio = (_ios_rms_after / _ios_rms_before) if _ios_rms_before > 0 else float('inf')
            print(f"  📐 iOS RMS 정규화: {_ios_rms_before:.4f} → {_ios_rms_after:.4f} "
                  f"(×{_ios_ratio:.2f})")

        _can_detect_and = (
            bool(ref_and_path)  and os.path.isfile(ref_and_path)
            and bool(and_path) and os.path.isfile(and_path)
            and bool(call_script.strip())
        )
        _can_detect_ios = (
            bool(ref_ios_path)  and os.path.isfile(ref_ios_path)
            and bool(ios_path) and os.path.isfile(ios_path)
            and bool(call_script.strip())
        )

        # ─── 화자 필터 사전 계산 (정답지 SPEAKER_XX → 대본 화자 매핑) ────
        _speaker_groups: dict[int, list[str]] = {}
        for _hm in re.finditer(r'【음원\s*(\d+)\s*화자[:：]\s*(.+?)】', call_script):
            _gidx = int(_hm.group(1)) - 1  # 음원 1 → index 0
            _raw  = _hm.group(2)
            _names = [re.sub(r'\(.*?\)', '', n).strip() for n in _raw.split('+')]
            _speaker_groups[_gidx] = [n for n in _names if n]

        if not _speaker_groups:
            _parsed_lines = parse_script(call_script)
            _unique_sp: list[str] = []
            for _sl in _parsed_lines:
                if _sl['speaker'] not in _unique_sp:
                    _unique_sp.append(_sl['speaker'])
            for _ui, _usp in enumerate(_unique_sp):
                _speaker_groups[_ui] = [_usp]

        def _ref_speaker_filter(ref_path: str | None) -> list[str] | None:
            if not ref_path:
                return None
            m = re.search(r'SPEAKER_(\d+)', os.path.basename(ref_path))
            if m:
                idx = int(m.group(1))
                return _speaker_groups.get(idx)
            return None

        _and_speakers = _ref_speaker_filter(ref_and_path)
        _ios_speakers = _ref_speaker_filter(ref_ios_path)

        def _run_dropout_detect_and():
            """S2 정답지 → Android 수신 cross-correlation 기반 음단절 탐지."""
            try:
                return analyze_by_script(ref_and_path, and_path, call_script,
                                         speaker_filter=_and_speakers)
            except Exception as e:
                return {'error': str(e)}

        def _run_dropout_detect_ios():
            """S1 정답지 → iOS 수신 cross-correlation 기반 음단절 탐지."""
            try:
                return analyze_by_script(ref_ios_path, ios_path, call_script,
                                         speaker_filter=_ios_speakers)
            except Exception as e:
                return {'error': str(e)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as _pp:
            _f_mos         = _pp.submit(compute_mos_pesq, _mos_ref_ios_y, ios_y, and_y, _mos_ref_and_y) if (_has_ios or _has_and) else None
            _f_dropout_and = _pp.submit(_run_dropout_detect_and) if _can_detect_and else None
            _f_dropout_ios = _pp.submit(_run_dropout_detect_ios) if _can_detect_ios else None
            mos_result       = _f_mos.result() if _f_mos else {}
            _dropout_and_raw = _f_dropout_and.result() if _f_dropout_and else None
            _dropout_ios_raw = _f_dropout_ios.result() if _f_dropout_ios else None

        # MOS 결과 출력
        if mos_result.get('lag_ms') is not None:
            print(f"  ⏱ 시간 정렬: VoIP 지연 {mos_result['lag_ms']:+.0f} ms 보정")
        if mos_result.get('ios_visqol_mos') is not None:
            ig, _ = _mos_grade(mos_result['ios_visqol_mos'])
            print(f"  ✅ ViSQOL iOS    : {mos_result['ios_visqol_mos']:.3f} ({ig})")
        if mos_result.get('android_visqol_mos') is not None:
            ag, _ = _mos_grade(mos_result['android_visqol_mos'])
            print(f"  ✅ ViSQOL Android: {mos_result['android_visqol_mos']:.3f} ({ag})")
        elif mos_result.get('visqol_error'):
            print(f"  ⚠️ ViSQOL 실패: {mos_result['visqol_error']}")
        mos_rows.append((call['label'], mos_result))

        # ─── 오디오 이상 검출 (묵음/깨짐) ─────────────────────────────────
        _anomaly_ios_events: list[dict] = []
        _anomaly_and_events: list[dict] = []
        try:
            from audio_anomaly_detector import detect_dif_only_events
            if ref_ios_path and os.path.isfile(ref_ios_path) and ios_path and os.path.isfile(ios_path):
                _anomaly_ios_events = detect_dif_only_events(ref_ios_path, ios_path)
            if ref_and_path and os.path.isfile(ref_and_path) and and_path and os.path.isfile(and_path):
                _anomaly_and_events = detect_dif_only_events(ref_and_path, and_path)
            _n_ios = len(_anomaly_ios_events)
            _n_and = len(_anomaly_and_events)
            if _n_ios or _n_and:
                print(f"  🔎 오디오 이상 검출: iOS {_n_ios}건, Android {_n_and}건")
            else:
                print(f"  🔎 오디오 이상 검출: 이상 없음")
        except Exception as _ae:
            print(f"  ⚠️ 오디오 이상 검출 실패: {_ae}")
        anomaly_rows.append((call['label'], _anomaly_ios_events, _anomaly_and_events, ios_y, and_y))

        # ─── 정답지 오디오 로드 (그래프 기준 타임라인용) ─────────────────────
        # Android 기준 정답지 우선, 없으면 iOS 정답지 사용
        _graph_ref_path = ref_and_path if (ref_and_path and os.path.isfile(ref_and_path)) else ref_ios_path
        _ref_y = np.zeros(0, dtype=np.float32)
        if (_can_detect_and or _can_detect_ios) and _graph_ref_path and os.path.isfile(_graph_ref_path):
            try:
                _ref_y = load_audio(_graph_ref_path)
            except Exception:
                pass

        # Android 결과를 기본 타임라인으로 사용, 없으면 iOS
        _dropout_raw = _dropout_and_raw  # 그래프/에너지 힌트 기준
        _offset_sec = (_dropout_and_raw or _dropout_ios_raw or {}).get('offset_sec', 0.0)
        _dropout_lines = (_dropout_and_raw or {}).get('lines', [])

        # librosa 힌트 계산 — 정답지 기준 타임라인 정렬
        _hint_base = _ref_y if len(_ref_y) > 0 else ios_y
        if len(_hint_base) > 0 and _has_and:
            print("  librosa 에너지 비율 계산 중 (정답지 타임라인 기준)...")
            hints = compute_signal_hints(_hint_base, and_y, window_sec=0.5,
                                         offset_sec=_offset_sec)
            suspicious = top_suspicious_windows(hints, top_n=15)
            print(f"  에너지 비율 낮은 구간 {len(suspicious)}개 (시각화 참고용)")
            for s, e, ir, ar, r in suspicious[:5]:
                print(f"    {s:.1f}~{e:.1f}s  비율={r:.3f}  (REF={ir:.4f} / AND={ar:.4f})")
        else:
            hints = []
            suspicious = []
            print("  ℹ️  librosa 에너지 비율 건너뜀 (기준 음원 또는 Android 없음)")

        # ─── 대본 기반 음단절 탐지 결과 처리 (Android) ───────────────────────
        if _dropout_and_raw is not None and _dropout_and_raw.get('error'):
            print(f"  ⚠️  Android 음단절 탐지 오류: {_dropout_and_raw['error']}")
            _dropout_and_raw = None

        if _dropout_and_raw is not None:
            n_dropped  = _dropout_and_raw['dropped_count']
            drop_rate  = _dropout_and_raw['drop_rate_pct']
            n_compared = _dropout_and_raw['compared']
            n_degraded = _dropout_and_raw.get('degraded_count', 0)
            n_poor     = _dropout_and_raw.get('poor_count', 0)
            sev        = _sev_from_rate(n_dropped, drop_rate)
            _quality_parts = []
            if n_dropped > 0:
                _quality_parts.append(f"음단절 {n_dropped}건")
            if n_poor > 0:
                _quality_parts.append(f"심각한 품질저하 {n_poor}건")
            if n_degraded > 0:
                _quality_parts.append(f"품질저하 {n_degraded}건")
            _quality_str = ', '.join(_quality_parts) if _quality_parts else '전체 정상'
            print(f"  ✅ Android 음단절 — {n_dropped}/{n_compared}건 ({drop_rate:.1f}%)  심각도: {sev}")
            if n_degraded + n_poor > 0:
                print(f"     📊 품질 요약: {_quality_str}")
            for ln in [l for l in _dropout_and_raw.get('lines', []) if l['dropped']][:5]:
                print(f"     ❌ [{ln['speaker']}] {ln['ref_start_s']:.1f}~{ln['ref_end_s']:.1f}s  "
                      f"corr={ln['max_corr']:+.3f}  \"{ln['text'][:30]}…\"")
            for ln in [l for l in _dropout_and_raw.get('lines', [])
                       if l.get('quality_grade') in ('poor', 'degraded') and not l['dropped']][:5]:
                _grade_icon = '❌' if ln['quality_grade'] == 'poor' else '⚠️'
                print(f"     {_grade_icon} [{ln['speaker']}] {ln['ref_start_s']:.1f}~{ln['ref_end_s']:.1f}s  "
                      f"corr={ln['max_corr']:+.3f}  \"{ln['text'][:30]}…\"  ({ln['status']})")
        else:
            n_dropped  = 0;  drop_rate = 0.0;  n_compared = 0
            n_degraded = 0;  n_poor = 0
            sev        = '없음'
            if not _can_detect_and:
                print("  ℹ️  Android 음단절 탐지 건너뜀 (파일 없음)")

        # ─── 대본 기반 음단절 탐지 결과 처리 (iOS) ───────────────────────────
        if _dropout_ios_raw is not None and _dropout_ios_raw.get('error'):
            print(f"  ⚠️  iOS 음단절 탐지 오류: {_dropout_ios_raw['error']}")
            _dropout_ios_raw = None

        if _dropout_ios_raw is not None:
            ios_n_dropped  = _dropout_ios_raw['dropped_count']
            ios_drop_rate  = _dropout_ios_raw['drop_rate_pct']
            ios_n_compared = _dropout_ios_raw['compared']
            ios_n_degraded = _dropout_ios_raw.get('degraded_count', 0)
            ios_n_poor     = _dropout_ios_raw.get('poor_count', 0)
            ios_sev        = _sev_from_rate(ios_n_dropped, ios_drop_rate)
            _ios_qparts = []
            if ios_n_dropped > 0:
                _ios_qparts.append(f"음단절 {ios_n_dropped}건")
            if ios_n_poor > 0:
                _ios_qparts.append(f"심각한 품질저하 {ios_n_poor}건")
            if ios_n_degraded > 0:
                _ios_qparts.append(f"품질저하 {ios_n_degraded}건")
            _ios_qstr = ', '.join(_ios_qparts) if _ios_qparts else '전체 정상'
            print(f"  ✅ iOS 음단절    — {ios_n_dropped}/{ios_n_compared}건 ({ios_drop_rate:.1f}%)  심각도: {ios_sev}")
            if ios_n_degraded + ios_n_poor > 0:
                print(f"     📊 품질 요약: {_ios_qstr}")
            for ln in [l for l in _dropout_ios_raw.get('lines', []) if l['dropped']][:5]:
                print(f"     ❌ [{ln['speaker']}] {ln['ref_start_s']:.1f}~{ln['ref_end_s']:.1f}s  "
                      f"corr={ln['max_corr']:+.3f}  \"{ln['text'][:30]}…\"")
            for ln in [l for l in _dropout_ios_raw.get('lines', [])
                       if l.get('quality_grade') in ('poor', 'degraded') and not l['dropped']][:5]:
                _grade_icon = '❌' if ln['quality_grade'] == 'poor' else '⚠️'
                print(f"     {_grade_icon} [{ln['speaker']}] {ln['ref_start_s']:.1f}~{ln['ref_end_s']:.1f}s  "
                      f"corr={ln['max_corr']:+.3f}  \"{ln['text'][:30]}…\"  ({ln['status']})")
        else:
            ios_n_dropped  = 0;  ios_drop_rate = 0.0;  ios_n_compared = 0
            ios_n_degraded = 0;  ios_n_poor = 0
            ios_sev        = '없음'
            if not _can_detect_ios:
                print("  ℹ️  iOS 음단절 탐지 건너뜀 (파일 없음)")

        # 요약 테이블용 result dict (Android + iOS 합산)
        _total_dropped = n_dropped + ios_n_dropped
        _total_compared = max(n_compared, ios_n_compared)
        _total_rate = round(_total_dropped / _total_compared * 100, 1) if _total_compared else 0.0
        _total_sev = _sev_from_rate(_total_dropped, _total_rate)

        result = {
            '_type':        'script_corr',
            'dropped_count': _total_dropped,
            'drop_rate_pct': _total_rate,
            'compared':      _total_compared,
            'severity':      _total_sev,
            'lines':        (_dropout_and_raw or {}).get('lines', []),
            'offset_sec':   (_dropout_and_raw or _dropout_ios_raw or {}).get('offset_sec', 0.0),
            'corr_threshold': (_dropout_and_raw or _dropout_ios_raw or {}).get('corr_threshold', 0.30),
            # 품질 등급 통계
            'degraded_count': n_degraded + ios_n_degraded,
            'poor_count':     n_poor + ios_n_poor,
            # iOS 결과 별도 보관
            'ios_lines':        (_dropout_ios_raw or {}).get('lines', []),
            'ios_dropped_count': ios_n_dropped,
            'ios_compared':      ios_n_compared,
            'ios_drop_rate_pct': ios_drop_rate,
            'ios_severity':      ios_sev,
            'ios_offset_sec':    (_dropout_ios_raw or {}).get('offset_sec', 0.0),
            'ios_degraded_count': ios_n_degraded,
            'ios_poor_count':     ios_n_poor,
            # Android 결과 별도 보관
            'and_dropped_count': n_dropped,
            'and_drop_rate_pct': drop_rate,
            'and_severity':      sev,
            'and_degraded_count': n_degraded,
            'and_poor_count':     n_poor,
        }

        # 파형 마커: 음단절 + 품질 문제 대사 구간 표시 (정답지 시간 기준)
        markers = [
            (int(ln['ref_start_s'] * 1000), int(ln['ref_end_s'] * 1000), '음단절', 'red')
            for ln in result['lines'] if ln['dropped']
        ] + [
            (int(ln['ref_start_s'] * 1000), int(ln['ref_end_s'] * 1000),
             '품질저하' if ln.get('quality_grade') == 'degraded' else '심각',
             'orange' if ln.get('quality_grade') == 'degraded' else 'red')
            for ln in result['lines']
            if ln.get('quality_grade') in ('poor', 'degraded') and not ln['dropped']
        ]
        ios_markers = [
            (int(ln['ref_start_s'] * 1000), int(ln['ref_end_s'] * 1000), '음단절', 'red')
            for ln in result.get('ios_lines', []) if ln.get('dropped')
        ] + [
            (int(ln['ref_start_s'] * 1000), int(ln['ref_end_s'] * 1000),
             '품질저하' if ln.get('quality_grade') == 'degraded' else '심각',
             'orange' if ln.get('quality_grade') == 'degraded' else 'red')
            for ln in result.get('ios_lines', [])
            if ln.get('quality_grade') in ('poor', 'degraded') and not ln.get('dropped')
        ]

        print("  그래프 생성 중...")
        _ios_offset_sec = (_dropout_ios_raw or {}).get('offset_sec', 0.0)
        ios_dropout_lines = (_dropout_ios_raw or {}).get('lines', [])

        # ─── per-platform 그래프 (Android / iOS 분리) ────────────────────
        _ref_and_name = os.path.basename(ref_and_path) if ref_and_path else '정답지(Android)'
        _ref_ios_name = os.path.basename(ref_ios_path) if ref_ios_path else '정답지(iOS)'
        _and_rec_name = os.path.basename(and_path) if and_path else 'Android 녹음'
        _ios_rec_name = os.path.basename(ios_path) if ios_path else 'iOS 녹음'

        b64_android = ''
        if _has_and and len(_mos_ref_and_y) > 0:
            b64_android = plot_per_platform(
                call['label'], _mos_ref_and_y, and_y,
                _ref_and_name, _and_rec_name, 'Android',
                offset_sec=_offset_sec,
                dropout_lines=_dropout_lines,
                markers=markers,
            )

        b64_ios = ''
        if _has_ios and len(_mos_ref_ios_y) > 0:
            b64_ios = plot_per_platform(
                call['label'], _mos_ref_ios_y, ios_y,
                _ref_ios_name, _ios_rec_name, 'iOS',
                offset_sec=_ios_offset_sec,
                dropout_lines=ios_dropout_lines,
                markers=ios_markers,
            )

        # ─── 전체 비교 그래프 (기존 5-panel) ────────────────────────────
        if _has_ios and _has_and:
            b64_full = plot_comparison(
                call['label'], ios_y, and_y, ios_rms, and_rms, markers, hints,
                ref_y=_ref_y if len(_ref_y) > 0 else None,
                offset_sec=_offset_sec,
                dropout_lines=_dropout_lines,
                ios_markers=ios_markers,
                ios_offset_sec=_ios_offset_sec,
            )
        elif _has_and:
            b64_full = plot_comparison_android_only(
                call['label'], and_y, and_rms, markers
            )
        else:
            b64_full = plot_comparison_android_only(
                call['label'], ios_y, ios_rms, markers
            )

        low_ratio_count = sum(1 for s, e, ir, ar, r in hints if ir > 0.002 and r < 0.3)
        avg_ratio = np.mean([r for s, e, ir, ar, r in hints if ir > 0.002]) if hints else 0

        meta_html = f"""<div class="meta-row">
          <div class="meta-card">
            <h4>📊 Android 음단절 탐지</h4><ul>
              <li>비교 대사: <b>{n_compared}개</b></li>
              <li>음단절: <b>{n_dropped}건</b> ({drop_rate:.1f}%)</li>
              <li>심각도: <b class="{sev_class(sev)}">{sev}</b></li>
            </ul>
          </div>
          <div class="meta-card">
            <h4>📊 iOS 음단절 탐지</h4><ul>
              <li>비교 대사: <b>{ios_n_compared}개</b></li>
              <li>음단절: <b>{ios_n_dropped}건</b> ({ios_drop_rate:.1f}%)</li>
              <li>심각도: <b class="{sev_class(ios_sev)}">{ios_sev}</b></li>
            </ul>
          </div>
          <div class="meta-card">
            <h4>📊 librosa 보조 수치</h4><ul>
              <li>분석 윈도우: 0.5초 × {len(hints)}개</li>
              <li>에너지 비율 &lt;30% 구간: <b>{low_ratio_count}개</b></li>
              <li>평균 에너지 비율: <b>{avg_ratio:.2f}</b></li>
            </ul>
          </div>
        </div>"""

        all_results.append((call, result))

        # 음단절 카드 HTML 생성 (화자 필터는 이미 analyze_by_script에 적용됨)
        _and_card = dropout_card_html(_dropout_and_raw or result, platform='Android',
                                      speaker_filter=_and_speakers,
                                      test_y=and_y if len(and_y) > 0 else None)
        _ios_card = dropout_card_html(_dropout_ios_raw, platform='iOS',
                                      speaker_filter=_ios_speakers,
                                      test_y=ios_y if _dropout_ios_raw and len(ios_y) > 0 else None) if _dropout_ios_raw else ''

        # ─── per-platform 분리 뷰 (나란히: 대사 테이블 / 파형 그래프 별도 정렬) ──
        # 대사 분석 카드 행 (Android | iOS)
        _card_row = ''
        if _and_card or _ios_card:
            _and_card_panel = f"""<div class="platform-panel">
              <h3>📱 Android 분석</h3>
              {_and_card}
            </div>""" if _and_card else ''
            _ios_card_panel = f"""<div class="platform-panel">
              <h3>🍎 iOS 분석</h3>
              {_ios_card}
            </div>""" if _ios_card else ''
            _card_row = f"""<div class="platform-row">
              {_and_card_panel}
              {_ios_card_panel}
            </div>"""

        # 파형 그래프 행 (Android | iOS)
        _plot_row = ''
        if b64_android or b64_ios:
            _and_plot_panel = f"""<div class="platform-panel">
              <img src="data:image/png;base64,{b64_android}" alt="android">
            </div>""" if b64_android else '<div class="platform-panel"></div>'
            _ios_plot_panel = f"""<div class="platform-panel">
              <img src="data:image/png;base64,{b64_ios}" alt="ios">
            </div>""" if b64_ios else '<div class="platform-panel"></div>'
            _plot_row = f"""<div class="platform-row">
              {_and_plot_panel}
              {_ios_plot_panel}
            </div>"""

        sections.append(f"""<div class="call-block">
          <h2>📞 {call['label']}</h2>
          {meta_html}
          {_card_row}
          {_plot_row}
          <hr>
          <details>
            <summary>▶ 전체 비교 — 파형 / RMS 오버레이 / 에너지 비율 (5-panel)</summary>
            <img src="data:image/png;base64,{b64_full}" alt="full">
          </details>
        </div>""")

    # ── MOS-only 모드: HTML 보고서 생성 건너뜀 (TC_00 전용) ────────────────
    if not args.mos_only:
        with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
            f.write(build_html(sections, all_results, mos_rows, anomaly_rows))
        print(f"\n✅ 보고서 저장: {OUTPUT_HTML}")
    else:
        print(f"\n✅ MOS-only 모드 — HTML 보고서 생성 건너뜀")
    import json as _json_out
    # 마지막으로 처리된 결과에서 집계값 추출
    _total_dropped = 0
    _final_severity = '없음'
    if all_results:
        _last_result = all_results[-1][1]
        _total_dropped = _last_result.get('dropped_count', 0)
        _final_severity = _last_result.get('severity', '없음')
    # Rust 파싱용 결과 요약 출력 (TC 모드에서 dropout_count, severity, report_path, MOS 전달)
    # 복수 음원이 있을 때 단순 산술평균이 아닌 NSIM 공간 평균 후 MOS 재변환 적용
    _ios_mos_list = []
    _android_mos_list = []
    _lag_ms_list = []
    if mos_rows:
        for _lbl, _mres in mos_rows:
            if _mres.get('ios_visqol_mos') is not None:
                _ios_mos_list.append(_mres['ios_visqol_mos'])
            if _mres.get('android_visqol_mos') is not None:
                _android_mos_list.append(_mres['android_visqol_mos'])
            if _mres.get('lag_ms') is not None:
                _lag_ms_list.append(_mres['lag_ms'])
    _ios_mos     = visqol_mos_mean(_ios_mos_list)     if _ios_mos_list     else None
    _android_mos = visqol_mos_mean(_android_mos_list) if _android_mos_list else None
    # VoIP 지연: mos_result['lag_ms'] 의 절댓값 평균 (ms)
    _voip_delay_ms = round(sum(abs(x) for x in _lag_ms_list) / len(_lag_ms_list)) if _lag_ms_list else 0
    # 마지막 결과에서 플랫폼별 세부 통계 추출
    _lr = all_results[-1][1] if all_results else {}
    # 디바이스 정보 (TEST_ENV에 조회된 값 활용)
    _result_payload = {
        'dropout_count':        _total_dropped,
        'severity':             _final_severity,
        'report_path':          '' if args.mos_only else OUTPUT_HTML,
        'ios_visqol_mos':       _ios_mos,
        'android_visqol_mos':   _android_mos,
        # Android 세부
        'and_dropped_count':    _lr.get('and_dropped_count', 0),
        'and_degraded_count':   _lr.get('and_degraded_count', 0),
        'and_poor_count':       _lr.get('and_poor_count', 0),
        'and_severity':         _lr.get('and_severity', '없음'),
        # iOS 세부
        'ios_dropped_count':    _lr.get('ios_dropped_count', 0),
        'ios_degraded_count':   _lr.get('ios_degraded_count', 0),
        'ios_poor_count':       _lr.get('ios_poor_count', 0),
        'ios_severity':         _lr.get('ios_severity', '없음'),
        # 공통
        'voip_delay_ms':        _voip_delay_ms,
        # 디바이스 & 앱 버전
        'android_app_ver':      TEST_ENV.get('Android 앱 버전', ''),
        'ios_app_ver':          TEST_ENV.get('iOS 앱 버전', ''),
        'android_device':       TEST_ENV.get('Android 단말', ''),
        'android_os_ver':       TEST_ENV.get('Android OS 버전', ''),
        'ios_device':           TEST_ENV.get('iOS 단말', ''),
        'ios_os_ver':           TEST_ENV.get('iOS OS 버전', ''),
        'profile_name':         TEST_ENV.get('테스트 시나리오', ''),
    }
    print(f"ANALYSIS_RESULT_JSON:{_json_out.dumps(_result_payload)}", flush=True)
    if not args.no_open and not args.mos_only:
        os.system(f"open {OUTPUT_HTML}")


if __name__ == '__main__':
    main()
