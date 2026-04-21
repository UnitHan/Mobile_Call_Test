# Audio Quality Analyzer

ref(원본 전송음)와 dif(수신 녹음본) WAV 파일을 비교하여 지연 보정, 이상 구간 검출(묵음/깨짐), 음질 지표, 스펙트럼 분석을 수행하는 데스크톱 도구입니다.

## 핵심 기능

- Cross-correlation + DTW 기반 지연 추정 및 자동 보정
- 주변 대비 ratio 급변 + correlation 기반 이상 구간 검출 (묵음/깨짐)
- 음질 지표: SNR, PESQ, STOI, RMS diff, Clipping, Noise Floor
- 스펙트럼 분석: Spectrogram, Spectral Centroid/Rolloff, Pitch, ZCR
- JSON / CSV / PNG / HTML 결과 내보내기
- PyQt5 다크 테마 GUI, 듀얼 페어 비교 분석

## 이상 검출 알고리즘

ref 대비 dif의 묵음과 음깨짐을 사람이 느끼는 수준으로 감지합니다.

- 프레임별 ref/dif RMS, peak, correlation 계산 (20ms 프레임, 10ms 홉)
- 주변 1초 구간의 ratio 중앙값 대비 급격한 하락 검출
- `digital_zero` (묵음): dif peak < `zero_peak_threshold` + ref RMS > `speech_strong_rms`, 최소 `min_anomaly_ms`
- `gain_drop` (깨짐 Type A): ratio < context_med × `gain_drop_ratio` + correlation > `gain_drop_min_corr`, 최소 `min_anomaly_ms`
- `gain_drop` (깨짐 Type B): ratio < context_med × `gain_drop_ratio_strict` + `min_anomaly_b_ms` 이상 지속 (gap `anomaly_gap_frames` 허용)
- 직전 200ms에서 dif 활성 신호가 없었던 자연 전환 구간은 오탐으로 제외
- 묵음 직후 200ms 이내의 distortion은 복구 과정으로 제외

---

### 이상 검출 상세 로직 (기술 버전)

이 섹션은 `silence_metrics.detect_anomalies()` 함수의 내부 동작을 단계별로 설명합니다.
모든 임계값은 `AnalysisConfig` 파라미터로 GUI에서 조정 가능하며, 괄호 안은 기본값입니다.

#### 1단계: 프레임 분할 및 특성 추출

오디오를 `anomaly_frame_ms`(20ms) 길이, `anomaly_hop_ms`(10ms) 간격으로 프레임 분할합니다.
각 프레임에서 4가지 특성을 계산합니다:

| 특성 | 계산식 | 의미 |
|---|---|---|
| `ref_rms` | √(mean(ref_frame²)) | ref 프레임의 에너지 크기 |
| `dif_rms` | √(mean(dif_frame²)) | dif 프레임의 에너지 크기 |
| `dif_peak` | max(\|dif_frame\|) | dif 프레임의 최대 진폭 |
| `frame_corr` | Pearson correlation(ref_frame, dif_frame) | ref-dif 파형 유사도 (-1~1) |

추가로 두 가지 파생값을 계산합니다:

- `speech`: ref_rms > `ref_silence_rms`(0.005) — ref에 신호가 존재하는 프레임
- `ratio`: dif_rms / ref_rms — ref 대비 dif의 에너지 비율 (ref_rms ≤ 0.005이면 1.0으로 처리)

#### 2단계: 주변 ratio 중앙값 (context_med) 계산

각 프레임 i에 대해 주변 ±1초(±100프레임) 범위에서 현재 ±200ms(±20프레임)를 제외한 구간의 ratio 중앙값을 계산합니다.

```
context 범위: [i-100, i-20) ∪ (i+20, i+100]
대상: speech=True인 프레임의 ratio만 수집
조건: 수집된 값이 6개 이상일 때만 중앙값 계산, 미만이면 1.0
```

현재 프레임 근처(±200ms)를 제외하는 이유는 이상 구간 자체의 값이 중앙값을 오염시키는 것을 방지하기 위함입니다.

