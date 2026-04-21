"""
tests/test_ios_wda_manager.py
──────────────────────────────────────────────────────────────────────────────
IosWdaManager 클래스 단위 테스트.

구현 상세:
 - get_iphone_ip : urllib 기반 서브넷 스캔 사용 (subprocess X)
 - get_ios_version: subprocess.run + xctrace list devices 파싱
 - find_wda_url  : ios_wda_manager 내 urllib.request.urlopen 사용
 - clear_wda_sessions: ios_wda_manager 내 urllib.request.urlopen 사용
"""
import pytest
import json
from unittest.mock import patch, MagicMock


def _urlopen_mock(body: bytes, status: int = 200):
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestGetIphoneIp:
    """IosWdaManager.get_iphone_ip — 서브넷 스캔 기반."""

    def test_returns_detected_ip_via_subnet_scan(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        def fake_urlopen(url, timeout=None):
            if '192.168.1.42' in str(url):
                return _urlopen_mock(json.dumps({'value': {'ready': True}}).encode())
            raise Exception('refused')

        with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
             patch('subprocess.run'), \
             patch('builtins.open', side_effect=Exception('no file')):
            ip = manager.get_iphone_ip('test-udid-1234')

        assert ip == '192.168.1.42'

    def test_returns_cached_ip_when_scan_fails(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()
        manager._cached_iphone_ip = '10.0.0.5'

        with patch('urllib.request.urlopen', side_effect=Exception('refused')), \
             patch('subprocess.run'), \
             patch('builtins.open', side_effect=Exception('no file')):
            ip = manager.get_iphone_ip(None)

        assert ip == '10.0.0.5'

    def test_returns_none_when_no_cache_and_all_fail(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()
        manager._cached_iphone_ip = None

        with patch('urllib.request.urlopen', side_effect=Exception('refused')), \
             patch('subprocess.run'), \
             patch('builtins.open', side_effect=Exception('no file')):
            ip = manager.get_iphone_ip(None)

        assert ip is None


class TestGetIosVersion:
    """IosWdaManager.get_ios_version — subprocess.run + xctrace 파싱."""

    def test_parses_version_from_xctrace(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        mock_result = MagicMock()
        mock_result.stdout = (
            "== Devices ==\n"
            "iPhone (test-udid-1234) (17.2.1)\n"
        )
        with patch('subprocess.run', return_value=mock_result):
            version = manager.get_ios_version('test-udid-1234')

        assert version == '17.2.1'

    def test_returns_default_when_udid_not_found(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        mock_result = MagicMock()
        mock_result.stdout = "== Devices ==\nother (99.9)\n"

        with patch('subprocess.run', return_value=mock_result):
            version = manager.get_ios_version('unknown-udid')

        assert version == '18.0'

    def test_returns_default_on_subprocess_error(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        with patch('subprocess.run', side_effect=Exception('xctrace missing')):
            version = manager.get_ios_version('any-udid')

        assert version == '18.0'


class TestFindWdaUrl:
    """IosWdaManager.find_wda_url — HTTP 프로브."""

    def test_returns_url_on_port_8100(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        def fake_urlopen(url, timeout=None):
            if ':8100/status' in str(url):
                return _urlopen_mock(json.dumps({'value': {'state': 'idle'}}).encode())
            raise Exception('not open')

        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            url = manager.find_wda_url('192.168.1.50', udid=None)

        assert url == 'http://192.168.1.50:8100'

    def test_returns_url_on_port_8200_when_8100_fails(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        def fake_urlopen(url, timeout=None):
            url_str = str(url)
            if ':8100' in url_str:
                raise Exception('refused')
            if ':8200/status' in url_str:
                return _urlopen_mock(json.dumps({'value': {'state': 'idle'}}).encode())
            raise Exception('not open')

        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            url = manager.find_wda_url('192.168.1.50', udid=None)

        assert url == 'http://192.168.1.50:8200'

    def test_returns_none_when_all_ports_fail_no_udid(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        with patch('urllib.request.urlopen', side_effect=Exception('refused')):
            url = manager.find_wda_url('192.168.1.50', udid=None)

        assert url is None


class TestClearWdaSessions:
    """IosWdaManager.clear_wda_sessions — 세션 삭제."""

    def test_deletes_active_session(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        call_count = [0]
        def fake_urlopen(req, **kwargs):
            call_count[0] += 1
            body = (
                json.dumps({'value': [{'id': 'sess-abc'}]}).encode()
                if call_count[0] == 1
                else b'{}'
            )
            return _urlopen_mock(body)

        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            manager.clear_wda_sessions('http://192.168.1.100:8100')

        assert call_count[0] >= 1

    def test_handles_empty_sessions_without_error(self):
        from ios_wda_manager import IosWdaManager
        manager = IosWdaManager()

        with patch('urllib.request.urlopen',
                   return_value=_urlopen_mock(json.dumps({'value': []}).encode())):
            manager.clear_wda_sessions('http://192.168.1.100:8100')
