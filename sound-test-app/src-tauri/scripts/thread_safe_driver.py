"""
thread_safe_driver.py
──────────────────────────────────────────────────────────────────────────────
Appium WebDriver 스레드 안전 래퍼.

UiAutomator2는 단일 스레드 서비스이므로, 여러 Python 스레드가 동시에
driver.page_source, driver.find_element() 등을 호출하면 instrumentation 크래시가 발생한다.
이 래퍼는 RLock으로 모든 드라이버 호출을 직렬화하여 경쟁 조건을 방지한다.
"""
import threading


class ThreadSafeDriver:
    """Appium WebDriver를 RLock으로 감싸 모든 호출을 직렬화하는 래퍼."""

    # Lock 없이 직접 접근 허용하는 속성 (내부 관리용)
    _PASSTHROUGH = frozenset({
        '_driver', '_lock', '_PASSTHROUGH',
    })

    def __init__(self, driver):
        object.__setattr__(self, '_driver', driver)
        object.__setattr__(self, '_lock', threading.RLock())

    # ── property 접근 ────────────────────────────────────────────────────

    @property
    def page_source(self):
        with self._lock:
            return self._driver.page_source

    @property
    def current_activity(self):
        with self._lock:
            return self._driver.current_activity

    @property
    def session_id(self):
        return self._driver.session_id  # read-only, thread-safe

    @property
    def capabilities(self):
        return self._driver.capabilities  # read-only dict

    # ── 일반 메서드 프록시 ────────────────────────────────────────────────

    def __getattr__(self, name):
        attr = getattr(self._driver, name)
        if not callable(attr):
            # RLock 보호 하에 속성 읽기
            with self._lock:
                return getattr(self._driver, name)
        # callable → Lock 으로 감싸기
        def _synchronized(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)
        return _synchronized

    def __setattr__(self, name, value):
        if name in ThreadSafeDriver._PASSTHROUGH:
            object.__setattr__(self, name, value)
        else:
            with self._lock:
                setattr(self._driver, name, value)

    # ── context manager ──────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self._driver.quit()
        except Exception:
            pass

    # ── 원본 드라이버 접근 (Lock 없이 — ADB 폴백 등에서 필요) ───────────

    @property
    def unwrapped(self):
        """원본 Appium WebDriver 반환 (Lock 미적용 — 주의해서 사용)."""
        return self._driver
