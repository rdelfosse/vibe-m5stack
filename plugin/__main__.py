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
""""""
Plugin module main entry point.

This allows running: python -m plugin [args...]
Which will load the M5Stack hook and then run Vibe CLI.

Note: Requires vibe to be installed. Use 'uv run python -m plugin' if
running from the project directory.
"""

import sys
import os
from pathlib import Path


def _handle_cli_command(argv: list) -> bool:
    """
    Handle CLI subcommands (setup, doctor) before loading Vibe.
    
    Args:
        argv: Command line arguments
    
    Returns:
        True if a CLI command was handled, False otherwise
    """
    # CLI commands that should NOT load Vibe
    cli_commands = {'setup', 'doctor'}
    
    # Determine the command position based on how we were called
    # Cases:
    # ['vibe-m5stack', 'setup', ...] -> command at index 1
    # ['plugin', 'setup', ...] -> command at index 1
    # ['python', '-m', 'plugin', 'setup', ...] -> command at index 3
    
    command_idx = 1
    if len(argv) >= 3 and argv[0] in ('python', 'python.exe') and argv[1] == '-m':
        # python -m plugin <command>
        command_idx = 3
    elif len(argv) >= 2 and argv[0] in ('python', 'python.exe') and argv[1].endswith('__main__.py'):
        # python ./plugin/__main__.py <command>
        command_idx = 2
    
    # Check if we have a command at the determined position
    if len(argv) <= command_idx:
        return False
    
    command = argv[command_idx].lower()
    
    if command in cli_commands:
        # Dispatch to CLI command handler
        from plugin.cli import main as cli_main
        
        # Build new_argv for CLI
        # argv is typically: ['vibe-m5stack', 'setup', ...] or ['python', '-m', 'plugin', 'setup', ...]
        if len(argv) >= 3 and argv[0] in ('python', 'python.exe') and argv[1] == '-m':
            # Called as: python -m plugin setup
            new_argv = ['vibe-m5stack'] + argv[3:]
        elif len(argv) >= 2 and argv[0] in ('python', 'python.exe') and argv[1].endswith('__main__.py'):
            # Called as: python ./plugin/__main__.py setup
            new_argv = ['vibe-m5stack'] + argv[2:]
        else:
            # Called as: vibe-m5stack setup or plugin setup
            new_argv = argv[:]
        
        sys.argv = new_argv
        exit_code = cli_main()
        sys.exit(exit_code)
    
    return False


def main():
    """Entry point for vibe-m5stack command."""
    # Add plugin directory to path (in case we're run from elsewhere)
    _PLUGIN_DIR = Path(__file__).parent.resolve()
    if str(_PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(_PLUGIN_DIR))

    # Handle CLI subcommands (setup, doctor) BEFORE loading vibe
    # This allows diagnostics and setup without requiring vibe to be installed
    if _handle_cli_command(sys.argv):
        # Command was handled, we already exited
        return

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
    from plugin import config

    # Check port resolution for user feedback (before TUI takes over stderr)
    resolved_port = config.resolve_port()
    if not resolved_port:
        print("[m5stack] No port resolved, auto-detecting...", file=sys.stderr)
    else:
        print(f"[m5stack] Port resolved: {resolved_port}", file=sys.stderr)

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
