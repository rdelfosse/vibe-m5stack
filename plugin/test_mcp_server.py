#!/usr/bin/env python3
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
Test script for MCP Server

This simulates a Vibe CLI sending a JSON-RPC request to the MCP server.
"""

import json
import subprocess
import sys
import time
import threading
from typing import Optional


def test_mcp_server():
    """Test the MCP server by sending a request via stdin."""
    
    print("Starting MCP server subprocess...")
    
    # Start the MCP server as a subprocess
    proc = subprocess.Popen(
        [sys.executable, "-m", "plugin.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    def read_stderr():
        """Read stderr in background and print it."""
        for line in proc.stderr:
            if line.strip():
                print(f"[MCP stderr] {line.strip()}", file=sys.stderr)
    
    # Start stderr reader thread
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()
    
    # Give server time to initialize
    time.sleep(2)
    
    # Send initialize request
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }
    
    print("Sending initialize request...")
    proc.stdin.write(json.dumps(init_request) + "\n")
    proc.stdin.flush()
    
    # Read initialize response (should be on stdout)
    for _ in range(10):
        line = proc.stdout.readline()
        if line:
            response = json.loads(line)
            print(f"Initialize response: {json.dumps(response, indent=2)}")
            
            if "error" in response:
                print(f"Error: {response['error']}")
                return False
            break
        time.sleep(0.5)
    else:
        print("No initialize response received")
        return False
    
    # List tools
    list_tools_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    
    print("\nSending tools/list request...")
    proc.stdin.write(json.dumps(list_tools_request) + "\n")
    proc.stdin.flush()
    
    for _ in range(10):
        line = proc.stdout.readline()
        if line:
            response = json.loads(line)
            print(f"Tools response: {json.dumps(response, indent=2)}")
            break
        time.sleep(0.5)
    
    # Call request_human_approval (this will block waiting for M5Stack response)
    print("\nCalling request_human_approval (check your M5Stack)...")
    call_request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "request_human_approval",
            "arguments": {
                "title": "MCP Test",
                "body": "This is a test from MCP server"
            }
        }
    }
    
    proc.stdin.write(json.dumps(call_request) + "\n")
    proc.stdin.flush()
    
    # Wait for response (with timeout)
    for _ in range(40):  # 40 * 0.5s = 20s timeout
        line = proc.stdout.readline()
        if line:
            response = json.loads(line)
            print(f"Approval response: {json.dumps(response, indent=2)}")
            return True
        time.sleep(0.5)
    
    print("Timeout waiting for approval response")
    return False


if __name__ == "__main__":
    try:
        success = test_mcp_server()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
