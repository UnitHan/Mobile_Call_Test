# Changelog

## [3.4.3] - 2026-04-02

### README 이상 검출 로직 상세 문서 추가
- 기술 버전: 8단계 파이프라인으로 분해하여 조건식, 계산식, 파라미터 테이블 포함
- 쉬운 설명 버전: 전화 통화·TV 볼륨 등 비유를 활용하여 신호 처리 비전문가도 이해 가능하도록 작성

## [3.4.2] - 2026-04-02

### 문서 동기화
- `audio_anomaly_detector.py` — 하드코딩 값 9개를 kwargs 파라미터로 전환, 직전 dif 활성도 검사(`_has_prior_activity`) 추가, docstring에 파라미터 목록 및 튜닝 예시 추가
- `README.md` — 이상 검출 알고리즘 설명을 파라미터 기반으로 갱신, 단일 스크립트 섹션에 파라미터 튜닝 예시 추가
- `.kiro/steering/product.md` — 이상 검출 알고리즘 파라미터화 반영, 직전 dif 활성도 검사 추가, 단일 스크립트 배포 기능 추가
- `.kiro/steering/structure.md` — `audio_anomaly_detector.py`/`sample_usage.py` 추가, 회귀 테스트 5 Pair로 갱신, AnalysisConfig 필드 상세화, 이상 검출 흐름에 전환 구간 오탐 제외 단계 추가
- `.kiro/steering/tech.md` — 이상 검출 임계값 하드코딩 금지 규칙, 단일 스크립트 동기화 규칙 추가
- `.kiro/specs/design.md` — AnalysisConfig 필드 갱신, detect_anomalies docstring 갱신, ParamPanel을 VAD/이상 검출 2그룹 구조로 갱신

## [3.4.1] - 2026-04-02

### audio_anomaly_detector.py 동기화 및 README 업데이트
- `_detect_anomalies()` 내부 하드코딩 값 9개를 kwargs 파라미터로 전환 (GUI 프로젝트의 AnalysisConfig와 동일한 기본값)
- 직전 dif 활성도 검사(`_has_prior_activity`) 로직 추가하여 자연 묵음→음성 전환 구간 오탐 방지
- `detect_dif_only_events()` 공개 API에 keyword-only 파라미터 9개 추가 (하위 호환 유지)
- docstring에 조정 가능한 파라미터 목록 및 튜닝 예시 추가
- `README.md` 이상 검출 알고리즘 섹션을 파라미터 기반 설명으로 갱신, 단일 스크립트 섹션에 파라미터 튜닝 예시 추가

## [3.4.0] - 2026-04-02

### AnalysisConfig 정리 및 하드코딩 파라미터화
- 미사용 파라미터 11개 삭제: `silence_boundary_margin_ms`, `dif_only_energy_threshold_db`, `noise_loss_peak_threshold`, `noise_loss_ref_energy_db`, `digital_zero_peak_threshold`, `digital_zero_ref_energy_db`, `energy_drop_db`, `digital_zero_threshold`, `gain_drop_db`, `anomaly_merge_ms` 및 기존 미사용 필드
- `detect_anomalies()` 내부 하드코딩 값 9개를 Config 파라미터로 전환:
  - `speech_strong_rms` (0.03): 확실한 음성 구간 판정 RMS 임계값
  - `zero_peak_threshold` (0.0005): dif 디지털 제로 판정 peak 임계값
  - `gain_drop_ratio` (0.4): 깨짐 Type A 주변 대비 ratio 임계값
  - `gain_drop_ratio_strict` (0.35): 깨짐 Type B ratio 임계값
  - `gain_drop_min_corr` (0.3): 깨짐 Type A 최소 correlation
  - `prior_activity_threshold` (0.01): 직전 dif 활성 판정 peak (전환 구간 오탐 제외)
  - `min_anomaly_ms` (50): 묵음/깨짐 A 최소 지속 시간
  - `min_anomaly_b_ms` (120): 깨짐 B 최소 지속 시간
  - `anomaly_gap_frames` (3): 깨짐 B gap 허용 프레임 수

