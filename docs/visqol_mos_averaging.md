# ViSQOL MOS 평균 산출 — NSIM 역함수 적용 테크니컬 노트

작성일: 2026-04-08  
관련 파일: `audio_quality.py`, `analyze_hybrid.py`

---

## 1. 문제 배경

ViSQOL이 출력하는 MOS-LQO 점수는 **비선형(exponential) 매핑**을 거친 값이다.  
복수 음원의 품질을 집계할 때 MOS 점수를 직접 산술평균하면 지각 품질 도메인이 왜곡된다.

### 단순 산술평균의 문제 예시

| 음원 | NSIM (선형 공간) | MOS-LQO |
|------|-----------------|---------|
| A    | 0.95            | 4.80    |
| B    | 0.30            | 2.03    |
| **NSIM 평균 → MOS** | **0.625 → 3.68** | |
| **MOS 직접 평균** | | **3.42** |

두 방법의 차이: **0.26 MOS** — 이는 '보통(Fair)' vs '양호(Fair~Good)' 등급 경계에 해당할 수 있다.

---

## 2. ViSQOL 내부 매핑 함수

소스: `visqol-3.3.3/src/speech_similarity_to_quality_mapper.cc`

```cpp
constexpr double kFitParameterA  = -262.847869;
constexpr double kFitParameterB  =    0.0154302525;
constexpr double kFitParameterX0 = -361.063949;
constexpr double kFitScale       =    1.245063;   // scale_to_max_mos=True 시

// NSIM → MOS
double mos_raw = A + exp(B * (NSIM - X0));
double mos     = clamp(mos_raw * scale, 1.0, 5.0);
```

`ExponentialFromFit` 함수 (`visqol-3.3.3/src/misc_math.cc`):

$$\text{MOS\_raw} = A + e^{B \cdot (\text{NSIM} - X_0)}$$

Python API (`visqol_lib_py`)는 `Init(..., True, ...)` 호출로 `scale_to_max_mos=True`를 기본 적용한다.  
→ NSIM=1.0이 MOS≈5.0으로 정규화된다.

---

## 3. 역함수 도출

MOS → NSIM 역산:

$$\text{NSIM} = X_0 + \frac{\ln\!\left(\dfrac{\text{MOS}}{\text{scale}} - A\right)}{B}$$

`scale=1.245063` (scale_to_max_mos=True 기준)

Python 구현 (`audio_quality.py`):

```python
_VISQOL_A     = -262.847869
_VISQOL_B     =    0.0154302525
_VISQOL_X0    = -361.063949
_VISQOL_SCALE =    1.245063

def visqol_mos_to_nsim(mos: float, scaled: bool = True) -> float:
    mos_unscaled = mos / _VISQOL_SCALE if scaled else mos
    inner = mos_unscaled - _VISQOL_A
    if inner <= 0:
        return 0.0
    return _VISQOL_X0 + math.log(inner) / _VISQOL_B
```

---

## 4. 올바른 평균 산출 절차

```
MOS₁, MOS₂, ..., MOSₙ
    ↓ 각각 역산
NSIM₁, NSIM₂, ..., NSIMₙ   ← 지각 선형 공간
    ↓ 산술평균
NSIM_mean
    ↓ 순방향 변환
MOS_mean                     ← 최종 대표값
```

Python (`visqol_mos_mean` in `audio_quality.py`):

```python
def visqol_mos_mean(mos_scores: list[float], scaled: bool = True) -> float:
    nsim_values = [visqol_mos_to_nsim(m, scaled) for m in mos_scores]
    nsim_mean   = sum(nsim_values) / len(nsim_values)
    return round(visqol_nsim_to_mos(nsim_mean, scaled), 3)
```

---

## 5. 수정 전/후 집계 로직 비교 (`analyze_hybrid.py`)

### 수정 전 (버그)
```python
# 루프를 돌며 계속 덮어씀 → 마지막 음원 값만 전달
for _lbl, _mres in mos_rows:
    if _mres.get('ios_visqol_mos') is not None:
        _ios_mos = _mres['ios_visqol_mos']   # 마지막 값만 남음
```

### 수정 후
```python
# 전체 점수 수집 후 NSIM 공간 평균
_ios_mos_list = [m['ios_visqol_mos'] for _, m in mos_rows if m.get('ios_visqol_mos')]
_ios_mos = visqol_mos_mean(_ios_mos_list) if _ios_mos_list else None
```

---

## 6. 유효 NSIM 범위

| MOS-LQO | NSIM (역산, scaled=True) |
|---------|------------------------|
| 5.0     | ≈ 1.000                |
| 4.5     | ≈ 0.862                |
| 4.0     | ≈ 0.754                |
| 3.5     | ≈ 0.658                |
| 3.0     | ≈ 0.565                |
| 2.5     | ≈ 0.469                |
| 2.0     | ≈ 0.364                |

NSIM은 선형에 가까운 지각 유사도 지표이므로 이 공간에서의 산술평균이 의미론적으로 타당하다.

---

## 7. 참고 문헌

- Hines, A. et al. "ViSQOL v3: An Open Source Production Ready Objective Speech and Audio Metric." QoMEX 2020.
- `visqol-3.3.3/src/speech_similarity_to_quality_mapper.cc`
- `visqol-3.3.3/src/misc_math.cc`
- ITU-T P.800: Methods for subjective determination of transmission quality.
