"""
Vibe M5Stack - CLI tests
Copyright 2026 Romain Delfosse

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
"""
Tests for plugin/cli.py - mocks only, no hardware required.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest


class MockSerial:
    """Mock for serial module."""
    VERSION = "3.5"
    
    class tools:
        class list_ports:
            @staticmethod
            def comports():
                return []


class MockSerialPort:
    """Mock for serial port object."""
    def __init__(self, device, description=""):
        self.device = device
        self.description = description
    
    def __str__(self):
        return f"{self.description} ({self.device})" if self.description else self.device


class TestCheckFunctions:
    """Tests for check_* functions with mocks."""
    
    def test_check_pyserial_importable(self):
        """Test pyserial detection when importable."""
        with patch.dict('sys.modules', {'serial': MockSerial}):
            from plugin.cli import check_pyserial
            passed, message = check_pyserial()
            assert passed is True
            assert "trouvé" in message.lower()
    
    def test_check_pyserial_not_importable(self):
        """Test pyserial detection when not importable."""
        import sys
        import builtins
        # Save original __import__
        original_import = builtins.__import__
        
        def raise_import_error(name, *args, **kwargs):
            if name == 'serial':
                raise ImportError("No module named 'serial'")
            return original_import(name, *args, **kwargs)
        
        # Temporarily replace __import__
        builtins.__import__ = raise_import_error
        
        # Clear serial from sys.modules if it exists
        if 'serial' in sys.modules:
            del sys.modules['serial']
        
        try:
            from plugin.cli import check_pyserial
            passed, message = check_pyserial()
            assert passed is False
            assert "non installé" in message.lower()
        finally:
            # Restore original __import__
            builtins.__import__ = original_import
    
    def test_list_serial_ports_empty(self):
        """Test serial port listing when no ports available."""
        mock_serial = MagicMock()
        mock_serial.tools.list_ports.comports = MagicMock(return_value=[])
        
        with patch.dict('sys.modules', {'serial': mock_serial, 'serial.tools.list_ports': mock_serial.tools.list_ports}):
            from plugin.cli import list_serial_ports
            ports = list_serial_ports()
            assert ports == []
    
    def test_list_serial_ports_with_ports(self):
        """Test serial port listing with mock ports."""
        mock_port = MockSerialPort("COM8", "Test Port")
        mock_serial = MagicMock()
        mock_serial.tools.list_ports.comports = MagicMock(return_value=[mock_port])
        
        with patch.dict('sys.modules', {'serial': mock_serial, 'serial.tools.list_ports': mock_serial.tools.list_ports}):
            from plugin.cli import list_serial_ports
            ports = list_serial_ports()
            assert len(ports) == 1
            assert ports[0].device == "COM8"
    
    def test_check_cp210x_present(self):
        """Test CP210x detection with matching port."""
        mock_port = MockSerialPort("COM8", "CP210x USB to UART Bridge")
        
        # Directly mock list_serial_ports to return our mock port
        import plugin.cli as cli_module
        original_list_ports = cli_module.list_serial_ports
        cli_module.list_serial_ports = lambda: [mock_port]
        
        try:
            from plugin.cli import check_cp210x_present
            passed, message = check_cp210x_present()
            assert passed is True
            assert "COM8" in message
        finally:
            cli_module.list_serial_ports = original_list_ports
    
    def test_check_cp210x_not_present(self):
        """Test CP210x detection with no matching port."""
        mock_port = MockSerialPort("COM8", "Some other device")
        
        import plugin.cli as cli_module
        original_list_ports = cli_module.list_serial_ports
        cli_module.list_serial_ports = lambda: [mock_port]
        
        try:
            from plugin.cli import check_cp210x_present
            passed, message = check_cp210x_present()
            assert passed is False
        finally:
            cli_module.list_serial_ports = original_list_ports
    
    def test_check_port_resolved_from_env(self):
        """Test port resolution from environment variable."""
        with patch.dict('os.environ', {'M5STACK_PORT': 'COM9'}, clear=False):
            with patch('plugin.cli.config.resolve_port', return_value='COM9'):
                from plugin.cli import check_port_resolved
                passed, message = check_port_resolved()
                assert passed is True
                assert "COM9" in message
    
    def test_check_port_resolved_from_config(self):
        """Test port resolution from config file."""
        with patch.dict('os.environ', {}, clear=False):
            with patch('plugin.cli.config.resolve_port', return_value='COM10'):
                from plugin.cli import check_port_resolved
                passed, message = check_port_resolved()
                assert passed is True
                assert "COM10" in message
    
    def test_check_port_not_resolved(self):
        """Test port resolution when no port available."""
        with patch.dict('os.environ', {}, clear=False):
            with patch('plugin.cli.config.resolve_port', return_value=None):
                from plugin.cli import check_port_resolved
                passed, message = check_port_resolved()
                assert passed is False
    
    def test_check_entrypoints_all_found(self):
        """Test entrypoint detection when all are found."""
        with patch('shutil.which', side_effect=lambda x: '/usr/bin/' + x):
            from plugin.cli import check_entrypoints
            passed, message = check_entrypoints()
            assert passed is True
            assert "Tous les entrypoints trouvés" in message
    
    def test_check_entrypoints_some_missing(self):
        """Test entrypoint detection when some are missing."""
        def mock_which(cmd):
            if cmd == 'vibe':
                return '/usr/bin/vibe'
            return None
        
        with patch('shutil.which', side_effect=mock_which):
            from plugin.cli import check_entrypoints
            passed, message = check_entrypoints()
            assert passed is False
            assert "manquants" in message.lower()


