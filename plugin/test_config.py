"""
Vibe M5Stack - Configuration tests
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
Tests for plugin/config.py - port resolution and config management.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestConfigResolution:
    """Tests for port resolution precedence: env > config > auto-detect."""
    
    def setup_method(self):
        """Set up test environment."""
        # Save original env
        self._orig_env_port = os.environ.get("M5STACK_PORT")
        # Clear M5STACK_PORT for tests
        if "M5STACK_PORT" in os.environ:
            del os.environ["M5STACK_PORT"]
        
        # Patch config module constants to use temp directory
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
        
        # Restore env
        if self._orig_env_port is not None:
            os.environ["M5STACK_PORT"] = self._orig_env_port
        elif "M5STACK_PORT" in os.environ:
            del os.environ["M5STACK_PORT"]
        
        # Restore config module constants
        config_module.CONFIG_DIR = self._orig_config_dir
        config_module.CONFIG_FILE = self._orig_config_file
        
        # Clean up temp directory
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
    
    def test_resolve_port_env_first(self):
        """Test that M5STACK_PORT env variable has highest precedence."""
        import plugin.config as config
        
        # Set env variable
        os.environ["M5STACK_PORT"] = "COM99"
        
        # Create a config file with different port
        config.save_config({"device": {"port": "COM10"}})
        
        # Mock auto_detect to return something else
        with patch.object(config, 'auto_detect_port', return_value="COM11"):
            assert config.resolve_port() == "COM99"
    
    def test_resolve_port_config_second(self):
        """Test that config.toml port is used when env is not set."""
        import plugin.config as config
        
        # Set config file port
        config.save_config({"device": {"port": "COM10"}})
        
        # Mock auto_detect to return something else
        with patch.object(config, 'auto_detect_port', return_value="COM11"):
            assert config.resolve_port() == "COM10"
    
    def test_resolve_port_auto_detect_third(self):
        """Test that auto-detect is used when env and config are not set."""
        import plugin.config as config
        
        # Mock auto_detect to return a port
        with patch.object(config, 'auto_detect_port', return_value="COM12"):
            assert config.resolve_port() == "COM12"
    
    def test_resolve_port_none(self):
        """Test that None is returned when no port is available."""
        import plugin.config as config
        
        # Mock auto_detect to return None
        with patch.object(config, 'auto_detect_port', return_value=None):
            assert config.resolve_port() is None
    
    def test_get_config_port(self):
        """Test reading port from config.toml."""
        import plugin.config as config
        
        # Config file doesn't exist
        assert config.get_config_port() is None
        
        # Create config with port
        config.save_config({"device": {"port": "COM8"}})
        assert config.get_config_port() == "COM8"
    
    def test_get_config_transport_default(self):
        """Test that transport defaults to 'usb'."""
        import plugin.config as config
        
        # Config file doesn't exist
        assert config.get_config_transport() == "usb"
        
        # Create config without transport
        config.save_config({"device": {"port": "COM8"}})
        assert config.get_config_transport() == "usb"
        
        # Create config with transport
        config.save_config({"device": {"port": "COM8", "transport": "bt"}})
        assert config.get_config_transport() == "bt"
    
    def test_save_detected_port(self):
        """Test saving detected port to config."""
        import plugin.config as config
        
        # Save a port
        config.save_detected_port("COM7", "usb")
        
        # Verify it was saved
        saved_config = config.load_config()
        assert saved_config["device"]["port"] == "COM7"
        assert saved_config["device"]["transport"] == "usb"
    
    def test_config_dir_created(self):
        """Test that config directory is created if it doesn't exist."""
        import plugin.config as config
        
        # The setup already created a temp dir, but test that it works
        config.save_config({"device": {"port": "COM1"}})
        assert config.CONFIG_FILE.exists()
    
    def test_load_empty_config(self):
        """Test loading config when file doesn't exist."""
        import plugin.config as config
        
        # Remove config file if it exists
        if config.CONFIG_FILE.exists():
            config.CONFIG_FILE.unlink()
        
        loaded = config.load_config()
        assert loaded == {}
    
    def test_config_precedence_full(self):
        """Test full precedence chain: env > config > auto-detect."""
        import plugin.config as config
        
        # Set all three
        os.environ["M5STACK_PORT"] = "COM_ENV"
        config.save_config({"device": {"port": "COM_CONFIG"}})
        
        with patch.object(config, 'auto_detect_port', return_value="COM_AUTO"):
            # Env should win
            assert config.resolve_port() == "COM_ENV"
        
        # Remove env
        del os.environ["M5STACK_PORT"]
        
        with patch.object(config, 'auto_detect_port', return_value="COM_AUTO"):
            # Config should win
            assert config.resolve_port() == "COM_CONFIG"
        
        # Remove config
        config.save_config({})
        
        with patch.object(config, 'auto_detect_port', return_value="COM_AUTO"):
            # Auto-detect should win
            assert config.resolve_port() == "COM_AUTO"


class TestConfigWriting:
    """Tests for config file writing."""
    
    def setup_method(self):
        """Set up test environment."""
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
    
    def test_save_and_load_roundtrip(self):
        """Test saving and loading config."""
        import plugin.config as config
        
        original_data = {
            "device": {
                "port": "COM5",
                "transport": "bt",
                "session_name": "test-session"
            },
            "other": {"key": "value"}
        }
        
        config.save_config(original_data)
        loaded_data = config.load_config()
        
        assert loaded_data == original_data