### GUI 파라미터 패널 재구성
- "VAD / 묵음 검출"과 "이상 검출 (묵음/깨짐)" 2개 그룹으로 분리
- 각 파라미터에 한글 설명 라벨 추가
- 미사용 파라미터 위젯 제거 (Boundary margin, Energy thr, Gain drop dB)
- 새 이상 검출 파라미터 위젯 9개 추가

### export 업데이트
- JSON 내보내기에 새 이상 검출 파라미터 포함

## [3.3.1] - 2026-04-01

### .gitignore 정리 및 IDE 설정 tracked 제거
- `.gitignore`를 프로젝트에 필요한 규칙만 남기도록 전면 정리 (Django, Flask, Scrapy 등 미사용 프레임워크 규칙 제거)
- `.kiro/` 디렉토리 gitignore 추가 (IDE 개인 설정)
- `sample_audio/` 디렉토리 단위 gitignore 추가 (기존 `*.wav`에 추가하여 이중 보호)
- 이미 tracked 되어 있던 `.kiro/` 내 9개 파일을 `git rm --cached`로 인덱스에서 제거 (로컬 파일 유지)

## [3.3.0] - 2026-04-01

### 단일 스크립트 배포용 파일 추가
- `audio_anomaly_detector.py` — 외부 프로젝트에서 import하여 사용할 수 있는 self-contained 스크립트. WAV 로드, 리샘플링, 지연 보정(CC+DTW), 이상 검출 로직을 단일 파일에 통합. 필수 라이브러리는 numpy, scipy, soundfile만 필요
- `sample_usage.py` — `detect_dif_only_events()` 함수 호출 예시 스크립트
- `detect_dif_only_events(ref_path, dif_path) -> list[dict]` 함수가 GUI의 'dif-only 이벤트' 테이블과 동일한 결과를 반환
- CLI 실행 지원: `python audio_anomaly_detector.py ref.wav dif.wav`
- `README.md`에 단일 스크립트 사용법 섹션 추가

## [3.2.0] - 2026-04-01

### 깨짐 Type B 오탐 방지 강화
- Type B ratio 임계값 강화: `context_med * 0.4` → `context_med * 0.35` (더 극단적인 하락만 검출)
- Type B 최소 지속시간 상향: 100ms → 120ms (짧은 전송 jitter 오탐 제거)
- A_dating_SPEAKER_00 + A_Android_ixiO_20260327_172033 Pair에서 발생하던 오탐 2건 제거
- 기존 Pair1~4 정답 검출에 영향 없음 확인

### 회귀 테스트 추가
- `tests/test_regression_ref_dif.py`에 Pair5(A_dating + A_Android → 정상, 이상 0건) 테스트 추가

## [3.1.1] - 2026-04-01

### 파형 차트 y축 범위 통일
- ref/dif 파형 차트의 y축 범위를 ref 기준으로 통일하여 진폭 비교가 직관적으로 가능하도록 개선

## [3.1.0] - 2026-04-01

### GUI 차트 음영 정리 및 코드 클린업
- 파형 차트(ref/dif): anomaly_segments(묵음/깨짐)만 음영 처리, 기존 dif_silence/ref_silence 오버레이 제거
- "ref 묵음 오버레이 표시" 체크박스 제거 (QCheckBox import, 스타일 포함)
- Residual, Volume Normalized Residual, Spectral Centroid, Spectral Rolloff 차트의 차이 하이라이트 음영 모두 제거

### 미사용 코드 제거
- `AnalysisConfigV2`에서 overlay threshold 필드 3개 제거 (`residual_diff_threshold`, `centroid_diff_threshold_hz`, `rolloff_diff_threshold_hz`) → 빈 서브클래스로 단순화
- `analyzer.py` validate_config에서 overlay threshold 검증 제거
- `export.py` save_json에서 overlay threshold JSON 출력 제거
- `main.py` ParamPanel에서 Residual highlight / Centroid / Rolloff 위젯 3개 제거
- `main.py` SingleResultPanel에서 `_mask_to_spans` 메서드, `SILENCE_DIF`/`SILENCE_REF` 색상 상수 제거

