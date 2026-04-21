# Tauri 프로젝트 생성 및 설정 가이드

## 1단계: Tauri 프로젝트 생성

```bash
# 프로젝트 생성
npm create tauri-app@latest sound-test-app

# 프롬프트 응답:
# - Package manager: npm
# - UI template: React
# - TypeScript: Yes
# - Install dependencies: Yes
```

## 2단계: 의존성 추가

```bash
cd sound-test-app

# React 라이브러리
npm install @tanstack/react-query zustand
npm install lucide-react

# TypeScript
npm install -D @types/node
```

## 3단계: Tauri 설정 (src-tauri/tauri.conf.json)

```json
{
  "build": {
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build",
    "devPath": "http://localhost:1420",
    "distDir": "../dist",
    "withGlobalTauri": false
  },
  "package": {
    "productName": "익시오 통화 테스트",
    "version": "1.0.0"
  },
  "tauri": {
    "allowlist": {
      "all": false,
      "shell": {
        "all": false,
        "execute": true,
        "sidecar": true,
        "open": false
      },
      "fs": {
        "all": true,
        "scope": [
          "$APPDATA/*",
          "$RESOURCE/*"
        ]
      },
      "dialog": {
        "all": true
      }
    },
    "bundle": {
      "active": true,
      "targets": "all",
      "identifier": "com.sound.test",
      "icon": [
        "icons/32x32.png",
        "icons/128x128.png",
        "icons/icon.icns",
        "icons/icon.ico"
      ],
      "resources": [
        "python/**/*",
        "audio_presets/**/*"
      ],
      "externalBin": [
        "python/python",
        "adb/adb"
      ]
    },
    "windows": [
      {
        "fullscreen": false,
        "height": 800,
        "resizable": true,
        "title": "익시오 통화 테스트",
        "width": 1200,
        "center": true
      }
    ]
  }
}
```

## 4단계: Rust 명령어 추가 (src-tauri/src/main.rs)

```rust
#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::process::Command;
use tauri::api::path::resource_dir;

#[tauri::command]
fn run_python_script(script: String, args: Vec<String>) -> Result<String, String> {
    let resource_dir = resource_dir(&tauri::PackageInfo::default(), &tauri::Env::default())
        .map_err(|e| e.to_string())?;
    
    let python_path = resource_dir.join("python").join("python");
    
    let output = Command::new(python_path)
        .arg(script)
        .args(args)
        .output()
        .map_err(|e| e.to_string())?;
    
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

#[tauri::command]
fn list_devices() -> Result<String, String> {
    run_python_script(
        "tauri_bridge.py".to_string(),
        vec!["list-devices".to_string()]
    )
}

#[tauri::command]
fn start_test(config: String) -> Result<String, String> {
    run_python_script(
        "tauri_bridge.py".to_string(),
        vec!["test".to_string(), "--config".to_string(), config]
    )
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            list_devices,
            start_test,
            run_python_script
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

## 5단계: Python 런타임 번들링

### Option A: PyInstaller 사용
```bash
# 가상환경에서
pip install pyinstaller

# 단일 실행파일 생성
pyinstaller --onefile tauri_bridge.py

# dist/tauri_bridge를 src-tauri/python/으로 복사
```

### Option B: Python Embedded 사용 (권장)
1. Python Embedded 다운로드: https://www.python.org/downloads/windows/
2. `python-3.10.x-embed-amd64.zip` 압축 해제
3. `src-tauri/python/`에 복사
4. 필요한 패키지 포함

## 6단계: 빌드

```bash
# 개발 모드
npm run tauri dev

# 프로덕션 빌드
npm run tauri build
```

## 7단계: 배포

빌드된 파일 위치:
- Windows: `src-tauri/target/release/bundle/msi/`
- macOS: `src-tauri/target/release/bundle/dmg/`

## 주의사항

1. **Xcode는 별도 설치 필요**
   - macOS에서 iOS 테스트 시
   - WebDriverAgent 빌드 필요

2. **앱 서명**
   - Windows: 선택사항
   - macOS: 필수 (개발자 인증서)

3. **용량 최적화**
   - Python 패키지 최소화
   - 불필요한 파일 제거
   - 리소스 압축

## 다음 작업

1. React UI 컴포넌트 작성
2. Tauri 명령어 연동
3. 실시간 로그 스트리밍
4. 에러 핸들링
5. 빌드 및 테스트
