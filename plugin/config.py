"""
Vibe M5Stack - Configuration management
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
Configuration management for vibe-m5stack.

Handles reading/writing config.toml and port resolution with precedence:
1. M5STACK_PORT environment variable
2. config.toml [device] port
3. Auto-detection via bridge
"""

import os
import sys
from pathlib import Path
from typing import Optional

# Config file location
CONFIG_DIR = Path.home() / ".vibe-m5stack"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def _ensure_config_dir():
    """Ensure the config directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _read_toml_file(path: Path) -> dict:
    """Read a TOML file. Works with Python 3.10+ using tomllib or tomli."""
    try:
        # Python 3.11+
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (ImportError, ModuleNotFoundError):
        # Python 3.10 or earlier - use tomli if available
        try:
            import tomli
            with open(path, "rb") as f:
                return tomli.load(f)
        except (ImportError, ModuleNotFoundError):
            # Fallback: return empty dict
            return {}


def _write_toml_file(path: Path, data: dict) -> None:
    """Write a TOML file. Uses tomli-w if available, otherwise toml."""
    try:
        import tomli_w
        with open(path, "wb") as f:
            tomli_w.dump(data, f)
    except (ImportError, ModuleNotFoundError):
        try:
            import toml
            with open(path, "w", encoding="utf-8") as f:
                toml.dump(data, f)
        except (ImportError, ModuleNotFoundError):
            raise RuntimeError(
                "No TOML writer available. Please install tomli-w or toml: pip install tomli-w"
            )


def load_config() -> dict:
    """Load configuration from config.toml."""
    _ensure_config_dir()
    if CONFIG_FILE.exists():
        return _read_toml_file(CONFIG_FILE)
    return {}


def save_config(data: dict) -> None:
    """Save configuration to config.toml."""
    _ensure_config_dir()
    _write_toml_file(CONFIG_FILE, data)


def get_config_port() -> Optional[str]:
    """Get port from config.toml if present."""
    config = load_config()
    return config.get("device", {}).get("port")


def get_config_transport() -> str:
    """Get transport from config.toml. Defaults to 'usb'."""
    config = load_config()
    return config.get("device", {}).get("transport", "usb")


def resolve_port() -> Optional[str]:
    """
    Resolve the M5Stack port with precedence:
    1. M5STACK_PORT environment variable
    2. config.toml [device] port
    3. Auto-detection (via bridge._probe_port with 6s timeout)
    
    Returns:
        str: The resolved port name (e.g., "COM8", "/dev/ttyUSB0")
        None: If no port could be resolved
    """
    # Priority 1: Environment variable
    env_port = os.environ.get("M5STACK_PORT")
    if env_port:
        return env_port
    
    # Priority 2: Config file
    config_port = get_config_port()
    if config_port:
        return config_port
    
    # Priority 3: Auto-detection
    return auto_detect_port()


def auto_detect_port(timeout: float = 6.0) -> Optional[str]:
    """
    Auto-detect the M5Stack serial port.
    
    Uses bridge._probe_port with increased timeout (6s instead of 1s)
    to reliably catch the firmware's ping (sent every 5s in IDLE mode).
    
    Args:
        timeout: Maximum time to wait for a valid message (default: 6.0s)
    
    Returns:
        str: Port name if found, None otherwise
    """
    from plugin.bridge import M5StackBridge
    
    # Create a temporary bridge just for probing
    temp_bridge = M5StackBridge(auto_connect=False)
    
    # Try to auto-detect with increased timeout
    port = temp_bridge._auto_detect_port()
    if port:
        return port
    
    return None


def save_detected_port(port: str, transport: str = "usb") -> None:
    """
    Save a detected port to config.toml.
    
    Args:
        port: The port name to save
        transport: Transport type ("usb" or "bt")
    """
    config = load_config()
    if "device" not in config:
        config["device"] = {}
    config["device"]["port"] = port
    config["device"]["transport"] = transport
    save_config(config)