### 미사용 스크립트 이동
- `explore_audio.py`, `explore_v2.py`~`explore_v10.py`, `explore_v7_debug.py`, `debug_final.py` (12개) → `unused_scripts/`로 이동

### 테스트 업데이트
- `tests/test_analyzer_v2.py` — overlay threshold 테스트 제거, 하위 호환 테스트로 재작성

### 문서 최신화
- `README.md` — 현재 기능에 맞게 전면 재작성
- `.kiro/steering/structure.md` — test_analyzer_v2 설명 갱신
- `.kiro/specs/audio-quality-analyzer/design.md` — AnalysisConfigV2, validate_config, silence_metrics 섹션 갱신

## [3.0.0] - 2026-04-01

### 이상 검출 알고리즘 전면 재설계 (주변 대비 ratio 급변 + correlation 기반)
- 기존 "음절 내 RMS ratio 중앙값" 방식을 폐기하고, **주변 1초 context 대비 ratio 급변 + 프레임 correlation** 기반 새 알고리즘으로 완전 교체
- 4개 정답 Pair에서 각 1건씩 정확히 검출, 오탐 0건 달성:
  - Pair1: 묵음 1회 (1.02s, digital_zero) ✓
  - Pair2: 깨짐 1회 (2.73s, gain_drop) ✓
  - Pair3: 묵음 1회 (72.47s, digital_zero) ✓
  - Pair4: 깨짐 1회 (72.61s, gain_drop) ✓

### 새 알고리즘 상세
- 프레임별 ref/dif RMS, peak, Pearson correlation 계산 (20ms 프레임, 10ms 홉)
- 주변 1초 구간(현재 ±200ms 제외)의 ratio 중앙값(context_med) 산출
- **묵음(digital_zero)**: dif_peak < 0.0005 + ref_rms > 0.03, 최소 50ms 연속
- **깨짐 Type A(gain_drop)**: ratio < context_med×0.4 + correlation > 0.3 (파형 유사, gain만 변화), 최소 50ms
- **깨짐 Type B(gain_drop)**: ratio < context_med×0.4 + 100ms 이상 지속 (gap 3프레임 허용 병합)
- 묵음 직후 200ms 이내의 distortion은 신호 복구 과정으로 제외하여 오탐 방지

### 파일 변경
- `silence_metrics.py` — 완전 재작성 (`detect_anomalies`, `_compute_frame_features`, `_compute_context_median`, `_find_segments`, `_find_segments_with_gap` 등)
- `tests/test_silence_metrics.py` — 새 알고리즘에 맞게 재작성 (10건)
- `tests/test_regression_ref_dif.py` — 4개 Pair 정답 기반 회귀 테스트로 재작성 (8건: Pair별 검출 수·위치·유형 검증)

### steering 문서 업데이트
- `product.md` — 이상 검출 알고리즘 섹션을 새 로직으로 갱신
- `structure.md` — silence_metrics.py 설명 변경, 이상 검출 흐름 갱신

## [2.3.0] - 2026-04-01

### 이상 검출 알고리즘 고도화 (음절 내 RMS ratio 중앙값 기반 v2)
- `silence_metrics.py` 완전 재작성: 기존 단순 프레임별 비교 + 다중 필터(경계 확장, 에너지 재검증, 잡음 소실 필터, 디지털 제로 검출) 파이프라인을 **음절(utterance) 내 RMS ratio 중앙값 기반 단일 알고리즘**으로 통합
- 핵심 함수: `detect_anomalies()`, `_compute_frame_stats()`, `_identify_utterances()`, `_detect_anomaly_frames()`, `_merge_anomaly_frames()`
- 기존 `_expand_segments`, `_verify_energy`, `_filter_noise_loss`, `_detect_digital_zero_segments` 등 6개 내부 함수 제거 → 코드량 514행 → 295행으로 42% 감소

