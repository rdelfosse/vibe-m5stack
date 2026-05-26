"""
Plugin module main entry point.

This allows running: python -m plugin [args...]
Which will load the M5Stack hook and then run Vibe CLI.

Note: Requires vibe to be installed. Use 'uv run python -m plugin' if
running from the project directory.
"""

import sys
import os
from pathlib import Path


def main():
    """Entry point for vibe-m5stack command."""
    # Add plugin directory to path (in case we're run from elsewhere)
    _PLUGIN_DIR = Path(__file__).parent.resolve()
    if str(_PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(_PLUGIN_DIR))

    # Check if vibe is available
    try:
        import vibe
    except ImportError:
        # vibe not installed - provide clear instructions
        print("Error: 'vibe' package not found in current Python environment.", file=sys.stderr)
        print("", file=sys.stderr)
        print("To use the M5Stack approval hook, please use one of:", file=sys.stderr)
        print("  1. uv run python -m plugin [args...]", file=sys.stderr)
        print("  2. .\\vibe-m5stack [args...]  (from project directory)", file=sys.stderr)
        print("  3. python -m plugin [args...]  (if vibe is installed in current env)", file=sys.stderr)
        print("", file=sys.stderr)
        print("Make sure mistral-vibe is installed in the Python environment you're using.", file=sys.stderr)
        sys.exit(1)

    # Load the hook - this monkey-patches AgentLoop
    import plugin.vibe_m5stack_hook

    # Check M5STACK_PORT for user feedback (before TUI takes over stderr)
    if not os.environ.get("M5STACK_PORT"):
        print("[m5stack] M5STACK_PORT not set, auto-detecting...", file=sys.stderr)

    # Now run Vibe CLI with the patched classes
    # Reconstruct sys.argv for Vibe: replace 'python -m plugin' with 'vibe'
    if len(sys.argv) >= 3 and sys.argv[-2] == '-m' and sys.argv[-1] == 'plugin':
        # Called as: python -m plugin (no extra args)
        sys.argv = ['vibe']
    elif len(sys.argv) >= 3 and sys.argv[1] == '-m' and sys.argv[2] == 'plugin':
        # Called as: python -m plugin arg1 arg2...
        # Replace 'python -m plugin' with 'vibe'
        sys.argv = ['vibe'] + sys.argv[3:]
    # else: leave as is (called as entrypoint, argv is already correct)

    # Import and run Vibe CLI
    from vibe.cli.entrypoint import parse_arguments, main

    # Parse arguments and run main
    try:
        args = parse_arguments()
        main()
    except SystemExit as e:
        # Preserve exit code
        sys.exit(e.code if e.code is not None else 0)


if __name__ == "__main__":
    main()
