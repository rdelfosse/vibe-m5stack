# Vibe M5Stack Integration - Two Approaches

This repository contains two different approaches for integrating M5Stack physical button approval with Mistral Vibe CLI.

## Branch: `main`
Base repository with M5Stack firmware and MCP server plugin.

## Branch: `feat/acp` (Demo/Experimental)
**ACP (Agent Client Protocol) Pure Implementation**

This branch contains a pure ACP-based implementation that launches `vibe-acp.exe` as an ACP agent and connects a custom ACP client.

**Files:**
- `plugin/acp_poc.py` - Phase A: Proof of concept for ACP handshake
- `plugin/acp_client.py` - Phase B/C: Full ACP client with M5Stack integration

**Characteristics:**
- ✅ Protocol-level guarantee for permission requests
- ✅ Clean ACP architecture
- ❌ **Loses Vibe CLI interface** (no Textual TUI, history, autocomplete)
- ❌ Requires running separate `vibe-acp.exe` process

**Status:** Working, hardware validated, but not suitable for daily use due to missing UI.

## Branch: `feat/m5stack-hook` (Recommended)
**Monkey-Patch Hook for Vibe CLI**

This branch implements a monkey-patching approach that intercepts permission callbacks in the standard Vibe CLI, forwarding them to the M5Stack device while preserving the full Textual UI.

**Files:**
- `plugin/vibe_m5stack_hook.py` - Core hook that patches `AgentLoop.set_approval_callback`
- `plugin/__main__.py` - Entry point for `python -m plugin`
- `vibe-m5stack` - Wrapper script for easy launching
- `plugin/test_hook.py` - Unit tests

**Characteristics:**
- ✅ **Keeps 100% of Vibe CLI interface** (Textual TUI, history, autocomplete, syntax highlighting)
- ✅ Only intercepts permission requests
- ✅ Lazy bridge initialization (connects on first approval request)
- ✅ Thread-safe async bridge wrapper
- ✅ Proper error handling with fallback to deny
- ✅ Works with all Vibe CLI features

**Usage:**
```bash
# Method 1: Global command (after `uv tool install --reinstall mistral-vibe --with-editable .` — see main README §2)
vibe-m5stack [vibe options...]

# Method 2: Wrapper script from repo root — bash/zsh only
./vibe-m5stack [vibe options...]

# Method 3: Using Python module
python -m plugin [vibe options...]

# Examples:
vibe-m5stack
vibe-m5stack "Create a test file"
vibe-m5stack --prompt "Write hello to test.txt"
```

> **Note Windows / PowerShell** : `./vibe-m5stack` ne fonctionne pas — le fichier est
> sans extension et sans shebang exécutable sous Windows. Utilise soit la commande
> globale `vibe-m5stack` après l'install (Method 1, recommandé), soit
> `python .\vibe-m5stack` / `python -m plugin` (Method 3) depuis la racine du repo.

**Environment:**
- M5Stack must be connected via USB (typically COM3 on Windows)
- Requires `pyserial` to be installed
- Must be run from the project directory or have `plugin/` in PYTHONPATH

**Button Mapping:**
- **A (Button A)**: Allow the operation
- **B (Button B)**: Reject the operation  
- **C (Button C)**: Cancel the operation

**Status:** ✅ Unit tests pass, ready for hardware validation.

## Comparison

| Feature | `feat/acp` (ACP Pure) | `feat/m5stack-hook` (Monkey-Patch) |
|---------|----------------------|-----------------------------------|
| Full Vibe UI | ❌ No | ✅ Yes |
| Protocol guarantee | ✅ ACP level | ✅ Callback level |
| Permission interception | ✅ All tools | ✅ All tools |
| Implementation complexity | Medium | Low |
| Maintenance | High (separate process) | Low (integrated) |
| Recommended for | Demo/Testing | Daily Use |

## Recommendation

Use **`feat/m5stack-hook`** for production use as it preserves the full Vibe CLI experience while adding M5Stack approval.

Use **`feat/acp`** for experimentation with the ACP protocol or if you need the protocol-level guarantees that ACP provides.

## Testing

Run unit tests for the hook:
```bash
python -m plugin.test_hook
```

All tests should pass without a physical M5Stack device (uses mocks).

## Hardware Validation

For both branches, hardware validation requires:
1. M5Stack Core 2 device with approval firmware
2. USB connection to PC (COM3 typical on Windows)
3. Firmware running the approval screen

The firmware should:
- Display approval requests with title and body
- Send JSON responses: `{"approved": true}` for A, `{"cancelled": true}` for B/C
- Handle request IDs for matching responses
