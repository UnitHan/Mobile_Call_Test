"""
gemini_analysis.py
─────────────────────────────────────────────────────────────────────────────
Gemini API를 사용한 음성 통화 음단절 분석 로직.

analyze_hybrid.py 에서 분리된 모듈.
프롬프트 상수, 분석 실행, JSON 파싱을 담당한다.
"""
from __future__ import annotations

import json
import re

import numpy as np

from _hybrid_config import GEMINI_MODEL, MAX_CLIP_SEC
from audio_plots import to_wav_bytes

# ── 탐지 레이어 플래그 ────────────────────────────────────
USE_ENERGY_ALIGN = True   # ref_y 없으면 자동으로 Gemini 단독 fallback
USE_WHISPER      = False  # Whisper 제거됨 — 항상 False
_ENERGY_DETECT_INST = None   # EnergyAlignDetector 인스턴스 캐시

# ─────────────────────────────────────────────────────────────────────────────
# 프롬프트 템플릿
# ─────────────────────────────────────────────────────────────────────────────

# ── [모드 A] EnergyAlign/Whisper 탐지 결과 기반 — 원인 분석 전담 ──
GEMINI_CAUSE_PROMPT = """당신은 iOS VoIP 앱 오디오 파이프라인 전문가입니다.

=== 배경 ===
ixi-O iOS 앱이 발화한 음성이:
- 파일 1 (iPhone 로컬 녹음): 네트워크 미경유, 원본에 가장 가까움 → 기준  [첨부 audio #1]
- 파일 2 (Android 수신 녹음): VoIP 네트워크 경유 후 수신 → 진단 대상  [첨부 audio #2]

두 오디오 파일이 첨부되어 있습니다. **음질·음색·노이즈 평가는 하지 마십시오.**
오직 아래 목표에만 집중하십시오:
  ▶ 대본의 각 문장(또는 단어)이 파일 2(Android 수신)에서 **누락·묵음 처리되었는지** 확인
  ▶ 이미 Whisper + librosa로 확정된 음단절 목록의 **기술적 원인** 분석

새로운 타임스탬프를 생성하거나 기존 타임스탬프를 수정하지 마십시오.

=== 대본 ===
{script}

=== Whisper + librosa 확정 탐지 결과 ===
{whisper_context}

=== 당신의 역할 ===
아래 두 가지를 모두 수행하십시오.

**① Whisper 탐지 결과 정합성 검증 (가장 중요)**
Whisper가 탐지한 각 음단절 항목에 대해, 첨부 오디오를 직접 청음하여:
- 해당 타임스탬프 구간에 실제로 파일2(Android)에서 그 발화가 누락되었는지 확인
- Whisper 탐지 텍스트가 대본의 해당 문장과 의미적으로 일치하는지 판단
- 오탐(false positive)이라고 판단되면 명확히 표시

**② 기술적 원인 분석**
정합성이 확인된 음단절에 대해서만 iOS 앱 파이프라인 원인 분석.

아래 JSON 형식으로만 답변 (마크다운 코드 블록 포함, 다른 설명 없이):
```json
{{
  "listening_summary": "대본 기준 파일2(Android 수신)에서 누락된 문장/단어 목록 요약 (2~3문장, 음질 평가 없이 누락 사실만 기술)",
  "whisper_validation": [
    {{
      "index": 1,
      "whisper_text": "Whisper가 탐지한 누락 텍스트 원문",
      "script_sentence": "대본의 해당 원문 문장",
      "verified": true,
      "verdict": "confirmed",
      "reason": "파일2 해당 구간에서 실제로 묵음 확인, 대본 문장과 일치"
    }}
  ],
  "root_cause": "iOS AudioSession/AVAudioEngine/VAD/RTP 패킷 전송 관점에서 가장 유력한 원인 (구체적 컴포넌트명 포함)",
  "dev_pain_points": [
    "[iOS] 점검: ...",
    "[Android 수신측] 점검(해당시): ...",
    "[공통] 점검: ..."
  ],
  "severity": "없음/경미/보통/심각"
}}
```
whisper_validation 배열은 Whisper 탐지 결과 목록과 **같은 순서·같은 개수**로 채우십시오.
verdict 값: "confirmed"(맞음) / "false_positive"(오탐) / "uncertain"(불확실)"""