#### 3단계: 묵음 (digital_zero) 검출

두 조건을 동시에 만족하는 프레임을 묵음 후보로 마킹합니다:

```
speech_strong: ref_rms > speech_strong_rms (0.03)  ← ref에 확실한 음성이 있고
zero_mask:     dif_peak < zero_peak_threshold (0.0005)  ← dif는 거의 무음
```

연속된 묵음 프레임을 구간으로 병합하고, `min_anomaly_ms`(50ms) = 5프레임 미만인 구간은 제거합니다.

#### 4단계: 자연 전환 구간 오탐 제외

묵음 구간 직전 200ms(20프레임)에서 dif_peak의 최대값을 확인합니다:

```
prior_dif_peak_max = max(dif_peak[seg_start - 20 : seg_start])
if prior_dif_peak_max < prior_activity_threshold (0.01):
    → 제외 (직전에 dif도 묵음이었으므로 자연 전환 구간)
```

이 필터는 ref가 먼저 음성을 시작하고 dif가 전송 지연으로 아직 시작하지 않은 구간을 오탐에서 제외합니다.
진짜 묵음은 직전에 dif에 활발한 음성(peak > 0.01)이 있다가 갑자기 dif만 무음이 되는 패턴입니다.

#### 5단계: 깨짐 Type A (gain_drop, correlation 기반) 검출

네 조건을 동시에 만족하는 프레임을 깨짐 A 후보로 마킹합니다:

```
speech_strong:  ref_rms > speech_strong_rms (0.03)       ← ref에 확실한 음성
ratio_drop:     ratio < context_med × gain_drop_ratio (0.4)  ← 주변 대비 ratio 60%+ 하락
not_zero:       dif_peak ≥ 0.001                         ← dif에 신호가 존재 (묵음 아님)
high_corr:      frame_corr > gain_drop_min_corr (0.3)    ← 파형 모양은 유사 (gain만 변화)
```

연속 구간 병합 후 `min_anomaly_ms`(50ms) 미만 제거.

Type A는 "파형은 같은데 볼륨만 줄어든" 패턴을 잡습니다. correlation이 높다는 것은 신호의 형태가 보존되어 있다는 의미입니다.

#### 6단계: 깨짐 Type B (gain_drop, 장시간 지속 기반) 검출

Type A에 해당하지 않는 프레임 중 더 엄격한 조건을 적용합니다:

```
speech_strong:      ref_rms > speech_strong_rms (0.03)
ratio_drop_strict:  ratio < context_med × gain_drop_ratio_strict (0.35)  ← 더 극단적 하락
not_zero:           dif_peak ≥ 0.001
not_type_a:         Type A에 해당하지 않는 프레임
```

gap 허용 병합: `anomaly_gap_frames`(3) 이하의 비이상 프레임을 무시하고 연속으로 취급합니다.
`min_anomaly_b_ms`(120ms) = 12프레임 미만인 구간은 제거합니다.

Type B는 correlation이 낮아 파형 자체가 변형된 경우를 잡습니다. 오탐 방지를 위해 더 엄격한 ratio 임계값과 긴 최소 지속시간을 요구합니다.

#### 7단계: 묵음 직후 복구 구간 제외

묵음(digital_zero) 구간 종료 후 200ms 이내에 시작하는 Type B 깨짐은 제외합니다:

```
for each gain_b_seg:
    if any(|gain_b_seg.start - silence_seg.end| < 200ms):
        → 제외
```

묵음 직후에는 신호가 복구되는 과도 구간이 존재하며, 이 구간의 ratio 하락은 정상적인 복구 과정입니다.

#### 8단계: 결과 조립

검출된 모든 구간을 `AnomalySegment`로 변환하고 시간순 정렬합니다:

| 필드 | 묵음 (digital_zero) | 깨짐 (gain_drop) |
|---|---|---|
| `anomaly_type` | `"digital_zero"` | `"gain_drop"` |
| `mean_gain_db` | -100.0 (고정) | 20 × log10(구간 평균 ratio) |
| `mean_correlation` | 구간 평균 frame_corr | 구간 평균 frame_corr |