### 데이터 모델 정리
- `models.py`: `AnomalySegment` dataclass 추가 (`anomaly_type`, `mean_gain_db`, `mean_correlation`)
- `AnalysisConfig`에 이상 검출 전용 파라미터 7개 추가 (`anomaly_frame_ms`, `anomaly_hop_ms`, `ref_silence_rms`, `digital_zero_threshold`, `gain_drop_db`, `min_anomaly_ms`, `anomaly_merge_ms`)
- `AnalysisResult`에 `anomaly_segments` 필드 추가, 음질 지표 필드에 default_factory 적용
- 기존 주석 정리 (불필요한 인라인 주석 제거)

### GUI 분석 결과 UI 재구성
- 상단 통계 카드: Silence Leakage / False Silence 제거 → "dif-only 음성 깨짐 수", "dif-only 깨짐 (ms)" 2개로 축소
- "dif-only 묵음 이벤트" → "dif-only 이벤트"로 이름 변경, "구분" 컬럼 추가 (묵음/깨짐 색상 구분)
- 파형 차트에 anomaly_segments 기반 음영 추가 (digital_zero=빨강, gain_drop=노랑)
- 분석 지표 텍스트에 "이상 검출: 묵음 N건, 깨짐 N건" 추가
- 상세 지표 테이블: 이상 검출(묵음/깨짐), 이상 총 시간 3행 추가, Silence Leakage/False Silence 행 제거
- 파라미터 패널: 구 silence_metrics 전용 파라미터 6개 제거 → Gain drop (dB) / Min anomaly (ms) 2개로 교체

### export 업데이트
- HTML 리포트: 동일한 UI 변경 반영 (통계 카드, 이벤트 테이블 구분 컬럼, 이상 검출 요약, 상세 지표)
- JSON 내보내기: `anomaly_segments` 배열 추가 (type, start_ms, end_ms, mean_gain_db 포함)

### analyzer 연동
- `analyzer.py`에서 `detect_anomalies()` 호출 추가, `anomaly_segments`를 `AnalysisResult`에 포함

### 테스트 재작성
- `tests/test_silence_metrics.py` — 완전 재작성 (10건: detect_anomalies 단위 테스트 6건, _difference_segments 3건, compute_silence_metrics 통합 1건)
- `tests/test_regression_ref_dif.py` — 재작성 (3건: B_iOS_dif_1 디지털 제로 검출, B_iOS_dif_gain 디지털 제로 0건 + gain_drop 검출, 레거시 샘플 호환)
- `tests/test_export.py` — HTML 검증 assertion을 새 UI에 맞게 업데이트 ("이상 검출" 키워드)
- 구 API 전용 `tests/test_silence_boundary_energy.py` 삭제

### steering 문서 업데이트
- `product.md` — 이상 검출 알고리즘 섹션 추가, HTML 내보내기·듀얼 페어 비교 반영
- `structure.md` — silence_metrics.py 설명 변경, 누락 테스트 파일 추가, 파이프라인 흐름에 이상 검출 단계 반영, 주요 데이터 모델 섹션 추가
- `tech.md` — 회귀 테스트 패턴, AnomalySegment 처리 컨벤션, default_factory 패턴 추가

## [2.2.0] - 2026-04-01

### 이상 검출 알고리즘 재설계 (음절 내 RMS ratio 중앙값 기반)
- 기존 단순 프레임별 RMS 비교 방식에서 전송 jitter로 인한 오탐 다수 발생
- 새 알고리즘: ref RMS 기반 음절(utterance) 식별 → 음절 내 dif/ref ratio 중앙값 산출 → 중앙값 대비 급격한 하락(< 40%)만 이상으로 판정
- 연속 5프레임(50ms) 이상인 구간만 보고하여 산발적 jitter 오탐 완전 제거
- 검증 결과: dif_gain → gain_drop 1건(2730ms), dif_1 → digital_zero 1건(1020ms) 정확히 일치
- `silence_metrics.py` 완전 재작성 (`_identify_utterances`, `_detect_anomaly_frames`, `_compute_frame_stats` 등)

