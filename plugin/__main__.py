"""
Plugin module main entry point.

This allows running: python -m plugin [args...]
Which will load the M5Stack hook and then run Vibe CLI.
"""

import sys
import os
from pathlib import Path

# Add plugin directory to path (in case we're run from elsewhere)
_PLUGIN_DIR = Path(__file__).parent.resolve()
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

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