#### 파라미터 요약

| 파라미터 | 기본값 | 역할 |
|---|---|---|
| `speech_strong_rms` | 0.03 | ref 확실한 음성 판정 RMS |
| `zero_peak_threshold` | 0.0005 | dif 디지털 제로 판정 peak |
| `gain_drop_ratio` | 0.4 | 깨짐 A: 주변 대비 ratio 임계값 |
| `gain_drop_ratio_strict` | 0.35 | 깨짐 B: 더 엄격한 ratio 임계값 |
| `gain_drop_min_corr` | 0.3 | 깨짐 A: 최소 파형 상관계수 |
| `prior_activity_threshold` | 0.01 | 직전 dif 활성 판정 peak |
| `min_anomaly_ms` | 50 | 묵음/깨짐 A 최소 지속 시간 (ms) |
| `min_anomaly_b_ms` | 120 | 깨짐 B 최소 지속 시간 (ms) |
| `anomaly_gap_frames` | 3 | 깨짐 B gap 허용 프레임 수 |

---

### 이상 검출 상세 로직 (쉬운 설명 버전)

이 섹션은 오디오 신호 처리에 익숙하지 않은 분을 위해 같은 알고리즘을 비유와 함께 풀어서 설명합니다.

#### 이 도구가 하는 일

전화 통화를 녹음했다고 생각해 보세요. 한쪽은 보내는 쪽의 원본 음성(ref), 다른 한쪽은 받는 쪽에서 녹음한 음성(dif)입니다. 이 도구는 두 녹음을 비교해서 "받는 쪽에서 소리가 끊기거나 이상하게 들린 구간"을 자동으로 찾아줍니다.

찾을 수 있는 이상은 두 가지입니다:
- 묵음 (digital_zero): 원본에는 말소리가 있는데, 수신 녹음에서는 완전히 소리가 사라진 구간
- 깨짐 (gain_drop): 원본에는 정상 볼륨의 말소리가 있는데, 수신 녹음에서는 볼륨이 갑자기 크게 줄어든 구간

#### 어떻게 찾나요?

##### 1. 음성을 잘게 자릅니다

두 녹음을 0.02초(20밀리초)짜리 조각으로 자릅니다. 0.01초(10밀리초)씩 겹치면서 자르기 때문에 빠짐없이 전체를 살펴볼 수 있습니다.

비유하면, 긴 종이 테이프를 2cm 간격으로 자르되 1cm씩 겹치게 자르는 것과 같습니다.

##### 2. 각 조각의 "크기"와 "모양"을 측정합니다

각 조각에서 네 가지를 측정합니다:

- 원본의 소리 크기 (ref_rms): 원본 조각이 얼마나 큰 소리인지
- 수신본의 소리 크기 (dif_rms): 수신 조각이 얼마나 큰 소리인지
- 수신본의 최대 진폭 (dif_peak): 수신 조각에서 가장 큰 순간값. 이 값이 거의 0이면 완전한 무음
- 파형 유사도 (correlation): 원본과 수신본의 소리 "모양"이 얼마나 비슷한지 (-1~1, 1에 가까울수록 똑같은 모양)

그리고 "에너지 비율"을 계산합니다:
```
에너지 비율 = 수신본 크기 ÷ 원본 크기
```
정상이면 이 값이 1.0 근처입니다. 0.5면 볼륨이 절반으로 줄었다는 뜻이고, 0이면 소리가 완전히 사라졌다는 뜻입니다.

##### 3. "주변과 비교"합니다

여기가 핵심입니다. 단순히 "에너지 비율이 낮다"고 이상으로 판정하면 오탐이 많이 발생합니다. 전송 과정에서 전체적으로 볼륨이 약간 줄어드는 것은 정상이기 때문입니다.

그래서 각 조각을 "주변 1초 구간"과 비교합니다:

```
현재 조각의 에너지 비율 vs 주변 1초 구간의 에너지 비율 중앙값
```