## [2.1.1] - 2026-04-01

### gain_drop_db 기본값 조정 (20 → 10)
- dif_gain의 -9~-11.5dB gain 변조 구간이 검출되지 않던 문제 수정
- `models.py`의 `gain_drop_db` 기본값을 20.0 → 10.0으로 변경
- `main.py` ParamPanel 기본값 동기화
- 회귀 테스트에 dif_gain gain_drop 검출 assertion 추가

## [2.1.0] - 2026-04-01

### GUI 분석 결과 UI 재구성
- 상단 통계 카드: Silence Leakage / False Silence 제거 → "dif-only 음성 깨짐 수", "dif-only 깨짐 (ms)" 2개로 축소
- "dif-only 묵음 이벤트" → "dif-only 이벤트"로 이름 변경, "구분" 컬럼 추가 (묵음/깨짐 색상 구분)
- 파형 차트(ref/dif)에 anomaly_segments 기반 음영 추가 (digital_zero=빨강, gain_drop=노랑)
- 분석 지표 텍스트에 "이상 검출: 묵음 N건, 깨짐 N건" 추가
- 상세 지표 테이블: 이상 검출(묵음/깨짐), 이상 총 시간 3행 추가, Silence Leakage/False Silence 행 제거
- 파라미터 패널: 구 silence_metrics 전용 파라미터 6개 제거, Gain drop (dB) / Min anomaly (ms) 2개 추가

### export 업데이트
- HTML 리포트: 동일한 UI 변경 반영 (통계 카드, 이벤트 테이블 구분 컬럼, 상세 지표)
- JSON 내보내기: `anomaly_segments` 배열 추가 (type, start_ms, end_ms, mean_gain_db 포함)

### 테스트
- `tests/test_export.py` HTML 검증 assertion을 새 UI에 맞게 업데이트

## [2.0.0] - 2026-04-01

### 이상 구간 검출 로직 전면 재작성
- 기존 앙상블 묵음 검출(energy + VAD + ZCR) 기반 dif-only 묵음 판정을 **프레임별 RMS 비교 기반 이상 구간 검출**로 교체
- 검출 가능 유형: `digital_zero`(음 빠짐), `gain_drop`(gain 변조)
- 프레임 단위로 ref RMS, dif peak, RMS ratio를 계산하여 판정 → 연속 이상 프레임 병합 → min/merge 필터링
- `AnomalySegment` dataclass 신규 추가 (`anomaly_type`, `mean_gain_db`, `mean_correlation` 포함)
- `AnalysisResult`에 `anomaly_segments` 필드 추가
- 기존 UI/export 호환을 위해 `SilenceMetrics`, `false_silence_segments` 인터페이스 유지

### 파일 변경
- `silence_metrics.py` — 완전 재작성 (`detect_anomalies`, `_classify_frame`, `_merge_anomaly_frames` 등)
- `analyzer.py` — 새 silence_metrics 연동, `anomaly_segments` 결과 조립 추가
- `models.py` — `AnomalySegment` 추가, `AnalysisConfig`에 이상 검출 파라미터 7개 추가 (`anomaly_frame_ms`, `digital_zero_threshold`, `gain_drop_db` 등)

### 기존 파일 백업
- 변경 전 전체 스크립트를 `unused_scripts/backup_260401/`에 백업

### 테스트
- `tests/test_silence_metrics.py` — 재작성 (10건: 디지털 제로 검출, gain drop 검출, ref 묵음 제외, 빈 입력, 짧은 이상 필터링, 차집합 연산, 통합 테스트)
- `tests/test_regression_ref_dif.py` — 재작성 (3건: B_iOS_dif_1 디지털 제로 1건 검출, B_iOS_dif_gain 디지털 제로 0건, 레거시 샘플 호환)
- 구 API 전용 `tests/test_silence_boundary_energy.py` 삭제 (백업 보관)
- 전체 59건 통과