class TestDoctorCommand:
    """Tests for doctor command."""
    
    def setup_method(self):
        """Set up test environment."""
        # Patch config module to use temp directory
        import plugin.config as config_module
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_config_dir = config_module.CONFIG_DIR
        self._orig_config_file = config_module.CONFIG_FILE
        
        config_module.CONFIG_DIR = Path(self._tmp_dir)
        config_module.CONFIG_FILE = config_module.CONFIG_DIR / "config.toml"
    
    def teardown_method(self):
        """Restore original environment."""
        import plugin.config as config_module
        import shutil
        config_module.CONFIG_DIR = self._orig_config_dir
        config_module.CONFIG_FILE = self._orig_config_file
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
    
    def test_doctor_with_all_checks_passing(self, capsys):
        """Test doctor command when all checks pass."""
        from plugin.cli import cmd_doctor
        
        with patch('plugin.cli.check_pyserial', return_value=(True, "pyserial trouvé")):
            with patch('plugin.cli.list_serial_ports', return_value=[MockSerialPort("COM8")]):
                with patch('plugin.cli.check_cp210x_present', return_value=(True, "CP210x trouvé")):
                    with patch('plugin.cli.config.resolve_port', return_value='COM8'):
                        with patch('plugin.cli.check_firmware_responds', return_value=(True, "Firmware OK")):
                            with patch('plugin.cli.check_entrypoints', return_value=(True, "Entrypoints OK")):
                                with patch('plugin.cli.check_vibe_importable', return_value=(True, "vibe OK")):
                                    with patch('plugin.cli.config.get_config_transport', return_value='usb'):
                                        exit_code = cmd_doctor()
                                        assert exit_code == 0
                                        captured = capsys.readouterr()
                                        assert "Tous les checks ont réussi" in captured.out
    
    def test_doctor_with_failing_check(self, capsys):
        """Test doctor command when a check fails."""
        from plugin.cli import cmd_doctor
        
        with patch('plugin.cli.check_pyserial', return_value=(False, "pyserial manquant")):
            with patch('plugin.cli.list_serial_ports', return_value=[]):
                exit_code = cmd_doctor()
                assert exit_code == 1
                captured = capsys.readouterr()
                assert "Certains checks ont échoué" in captured.out


