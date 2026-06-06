"""
Vibe M5Stack - CLI commands (setup, doctor)
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
CLI commands for vibe-m5stack: setup and doctor.

These commands are dispatched BEFORE loading Vibe to allow diagnostics
and configuration without starting the full application.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from plugin import config


def print_status(symbol: str, message: str, status: str = "info") -> None:
    """Print a status line with color-aware symbols."""
    colors = {
        "success": "\033[92m",  # green
        "error": "\033[91m",    # red
        "warning": "\033[93m", # yellow
        "info": "\033[96m",     # cyan
    }
    reset = "\033[0m"
    
    # Check if colors are supported (not Windows cmd without ansi)
    use_color = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    if not use_color:
        # Fallback for non-color terminals
        symbols_map = {"✓": "[OK]", "✗": "[FAIL]", "?": "[WARN]", "⚠": "[WARN]", "i": "[INFO]"}
        symbol = symbols_map.get(symbol, symbol)
        # Sécurité encodage : sur une console Windows cp1252, un symbole unicode non
        # mappé (ex. ⚠) ferait planter print() avec UnicodeEncodeError.
        try:
            print(f"{symbol} {message}")
        except UnicodeEncodeError:
            print(f"{message}".encode("ascii", "replace").decode("ascii"))
    else:
        color = colors.get(status, colors["info"])
        try:
            print(f"{color}{symbol} {message}{reset}")
        except UnicodeEncodeError:
            print(f"{color}{message}{reset}".encode("ascii", "replace").decode("ascii"))


def check_pyserial() -> Tuple[bool, str]:
    """Check if pyserial is importable."""
    try:
        import serial
        return True, f"pyserial {serial.VERSION} trouvé"
    except ImportError:
        return False, "pyserial non installé (pip install pyserial)"


def list_serial_ports() -> list:
    """List available serial ports."""
    try:
        import serial.tools.list_ports
        return list(serial.tools.list_ports.comports())
    except Exception:
        return []


def check_cp210x_present() -> Tuple[bool, str]:
    """Check if CP210x/Silabs USB-UART device is present."""
    ports = list_serial_ports()
    if not ports:
        return False, "Aucun port série détecté"
    
    # Check for CP210x or CH340 keywords
    cp210x_keywords = ['CP210', 'CH340', 'M5STACK', 'SILABS']
    for port in ports:
        port_str = str(port).upper()
        if any(kw in port_str for kw in cp210x_keywords):
            return True, f"Trouvé: {port.device} ({port.description})"
    
    return False, (f"Pas de CP210x/CH340 ({', '.join([p.device for p in ports])}) — "
                   "requis pour FLASHER le M5Stack Fire (USB) ; pas nécessaire au runtime Bluetooth")


def check_port_resolved() -> Tuple[bool, str]:
    """Check if port can be resolved via config."""
    port = config.resolve_port()
    if port:
        return True, f"Port résolu: {port}"
    return False, "Port non résolu (essaye M5STACK_PORT ou vibe-m5stack setup)"


def check_firmware_responds(port: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """Check if firmware responds to ping on the given port.
    
    Returns:
        Tuple of (success, message, firmware_version)
    """
    if port is None:
        port = config.resolve_port()
    
    if not port:
        return False, "Aucun port pour tester", None
    
    try:
        import serial
        with serial.Serial(port, baudrate=115200, timeout=0.5) as ser:
            # Wait for a ping message (firmware sends every 5s in IDLE)
            deadline = time.monotonic() + 7.0
            buf = b""
            fw_version = None
            while time.monotonic() < deadline:
                if ser.in_waiting:
                    buf += ser.read(ser.in_waiting or 1)
                
                # Process complete lines
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line.decode("utf-8", errors="ignore"))
                        if isinstance(msg, dict) and msg.get("type") == "ping":
                            fw_version = msg.get("fw")
                            return True, f"Firmware répond sur {port} (ping reçu)", fw_version
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                
                time.sleep(0.05)
            
            return False, f"Pas de réponse du firmware sur {port} (timeout 7s)", None
    except Exception as e:
        return False, f"Erreur de connexion sur {port}: {e}", None


def check_entrypoints() -> Tuple[bool, str]:
    """Check if vibe-m5stack entrypoints are on PATH."""
    entrypoints = ['vibe', 'vibe-m5stack', 'm5stack-mcp-server']
    found = []
    missing = []
    
    for ep in entrypoints:
        try:
            # Check if the entrypoint exists on PATH
            import shutil
            ep_path = shutil.which(ep)
            if ep_path:
                found.append(ep)
            else:
                missing.append(ep)
        except Exception:
            missing.append(ep)
    
    if not missing:
        return True, f"Tous les entrypoints trouvés: {', '.join(found)}"
    return False, f"Entrypoints manquants: {', '.join(missing)} (exécute: uv tool install --reinstall mistral-vibe --with-editable . --with-executables-from vibe-m5stack)"


def check_vibe_importable() -> Tuple[bool, str]:
    """Check if vibe can be imported in current environment."""
    try:
        import vibe
        return True, "vibe importable"
    except ImportError as e:
        return False, f"vibe non importable: {e}"


def check_bt_ports() -> Tuple[bool, str]:
    """Check for Bluetooth serial ports (for BT transport)."""
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        bt_ports = [p for p in ports if 'Bluetooth' in str(p).upper() or 'Standard Serial' in str(p)]
        
        if bt_ports:
            port_names = [p.device for p in bt_ports]
            return True, f"Ports Bluetooth trouvés: {', '.join(port_names)}"
        return False, "Aucun port Bluetooth Standard Serial trouvé"
    except Exception as e:
        return False, f"Erreur de détection Bluetooth: {e}"


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """Parse a SemVer version string into (major, minor, patch).
    
    Returns (0, 0, 0) for invalid versions.
    """
    if not version_str:
        return (0, 0, 0)
    # Remove leading 'v' if present
    version_str = version_str.lstrip('v')
    # Match X.Y.Z pattern
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version_str)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return (0, 0, 0)


def compare_versions(v1: str, v2: str) -> int:
    """Compare two SemVer version strings.
    
    Returns:
        -1 if v1 < v2
        0 if v1 == v2
        1 if v1 > v2
    """
    major1, minor1, patch1 = parse_version(v1)
    major2, minor2, patch2 = parse_version(v2)
    
    if major1 < major2:
        return -1
    elif major1 > major2:
        return 1
    
    if minor1 < minor2:
        return -1
    elif minor1 > minor2:
        return 1
    
    if patch1 < patch2:
        return -1
    elif patch1 > patch2:
        return 1
    
    return 0


def get_plugin_version() -> str:
    """Get the plugin version from VERSION file or package metadata."""
    # Try reading VERSION file first
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        try:
            with open(version_file, 'r') as f:
                return f.read().strip()
        except Exception:
            pass
    
    # Fallback to package metadata
    try:
        from importlib.metadata import version
        return version("vibe-m5stack")
    except Exception:
        return "0.2.0"  # Default fallback


def cmd_doctor() -> int:
    """
    Run diagnostics and display system status.
    
    Returns:
        0 if all checks pass, 1 otherwise
    """
    print("\n" + "=" * 60)
    print("  VIBE M5STACK - Diagnostic (doctor)")
    print("=" * 60 + "\n")
    
    # Each check: (nom, fonction, catégorie, required).
    # required=False -> un échec est un WARNING (⚠) non bloquant. Cas CP210x : le
    # driver USB-UART est requis pour FLASHER le Fire (USB), mais pas au runtime
    # Bluetooth. Si le device tourne déjà en BT, son absence ne doit pas faire
    # échouer le diagnostic — d'où le warning (et non un échec dur).
    checks = [
        ("pyserial", check_pyserial, "pyserial", True),
        ("Ports série", lambda: (True, f"{len(list_serial_ports())} port(s) détecté(s)") if list_serial_ports() else (False, "Aucun port série"), "ports", True),
        ("CP210x/CH340", check_cp210x_present, "hardware", False),
        ("Port résolu", check_port_resolved, "config", True),
    ]

    # Only check firmware if port is resolved
    port = config.resolve_port()
    firmware_version = None
    if port:
        firmware_check = check_firmware_responds(port)
        # firmware_check returns (passed, message, fw_version)
        checks.append(("Firmware", lambda fv=firmware_check: fv, "firmware", True))
        firmware_version = firmware_check[2]

    checks.extend([
        ("Entrypoints", check_entrypoints, "install", True),
        ("vibe importable", check_vibe_importable, "python", True),
    ])

    # Check BT only if transport is bt (non bloquant)
    if config.get_config_transport() == "bt":
        checks.append(("BT ports", check_bt_ports, "bluetooth", False))

    all_passed = True
    for name, check_func, category, required in checks:
        try:
            result = check_func()
            # Handle both (passed, message) and (passed, message, fw_version) returns
            if isinstance(result, tuple) and len(result) == 3:
                passed, message, fw_version = result
                # Store firmware version from the firmware check
                if name == "Firmware" and fw_version:
                    firmware_version = fw_version
            else:
                passed, message = result
            if passed:
                symbol, status = "✓", "success"
            elif required:
                symbol, status = "✗", "error"
                all_passed = False
            else:
                # Échec non bloquant -> warning
                symbol, status = "⚠", "warning"
            print_status(symbol, f"{name:20s} {message}", status)
        except Exception as e:
            symbol, status = ("✗", "error") if required else ("⚠", "warning")
            print_status(symbol, f"{name:20s} Erreur: {e}", status)
            if required:
                all_passed = False
    
    # Firmware version compatibility check
    if firmware_version:
        plugin_version = get_plugin_version()
        cmp_result = compare_versions(firmware_version, plugin_version)
        if cmp_result < 0:
            print_status("⚠", f"Version firmware {firmware_version} < plugin {plugin_version} - reflashe via le web flasher", "warning")
        else:
            print_status("✓", f"Version firmware: {firmware_version} (compatible avec plugin {plugin_version})", "info")
    elif port:
        # Firmware responded but no version field (old firmware)
        print_status("⚠", "Firmware sans champ 'fw' - firmware ancien, reflashe via le web flasher", "warning")
    
    print("\n" + "=" * 60)
    if all_passed:
        print_status("✓", "Tous les checks ont réussi!", "success")
        return 0
    else:
        print_status("✗", "Certains checks ont échoué. Voir les indices ci-dessus.", "error")
        return 1


def cmd_setup() -> int:
    """
    Setup M5Stack device - detect and save port.
    
    Returns:
        0 on success, 1 on failure
    """
    print("\n" + "=" * 60)
    print("  VIBE M5STACK - Configuration (setup)")
    print("=" * 60 + "\n")
    
    # First, check prerequisites
    print("Vérification des prérequis...\n")
    
    pyserial_ok, pyserial_msg = check_pyserial()
    print_status("✓" if pyserial_ok else "✗", pyserial_msg, "success" if pyserial_ok else "error")
    
    if not pyserial_ok:
        print("\n" + "-" * 60)
        print("Erreur: pyserial est requis. Installe-le avec:")
        print("  pip install pyserial")
        print("-" * 60 + "\n")
        return 1
    
    ports = list_serial_ports()
    if not ports:
        print_status("✗", "Aucun port série détecté", "error")
        print("\n" + "-" * 60)
        print("Erreur: Aucun port série trouvé.")
        print("Vérifie que:")
        print("  1. Le M5Stack est branché par USB (câble data)")
        print("  2. Le driver CP210x est installé (Windows)")
        print("  3. Le device est sous tension")
        print("-" * 60 + "\n")
        return 1
    
    print_status("✓", f"{len(ports)} port(s) série détecté(s)", "success")
    
    # List ports for user selection
    print("\nPorts détectés:")
    for i, port in enumerate(ports, 1):
        print(f"  {i}. {port.device:15s} - {port.description}")
    
    # If only one CP210x/CH340 port, auto-select it
    cp210x_ports = []
    for port in ports:
        port_str = str(port).upper()
        if any(kw in port_str for kw in ['CP210', 'CH340', 'M5STACK', 'SILABS']):
            cp210x_ports.append(port)
    
    if len(cp210x_ports) == 1:
        selected_port = cp210x_ports[0].device
        print(f"\n✓ Port M5Stack auto-détecté: {selected_port}")
    elif len(cp210x_ports) > 1:
        print("\nPlusieurs ports CP210x/CH340 détectés. Sélectionne le bon:")
        for i, port in enumerate(cp210x_ports, 1):
            print(f"  {i}. {port.device:15s} - {port.description}")
        
        try:
            choice = input("\nNuméro du port (1-{}): ".format(len(cp210x_ports)))
            idx = int(choice) - 1
            if 0 <= idx < len(cp210x_ports):
                selected_port = cp210x_ports[idx].device
            else:
                print("Sélection invalide.")
                return 1
        except (ValueError, EOFError):
            print("Entrée invalide.")
            return 1
    else:
        # No CP210x/CH340 found, ask user to select
        print("\nAucun port CP210x/CH340 détecté. Sélectionne manuellement:")
        try:
            choice = input("\nNuméro du port (1-{}): ".format(len(ports)))
            idx = int(choice) - 1
            if 0 <= idx < len(ports):
                selected_port = ports[idx].device
            else:
                print("Sélection invalide.")
                return 1
        except (ValueError, EOFError):
            print("Entrée invalide.")
            return 1
    
    # Test the port by trying to connect and check for firmware response
    print(f"\nTest de la connexion sur {selected_port}...")
    firmware_ok, firmware_msg, _fw_version = check_firmware_responds(selected_port)
    print_status("✓" if firmware_ok else "⚠", firmware_msg, "success" if firmware_ok else "warning")
    
    # Save to config
    print(f"\nSauvegarde de la configuration...")
    transport = "bt" if "Bluetooth" in str(selected_port).upper() or "Standard Serial" in str(selected_port) else "usb"
    config.save_detected_port(selected_port, transport)
    print_status("✓", f"Port {selected_port} sauvegardé dans {config.CONFIG_FILE}", "success")
    
    print("\n" + "=" * 60)
    print("  Configuration terminée!")
    print("=" * 60 + "\n")
    return 0


def main() -> int:
    """
    Main entry point for CLI commands.
    
    Dispatches to setup or doctor commands.
    
    Returns:
        Exit code (0 = success, 1 = error)
    """
    parser = argparse.ArgumentParser(
        description="Vibe M5Stack - Commandes CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  vibe-m5stack setup       # Détecter et configurer le port
  vibe-m5stack doctor      # Diagnostic du système
  vibe-m5stack             # Lancer Vibe (comme avant)
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commandes disponibles")
    
    # Setup command
    setup_parser = subparsers.add_parser(
        "setup",
        help="Détecter et configurer le M5Stack",
        description="Détecte automatiquement le M5Stack et sauvegarde la configuration."
    )
    setup_parser.set_defaults(func=cmd_setup)
    
    # Doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnostic du système",
        description="Vérifie que tout est correctement configuré pour utiliser le M5Stack."
    )
    doctor_parser.set_defaults(func=cmd_doctor)
    
    args = parser.parse_args()
    
    if hasattr(args, "func"):
        return args.func()
    else:
        # No subcommand - this should not happen as __main__.py handles it
        parser.print_help()
        return 1