## [1.7.0] - 2026-03-31

### 잡음 소실(noise loss) 필터 추가
- dif가 디지털 제로(peak < 0.002)이고 ref가 미세 잡음(energy ≤ -30dB)인 구간을 dif-only 묵음에서 제외
- 전송 과정에서 미세 배경 잡음이 소실된 구간을 "새로 삽입된 묵음"이 아닌 "잡음 소실"로 간주
- `silence_metrics.py`에 `_filter_noise_loss()` 함수 추가
- `compute_silence_metrics()`에 `ref_audio` 파라미터 추가 (하위 호환: 기본값 None)
- `analyzer.py`에서 `ref_common` 신호를 `compute_silence_metrics`에 전달
- `models.py`의 `AnalysisConfig`에 `noise_loss_peak_threshold`(기본 0.002), `noise_loss_ref_energy_db`(기본 -30dB) 파라미터 추가
- GUI에 Noise loss peak, Noise loss ref (dB) 파라미터 위젯 추가
- 디버깅용 임시 스크립트 6개 정리 삭제

### 테스트
- `tests/test_silence_boundary_energy.py`에 잡음 소실 필터 테스트 6건 추가 (총 18건)
  - `_filter_noise_loss` 단위 테스트 5건 (dif 제로+ref 잡음 제거, dif 제로+ref 음성 유지, dif 비제로 유지, 혼합, 빈 입력)
  - 통합 테스트 1건 (`compute_silence_metrics`에서 잡음 소실 필터 적용 검증)

## [1.6.0] - 2026-03-31

### dif-only 묵음 경계 오탐 제거 (방안 B + C)
- 방안 B: ref 묵음 구간 양쪽 경계를 `silence_boundary_margin_ms`(기본 100ms)만큼 확장한 뒤 차집합 수행 → 묵음↔음성 전환부에 걸친 오탐 흡수
- 방안 C: 차집합 후 남은 dif-only 구간의 실제 에너지를 `dif_only_energy_threshold_db`(기본 -40dB) 절대 임계값으로 재검증 → 소리가 있는 구간 제거
- `silence_metrics.py`에 `_expand_segments()`, `_verify_energy()` 함수 추가
- `compute_silence_metrics()`에 `dif_audio` 파라미터 추가 (하위 호환: 기본값 None)
- `analyzer.py`에서 `dif_common` 신호를 `compute_silence_metrics`에 전달
- `models.py`의 `AnalysisConfig`에 `silence_boundary_margin_ms`, `dif_only_energy_threshold_db` 파라미터 추가
- GUI에 Boundary margin (ms), Energy thr (dB) 파라미터 위젯 추가

### 테스트
- `tests/test_silence_boundary_energy.py` 추가 (12건)
  - `_expand_segments` 단위 테스트 5건 (양쪽 확장, 경계 클램핑, 겹침 병합, margin=0, 빈 입력)
  - `_verify_energy` 단위 테스트 3건 (무음 통과, 유음 제거, 혼합)
  - 통합 테스트 3건 (경계 오탐 제거, 정상 dif-only 유지, 에너지 재검증 제거)
  - Hypothesis PBT 1건 (확장 구간 범위 불변 속성)

## [1.5.1] - 2026-03-31

### dif-only 묵음 검출 불일치 원인 분석
- Pair1(전체 음원)에서 dif-only 묵음 수 1로 검출되나, 해당 구간만 slice한 Pair2에서는 0으로 검출되는 현상 조사
- 원인 분석 결과 5가지 요인 식별:
  1. **지연 보정(delay) 차이**: slice 음원은 이미 정렬된 상태인데 cross-correlation + DTW가 다른 delay를 추정하여 정렬을 깨뜨릴 수 있음
  2. **Noise Floor 동적 임계값 변화**: 전체 음원 vs slice 구간의 에너지 분포 차이로 `noise_floor_percentile` 기반 threshold가 달라짐
  3. **`extract_common_segment` 길이 자르기**: delay 보정 후 공통 구간 범위가 달라져 묵음 구간이 분석 범위에서 제외될 수 있음
  4. **`min_silence_ms` (200ms) 경계 필터링**: 시간 축 미세 변화로 경계값 구간이 필터링됨
  5. **`silence_merge_ms` (50ms) 병합 차이**: slice 경계에서 병합 결과가 달라질 수 있음
