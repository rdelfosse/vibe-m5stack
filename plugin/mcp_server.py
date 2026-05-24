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


async def fetch_credit_usage() -> int:
    """
    Fetch credit usage percentage from Mistral API.
    Returns percentage used (0-100).
    Returns -1 on error.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        logger.warning("MISTRAL_API_KEY not found, cannot fetch credit usage")
        return -1
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Try multiple endpoints - Mistral API structure may vary
    endpoints = [
        "https://api.mistral.ai/v1/usage",
        "https://api.mistral.ai/v1/users/me",
    ]
    
    try:
        async with aiohttp.ClientSession() as session:
            for url in endpoints:
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            data = await response.json()
                            percent = _parse_credit_from_response(data)
                            if percent >= 0:
                                return percent
                        elif response.status == 404:
                            # Endpoint not found, try next
                            continue
                        else:
                            logger.warning(f"Credit API {url} returned status {response.status}")
                except aiohttp.ClientError as e:
                    logger.debug(f"Failed to fetch from {url}: {e}")
                    continue
            
            # Also try to get organization ID and query organization usage
            try:
                org_url = "https://api.mistral.ai/v1/organizations"
                async with session.get(org_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        orgs = await response.json()
                        if orgs and isinstance(orgs, list) and len(orgs) > 0:
                            org_id = orgs[0].get("id")
                            if org_id:
                                org_usage_url = f"https://api.mistral.ai/v1/organizations/{org_id}/usage"
                                async with session.get(org_usage_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as org_response:
                                    if org_response.status == 200:
                                        org_data = await org_response.json()
                                        percent = _parse_credit_from_response(org_data)
                                        if percent >= 0:
                                            return percent
            except Exception as e:
                logger.debug(f"Failed to fetch organization usage: {e}")
            
            logger.warning("Could not fetch credit usage from any endpoint")
            return -1
    except Exception as e:
        logger.warning(f"Unexpected error fetching credit: {e}")
        return -1


def _parse_credit_from_response(data: dict) -> int:
    """
    Parse credit usage percentage from API response.
    Returns percentage (0-100) or -1 if cannot parse.
    """
    # Try different possible structures
    
    # Structure 1: {"usage": {"percent": 75}}
    if "usage" in data and isinstance(data["usage"], dict):
        if "percent" in data["usage"]:
            return int(data["usage"]["percent"])
        elif "credits" in data["usage"]:
            usage = data["usage"]["credits"]
            if "used" in usage and "total" in usage and usage["total"] > 0:
                return int((usage["used"] / usage["total"]) * 100)
    
    # Structure 2: {"credits": {"used": 750, "total": 1000}}
    elif "credits" in data and isinstance(data["credits"], dict):
        credits = data["credits"]
        if "used" in credits and "total" in credits and credits["total"] > 0:
            return int((credits["used"] / credits["total"]) * 100)
    
    # Structure 3: {"quota": {"used": 750, "total": 1000}}
    elif "quota" in data and isinstance(data["quota"], dict):
        quota = data["quota"]
        if "used" in quota and "total" in quota and quota["total"] > 0:
            return int((quota["used"] / quota["total"]) * 100)
    
    # Structure 4: {"data": [{"used_tokens": 750000, "max_tokens": 1000000}]}
    elif "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
        item = data["data"][0]
        if "used_tokens" in item and "max_tokens" in item and item["max_tokens"] > 0:
            return int((item["used_tokens"] / item["max_tokens"]) * 100)
    
    # Structure 5: Direct percent field
    elif "percent" in data:
        return int(data["percent"])
    elif "percentage" in data:
        return int(data["percentage"])
    
    # If we can't parse, log the response for debugging
    logger.debug(f"Unexpected credit API response structure: {data}")
    return -1


async def send_credit_periodically():
    """Periodically fetch and send credit usage to M5Stack."""
    while True:
        try:
            bridge = get_bridge()
            percent = await fetch_credit_usage()
            if percent >= 0:
                bridge.send_credit_info(percent)
                logger.debug(f"Sent credit info: {percent}%")
            else:
                # Send N/A (255 or special value)
                bridge.send_credit_info(0)
                logger.debug("Sent credit info: N/A")
        except Exception as e:
            logger.warning(f"Error in credit task: {e}")
        
        # Wait 5 seconds between updates (matches ping interval)
        await asyncio.sleep(5)


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