class TestSetupCommand:
    """Tests for setup command."""
    
    def setup_method(self):
        """Set up test environment."""
        # Patch config module to use temp directory
        import plugin.config as config_module
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_config_dir = config_module.CONFIG_DIR
        self._orig_config_file = config_module.CONFIG_FILE
        
        config_module.CONFIG_DIR = Path(self._tmp_dir)
        config_module.CONFIG_FILE = config_module.CONFIG_DIR / "config.toml"
        
        # Clean up any existing config
        if config_module.CONFIG_FILE.exists():
            config_module.CONFIG_FILE.unlink()
    
    def teardown_method(self):
        """Restore original environment."""
        import plugin.config as config_module
        import shutil
        config_module.CONFIG_DIR = self._orig_config_dir
        config_module.CONFIG_FILE = self._orig_config_file
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
    
    def test_setup_no_pyserial(self, capsys):
        """Test setup when pyserial is not installed."""
        from plugin.cli import cmd_setup
        
        with patch('plugin.cli.check_pyserial', return_value=(False, "pyserial non installé")):
            with patch('plugin.cli.list_serial_ports', return_value=[]):
                exit_code = cmd_setup()
                assert exit_code == 1
                captured = capsys.readouterr()
                assert "pyserial" in captured.out.lower()
    
    def test_setup_no_ports(self, capsys):
        """Test setup when no serial ports are available."""
        from plugin.cli import cmd_setup
        
        with patch('plugin.cli.check_pyserial', return_value=(True, "pyserial trouvé")):
            with patch('plugin.cli.list_serial_ports', return_value=[]):
                exit_code = cmd_setup()
                assert exit_code == 1
                captured = capsys.readouterr()
                assert "Aucun port série" in captured.out
    
    def test_setup_cp210x_auto_selected(self, capsys):
        """Test setup when CP210x port is auto-selected."""
        from plugin.cli import cmd_setup
        
        mock_port = MockSerialPort("COM8", "CP210x USB to UART Bridge")
        
        with patch('plugin.cli.check_pyserial', return_value=(True, "pyserial trouvé")):
            with patch('plugin.cli.list_serial_ports', return_value=[mock_port]):
                with patch('plugin.cli.check_firmware_responds', return_value=(True, "Firmware OK")):
                    with patch('plugin.cli.input', return_value='1'):
                        with patch('plugin.cli.config.save_detected_port') as mock_save:
                            exit_code = cmd_setup()
                            # Should have saved the port
                            mock_save.assert_called_once()
                            assert exit_code == 0
    
    def test_setup_saves_config(self, capsys):
        """Test that setup saves the detected port to config."""
        from plugin.cli import cmd_setup
        from plugin import config
        
        mock_port = MockSerialPort("COM7", "Test Port")
        
        with patch('plugin.cli.check_pyserial', return_value=(True, "pyserial trouvé")):
            with patch('plugin.cli.list_serial_ports', return_value=[mock_port]):
                with patch('plugin.cli.check_firmware_responds', return_value=(True, "Firmware OK")):
                    with patch('plugin.cli.input', return_value='1'):
                        exit_code = cmd_setup()
                        assert exit_code == 0
                        
                        # Verify config was saved
                        saved_config = config.load_config()
                        assert saved_config['device']['port'] == 'COM7'


class TestCLIDispatch:
    """Tests for CLI command dispatching in __main__.py"""
    
    def test_handle_cli_command_non_cli(self):
        """Test that non-CLI commands return False."""
        from plugin.__main__ import _handle_cli_command
        
        # These should NOT trigger CLI handling
        non_cli_cases = [
            (['vibe-m5stack'], False),
            (['vibe-m5stack', 'other'], False),
            (['python', '-m', 'plugin'], False),
        ]
        
        for argv, should_handle in non_cli_cases:
            result = _handle_cli_command(argv)
            assert result == should_handle
    
    def test_handle_cli_command_cli_commands(self):
        """Test that CLI commands trigger dispatch (but exit early)."""
        from plugin.__main__ import _handle_cli_command
        import plugin.__main__ as main_module
        import plugin.cli as cli_module
        
        # Save original sys.exit
        original_exit = main_module.sys.exit
        exit_called_with = []
        
        # Mock sys.exit to record the call
        def mock_exit(code=0):
            exit_called_with.append(code)
        
        main_module.sys.exit = mock_exit
        
        try:
            # Import cli.main before patching to ensure it exists
            from plugin.cli import main as cli_main_orig
            
            with patch.object(cli_module, 'main', return_value=0) as mock_cli_main:
                # These should trigger CLI handling and call sys.exit
                cli_cases = [
                    ['vibe-m5stack', 'setup'],
                    ['python', '-m', 'plugin', 'setup'],
                    ['plugin', 'setup'],
                    ['vibe-m5stack', 'SETUP'],
                    ['vibe-m5stack', 'doctor'],
                ]
                
                for argv in cli_cases:
                    exit_called_with.clear()
                    result = _handle_cli_command(argv)
                    # Since sys.exit is mocked, the function should still return True
                    # But actually it doesn't reach the return statement
                    # So we just verify that sys.exit was called
                    assert len(exit_called_with) == 1, f"sys.exit not called for {argv}"
                    mock_cli_main.assert_called()
        finally:
            main_module.sys.exit = original_exit


class TestPrintStatus:
    """Tests for print_status function."""
    
    def test_print_status_with_colors(self, capsys):
        """Test print_status with color support."""
        from plugin.cli import print_status
        
        with patch('sys.stdout.isatty', return_value=True):
            print_status("✓", "Test message", "success")
            captured = capsys.readouterr()
            # Should contain ANSI color codes
            assert "\033[92m" in captured.out  # green
            assert "✓ Test message" in captured.out
    
    def test_print_status_without_colors(self, capsys):
        """Test print_status without color support."""
        from plugin.cli import print_status
        
        with patch('sys.stdout.isatty', return_value=False):
            print_status("✓", "Test message", "success")
            captured = capsys.readouterr()
            # Should use fallback symbols
            assert "[OK] Test message" in captured.out
            assert "\033[" not in captured.out  # No ANSI codes
