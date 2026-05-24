"""
M5Stack Utilities for Vibe CLI

Provides session management, strict mode, and automatic retry logic
for M5Stack approval requests.
"""

import os
import time
import uuid
import logging
from typing import Optional, Dict, Any
from .bridge import M5StackBridge

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages session identification for M5Stack approval requests.
    
    Generates unique session IDs and handles session naming via
    environment variables or auto-generation.
    """
    
    SESSION_NAME_ENV = "VIBE_SESSION_NAME"
    STRICT_MODE_ENV = "VIBE_M5STACK_STRICT"
    MAX_RETRIES_ENV = "VIBE_M5STACK_MAX_RETRIES"
    RETRY_DELAY_ENV = "VIBE_M5STACK_RETRY_DELAY"
    
    def __init__(self):
        """Initialize session manager."""
        self._session_name: Optional[str] = None
        self._session_id: Optional[str] = None
    
    @property
    def session_name(self) -> str:
        """
        Get the session name.
        
        Priority:
        1. Explicitly set via set_session_name()
        2. VIBE_SESSION_NAME environment variable
        3. Auto-generated short UUID
        
        Returns:
            Session name string (max 12 chars for M5Stack display)
        """
        if self._session_name:
            return self._session_name[:12]
        
        name = os.getenv(self.SESSION_NAME_ENV)
        if name:
            return name[:12]
        
        # Auto-generate short session ID
        if not self._session_id:
            self._session_id = str(uuid.uuid4())[:8]
        return self._session_id[:12]
    
    @session_name.setter
    def session_name(self, value: str):
        """Set the session name explicitly."""
        self._session_name = value
    
    @property
    def is_strict_mode(self) -> bool:
        """Check if strict M5Stack mode is enabled."""
        return os.getenv(self.STRICT_MODE_ENV, "false").lower() == "true"
    
    @property
    def max_retries(self) -> int:
        """Get maximum retry attempts for M5Stack connection."""
        try:
            return int(os.getenv(self.MAX_RETRIES_ENV, "10"))
        except ValueError:
            return 10
    
    @property
    def retry_delay(self) -> float:
        """Get delay between retries in seconds."""
        try:
            return float(os.getenv(self.RETRY_DELAY_ENV, "2.0"))
        except ValueError:
            return 2.0
    
    def format_title(self, title: str) -> str:
        """
        Format a title with session prefix.
        
        Args:
            title: Original title
            
        Returns:
            Formatted title with session prefix: [SessionName] Title
        """
        session = self.session_name
        # Ensure total length doesn't exceed reasonable display limits
        max_body_len = 30 - len(session) - 3  # 3 for [] and space
        truncated_title = title[:max_body_len] if title else ""
        return f"[{session}] {truncated_title}"


class StrictApprovalHandler:
    """
    Handles approval requests in strict M5Stack mode.
    
    Automatically routes all approval requests through M5Stack
    with session management and automatic retry logic.
    """
    
    def __init__(self, bridge: Optional[M5StackBridge] = None):
        """
        Initialize the strict approval handler.
        
        Args:
            bridge: M5StackBridge instance. If None, creates a new one.
        """
        self.bridge = bridge or M5StackBridge(auto_connect=True)
        self.session_manager = SessionManager()
    
    def request_approval(
        self,
        title: str,
        body: str,
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Send an approval request with session management and retries.
        
        Args:
            title: Short title for the request
            body: Detailed description
            timeout: Maximum total time to wait (including retries)
            
        Returns:
            Response message from M5Stack or None on failure
        """
        formatted_title = self.session_manager.format_title(title)
        
        max_retries = self.session_manager.max_retries
        retry_delay = self.session_manager.retry_delay
        
        if timeout is None:
            # Default timeout: retries * delay + buffer
            timeout = max_retries * retry_delay + 5.0
        
        deadline = time.time() + timeout
        last_error = None
        
        for attempt in range(max_retries + 1):
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning(
                    f"Strict approval timed out after {timeout}s: {formatted_title}"
                )
                return None
            
            # Ensure bridge is connected
            if not self.bridge.is_connected:
                if attempt < max_retries:
                    logger.info(
                        f"M5Stack not connected, retry {attempt + 1}/{max_retries}..."
                    )
                    self.bridge.connect()
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error("M5Stack connection failed after all retries")
                    return None
            
            try:
                response = self.bridge.request_approval(
                    formatted_title, body
                )
                
                if response is not None:
                    logger.debug(
                        f"Approval response received: {response}"
                    )
                    return response
                
                last_error = "No response received"
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"Approval request error: {e}")
            
            # Retry logic
            if attempt < max_retries:
                wait_time = min(retry_delay, remaining)
                logger.info(
                    f"Retry {attempt + 1}/{max_retries} in {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
        
        logger.error(
            f"Strict approval failed after {max_retries + 1} attempts: {last_error}"
        )
        return None
    
    def request_approval_strict(
        self,
        title: str,
        body: str,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Strict approval request that returns a simple boolean.
        
        Args:
            title: Short title for the request
            body: Detailed description
            timeout: Maximum time to wait
            
        Returns:
            True if approved, False if rejected or cancelled, raises on error
            
        Raises:
            RuntimeError: If M5Stack is unavailable in strict mode
        """
        if self.session_manager.is_strict_mode:
            response = self.request_approval(title, body, timeout)
            
            if response is None:
                raise RuntimeError(
                    f"M5Stack approval timeout in strict mode: {title}"
                )
            
            if response.get('approved', False):
                return True
            elif response.get('cancelled', False):
                return False
            else:
                return False
        else:
            # Fallback to console input in non-strict mode
            return input(f"{body} (y/n): ").lower() == 'y'
    
    def set_session_name(self, name: str):
        """Set the session name explicitly."""
        self.session_manager.session_name = name
    
    @property
    def session_name(self) -> str:
        """Get the current session name."""
        return self.session_manager.session_name


# Global singleton instance
_approval_handler: Optional[StrictApprovalHandler] = None


def get_approval_handler() -> StrictApprovalHandler:
    """
    Get the global approval handler instance.
    
    Returns:
        Singleton StrictApprovalHandler instance
    """
    global _approval_handler
    if _approval_handler is None:
        _approval_handler = StrictApprovalHandler()
    return _approval_handler


def request_m5stack_approval(
    title: str,
    body: str,
    session_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to request M5Stack approval.
    
    Args:
        title: Short title for the request
        body: Detailed description
        session_name: Optional session name override
        
    Returns:
        Response message from M5Stack or None on failure
    """
    handler = get_approval_handler()
    
    if session_name:
        handler.set_session_name(session_name)
    
    return handler.request_approval(title, body)


def request_m5stack_approval_strict(
    title: str,
    body: str,
    session_name: Optional[str] = None
) -> bool:
    """
    Convenience function for strict boolean approval.
    
    Args:
        title: Short title for the request
        body: Detailed description
        session_name: Optional session name override
        
    Returns:
        True if approved, False otherwise. Raises in strict mode on error.
    """
    handler = get_approval_handler()
    
    if session_name:
        handler.set_session_name(session_name)
    
    return handler.request_approval_strict(title, body)
