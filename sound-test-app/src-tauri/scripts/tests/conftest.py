"""
tests/conftest.py
─────────────────────────────────────────────
공통 pytest fixtures 및 경로 설정.
"""
import sys
from pathlib import Path

# scripts/ 를 import 경로에 추가 (tests/ 에서 실행해도 동작하도록)
scripts_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scripts_dir))