예를 들어, 주변 1초 동안 에너지 비율이 대체로 0.8이었는데 갑자기 0.2로 떨어졌다면, 그것은 "주변 대비 급격한 하락"이므로 이상으로 판정합니다.

주변 값을 계산할 때 현재 조각 근처 ±0.2초는 제외합니다. 이상 구간 자체의 값이 "주변 평균"을 오염시키는 것을 방지하기 위해서입니다.

##### 4. 묵음을 찾습니다

다음 두 조건이 동시에 성립하면 "묵음"입니다:

- 원본에 확실한 말소리가 있다 (원본 크기 > 0.03)
- 수신본의 최대 진폭이 거의 0이다 (< 0.0005)

즉, "원본에서는 사람이 말하고 있는데 수신본에서는 완전히 조용한" 구간입니다.

단, 너무 짧은 구간(50ms 미만)은 무시합니다. 사람이 느끼기 어려운 수준이기 때문입니다.

##### 5. "진짜 묵음"과 "자연스러운 전환"을 구분합니다

여기서 중요한 필터가 하나 있습니다. 대화에서 말이 끝나고 잠시 쉬었다가 다시 말하는 구간을 생각해 보세요:

- 원본과 수신본 모두 조용하다가 → 원본이 먼저 말을 시작 → 수신본은 전송 지연으로 아직 조용
- 이 구간은 "원본에 소리가 있는데 수신본이 조용한" 조건에 걸리지만, 실제로는 정상입니다

이것을 구분하기 위해 묵음 구간 직전 0.2초를 확인합니다:
- 직전에 수신본에도 활발한 소리가 있었다면 → 진짜 묵음 (갑자기 끊긴 것)
- 직전에 수신본도 조용했다면 → 자연스러운 전환 구간 (오탐으로 제외)

##### 6. 깨짐을 찾습니다 (두 가지 유형)

깨짐 Type A — "볼륨만 줄어든" 경우:
- 원본에 확실한 말소리가 있다
- 에너지 비율이 주변 대비 60% 이상 떨어졌다 (주변 중앙값 × 0.4 미만)
- 수신본에 신호가 존재한다 (완전 무음은 아님)
- 파형 유사도가 0.3 이상이다 (소리의 "모양"은 비슷하게 유지됨)

비유하면, TV 볼륨을 갑자기 확 줄인 것과 같습니다. 프로그램 내용(파형 모양)은 같은데 소리만 작아진 상태입니다.

깨짐 Type B — "파형 자체가 변형된" 경우:
- Type A와 비슷하지만 파형 유사도 조건이 없는 대신, 더 엄격한 기준을 적용합니다
- 에너지 비율이 주변 대비 65% 이상 떨어져야 합니다 (주변 중앙값 × 0.35 미만)
- 최소 120ms 이상 지속되어야 합니다 (Type A는 50ms)
- 중간에 3프레임(30ms) 이하의 정상 구간이 끼어 있어도 하나의 깨짐으로 연결합니다

비유하면, TV 신호가 불안정해서 화면이 깨지는 것과 같습니다. 소리의 모양 자체가 달라졌기 때문에 더 확실한 증거(긴 지속시간, 큰 하락폭)를 요구합니다.

##### 7. 묵음 직후의 "복구 구간"은 무시합니다

소리가 완전히 끊겼다가 다시 돌아올 때, 처음 0.2초 정도는 볼륨이 서서히 올라오는 과도 구간이 있습니다. 이 구간은 에너지 비율이 낮게 나오지만 정상적인 복구 과정이므로 깨짐으로 판정하지 않습니다.

##### 8. 최종 결과

모든 검출된 구간을 시간순으로 정렬하여 반환합니다. 각 구간에는 다음 정보가 포함됩니다:

- 시작/종료 시간, 지속 시간
- 유형: "묵음" 또는 "깨짐"
- 평균 gain (dB): 깨짐의 경우 볼륨이 얼마나 줄었는지. 예: -10dB면 약 1/3로 줄어든 것
- 평균 correlation: 파형이 얼마나 유사한지. 1.0에 가까우면 볼륨만 변한 것, 0에 가까우면 파형 자체가 변형된 것

