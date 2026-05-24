"""
M5Stack Vibe Approval Plugin

This plugin enables Mistral Vibe CLI to use an M5Stack Core 2 device
for approval workflows (commits, PRs, etc.).

Usage:
    The plugin automatically detects the M5Stack device and sends
    approval requests to it. User responds via physical buttons.
"""

__version__ = "0.1.0"

# Note: Do NOT import bridge/approval at module level to avoid
# opening serial port prematurely. Use lazy imports instead.
