"""
_hybrid_config.py
─────────────────────────────────────────────────────────────────────────────
analyze_hybrid 계열 모듈이 공유하는 상수·설정값.

각 모듈이 여기서 import 하므로 순환 의존성 없이 설정값을 공유할 수 있다.
"""
from __future__ import annotations

import os
from pathlib import Path

_BASE_DIR      = Path(__file__).parent
_REF_DIR       = _BASE_DIR / "reference_audio"
RECORDINGS_DIR = str(_BASE_DIR / "recordings")
COLLECTED_DIR  = str(_BASE_DIR / "audio_files" / "recordings" / "collected")
ENV_FILE       = str(_BASE_DIR / "env")
OUTPUT_HTML    = str(_BASE_DIR / "hybrid_report.html")

MAX_CLIP_SEC: float | None = None  # 오디오 클립 최대 길이 (None=전체)

# ── 테스트 환경 정보 ──
TEST_ENV: dict[str, str] = {
    "앱 이름":          "ixi-O",
    "테스트 일시":      "",
    "테스트 시나리오":  "",   # 음원 프로파일명 (앱에서 --profile-name 로 주입)
    "테스트 환경":      "실제 디바이스 통화 녹음 비교",
    "Android 앱 버전": "",
    "Android 단말":     "",   # 동적으로 채워짐
    "Android OS 버전": "",   # 동적으로 채워짐
    "iOS 앱 버전":      "",   # 동적으로 채워짐
    "iOS 단말":         "",   # 동적으로 채워짐
    "iOS OS 버전":      "",   # 동적으로 채워짐
    "분석 도구":        "대본 cross-correlation + ViSQOL MOS",
    "작성자":           "",
}

# ── 음원 정답지 (화자별 분리) ──
# AUDIO_REFERENCE: 레거시 호환용 — 양쪽 공통 정답지 (단일 파일)
AUDIO_REFERENCE: dict[int, str] = {
    1: str(_REF_DIR / "audiomass-output_mono.wav"),
    2: "",
}
# AUDIO_REFERENCE_IOS: iOS 수신 녹음용 정답지 (iPhone이 수신한 음원의 원본)
# AUDIO_REFERENCE_ANDROID: Android 수신 녹음용 정답지 (Android가 수신한 음원의 원본)
# S1→iPhone 입력→iPhone 전송→Android 수신, S2→Android 입력→Android 전송→iPhone 수신
# 비어 있으면 AUDIO_REFERENCE 값으로 폴백
AUDIO_REFERENCE_IOS: dict[int, str] = {
    1: str(_REF_DIR / "dating_SPEAKER_01.wav"),   # S2→Android에 입력→iPhone이 수신
}
AUDIO_REFERENCE_ANDROID: dict[int, str] = {
    1: str(_REF_DIR / "dating_SPEAKER_00.wav"),   # S1→iPhone에 입력→Android가 수신
}

# ── 보이스피싱 정답지 (TC_03/TC_04 전용, 화자별 분리) ──
VISHING_REF_PATH: str = str(_REF_DIR / "audiomass-output_mono.wav")  # 레거시 호환
VISHING_REF_IOS: dict[int, str] = {
    1: str(_REF_DIR / "vishing_SPEAKER_01.wav"),   # 피해자(김버그) → iPhone 수신
}
VISHING_REF_ANDROID: dict[int, str] = {
    1: str(_REF_DIR / "vishing_SPEAKER_00.wav"),   # 가해자(박편육/임채팅) → Android 수신
}

# ── 통화별 메타데이터 ── (비워둠 → 파일명 기반 자동 생성)
CALL_META: dict[int, dict] = {}
