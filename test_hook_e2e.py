"""End-to-end test of the vibe-m5stack hook, bypassing Vibe entirely.

Directly invokes plugin.vibe_m5stack_hook.m5stack_approval_callback with a fake
write_file request. If the M5Stack screen lights up and the button press
produces a real ApprovalResponse, the entire vibe-m5stack pipeline is proven OK
— hook -> bridge -> BT -> firmware -> button -> response.

Use this whenever you suspect the M5Stack/BT side and want to rule out Vibe
itself. Run it from a terminal where M5STACK_PORT is set (or pass --port).

Run:
    python test_hook_e2e.py
    python test_hook_e2e.py --port COM10
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from pydantic import BaseModel


class FakeWriteFileArgs(BaseModel):
    """Minimal mock matching what Vibe passes for write_file."""
    path: str
    content: str


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", help="M5STACK_PORT override (e.g. COM10)")
    args = parser.parse_args()

    if args.port:
        os.environ["M5STACK_PORT"] = args.port

    port = os.environ.get("M5STACK_PORT")
    if not port:
        print("ERROR: M5STACK_PORT not set and --port not given", file=sys.stderr)
        return 1

    print(f"==> Test hook end-to-end on {port}")
    print()

    # Import the hook the same way vibe-m5stack does
    sys.path.insert(0, str(Path(__file__).parent))
    from plugin.vibe_m5stack_hook import m5stack_approval_callback
    from vibe.core.types import ApprovalResponse

    fake_args = FakeWriteFileArgs(
        path="hello.txt",
        content="salut depuis le test e2e",
    )

    print("Sending fake write_file approval through the hook...")
    print("Look at the M5Stack screen — you should see an approval screen.")
    print("Press A to approve, B/C to reject. Default timeout 30s.")
    print()

    response, feedback = await m5stack_approval_callback(
        tool_name="write_file",
        args=fake_args,
        tool_call_id="test-e2e-001",
        required_permissions=None,
    )

    print()
    print(f"==> Hook returned: response={response.name}, feedback={feedback!r}")

    if response == ApprovalResponse.YES:
        print()
        print("SUCCESS: hook + bridge + BT + firmware + button = all working.")
        print("If vibe-m5stack still doesn't trigger this path, the bug is in")
        print("Vibe (model emitting tool_calls as text instead of function calls).")
        return 0
    else:
        print()
        print("Hook returned NO — could be timeout, reject, or bridge failure.")
        print("Check ~/.vibe/logs/m5stack_hook.log for the underlying reason.")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