# ── [모드 B] Gemini 단독 방식 (fallback) ──
GEMINI_PROMPT = """당신은 VoIP 앱 통화 품질 QA 전문가이자 모바일 오디오 아키텍처 전문가입니다.

=== 테스트 녹음 구조 ===
- **파일 1 (iPhone 로컬 녹음)**: iOS ixi-O 앱 발화를 iPhone이 자체 녹음 → 기준 파일
- **파일 2 (Android 수신 녹음)**: 동일 발화가 VoIP 네트워크 경유 Android 수신 → 진단 대상

대본 기준으로 파일 2에서 누락된 발화를 찾아 iOS ixi-O 앱 오디오 파이프라인 결함을 진단하십시오.
**음질·음색·노이즈·열화·금속음 평가는 일절 하지 마십시오. 오직 음단절(누락 발화)만 분석하십시오.**

=== 대본 ===
{script}

=== librosa 에너지 힌트 ===
{hints_json}

아래 JSON 형식으로만 답변 (마크다운 코드 블록 포함, 다른 설명 없이):
```json
{{
  "listening_summary": "대본 기준 파일2(Android 수신)에서 누락된 문장/단어 목록 요약 (음질 평가 없이 누락 사실만 기술, 2~3문장)",
  "initial_dropout": {{
    "local_detected": false,
    "remote_detected": true,
    "local_first_ms": 200,
    "remote_first_ms": 3800,
    "cut_content": "누락된 대본 내용",
    "duration_ms": 3600
  }},
  "mid_call_dropouts": [
    {{
      "timestamp_ref_ms": 12500,
      "duration_ms": 800,
      "script_expected": "이 시점 예상 발화",
      "local_actual": "파일1 실제 내용",
      "remote_actual": "묵음",
      "dropout_in": "수신만",
      "confidence": "high"
    }}
  ],
  "root_cause": "iOS ixi-O 앱 AudioSession/AVAudioEngine/VAD/네트워크 전송 로직 관점 원인",
  "dev_pain_points": ["[iOS] 점검: ...", "[Android 수신측] 점검: ...", "[공통] 점검: ..."],
  "severity": "없음/경미/보통/심각"
}}
```"""


# ─────────────────────────────────────────────────────────────────────────────
# 탐지 결과 직렬화
# ─────────────────────────────────────────────────────────────────────────────

def _dropouts_to_json_list(whisper_result) -> list[dict]:
    """DropoutSegment 리스트를 dict 리스트로 직렬화 (Gemini 프롬프트용)."""
    out = []
    for d in whisper_result.dropouts:
        if isinstance(d, dict):
            out.append({
                'timestamp_ref_ms': d.get('start_ms', 0),
                'duration_ms':      d.get('duration_ms', 0),
                'missing_text':     d.get('missing_text', ''),
                'script_context':   d.get('script_context', d.get('missing_text', '')),
                'dropout_in':       d.get('dropout_in', '수신만'),
                'energy_ratio':     d.get('energy_ratio', 0.0),
                'confidence':       d.get('confidence', 'medium'),
            })
        else:
            out.append({
                'timestamp_ref_ms': getattr(d, 'start_ms', 0),
                'duration_ms':      getattr(d, 'duration_ms', 0),
                'missing_text':     getattr(d, 'missing_text', ''),
                'script_context':   getattr(d, 'script_context',
                                            getattr(d, 'missing_text', '')),
                'dropout_in':       getattr(d, 'dropout_in', '수신만'),
                'energy_ratio':     getattr(d, 'energy_ratio', 0.0),
                'confidence':       getattr(d, 'confidence', 'medium'),
            })
    return out


