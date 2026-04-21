"""audio_lib.consts — 오디오 분석 공통 상수

모든 analyze_*.py, script_gap_detector.py, gap_detector.py 에서 공유합니다.
값을 수정하면 전체 분석 파이프라인에 즉시 반영됩니다.
"""

# ── 기본 녹음 포맷 ─────────────────────────────────────────────
SR           = 16000    # 통화 대역 샘플링 레이트 (16kHz)

# ── RMS 프레임 설정 ────────────────────────────────────────────
# 전 분석 파일 통일: RMS_HOP=128 (8ms 해상도)
# 이전 analyze_waveform_compare / analyze_waveform_gemini 는 256 사용 → 128 로 통합
# (MIN_DROPOUT_FRAMES= 해당 파일에서 4→8 로 조정해 동일 64ms 최소 기준 유지)
RMS_FRAME    = 512      # RMS 프레임 크기 — 32ms @ 16kHz
RMS_HOP      = 128      # RMS hop 크기   — 8ms 해상도

# ── energy_profile 프레임 설정 ─────────────────────────────────
# script_gap_detector.py / gap_detector.py 의 dB 에너지 계산에 사용
FRAME_MS     = 20       # 에너지 프레임 크기 (ms)

# ── 음단절 판정 dB 임계값 ──────────────────────────────────────
SILENCE_DB   = -50.0    # 이 dB 이하 → 무음 (MIC 녹음 기준)
REF_MIN_DB   = -45.0    # 정답지(ref)가 이 dB 이하 → 원래 묵음 → 음단절 판정 제외

# ── RMS 비율 기반 드롭아웃 임계값 ──────────────────────────────
DROPOUT_RATIO = 0.08    # 평균 RMS 대비 이 비율 이하 → 무음
