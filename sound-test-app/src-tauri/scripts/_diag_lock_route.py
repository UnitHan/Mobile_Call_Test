"""
_lock_audio_route_via_agent() 동작 정밀 진단 스크립트
실행: python3 _diag_lock_route.py
"""
import sys
import os
import inspect
import importlib
import importlib.util
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
PY_FILE = SCRIPTS_DIR / 'ios_call_handler.py'

print("=" * 60)
print(f"Python 버전  : {sys.version}")
print(f"실행 경로    : {sys.executable}")
print(f".py 파일 경로: {PY_FILE}")
print(f".py mtime    : {PY_FILE.stat().st_mtime:.0f}")
print("=" * 60)

# ── 1. 소스 파일에 import os / from pathlib import Path 있는지 확인 ──
src = PY_FILE.read_text(encoding='utf-8')
lines_import_os   = [i+1 for i, l in enumerate(src.splitlines()) if l.strip().startswith('import os')]
lines_import_path = [i+1 for i, l in enumerate(src.splitlines()) if 'from pathlib import Path' in l]
print(f"\n[1] 소스 파일 import 확인")
print(f"  'import os'               : {lines_import_os or '❌ 없음!'}")
print(f"  'from pathlib import Path': {lines_import_path or '❌ 없음!'}")

# ── 2. _NATIVE_IOS_BUNDLE / _NATIVE_AND_PACKAGE 상수 확인 ──────────
native_ios = None
native_and = None
for line in src.splitlines():
    if '_NATIVE_IOS_BUNDLE' in line and '=' in line and '#' not in line.split('=')[0]:
        native_ios = line.strip()
    if '_NATIVE_AND_PACKAGE' in line and '=' in line and '#' not in line.split('=')[0]:
        native_and = line.strip()
print(f"\n[2] 클래스 상수 확인")
print(f"  {native_ios or '❌ _NATIVE_IOS_BUNDLE 없음!'}")
print(f"  {native_and or '❌ _NATIVE_AND_PACKAGE 없음!'}")

# ── 3. 조건 로직 확인 ────────────────────────────────────────────────
cond_block = []
in_func = False
for line in src.splitlines():
    if 'def _lock_audio_route_via_agent' in line:
        in_func = True
    if in_func:
        cond_block.append(line)
        if len(cond_block) > 5 and 'return False' in line:
            break
        if len(cond_block) > 30:
            break
print(f"\n[3] 조건 로직 (소스에서 직접 추출):")
for l in cond_block[:20]:
    print(f"  {l}")

# ── 4. 모듈 동적 import 후 실제 실행 테스트 ─────────────────────────
print(f"\n[4] 모듈 직접 로딩 후 실행 테스트")
spec = importlib.util.spec_from_file_location("ios_call_handler", PY_FILE)
mod  = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    print(f"  ✅ 모듈 로딩 성공")
except Exception as e:
    print(f"  ❌ 모듈 로딩 실패: {e}")
    sys.exit(1)

# ── 5. 메서드 소스 코드 검증 ─────────────────────────────────────────
mixin = mod.IosCallHandlerMixin
method = getattr(mixin, '_lock_audio_route_via_agent', None)
print(f"\n[5] 메서드 소스 검증")
if method is None:
    print(f"  ❌ _lock_audio_route_via_agent 메서드 없음!")
    sys.exit(1)
method_src = inspect.getsource(method)
has_print = '🔔' in method_src or '라우팅 고정' in method_src
print(f"  ✅ 메서드 발견 ({len(method_src)}자)")
print(f"  '🔔 [라우팅 고정]' print 포함: {'✅' if has_print else '❌ 없음!'}")

# ── 6. Mock 객체로 실제 조건 평가 테스트 ────────────────────────────
print(f"\n[6] Mock 객체로 조건 평가 테스트")

class MockAudioHandler:
    class _http:
        _serving_dir = str(SCRIPTS_DIR)

class MockObj(mixin):
    ios_app_bundle_id   = 'com.apple.mobilephone'
    android_app_package = 'com.samsung.android.dialer'
    audio_handler       = MockAudioHandler()

obj = MockObj()

NATIVE_IOS = mixin._NATIVE_IOS_BUNDLE
NATIVE_AND  = mixin._NATIVE_AND_PACKAGE

ios_bundle  = obj.ios_app_bundle_id
android_pkg = obj.android_app_package
is_native_ios = (ios_bundle  == NATIVE_IOS)
is_native_and = (android_pkg == NATIVE_AND)

print(f"  ios_bundle      = '{ios_bundle}'")
print(f"  android_pkg     = '{android_pkg}'")
print(f"  _NATIVE_IOS_BUNDLE   = '{NATIVE_IOS}'")
print(f"  _NATIVE_AND_PACKAGE  = '{NATIVE_AND}'")
print(f"  is_native_ios   = {is_native_ios}")
print(f"  is_native_and   = {is_native_and}")
cond = not is_native_ios and not is_native_and
print(f"  조건(스킵 여부): not {is_native_ios} and not {is_native_and} = {cond}")
if cond:
    print(f"  ❌ 조건이 True → return False (스킵됨!)")
else:
    print(f"  ✅ 조건이 False → 실행됨 (print 출력되어야 함)")

# ── 7. 실제 메서드 호출 (dry run) ────────────────────────────────────
print(f"\n[7] 실제 _lock_audio_route_via_agent() 호출 (dry run):")
print(f"--- 출력 시작 ---", flush=True)
try:
    result = obj._lock_audio_route_via_agent()
    print(f"--- 출력 끝 ---", flush=True)
    print(f"  반환값: {result}")
except Exception as e:
    print(f"--- 출력 끝 ---", flush=True)
    print(f"  ❌ 예외 발생: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ── 8. __pycache__ 상태 확인 ─────────────────────────────────────────
print(f"\n[8] __pycache__ 상태:")
cache_dir = SCRIPTS_DIR / '__pycache__'
for p in sorted(cache_dir.glob('ios_call_handler*.pyc')):
    mt = p.stat().st_mtime
    src_mt = PY_FILE.stat().st_mtime
    fresh = '✅ 최신' if mt >= src_mt else f'⚠️ 오래됨 (py={src_mt:.0f}, pyc={mt:.0f})'
    print(f"  {p.name}  mtime={mt:.0f}  {fresh}")

# ── 9. 실제 테스트 실행 시 사용하는 python 버전 확인 ──────────────────
print(f"\n[9] 시스템 python3 버전:")
import subprocess
r = subprocess.run(['python3', '--version'], capture_output=True, text=True)
print(f"  {r.stdout.strip() or r.stderr.strip()}")
r2 = subprocess.run(['which', 'python3'], capture_output=True, text=True)
print(f"  경로: {r2.stdout.strip()}")

print(f"\n{'='*60}")
print("진단 완료")
