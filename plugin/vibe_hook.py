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
Mistral Vibe CLI Hook for M5Stack Approval

This module provides a hook to intercept approval requests from Vibe CLI
and send them to the M5Stack device for physical button approval.

Usage:
    from vibe_hook import approval_hook
    
    # In your Vibe workflow:
    if approval_hook.request("Commit changes", "3 files modified"):
        # User approved via M5Stack
        perform_commit()

Environment variables:
    VIBE_SESSION_NAME: Session name for multi-session support (default: auto-generated)
    VIBE_M5STACK_STRICT: If "true", forces M5Stack approval (no console fallback)
    VIBE_M5STACK_MAX_RETRIES: Max connection retries (default: 10)
    VIBE_M5STACK_RETRY_DELAY: Delay between retries in seconds (default: 2.0)
"""

import os
import time
import uuid
from .bridge import M5StackBridge


class M5StackApprovalHook:
    """
    Hooks into Vibe CLI to use M5Stack for approvals.
    
    When Vibe needs user approval, this sends the request to M5Stack
    and waits for a physical button press (A=Approve, B=Reject, C=Cancel).
    
    In strict mode (VIBE_M5STACK_STRICT=true), all approvals MUST go through
    M5Stack. In normal mode, falls back to console if M5Stack unavailable.
    """
    
    SESSION_NAME_ENV = "VIBE_SESSION_NAME"
    STRICT_MODE_ENV = "VIBE_M5STACK_STRICT"
    MAX_RETRIES_ENV = "VIBE_M5STACK_MAX_RETRIES"
    RETRY_DELAY_ENV = "VIBE_M5STACK_RETRY_DELAY"
    
    def __init__(self, port=None, auto_connect=True):
        """
        Initialize the hook.
        
        Args:
            port: Serial port (e.g., 'COM4'). If None, auto-detects.
            auto_connect: If True, connects to M5Stack on init.
        """
        self.port = port
        self.auto_connect = auto_connect
        self._session_name = None
        self.bridge = M5StackBridge(port=port, auto_connect=auto_connect)
        self.enabled = self.bridge.is_connected
        self._strict_mode = os.getenv(self.STRICT_MODE_ENV, "false").lower() == "true"
        
        if not self.enabled:
            if self._strict_mode:
                print("[WARN] [STRICT MODE] M5Stack not connected. Will retry on first request...")
            else:
                print("[WARN] M5Stack not connected. Falling back to console input.")
    
    @property
    def session_name(self):
        """Get session name from env or auto-generate."""
        if self._session_name:
            return self._session_name
        return os.getenv(self.SESSION_NAME_ENV, str(uuid.uuid4())[:8])
    
    @session_name.setter
    def session_name(self, value: str):
        """Set session name explicitly."""
        self._session_name = value
    
    @property
    def strict_mode(self):
        """Check if strict mode is enabled."""
        return self._strict_mode or os.getenv(self.STRICT_MODE_ENV, "false").lower() == "true"
    
    @property
    def max_retries(self):
        """Get max retry attempts."""
        try:
            return int(os.getenv(self.MAX_RETRIES_ENV, "10"))
        except ValueError:
            return 10
    
    @property
    def retry_delay(self):
        """Get delay between retries."""
        try:
            return float(os.getenv(self.RETRY_DELAY_ENV, "2.0"))
        except ValueError:
            return 2.0
    
    def _format_title(self, title: str) -> str:
        """Format title with session prefix."""
        session = self.session_name
        max_body_len = 30 - len(session) - 3  # 3 for [] and space
        truncated_title = title[:max_body_len] if title else ""
        return f"[{session}] {truncated_title}"
    
    def _ensure_connected(self, timeout: float = None) -> bool:
        """
        Ensure M5Stack is connected, with retries.
        
        Args:
            timeout: Total timeout in seconds
            
        Returns:
            True if connected, False otherwise
        """
        if timeout is None:
            timeout = self.max_retries * self.retry_delay + 5.0
        
        deadline = time.time() + timeout
        
        for attempt in range(self.max_retries + 1):
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            
            if self.bridge.is_connected:
                return True
            
            if attempt < self.max_retries:
                print(f"[WARN] M5Stack not connected, retry {attempt + 1}/{self.max_retries}...")
                self.bridge.connect()
                time.sleep(min(self.retry_delay, remaining))
        
        return False

    def request(self, title, body, request_id=None, timeout=30):
        """
        Request approval from user via M5Stack.
        
        In strict mode: forces M5Stack approval, retries connection.
        In normal mode: falls back to console if M5Stack unavailable.
        
        Args:
            title: Short title for the request
            body: Detailed description
            request_id: Optional unique ID
            timeout: Timeout in seconds
        
        Returns:
            bool: True if approved, False if rejected, None if cancelled
        """
        formatted_title = self._format_title(title)
        
        # In strict mode, we MUST use M5Stack
        if self.strict_mode:
            if not self._ensure_connected(timeout):
                raise RuntimeError(
                    f"[STRICT MODE] M5Stack connection failed after {self.max_retries} retries"
                )
            
            response = self.bridge.request_approval(formatted_title, body, request_id)
            
            if response is None:
                raise RuntimeError("[STRICT MODE] Approval timeout")
            
            if response.get('cancelled', False):
                print("[CANCEL] Cancelled via M5Stack")
                return None
            
            approved = response.get('approved', False)
            print(f"[{'OK' if approved else 'REJECT'}] via M5Stack")
            return approved
        
        # Normal mode: try M5Stack, fallback to console
        if self.enabled or self.bridge.is_connected:
            response = self.bridge.request_approval(formatted_title, body, request_id)
            
            if response is None:
                print("[TIMEOUT] Approval timeout, falling back to console")
            else:
                if response.get('cancelled', False):
                    print("[CANCEL] Cancelled via M5Stack")
                    return None
                
                approved = response.get('approved', False)
                print(f"[{'OK' if approved else 'REJECT'}] via M5Stack")
                return approved
        
        # Console fallback
        response = input(f"{formatted_title}\n{body}\nApprove? [y/n/c]: ").lower()
        if response == 'y':
            return True
        elif response == 'c':
            return None
        return False
    
    def is_connected(self):
        """Check if M5Stack is connected and ready."""
        return self.enabled and self.bridge.is_connected
    
    def close(self):
        """Close the connection."""
        self.bridge.close()
        self.enabled = False


# Global hook instance (optional)
approval_hook = M5StackApprovalHook()


# Example integration with Vibe CLI
if __name__ == "__main__":
    # Test the hook
    hook = M5StackApprovalHook()
    
    if hook.is_connected():
        print("Testing M5Stack approval...")
        
        # Simulate a commit approval
        if hook.request(
            title="Test Commit",
            body="This is a test approval request"
        ):
            print("✅ Commit approved!")
        else:
            print("❌ Commit rejected")
    else:
        print("M5Stack not connected. Using console fallback.")
