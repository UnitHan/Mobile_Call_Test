# Tauri + React 익시오 통화 테스트 앱

## 프로젝트 구조

```
sound-test-app/
├── src/                          # React 프론트엔드
│   ├── App.tsx                   # 메인 앱
│   ├── components/
│   │   ├── DeviceConfig.tsx      # 디바이스 설정
│   │   ├── TestConfig.tsx        # 테스트 설정 (시간, 오디오)
│   │   ├── TestRunner.tsx        # 테스트 실행 화면
│   │   ├── TestResults.tsx       # 테스트 결과 표시
│   │   └── CallSummary.tsx       # 통화요약 검증
│   ├── hooks/
│   │   └── useAppium.ts          # Appium 상태 관리
│   └── types.ts                  # TypeScript 타입 정의
│
├── src-tauri/                    # Tauri 백엔드
│   ├── src/
│   │   ├── main.rs               # Rust 메인
│   │   ├── appium.rs             # Appium 제어
│   │   ├── python_bridge.rs     # Python 스크립트 실행
│   │   └── audio.rs              # 오디오 파일 관리
│   ├── python/                   # 내장 Python 스크립트
│   │   ├── ixio_call_test.py
│   │   ├── audio_handler.py
│   │   ├── call_state_detector.py
│   │   └── config.py
│   ├── resources/                # 내장 리소스
│   │   ├── python/               # Python 런타임 (임베딩)
│   │   ├── appium/               # Appium Server
│   │   └── adb/                  # ADB 도구
│   └── tauri.conf.json
│
└── audio_presets/                # 테스트 오디오 프리셋
    ├── test_1min.wav
    ├── test_3min.wav
    ├── test_5min.wav
    └── test_10min.wav
```

## 주요 기능

### 1. 디바이스 관리
- Android/iOS 디바이스 자동 검색
- UDID, 플랫폼 버전 자동 감지
- 연결 상태 실시간 표시

### 2. 앱 선택
- ✅ 익시오 (com.lguplus.aicallagent)
- ✅ 에이닷
- ✅ 삼성 전화
- ✅ 애플 전화
- 발신자/수신자 각각 다른 앱 선택 가능

### 3. 테스트 설정
- 테스트 길이: 1분/3분/5분/10분 프리셋
- 오디오 파일: 커스텀 WAV 업로드 가능
- 전화번호 저장 및 관리

### 4. 테스트 실행
- 실시간 진행 상황 표시
- 로그 출력
- 통화 상태 모니터링

### 5. 통화요약 검증
- 최근 기록 자동 확인
- 통화요약 텍스트 추출
- 검증 규칙 설정 (사용자 추가 가능)

## 내장 요소

### ✅ 포함됨
- Python 3.10 런타임
- Appium Server
- ADB 도구
- 필수 Python 패키지
- 테스트 스크립트

### ❌ 제외됨 (사전 설치 필요)
- Xcode (iOS 테스트용, macOS만)
- WebDriverAgent (Xcode로 빌드 필요)

## 빌드 크기 예상
- Windows: ~150MB
- macOS: ~200MB (iOS 지원)

## 실행 흐름

1. 앱 실행 → 내장 Appium Server 자동 시작
2. 디바이스 연결 확인
3. 테스트 설정 (앱, 시간, 오디오)
4. "테스트 시작" 버튼 클릭
5. 자동 실행:
   - 익시오 앱 실행
   - 키패드 열기
   - 전화번호 입력
   - 발신/수신
   - 오디오 재생
   - 통화 종료
   - 통화요약 확인
6. 결과 표시

## 다음 단계

1. Tauri 프로젝트 생성
2. React UI 구현
3. Rust 백엔드 구현 (Python 브리지)
4. Python 런타임 및 의존성 번들링
5. 빌드 및 테스트
