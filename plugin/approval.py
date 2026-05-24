"""
Approval Hook for Vibe CLI

Integrates with Mistral Vibe CLI to intercept approval requests
and send them to the M5Stack device.
"""

import functools
from typing import Callable, Any, Optional
from .bridge import M5StackBridge


class ApprovalHook:
    """
    Hooks into Vibe CLI functions that require user approval.
    
    When an approval is needed, sends the request to M5Stack and
    waits for user response via physical buttons.
    """
    
    def __init__(self, bridge: Optional[M5StackBridge] = None):
        """
        Initialize the approval hook.
        
        Args:
            bridge: M5StackBridge instance. If None, creates a new one.
        """
        self.bridge = bridge or M5StackBridge()
        self.enabled = self.bridge.is_connected
    
    def wrap_approval_function(self, func: Callable, 
                               title_func: Optional[Callable] = None,
                               body_func: Optional[Callable] = None) -> Callable:
        """
        Wrap a function to intercept approval requests.
        
        Args:
            func: The original function to wrap
            title_func: Function to extract title from args
            body_func: Function to extract body from args
        
        Returns:
            Wrapped function
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                # Fallback to original function
                return func(*args, **kwargs)
            
            # Extract title and body
            title = title_func(args, kwargs) if title_func else "Approval Request"
            body = body_func(args, kwargs) if body_func else "Please review and approve"
            
            # Send to M5Stack
            response = self.bridge.request_approval(title, body)
            
            if response is None:
                print("Approval timeout - defaulting to original behavior")
                return func(*args, **kwargs)
            
            # Handle response
            if response.get('approved', False):
                print(f"Approved via M5Stack: {title}")
                return True  # Or whatever the approval returns
            elif response.get('cancelled', False):
                print(f"Cancelled via M5Stack: {title}")
                return False
            else:
                print(f"Rejected via M5Stack: {title}")
                return False
        
        return wrapper
    
    def create_approval_wrapper(self, prompt_text: str) -> Callable:
        """
        Create a simple approval wrapper for yes/no prompts.
        
        Args:
            prompt_text: The text to display
        
        Returns:
            A function that returns True if approved, False otherwise
        """
        def wrapper():
            if not self.enabled:
                # Fallback to console input
                return input(f"{prompt_text} (y/n): ").lower() == 'y'
            
            response = self.bridge.request_approval("Prompt", prompt_text)
            if response is None:
                return False
            return response.get('approved', False)
        
        return wrapper
    
    def install_hooks(self):
        """
        Install hooks into Vibe CLI (to be implemented based on Vibe's API).
        
        This would typically patch functions like:
        - confirm_commit
        - confirm_pr
        - any other approval prompts
        """
        # This is a placeholder - actual implementation depends on Vibe's internals
        print("Installing M5Stack approval hooks...")
        # Example (pseudo-code):
        # vibe.commands.confirm = self.wrap_approval_function(
        #     vibe.commands.confirm,
        #     title_func=lambda args, kwargs: kwargs.get('message', 'Confirm'),
        #     body_func=lambda args, kwargs: kwargs.get('details', '')
        # )
    
    def enable(self):
        """Enable the approval hook."""
        self.enabled = True
    
    def disable(self):
        """Disable the approval hook."""
        self.enabled = False
    
    def is_enabled(self) -> bool:
        """Check if hook is enabled."""
        return self.enabled and self.bridge.is_connected


# Convenience function to create a hook with auto-connect
def create_approval_hook(port: Optional[str] = None) -> ApprovalHook:
    """
    Create and return an ApprovalHook with auto-connect.
    
    Args:
        port: Optional serial port to use
    
    Returns:
        Configured ApprovalHook instance
    """
    bridge = M5StackBridge(port=port, auto_connect=True)
    hook = ApprovalHook(bridge)
    if hook.is_enabled():
        hook.install_hooks()
    return hook
