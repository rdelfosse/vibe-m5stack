"""
Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
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
M5Stack Vibe Approval Plugin

This plugin enables Mistral Vibe CLI to use an M5Stack Core 2 device
for approval workflows (commits, PRs, etc.).

Usage:
    The plugin automatically detects the M5Stack device and sends
    approval requests to it. User responds via physical buttons.
"""

from pathlib import Path

# Source unique de vérité : le fichier VERSION (pyproject dynamic version).
# En installé (wheel), la metadata du package fait foi ; en checkout source,
# on lit directement le fichier. Ne pas hardcoder ici.
try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("vibe-m5stack")
except Exception:
    try:
        __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        __version__ = "0.0.0"

# Note: Do NOT import bridge/approval at module level to avoid
# opening serial port prematurely. Use lazy imports instead.