- 코드 수정 없이 분석만 진행 (개선 방향 도출 완료, 추후 반영 예정)

## [1.5.0] - 2026-03-27

### HTML 리포트 내보내기 기능 추가
- 분석 결과 전체(요약 통계, 지표 테이블, 차트)를 self-contained HTML 파일로 저장하는 기능 추가
- 차트는 base64 PNG로 인라인 삽입되어 HTML 파일 하나만 공유하면 브라우저에서 모든 정보 확인 가능
- 다크 테마 CSS 적용, 반응형 레이아웃 지원
- 싱글/듀얼 모드 모두 지원 (듀얼 시 Pair 1 / Pair 2 좌우 배치)
- GUI에 "HTML 저장" 버튼 추가 (PNG 저장 옆)
- `export.py`에 `save_html()`, `_fig_to_base64()`, `_build_result_html()` 함수 추가

### 테스트
- `tests/test_export.py`에 HTML 내보내기 테스트 2건 추가
  - 싱글 결과 HTML 생성 및 필수 콘텐츠(지표, 차트 base64, 테이블) 포함 검증
  - 듀얼 결과 HTML 생성 시 Pair 1 / Pair 2 및 듀얼 레이아웃 포함 검증

## [1.4.2] - 2026-03-27

### 음량 정규화 잔차 차트 타이틀 개선
- `gain=0.5000` → `dif = 0.50× ref` 형태로 변경하여 직관적으로 "몇 배"인지 표시
- 소수점 둘째 자리에서 올림(ceil) 처리
- `×` 단위 표기 추가
- 예시: `Residual – Volume Normalized (dif = 0.50× ref, -6.02 dB)`

## [1.4.1] - 2026-03-27

### 음량 정규화 잔차 차트에 볼륨 차이(dB) 표기 추가
- 차트 타이틀에 ref 대비 dif의 볼륨 차이를 dB 단위로 표시 (예: `dif vol: -6.02 dB vs ref`)
- dif가 ref보다 크면 양수(+), 작으면 음수(-) 부호로 직관적 확인 가능
- 계산식: `20 * log10(dif_rms / ref_rms)`
- 양쪽 모두 무음이거나 dif가 무음인 경우 0.0 dB 폴백

### 테스트
- `tests/test_volume_normalized_residual.py` 확장 (8건 → 10건)
  - dB 부호 규칙 검증 테스트 추가 (`test_vol_diff_db_sign_convention`)
  - Hypothesis PBT: `vol_diff_db = 20*log10(scale)` 관계 검증 추가 (`test_vol_diff_db_matches_scale`)
  - 기존 테스트에 dB 값 정확도 assertion 추가

## [1.4.0] - 2026-03-27

### 음량 정규화 잔차(Volume-Normalized Residual) 차트 추가
- 기존 `Residual (ref - dif)` 차트 바로 아래에 음량 정규화 잔차 차트 신규 추가
- dif의 전체 RMS를 ref의 RMS에 맞추는 gain을 계산하여 dif를 스케일링한 뒤 `ref - dif_scaled`을 표시
- 볼륨 차이만 존재하는 두 신호의 경우 잔차가 0으로 표시되어, 순수 파형 차이만 시각적으로 확인 가능
- 차트 타이틀에 적용된 gain 값 표시 (예: `gain=2.0000`)
- 기존 잔차 차트와 동일한 threshold 하이라이트 적용
- Pair 1 / Pair 2 모두 동일하게 적용
- PNG 내보내기 시 새 차트 포함

