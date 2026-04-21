"""
crash_reporter.py — iOS 앱 크래시 감지 + 로그 수집 + 메일 발송

사용법:
    from crash_reporter import CrashReporter
    reporter = CrashReporter(ios_udid="...", android_udid="...")
    if reporter.detect_crash(driver):           # Appium driver 전달
        reporter.handle_crash(driver)           # 로그 수집 + 메일
"""

import os
import subprocess
import smtplib
import traceback
import platform
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

# ── 메일 설정 (환경변수 우선, 없으면 .env.mail 파일, 없으면 빈 문자열) ────────
_SMTP_HOST     = "smtp.gmail.com"
_SMTP_PORT     = 587
_SENDER        = os.environ.get("CRASH_MAIL_FROM", "m9.chapter1@gmail.com")
_RECIPIENT     = os.environ.get("CRASH_MAIL_TO",   "m9.chapter1@gmail.com")

def _load_env_mail() -> str:
    """scripts/.env.mail 파일에서 CRASH_MAIL_PASS 값을 읽어 반환."""
    env_file = Path(__file__).parent / ".env.mail"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("CRASH_MAIL_PASS=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

_APP_PASSWORD  = os.environ.get("CRASH_MAIL_PASS", "") or _load_env_mail()

# iOS 크래시 팝업 판별 키워드 (한국어/영어)
_CRASH_ALERT_KW = ["충돌함", "Crashed", "앱이 충돌", "종료되었습니다", "unexpected"]
_IXIO_BUNDLE    = "com.lguplus.aicallagent"
_LOG_DIR        = Path(__file__).parent / "crash_logs"


class CrashReporter:
    """iOS 크래시 감지 → 로그 수집 → 메일 발송 전담 클래스."""

    def __init__(self, ios_udid: str = "", android_udid: str = "",
                 ios_bundle_id: str = _IXIO_BUNDLE):
        self.ios_udid     = ios_udid
        self.android_udid = android_udid
        self._bundle_id   = ios_bundle_id
        _LOG_DIR.mkdir(exist_ok=True)

    # ── 크래시 감지 ────────────────────────────────────────────────────────────

    def detect_crash(self, driver) -> bool:
        """Appium driver 에서 iOS 크래시 팝업 또는 앱 상태를 확인.

        Returns:
            True  — 크래시 감지
            False — 정상
        """
        # 방법 1: 시스템 크래시 alert ('익시오(ixi-O) 앱이 충돌함')
        try:
            from appium.webdriver.common.appiumby import AppiumBy
            src = driver.page_source
            if any(kw in src for kw in _CRASH_ALERT_KW):
                print("🚨 [CrashReporter] 크래시 팝업 감지")
                # "안 함" 버튼 클릭해 팝업 닫기 (앱 재시작 가능 상태로)
                try:
                    btn = driver.find_element(AppiumBy.XPATH,
                        '//XCUIElementTypeButton[@name="안 함" or @name="Don\'t Send"]')
                    btn.click()
                    print("  ✓ 크래시 팝업 닫힘 ('안 함')")
                except Exception:
                    pass
                return True
        except Exception:
            pass

        # 방법 2: 앱 상태 = BACKGROUND (5 또는 6) — 정상은 RUNNING_IN_FOREGROUND(4)
        try:
            state = driver.query_app_state(self._bundle_id)
            if state in (5, 6):   # NOT_RUNNING / BACKGROUND
                print(f"🚨 [CrashReporter] 앱 상태 이상 감지 (state={state})")
                return True
        except Exception:
            pass

        return False

    # ── 로그 수집 ──────────────────────────────────────────────────────────────

    def collect_logs(self) -> dict[str, Path]:
        """iOS 크래시 로그 + Android logcat 수집 → {이름: 경로} 반환."""
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        files = {}

        # ① iOS 크래시 로그 (pymobiledevice3)
        if self.ios_udid:
            ios_log = _LOG_DIR / f"ios_crash_{ts}.log"
            try:
                result = subprocess.run(
                    ["pymobiledevice3", "crash", "list", "--udid", self.ios_udid],
                    capture_output=True, text=True, timeout=15
                )
                # 최신 크래시 리포트 1개 pull
                lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
                if lines:
                    latest = lines[-1]
                    pull = subprocess.run(
                        ["pymobiledevice3", "crash", "pull",
                         "--udid", self.ios_udid, latest, str(_LOG_DIR)],
                        capture_output=True, text=True, timeout=30
                    )
                    fetched = _LOG_DIR / latest
                    if fetched.exists():
                        ios_log = fetched
                        print(f"  ✓ iOS 크래시 리포트 수집: {fetched.name}")

                # syslog도 함께 수집 (10초 분량)
                syslog_f = _LOG_DIR / f"ios_syslog_{ts}.log"
                try:
                    slog = subprocess.run(
                        ["pymobiledevice3", "syslog", "stream",
                         "--udid", self.ios_udid, "--timeout", "5"],
                        capture_output=True, text=True, timeout=10
                    )
                    syslog_f.write_text(slog.stdout or slog.stderr, encoding="utf-8")
                    files["ios_syslog"] = syslog_f
                    print(f"  ✓ iOS syslog 수집: {syslog_f.name}")
                except Exception:
                    pass

                ios_log.write_text(
                    result.stdout or result.stderr or "(내용 없음)", encoding="utf-8"
                )
                files["ios_crash"] = ios_log
            except FileNotFoundError:
                msg = "[pymobiledevice3 미설치 — pip install pymobiledevice3]"
                ios_log.write_text(msg, encoding="utf-8")
                files["ios_crash"] = ios_log
                print(f"  ⚠️ pymobiledevice3 없음 — 설치 로그만 첨부")
            except Exception as e:
                ios_log.write_text(f"수집 오류: {e}\n{traceback.format_exc()}",
                                   encoding="utf-8")
                files["ios_crash"] = ios_log
                print(f"  ⚠️ iOS 로그 수집 실패: {e}")

        # ② Android logcat
        if self.android_udid:
            and_log = _LOG_DIR / f"android_logcat_{ts}.log"
            try:
                result = subprocess.run(
                    ["adb", "-s", self.android_udid, "logcat",
                     "-d", "-v", "time", "*:W"],
                    capture_output=True, text=True, timeout=20
                )
                and_log.write_text(result.stdout or result.stderr, encoding="utf-8")
                files["android_logcat"] = and_log
                print(f"  ✓ Android logcat 수집: {and_log.name}")
                # logcat 버퍼 클리어 (다음 실행과 중복 방지)
                subprocess.run(
                    ["adb", "-s", self.android_udid, "logcat", "-c"],
                    capture_output=True, timeout=5
                )
            except Exception as e:
                and_log.write_text(f"수집 오류: {e}", encoding="utf-8")
                files["android_logcat"] = and_log
                print(f"  ⚠️ Android 로그 수집 실패: {e}")

        # ③ macOS 시스템 정보 (간단)
        sys_log = _LOG_DIR / f"sysinfo_{ts}.txt"
        sys_log.write_text(
            f"macOS: {platform.mac_ver()[0]}\n"
            f"Python: {platform.python_version()}\n"
            f"Time: {datetime.now().isoformat()}\n"
            f"iOS UDID: {self.ios_udid}\n"
            f"Android UDID: {self.android_udid}\n",
            encoding="utf-8"
        )
        files["sysinfo"] = sys_log

        return files

    # ── 메일 발송 ──────────────────────────────────────────────────────────────

    def send_mail(self, log_files: dict[str, Path], extra_body: str = "") -> bool:
        """크래시 리포트 메일 발송.

        Returns:
            True  — 발송 성공
            False — 발송 실패
        """
        if not _APP_PASSWORD:
            print("  ⚠️ [CrashReporter] CRASH_MAIL_PASS 환경변수 없음 — 메일 생략")
            return False

        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"[ixi-O 크래시] 앱 충돌 감지 — {ts_str}"

        body = f"""ixi-O 자동화 테스트 중 앱 크래시가 감지되었습니다.

발생 시각  : {ts_str}
iOS UDID   : {self.ios_udid or '—'}
Android    : {self.android_udid or '—'}

크래시 팝업: '익시오(ixi-O) 앱이 충돌함' 시스템 alert 또는 앱 상태 이상
처리 결과  : 팝업 닫기 → 로그 수집 → 테스트 자동 재시작 예정

{"─"*50}
{extra_body}
"""

        msg = MIMEMultipart()
        msg["From"]    = _SENDER
        msg["To"]      = _RECIPIENT
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # 로그 파일 첨부
        for name, path in log_files.items():
            if path.exists():
                part = MIMEBase("application", "octet-stream")
                part.set_payload(path.read_bytes())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={path.name}"
                )
                msg.attach(part)

        try:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(_SENDER, _APP_PASSWORD)
                server.sendmail(_SENDER, _RECIPIENT, msg.as_string())
            print(f"  ✅ 크래시 리포트 메일 발송 완료 → {_RECIPIENT}")
            return True
        except smtplib.SMTPAuthenticationError:
            print("  ❌ Gmail 인증 실패 — CRASH_MAIL_PASS 앱 비밀번호를 확인하세요.")
        except Exception as e:
            print(f"  ❌ 메일 발송 실패: {e}")
        return False

    # ── 통합 처리 ──────────────────────────────────────────────────────────────

    def handle_crash(self, driver, extra_body: str = "") -> None:
        """크래시 감지 후 로그 수집 + 메일 발송까지 한 번에 처리."""
        print("\n" + "="*60)
        print("🚨 [CrashReporter] 크래시 처리 시작")
        print("="*60)
        print("  📂 로그 수집 중...")
        log_files = self.collect_logs()
        print(f"  📨 메일 발송 중 → {_RECIPIENT}")
        self.send_mail(log_files, extra_body=extra_body)
        print("="*60 + "\n")


# ── 앱 비밀번호 설정 헬퍼 (최초 1회 실행) ─────────────────────────────────────

def setup_mail_password(password: str) -> None:
    """런타임에 앱 비밀번호를 직접 주입 (환경변수 대체용)."""
    global _APP_PASSWORD
    _APP_PASSWORD = password
    # .env.mail 파일에도 저장 (재시작 후에도 유지)
    env_file = Path(__file__).parent / ".env.mail"
    env_file.write_text(f'CRASH_MAIL_PASS={password}\n', encoding="utf-8")
    print(f"  ✅ 앱 비밀번호 저장 완료: {env_file}")
