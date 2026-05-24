"""
MCP Server for M5Stack Human Approval.

Exposes a single tool `request_human_approval(title, body)` over stdio JSON-RPC.
Wired into Vibe CLI via ~/.vibe/config.toml mcp_servers entry.
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Optional

import aiohttp

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .bridge import M5StackBridge

logger = logging.getLogger(__name__)

_bridge: Optional[M5StackBridge] = None
_credit_task: Optional[asyncio.Task] = None


# Vibe usage percentage comes from the Mistral *console* (not the public API),
# which requires an Ory session cookie + CSRF token. Set these in ~/.vibe/.env:
#   MISTRAL_SESSION_COOKIE=ory_session_xxx=...; csrftoken=...; (full Cookie value)
#   MISTRAL_CSRF_TOKEN=<value of csrftoken cookie>
# Refresh both when they expire (typically every few weeks) by logging in to
# console.mistral.ai and copying the headers from the /api/billing/v2/vibe-usage
# request in DevTools.
VIBE_USAGE_URL = "https://console.mistral.ai/api/billing/v2/vibe-usage"


async def fetch_credit_usage() -> int:
    """Fetch Vibe usage % (0-100) for the current month. Returns -1 on error."""
    cookie = os.environ.get("MISTRAL_SESSION_COOKIE")
    csrf = os.environ.get("MISTRAL_CSRF_TOKEN")
    if not cookie or not csrf:
        logger.warning("MISTRAL_SESSION_COOKIE / MISTRAL_CSRF_TOKEN not set — credit gauge disabled")
        return -1

    headers = {
        "Cookie": cookie,
        "x-csrftoken": csrf,
        "Referer": "https://console.mistral.ai/codestral/cli",
        "Accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(VIBE_USAGE_URL, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 401 or resp.status == 302:
                    logger.warning("vibe-usage auth expired — refresh session cookie")
                    return -1
                if resp.status != 200:
                    logger.warning(f"vibe-usage HTTP {resp.status}")
                    return -1
                data = await resp.json()
                pct = data.get("usage_percentage")
                if pct is None:
                    logger.warning(f"no usage_percentage in response: {data}")
                    return -1
                return max(0, min(100, int(round(pct * 100))))
    except Exception as e:
        logger.warning(f"vibe-usage fetch failed: {e}")
        return -1


async def send_credit_periodically():
    """Periodically fetch usage % and forward to the M5Stack."""
    while True:
        try:
            bridge = get_bridge()
            percent = await fetch_credit_usage()
            if percent >= 0:
                bridge.send_credit_info(percent)
                logger.debug(f"Sent credit info: {percent}%")
            # else: leave the M5Stack's last known value alone — gauge will
            # naturally show "N/A" only on cold start when nothing was sent.
        except Exception as e:
            logger.warning(f"Error in credit task: {e}")

        # Usage updates server-side at most once per minute; no need to poll faster.
        await asyncio.sleep(60)


def get_bridge() -> M5StackBridge:
    """Lazy serial open: don't touch COM8 until the first tool invocation."""
    global _bridge
    if _bridge is None:
        logger.info("Opening serial bridge to M5Stack on COM8...")
        _bridge = M5StackBridge(port="COM8", auto_connect=True)
        if not _bridge.is_connected:
            raise RuntimeError("M5Stack not reachable on COM8")
    return _bridge


server = Server("m5stack-approval")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="request_human_approval",
            description=(
                "Block until the user confirms or rejects via the physical "
                "M5Stack device. Button A=approve, B=reject, C=cancel. "
                "Use before any destructive or sensitive action."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short headline shown on the M5Stack screen.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional detailed description shown below the title.",
                    },
                },
                "required": ["title"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "request_human_approval":
        raise ValueError(f"Unknown tool: {name}")

    title = arguments["title"]
    body = arguments.get("body", "")

    # M5StackBridge.request_approval is blocking on serial I/O. Offload to a
    # worker thread so the asyncio event loop (and the MCP heartbeat) keeps running.
    bridge = get_bridge()
    response = await asyncio.to_thread(bridge.request_approval, title, body)

    if response is None:
        result = {"approved": False, "cancelled": True, "error": "timeout"}
    else:
        result = {
            "approved": bool(response.get("approved", False)),
            "cancelled": bool(response.get("cancelled", False)),
        }

    return [TextContent(type="text", text=json.dumps(result))]


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info("M5Stack MCP server starting (stdio transport)")
    async with stdio_server() as (read_stream, write_stream):
        # Start credit info task
        global _credit_task
        _credit_task = asyncio.create_task(send_credit_periodically())
        
        try:
            await server.run(read_stream, write_stream, server.create_initialization_options())
        finally:
            # Cancel credit task
            if _credit_task is not None:
                _credit_task.cancel()
                try:
                    await _credit_task
                except asyncio.CancelledError:
                    pass


def main() -> None:
    try:
        asyncio.run(amain())
    finally:
        if _bridge is not None:
            try:
                _bridge.close()
            except Exception as e:
                logger.error(f"Bridge close failed: {e}")


if __name__ == "__main__":
    main()
