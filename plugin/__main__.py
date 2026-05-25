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
# Reconstruct command line: remove '-m', 'plugin', keep the rest
if len(sys.argv) > 2 and sys.argv[-2] == '-m' and sys.argv[-1] == 'plugin':
    # Called as: python -m plugin
    vibe_args = []
elif len(sys.argv) > 2 and sys.argv[1] == '-m' and sys.argv[2] == 'plugin':
    # Called as: python -m plugin arg1 arg2
    vibe_args = sys.argv[3:]
    sys.argv = ['vibe'] + vibe_args
else:
    # Fallback: just pass through
    vibe_args = sys.argv[1:]
    sys.argv = ['vibe'] + vibe_args

# Import and run Vibe CLI
from vibe.cli.cli import run_cli
import argparse

# Parse arguments the same way Vibe does
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('initial_prompt', nargs='?')
parser.add_argument('-p', '--prompt', nargs='?', const='')
parser.add_argument('--max-turns', type=int)
parser.add_argument('--max-price', type=float)
parser.add_argument('--enabled-tools', action='append')
parser.add_argument('--output')
parser.add_argument('--agent')
parser.add_argument('--setup', action='store_true')
parser.add_argument('--workdir')
parser.add_argument('--add-dir', action='append')
parser.add_argument('--trust', action='store_true')
parser.add_argument('-c', '--continue', dest='continue_session', action='store_true')
parser.add_argument('--resume', nargs='?', const=True)

try:
    args, _ = parser.parse_known_args()
    run_cli(args)
except SystemExit:
    pass
