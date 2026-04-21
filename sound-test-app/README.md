# sound-test-app

Tauri v2 + React/TypeScript GUI 앱. 익시오 통화 자동화 테스트의 프론트엔드입니다.

## 개발 서버 실행

```bash
npm install
npm run tauri dev
```

## 빌드

```bash
npm run tauri build
```

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| UI | React 18 + TypeScript + Vite |
| 데스크톱 런타임 | Tauri v2 (Rust) |
| 자동화 백엔드 | Python 3.10+ (Appium) |

## 주요 화면 구성

- **DeviceSection** - 화자1·화자2 단말 선택 (Android/iOS 자동 감지)
- **AudioSection** - 음원 파일 및 USB 사운드카드 선택
- **SpeakerSection** - 전화번호, 채널(L/R) 설정
- **LogPanel** - 실시간 테스트 로그
- **EnvPanel** - 환경(Appium, ADB, Python) 상태 확인

## 추천 IDE

[VS Code](https://code.visualstudio.com/) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
