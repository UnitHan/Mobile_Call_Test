#!/usr/bin/env python3
"""녹음본 볼륨을 정답지(레퍼런스)와 동일하게 맞추는 스크립트.

RMS 기반으로 정답지의 평균 볼륨을 측정한 후,
녹음본에 gain을 적용하여 동일 RMS로 조정합니다.
샘플레이트 차이(44100 vs 48000)는 볼륨 조정에 영향 없으므로 그대로 유지합니다.
"""
import sys
import numpy as np
import soundfile as sf
from pathlib import Path


def rms_dbfs(data: np.ndarray) -> float:
    """오디오 데이터의 RMS를 dBFS로 반환."""
    rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
    if rms < 1e-10:
        return -200.0
    return 20.0 * np.log10(rms)


def peak_dbfs(data: np.ndarray) -> float:
    """오디오 데이터의 peak를 dBFS로 반환."""
    peak = np.max(np.abs(data.astype(np.float64)))
    if peak < 1e-10:
        return -200.0
    return 20.0 * np.log10(peak)


def normalize_to_reference(ref_path: str, rec_path: str, out_path: str | None = None):
    """녹음본 볼륨을 정답지 RMS에 맞춰 조정.
    
    Args:
        ref_path: 정답지 WAV 경로
        rec_path: 녹음본 WAV 경로
        out_path: 출력 경로 (None이면 _normalized 접미사 추가)
    """
    # 정답지 읽기
    ref_data, ref_sr = sf.read(ref_path, dtype='float64')
    if ref_data.ndim > 1:
        ref_data = np.mean(ref_data, axis=1)  # 스테레오 → 모노 평균
    ref_rms = rms_dbfs(ref_data)
    ref_peak = peak_dbfs(ref_data)

    # 녹음본 읽기
    rec_data, rec_sr = sf.read(rec_path, dtype='float64')
    is_stereo = rec_data.ndim > 1
    if is_stereo:
        # 스테레오: 채널별 평균 RMS로 gain 계산, 양 채널에 동일 gain 적용
        rec_mono = np.mean(rec_data, axis=1)
    else:
        rec_mono = rec_data
    rec_rms = rms_dbfs(rec_mono)
    rec_peak = peak_dbfs(rec_mono)

    # gain 계산 (dB 차이 → 선형 배율)
    gain_db = ref_rms - rec_rms
    gain_linear = 10.0 ** (gain_db / 20.0)

    # gain 적용
    adjusted = rec_data * gain_linear

    # 클리핑 방지: peak가 0 dBFS를 초과하면 리미팅
    adj_peak = np.max(np.abs(adjusted))
    if adj_peak > 1.0:
        print(f"  ⚠️ 클리핑 감지 (peak={20*np.log10(adj_peak):.1f} dBFS) → 리미팅 적용")
        adjusted = adjusted / adj_peak * 0.99

    # 출력 경로
    if out_path is None:
        p = Path(rec_path)
        out_path = str(p.parent / f"{p.stem}_normalized{p.suffix}")

    # 저장 (원본 샘플레이트 유지)
    sf.write(out_path, adjusted, rec_sr, subtype='PCM_16')

    # 검증
    verify_data, _ = sf.read(out_path, dtype='float64')
    if verify_data.ndim > 1:
        verify_mono = np.mean(verify_data, axis=1)
    else:
        verify_mono = verify_data
    final_rms = rms_dbfs(verify_mono)
    final_peak = peak_dbfs(verify_mono)

    return {
        'ref_rms': ref_rms, 'ref_peak': ref_peak,
        'rec_rms': rec_rms, 'rec_peak': rec_peak,
        'gain_db': gain_db,
        'final_rms': final_rms, 'final_peak': final_peak,
        'out_path': out_path,
    }


def main():
    ref_path = "/Users/qabulls/Downloads/A_dating_couple.wav"
    rec_dir = "/Users/qabulls/Documents/sound/audio_files/recordings/collected"
    rec_files = [
        f"{rec_dir}/Android_ixiO_20260326_110205.wav",
        f"{rec_dir}/iOS_ixiO_20260326_110205.wav",
    ]

    print(f"{'='*60}")
    print(f"  녹음본 볼륨 → 정답지 볼륨 매칭")
    print(f"{'='*60}")
    print(f"📂 정답지: {Path(ref_path).name}")

    # 정답지 정보
    ref_data, ref_sr = sf.read(ref_path, dtype='float64')
    if ref_data.ndim > 1:
        ref_mono = np.mean(ref_data, axis=1)
    else:
        ref_mono = ref_data
    print(f"   SR={ref_sr}Hz, {len(ref_mono)/ref_sr:.1f}s, "
          f"RMS={rms_dbfs(ref_mono):.1f} dBFS, Peak={peak_dbfs(ref_mono):.1f} dBFS\n")

    for rec_path in rec_files:
        if not Path(rec_path).exists():
            print(f"❌ 파일 없음: {rec_path}")
            continue

        print(f"{'─'*60}")
        print(f"📁 녹음본: {Path(rec_path).name}")

        result = normalize_to_reference(ref_path, rec_path)

        print(f"  [Before] RMS={result['rec_rms']:.1f} dBFS, Peak={result['rec_peak']:.1f} dBFS")
        print(f"  [Target] RMS={result['ref_rms']:.1f} dBFS (정답지)")
        print(f"  [Gain]   {result['gain_db']:+.1f} dB")
        print(f"  [After]  RMS={result['final_rms']:.1f} dBFS, Peak={result['final_peak']:.1f} dBFS")
        print(f"  ✅ 저장: {result['out_path']}")
        print()

    print(f"{'='*60}")
    print(f"완료! _normalized 접미사가 붙은 파일이 생성되었습니다.")


if __name__ == '__main__':
    main()
