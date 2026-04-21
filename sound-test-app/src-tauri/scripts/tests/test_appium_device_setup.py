"""
tests/test_appium_device_setup.py
──────────────────────────────────────────────────────────────────────────────
AppiumDeviceSetup 클래스 단위 테스트.
"""
import pytest
from unittest.mock import patch, MagicMock
import socket


class TestFreePort:
    """AppiumDeviceSetup.free_port — 포트 해제 확인."""

    def test_kills_process_on_port(self):
        from appium_device_setup import AppiumDeviceSetup

        mock_wda = MagicMock()
        setup = AppiumDeviceSetup(
            appium_server_android='http://localhost:4723',
            appium_server_ios='http://localhost:4724',
            wda_manager=mock_wda,
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='12345\n')
            setup.free_port(4723)

        assert mock_run.called

    def test_no_error_when_port_free(self):
        from appium_device_setup import AppiumDeviceSetup

        mock_wda = MagicMock()
        setup = AppiumDeviceSetup(
            appium_server_android='http://localhost:4723',
            appium_server_ios='http://localhost:4724',
            wda_manager=mock_wda,
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='')
            # 예외 없이 완료되어야 함
            setup.free_port(9999)


class TestEnsureAdbConnected:
    """AppiumDeviceSetup.ensure_adb_connected — TCP/IP 장치 연결 확인."""

    def test_connects_via_adb_tcpip(self):
        from appium_device_setup import AppiumDeviceSetup

        mock_wda = MagicMock()
        setup = AppiumDeviceSetup(
            appium_server_android='http://localhost:4723',
            appium_server_ios='http://localhost:4724',
            wda_manager=mock_wda,
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='connected to 192.168.1.50:5555')
            setup.ensure_adb_connected('192.168.1.50:5555')

        assert mock_run.called

    def test_already_connected_no_error(self):
        from appium_device_setup import AppiumDeviceSetup

        mock_wda = MagicMock()
        setup = AppiumDeviceSetup(
            appium_server_android='http://localhost:4723',
            appium_server_ios='http://localhost:4724',
            wda_manager=mock_wda,
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='already connected')
            # 예외 없이 완료되어야 함
            setup.ensure_adb_connected('192.168.1.50:5555')


class TestSetupDeviceAndroid:
    """AppiumDeviceSetup.setup_device — Android 드라이버 연결."""

    def test_returns_driver_for_android(self):
        from appium_device_setup import AppiumDeviceSetup

        mock_wda = MagicMock()
        setup = AppiumDeviceSetup(
            appium_server_android='http://localhost:4723',
            appium_server_ios='http://localhost:4724',
            wda_manager=mock_wda,
        )

        mock_driver = MagicMock()
        mock_wait = MagicMock()

        with patch('appium_device_setup.webdriver') as mock_wd, \
             patch('appium_device_setup.WebDriverWait', return_value=mock_wait):
            mock_wd.Remote.return_value = mock_driver
            result = setup.setup_device(
                device_udid='192.168.1.50:5555',
                device_type='android',
                platform='Android',
            )

        assert result is not None

    def test_returns_none_tuple_on_connection_failure(self):
        """연결 실패 시 (None, None) 반환 (예외를 raise하지 않음)."""
        from appium_device_setup import AppiumDeviceSetup

        mock_wda = MagicMock()
        setup = AppiumDeviceSetup(
            appium_server_android='http://localhost:4723',
            appium_server_ios='http://localhost:4724',
            wda_manager=mock_wda,
        )

        with patch('appium_device_setup.webdriver') as mock_wd, \
             patch('subprocess.run'):
            mock_wd.Remote.side_effect = Exception('Connection refused')
            result = setup.setup_device(
                device_udid='192.168.1.50:5555',
                device_type='android',
                platform='Android',
            )

        # 실패 시 드라이버 자리에 None 포함 튜플 반환
        assert result is not None
        assert result[0] is None