## 실행 방법

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 테스트

```powershell
venv\Scripts\python -m pytest tests/ -q
```

`sample_audio/` 디렉토리에 WAV 파일이 없으면 일부 회귀 테스트는 skip됩니다.

## 모듈 구조

| 파일 | 역할 |
|---|---|
| `main.py` | PyQt5 GUI 엔트리포인트 |
| `analyzer.py` | 분석 파이프라인 Facade |
| `audio_io.py` | WAV 로드, 포맷 정규화, 리샘플링 |
| `delay.py` | Cross-correlation + DTW 지연 보정 |
| `vad.py` | 묵음 판별 앙상블 (log-energy + WebRTC VAD + ZCR) |
| `silence_metrics.py` | 이상 구간 검출 (주변 대비 ratio 급변 + correlation) |
| `metrics.py` | SNR, PESQ, STOI, RMS, Clipping, Noise Floor |
| `spectrum.py` | 스펙트럼 분석 |
| `export.py` | JSON / CSV / PNG / HTML 저장 |
| `models.py` | 데이터 모델 (dataclass) |
| `errors.py` | 오류 코드 및 예외 클래스 |
| `tests/` | pytest 테스트 |
| `unused_scripts/` | 미사용 레거시 스크립트 |

## 출력 데이터 해석

| 지표 | 설명 |
|---|---|
| Delay | 적용된 최종 지연(ms). coarse/refined 중 MAE가 낮은 값 자동 선택 |
| 이상 검출 (묵음) | dif에서 디지털 제로 구간 수 (0 = 정상) |
| 이상 검출 (깨짐) | dif에서 gain 변조 구간 수 (0 = 정상) |
| SNR (dB) | 높을수록 ref와 유사 |
| PESQ | 1.0~4.5, 높을수록 음질 좋음 |
| STOI | 0.0~1.0, 높을수록 명료도 유사 |
| RMS diff (dB) | 0에 가까울수록 레벨 유사 |
| Clipping | 0에 가까울수록 좋음 |
| Noise floor (dB) | 낮을수록 조용한 배경 |

## 주의사항

- PESQ는 C++ 컴파일러가 필요하며, 미설치 시 N/A로 표시됩니다.
- 삽입/삭제 편집이 큰 파일은 DTW refine이 불안정할 수 있어 자동 fallback(coarse) 로직을 사용합니다.

### PESQ 설치 (Windows)

```powershell
# Microsoft C++ Build Tools 설치 필요: https://visualstudio.microsoft.com/visual-cpp-build-tools/
venv\Scripts\python -m pip install pesq
```

## 단일 스크립트 (다른 프로젝트에서 import)

`audio_anomaly_detector.py` 파일 하나만으로 이상 검출 기능을 사용할 수 있습니다.
GUI, 스펙트럼 분석 등 부가 기능 없이 핵심 검출 결과만 반환합니다.

```python
from audio_anomaly_detector import detect_dif_only_events

events = detect_dif_only_events("ref.wav", "dif.wav")
for e in events:
    print(f"#{e['index']} [{e['type']}] {e['duration_ms']:.0f}ms "
          f"({e['start_s']:.3f}s ~ {e['end_s']:.3f}s)")
```

파라미터 튜닝도 가능합니다:
```python
events = detect_dif_only_events("ref.wav", "dif.wav",
    speech_strong_rms=0.05,     # 음성 판정 RMS 임계값 (기본 0.03)
    zero_peak_threshold=0.001,  # 묵음 판정 peak 임계값 (기본 0.0005)
    min_anomaly_ms=80,          # 최소 이상 지속 시간 (기본 50ms)
)
```

필수 라이브러리: `numpy`, `scipy`, `soundfile`

CLI로도 실행 가능합니다:
```powershell
python audio_anomaly_detector.py ref.wav dif.wav
```

사용 예시는 `sample_usage.py`를 참고하세요.
