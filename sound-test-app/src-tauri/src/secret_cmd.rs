/// secret_cmd.rs — macOS Keychain 기반 비밀번호 안전 저장
///
/// localStorage 평문 저장 대신 OS Keychain (macOS Security framework)을 사용합니다.
/// Keychain은 앱 샌드박스 내에서만 접근 가능하며, 다른 앱이나 프로세스에서 읽을 수 없습니다.
/// 비밀번호는 Keychain 내부에서 AES-256으로 암호화되어 보관됩니다 (macOS 기본 동작).

use keyring::Entry;

const SERVICE: &str = "com.qabulls.call";

/// Keychain에 비밀번호 저장
#[tauri::command]
pub fn store_secret(account: String, secret: String) -> Result<(), String> {
    let entry = Entry::new(SERVICE, &account)
        .map_err(|e| format!("Keychain entry 생성 실패: {e}"))?;
    entry.set_password(&secret)
        .map_err(|e| format!("Keychain 저장 실패: {e}"))?;
    println!("[keychain] ✅ 저장 완료: {account}");
    Ok(())
}

/// Keychain에서 비밀번호 조회
#[tauri::command]
pub fn get_secret(account: String) -> Result<Option<String>, String> {
    let entry = Entry::new(SERVICE, &account)
        .map_err(|e| format!("Keychain entry 생성 실패: {e}"))?;
    match entry.get_password() {
        Ok(pw)                         => Ok(Some(pw)),
        Err(keyring::Error::NoEntry)   => Ok(None),
        Err(e)                        => Err(format!("Keychain 조회 실패: {e}")),
    }
}

/// Keychain에서 비밀번호 삭제
#[tauri::command]
pub fn delete_secret(account: String) -> Result<(), String> {
    let entry = Entry::new(SERVICE, &account)
        .map_err(|e| format!("Keychain entry 생성 실패: {e}"))?;
    match entry.delete_credential() {
        Ok(_)                         => { println!("[keychain] 🗑 삭제 완료: {account}"); Ok(()) },
        Err(keyring::Error::NoEntry)  => Ok(()),
        Err(e)                       => Err(format!("Keychain 삭제 실패: {e}")),
    }
}