def _dropouts_to_gemini_context(whisper_result) -> str:
    """음단절 목록을 Gemini 원인 분석 프롬프트에 삽입할 텍스트로 변환."""
    items = _dropouts_to_json_list(whisper_result)
    if not items:
        return "음단절 탐지 없음"
    lines = []
    for i, d in enumerate(items, 1):
        ts_s = d['timestamp_ref_ms'] / 1000
        lines.append(
            f"[{i}] {ts_s:.2f}s +{d['duration_ms']}ms "
            f"confidence={d['confidence']} ratio={d['energy_ratio']:.3f} "
            f"text=\"{d['missing_text'][:40]}\""
        )
    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Gemini JSON 파싱
# ─────────────────────────────────────────────────────────────────────────────

def _parse_gemini_json(raw: str) -> dict:
    """Gemini 응답에서 JSON 블록을 추출·정제 후 파싱."""
    candidates: list[str] = []
    fence_re = re.compile(r'```(?:json)?\s*([\s\S]*?)```', re.IGNORECASE)
    for m in fence_re.finditer(raw):
        c = m.group(1).strip()
        if c.startswith('{') or c.startswith('['):
            candidates.append(c)
    if not candidates:
        candidates = [raw.strip()]

    def _fixup(s: str) -> str:
        # 후행 쉼표 제거
        s = re.sub(r',\s*([}\]])', r'\1', s)
        # // 주석 제거
        s = re.sub(r'//[^\n]*', '', s)
        # # 주석 제거 (값 자리 아닐 때)
        s = re.sub(r'([,{\[]\s*)#[^\n]*', r'\1', s)
        # 한글 설명문이 따옴표 없이 삽입된 경우 → 빈 문자열로 교체
        s = re.sub(r':\s*(?=[가-힣])', ': "', s)
        s = re.sub(r'([가-힣]+)\s*(?=[,}\]])', r'\1"', s)
        return s

    for c in candidates:
        for text in (c, _fixup(c)):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue

    return {"error": "JSON 파싱 전체 실패", "raw": raw[:2000]}


# ─────────────────────────────────────────────────────────────────────────────
# 초기 누락 내용 추출
# ─────────────────────────────────────────────────────────────────────────────

def _find_cut_content(whisper_result) -> str:
    """초기 묵음 구간(0 ~ remote_first_ms)에서 누락된 발화 텍스트 추출."""
    cutoff_ms = whisper_result.remote_first_ms
    if cutoff_ms <= 200:
        return ""
    cut_words = [
        w.word for w in whisper_result.local_words
        if w.start_ms < cutoff_ms
    ]
    return " ".join(cut_words) if cut_words else ""


# ─────────────────────────────────────────────────────────────────────────────
# Gemini 분석 메인
# ─────────────────────────────────────────────────────────────────────────────

