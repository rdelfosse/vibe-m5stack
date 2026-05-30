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
Test script for M5Stack Bridge

Run this to test communication with your M5Stack device.
"""

from bridge import M5StackBridge
import time


def test_connection():
    """Test basic connection to M5Stack."""
    print("Testing M5Stack connection...")
    
    # Create bridge with auto-detect
    bridge = M5StackBridge(auto_connect=True)
    
    if not bridge.is_connected:
        print("Failed to connect to M5Stack")
        return False
    
    print(f"✓ Connected to {bridge.port}")
    
    # Test ping
    print("Sending ping...")
    bridge.send({"type": "ping"})
    
    # Wait for pong
    for _ in range(5):
        msg = bridge.receive(timeout=1.0)
        if msg:
            print(f"✓ Received: {msg}")
            break
    else:
        print("✗ No response to ping")
    
    return True


def test_approval():
    """Test approval workflow."""
    print("\nTesting approval workflow on COM8...")
    
    bridge = M5StackBridge(port="COM8", auto_connect=True)
    if not bridge.is_connected:
        return False
    
    # Send approval request
    print("Sending approval request (check your M5Stack)...")
    response = bridge.request_approval(
        title="Test Commit",
        body="This is a test approval request from PC"
    )
    
    if response:
        print(f"✓ Response received: {response}")
        approved = response.get('approved', False)
        print(f"  Approved: {approved}")
        return True
    else:
        print("✗ No response received (timeout)")
        return False


def main():
    print("=" * 50)
    print("M5Stack Vibe Approval Tool - Test Suite")
    print("=" * 50)
    
    success = True
    
    # Test 1: Connection
    if not test_connection():
        success = False
    
    # Test 2: Approval
    if not test_approval():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
    print("=" * 50)


if __name__ == "__main__":
    main()