### 테스트
- `tests/test_volume_normalized_residual.py` 추가 (8건)
  - 동일 신호, 볼륨만 다른 신호, 파형이 다른 신호, 무음 신호 등 케이스별 검증
  - Hypothesis PBT: 임의 양수 스케일 × 동일 파형 → 정규화 후 잔차 ≈ 0 속성 검증

## [1.3.0] - 2026-03-26

### GUI 레이아웃 개선 (2차)
- 상세 지표 테이블: 스크롤바 제거(`ScrollBarAlwaysOff`) + 행 수 기반 `setFixedHeight` 자동 계산으로 스크롤 없이 전체 표시
- 분석 파라미터: `QFormLayout` 단일 컬럼 → `QGridLayout` 2컬럼 배치로 변경하여 좌우 여백 최소화
- 파일 선택 패널: Pair 1 / Pair 2를 세로 나열에서 `QHBoxLayout` 가로 나란히 배치로 변경

## [1.2.0] - 2026-03-26

### GUI 레이아웃 개선
- 상세 지표 테이블의 고정 높이 제한(`maxHeight`) 제거 → 스크롤 없이 전체 지표를 한눈에 확인 가능
- 분석 파라미터 패널을 접기/펼치기(토글) 방식으로 변경 → 초기에는 숨김 처리하여 화면을 깔끔하게 유지
- 기존 파일 선택 + 파라미터 좌우 분할(`QSplitter`) 레이아웃을 세로 배치로 변경

### 차트 시간축 정렬
- Spectral Centroid / Rolloff 차트의 x축을 프레임 인덱스에서 시간(초) 단위로 변환
- 파형, 잔차, 스펙트로그램, 스펙트럼 트렌드 등 모든 시간축 차트의 x범위(`xlim`)를 `(0, max_time)`으로 통일하여 0초~끝 시간이 시각적으로 정렬되도록 개선

## [1.1.0] - 2026-03-26

### GUI 전면 리디자인
- 다크 테마 기반 현대적 UI로 전면 교체 (Fusion 스타일 + 커스텀 색상 팔레트)
- 카드 기반 레이아웃, 둥근 모서리, 통일된 색상 체계로 시인성 대폭 개선
- matplotlib 차트도 다크 테마 적용 (magma colormap 등)
- 한글 UI 라벨 적용 (버튼, 메뉴, 지표 해석 등)

### 듀얼 페어 비교 분석 기능 추가
- 음원 파일 4개(ref1/dif1, ref2/dif2) 입력 지원
- Pair 1, Pair 2를 한 번에 분석하고 결과를 좌우 나란히 비교 가능
- Pair 2는 선택 사항으로, 기존처럼 2개 파일만으로도 정상 동작
- `DualAnalysisWorker` 추가: 두 페어를 순차 분석하는 QThread 워커
- `ResultContainer`: 싱글/듀얼 모드 자동 전환 결과 컨테이너
- JSON/CSV/PNG 내보내기 시 듀얼 모드면 `_pair2` 접미사로 두 번째 결과 자동 저장

### 내부 구조 변경
- `FilePanel`: `FilePairWidget` 기반으로 재구성 (Pair 1 + Pair 2)
- `ResultPanel` → `SingleResultPanel`로 리네이밍 및 독립 패널화
- 통계 요약 카드 위젯(`_stat_widget`) 도입: 핵심 지표를 큰 숫자로 즉시 확인 가능
- 지표 테이블 해석 컬럼 한글화

## [1.0.0] - 초기 버전

- ref/dif WAV 파일 비교 분석 (단일 페어)
- Cross-correlation + DTW 지연 추정 및 자동 보정
- log-energy + WebRTC VAD + ZCR 앙상블 묵음 검출
- 음질 지표: SNR, PESQ, STOI, RMS diff, Clipping, Noise Floor
- 스펙트럼 분석: Spectrogram, Spectral Centroid/Rolloff, Pitch, ZCR
- 묵음 지표: Silence Leakage, False Silence, dif-only Silence
- JSON / CSV / PNG 결과 내보내기
- PyQt5 기반 GUI
