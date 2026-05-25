"""
Plugin module main entry point.

This allows running: python -m plugin [args...]
Which will load the M5Stack hook and then run Vibe CLI.

Note: Requires vibe to be installed. Use 'uv run python -m plugin' if
running from the project directory.
"""

import sys
import os
import subprocess
from pathlib import Path

# Add plugin directory to path (in case we're run from elsewhere)
_PLUGIN_DIR = Path(__file__).parent.resolve()
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# Check if vibe is available, if not try to use uv
try:
    import vibe
    _vibe_available = True
except ImportError:
    _vibe_available = False
    # Try to find uv and re-execute with it
    uv_exe = None
    
    # Try common locations for uv
    common_paths = [
        os.path.join(os.path.expanduser("~"), ".local", "bin", "uv.exe"),
        os.path.join(os.path.expanduser("~"), ".local", "bin", "uv"),
        os.path.join(_PLUGIN_DIR.parent, ".venv", "Scripts", "uv.exe"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            uv_exe = path
            break
    
    if uv_exe:
        # Re-execute with uv run
        new_cmd = [uv_exe, "run", sys.executable, "-m", "plugin"] + sys.argv[3:]
        sys.exit(subprocess.run(new_cmd).returncode)
    else:
        print("Error: 'vibe' package not found.", file=sys.stderr)
        print("Please install mistral-vibe or use: uv run python -m plugin", file=sys.stderr)
        sys.exit(1)

# Load the hook - this monkey-patches AgentLoop
import plugin.vibe_m5stack_hook

# Now run Vibe CLI with the patched classes
# Reconstruct sys.argv for Vibe: replace 'python -m plugin' with 'vibe'
if len(sys.argv) >= 3 and sys.argv[-2] == '-m' and sys.argv[-1] == 'plugin':
    # Called as: python -m plugin (no extra args)
    sys.argv = ['vibe']
elif len(sys.argv) >= 3 and sys.argv[1] == '-m' and sys.argv[2] == 'plugin':
    # Called as: python -m plugin arg1 arg2...
    # Replace 'python -m plugin' with 'vibe'
    sys.argv = ['vibe'] + sys.argv[3:]
# else: leave as is (shouldn't happen)

# Import and run Vibe CLI
from vibe.cli.entrypoint import parse_arguments, main

# Parse arguments and run main
try:
    args = parse_arguments()
    main()
except SystemExit as e:
    # Preserve exit code
    sys.exit(e.code if e.code is not None else 0)
