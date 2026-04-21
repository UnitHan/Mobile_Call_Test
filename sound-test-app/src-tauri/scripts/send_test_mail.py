"""
send_test_mail.py — Gmail 인증 설정 + 테스트 메일 발송

실행:
    python send_test_mail.py

처음 실행 시:
    1. Gmail 앱 비밀번호 입력 → .env.mail 에 저장
    2. 테스트 메일 발송

이후 실행 시:
    .env.mail 에서 자동 로드 → 바로 발송
"""

import sys
import smtplib
import getpass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime

_ENV_FILE  = Path(__file__).parent / ".env.mail"
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587
_ADDR      = "m9.chapter1@gmail.com"


def _load_password() -> str:
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("CRASH_MAIL_PASS=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _save_password(pw: str) -> None:
    _ENV_FILE.write_text(f"CRASH_MAIL_PASS={pw}\n", encoding="utf-8")
    print(f"  ✅ 비밀번호 저장 완료: {_ENV_FILE}")


def _send(password: str) -> bool:
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = MIMEMultipart()
    msg["From"]    = _ADDR
    msg["To"]      = _ADDR
    msg["Subject"] = f"[ixi-O] 크래시 리포트 메일 설정 완료 — {ts}"
    msg.attach(MIMEText(
        f"테스트 메일입니다.\n\n"
        f"발송 시각: {ts}\n"
        f"설정 파일: {_ENV_FILE}\n\n"
        f"이제 앱 크래시 발생 시 이 주소로 자동 발송됩니다.",
        "plain", "utf-8"
    ))
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(_ADDR, password)
            srv.sendmail(_ADDR, _ADDR, msg.as_string())
        print(f"\n  ✅ 테스트 메일 발송 성공 → {_ADDR}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("\n  ❌ Gmail 인증 실패")
        print("  → Google 계정 보안: 2단계 인증 ON → 앱 비밀번호 생성 필요")
        print("  → https://myaccount.google.com/apppasswords")
        return False
    except Exception as e:
        print(f"\n  ❌ 발송 실패: {e}")
        return False


def main():
    print("=" * 50)
    print("  ixi-O 크래시 리포트 메일 설정")
    print("=" * 50)

    password = _load_password()

    if password:
        print(f"\n  📂 기존 설정 파일 발견: {_ENV_FILE}")
        print("  비밀번호가 저장되어 있습니다. 테스트 메일을 발송합니다...")
    else:
        print("\n  Gmail 앱 비밀번호가 필요합니다.")
        print("  발급 경로: Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호")
        print("  URL: https://myaccount.google.com/apppasswords\n")
        password = getpass.getpass("  Gmail 앱 비밀번호 (16자리, 입력 내용 안 보임): ").strip()
        if not password:
            print("  ❌ 비밀번호를 입력하지 않았습니다.")
            sys.exit(1)

    ok = _send(password)

    if ok:
        _save_password(password)
        print("\n  이후 크래시 발생 시 자동으로 메일이 발송됩니다.")
        print("=" * 50)
    else:
        # 비밀번호가 틀린 경우 저장된 파일 삭제 후 재시도 유도
        if _ENV_FILE.exists():
            _ENV_FILE.unlink()
            print("  기존 저장 파일을 삭제했습니다. 다시 실행하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