def gemini_hybrid_analyze(client, call_label: str,
                           ios_y: np.ndarray, and_y: np.ndarray,
                           suspicious_hints: list, script: str = "",
                           whisper_result=None) -> dict:
    """
    USE_WHISPER=True  → EnergyAlign/Whisper 탐지 결과를 입력받아 Gemini는 원인 분석만.
    USE_WHISPER=False → Gemini 단독 방식 (fallback).
    """
    from google.genai import types  # type: ignore

    # ── Mode A: 3-Layer (Whisper/EnergyAlign + librosa + Gemini 청음) ────
    if USE_WHISPER and whisper_result is not None and whisper_result.error is None:
        whisper_ctx = _dropouts_to_gemini_context(whisper_result)
        prompt = GEMINI_CAUSE_PROMPT.format(script=script, whisper_context=whisper_ctx)

        ios_wav = to_wav_bytes(ios_y, clip_sec=MAX_CLIP_SEC)
        and_wav = to_wav_bytes(and_y, clip_sec=MAX_CLIP_SEC)

        resp = None
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=ios_wav, mime_type="audio/wav"),
                    types.Part.from_bytes(data=and_wav, mime_type="audio/wav"),
                    prompt,
                ]
            )
            gemini_json = _parse_gemini_json(resp.text.strip())
        except json.JSONDecodeError as e:
            raw_preview = (resp.text[:2000] if resp else "")
            gemini_json = {"error": f"JSON 파싱 실패: {e}", "raw": raw_preview}
        except Exception as e:
            gemini_json = {"error": str(e)}

        initial_dropout = {
            "local_detected":  whisper_result.local_first_ms > 500,
            "remote_detected": whisper_result.remote_first_ms > 500,
            "local_first_ms":  whisper_result.local_first_ms,
            "remote_first_ms": whisper_result.remote_first_ms,
            "duration_ms":     max(0, whisper_result.remote_first_ms
                                      - whisper_result.local_first_ms),
            "cut_content":     _find_cut_content(whisper_result),
        }

        mid_dropouts = []
        validations  = gemini_json.get("whisper_validation", [])
        for idx_d, d in enumerate(_dropouts_to_json_list(whisper_result)):
            script_ctx   = d.get("script_context", "").strip()
            display_text = script_ctx if script_ctx else d["missing_text"]
            val = validations[idx_d] if idx_d < len(validations) else {}
            mid_dropouts.append({
                "timestamp_ref_ms": d["timestamp_ref_ms"],
                "duration_ms":      d["duration_ms"],
                "missing_text":     d["missing_text"],
                "script_expected":  display_text,
                "local_actual":     display_text,
                "remote_actual":    "묵음",
                "dropout_in":       d["dropout_in"],
                "energy_ratio":     d["energy_ratio"],
                "confidence":       d["confidence"],
                "source":           "whisper+librosa",
                "gemini_verdict":   val.get("verdict", ""),
                "gemini_reason":    val.get("reason",  ""),
            })

        return {
            "listening_summary":  gemini_json.get("listening_summary", ""),
            "initial_dropout":    initial_dropout,
            "mid_call_dropouts":  mid_dropouts,
            "root_cause":         gemini_json.get("root_cause", ""),
            "dev_pain_points":    gemini_json.get("dev_pain_points", []),
            "severity":           gemini_json.get("severity", "확인불가"),
            "whisper_validation": gemini_json.get("whisper_validation", []),
            "detection_source":   "whisper+librosa+gemini(audio)",
            "_gemini_raw":        gemini_json,
        }

    # ── Mode B: Gemini 단독 (fallback) ───────────────────────────────
    ios_wav = to_wav_bytes(ios_y, clip_sec=MAX_CLIP_SEC)
    and_wav = to_wav_bytes(and_y, clip_sec=MAX_CLIP_SEC)

    hints_list = [
        {
            "start_sec":         round(s, 2),
            "end_sec":           round(e, 2),
            "ios_rms":           round(ir, 5),
            "android_rms":       round(ar, 5),
            "android_ios_ratio": round(r, 3),
        }
        for s, e, ir, ar, r in suspicious_hints
    ]
    hints_json_str = json.dumps(hints_list, ensure_ascii=False, indent=2)
    prompt = GEMINI_PROMPT.format(
        call_label=call_label, script=script, hints_json=hints_json_str
    )

    resp = None
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=ios_wav, mime_type="audio/wav"),
                types.Part.from_bytes(data=and_wav, mime_type="audio/wav"),
                prompt,
            ]
        )
        result = _parse_gemini_json(resp.text.strip())
        result["detection_source"] = "gemini-only"
        return result
    except json.JSONDecodeError as e:
        raw_preview = (resp.text[:2000] if resp else "")
        return {"error": f"JSON 파싱 실패: {e}", "raw": raw_preview,
                "detection_source": "gemini-only"}
    except Exception as e:
        return {"error": str(e), "detection_source": "gemini-only"}
