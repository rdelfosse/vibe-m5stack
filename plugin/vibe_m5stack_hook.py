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
Vibe M5Stack Hook - Intercepts tool permission requests and forwards to M5Stack device.

This module monkey-patches Vibe's AgentLoop to wrap the approval callback
with a race between the native Textual UI modal and the M5Stack device.
Whichever responds first wins.

Usage:
    This module is automatically loaded by the vibe-m5stack wrapper script.
    It should NOT be imported directly.

Environment:
    - M5Stack must be connected via USB
    - Requires pyserial to be installed
    - Optional: M5STACK_PORT env var to specify port (e.g., "COM8")
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Setup logging to file only - NO stderr to avoid TUI pollution
from plugin import config
_log_dir = Path.home() / ".vibe" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(_log_dir / "m5stack_hook.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger = logging.getLogger("m5stack_hook")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.propagate = False  # CRITICAL - prevents logs from bubbling to root logger (stderr)

# Add plugin directory to path
_PLUGIN_DIR = Path(__file__).parent.resolve()
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from plugin.bridge import M5StackBridge
from plugin.m5stack_utils import SessionManager
# Fail-fast AVANT tout import spécifique >=2.23 (ApprovalRequestEvent
# n'existe pas en 2.22 : l'importer d'abord donnerait un ImportError cryptique
# au lieu de ce message actionnable).
from vibe.core.agent_loop import AgentLoop
if hasattr(AgentLoop, "set_approval_callback"):  # API < 2.23
    raise RuntimeError(
        "vibe-m5stack >= 0.5.1 requiert mistral-vibe >= 2.23 "
        "(détecté : ancienne API d'approbation). Mets à jour : uv tool upgrade mistral-vibe"
    )

from vibe.core.types import ApprovalResponse
from vibe.core.tools.permissions import RequiredPermission

from vibe.core.types import (
    UserMessageEvent,
    AssistantEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
    WaitingForInputEvent,
    CompactStartEvent,
    CompactEndEvent,
    PlanReviewRequestedEvent,
    SessionTitleUpdatedEvent,
    ApprovalRequestEvent,
)

# Global state tracking for status
_status_seq = 0
_last_status_state = "done"
_last_status_detail = ""
_last_status_activity = ""
# Global references for voice handler callbacks
_agent_loop = None
_asyncio_loop = None
# Instance de la TUI (VibeApp en >=2.23, TextualUI avant), capturée à sa
# construction via _patch_tui_capture() : sert à soumettre les prompts vocaux
# comme de vrais messages utilisateur.
_tui_instance = None
# request_id (uuid) de l'approbation broker en cours : posé par la course
# _race_m5stack_approval, consommé par le reject vocal. L'id série (int) du
# protocole device ne peut PAS transporter l'uuid — une seule approbation à la
# fois côté device, donc un global suffit.
_active_broker_request_id = None

# Tool classification for thinking activity
READING_TOOLS = {"read_file", "read", "grep", "search", "glob", "ls",
                 "list_dir", "web_fetch", "fetch", "web_search"}
EXEC_TOOLS = {"bash", "shell", "run", "write_file", "write",
              "search_replace", "str_replace", "edit", "apply_patch"}

# Session manager singleton for multi-session support
_session_mgr = SessionManager()




def map_event_to_status(event) -> tuple:
    """Map Vibe events to agent states and activities."""
    global _status_seq, _last_status_activity
    
    state = "thinking"
    detail = ""
    activity = "reasoning"  # Default activity for thinking state
    seq_increment = False
    
    event_type = type(event).__name__
    
    if event_type in ("ToolCallEvent", "AssistantEvent", "ReasoningEvent", "ToolStreamEvent"):
        state = "thinking"
        # Only ToolCallEvent carries a tool_name. For the others, leave detail
        # empty — never fall back to str(event), which is the Python object repr
        # and would be shown verbatim on the device screen.
        tool_name = getattr(event, "tool_name", None)
        detail = str(tool_name)[:40] if tool_name else ""
        seq_increment = True
        
        # Determine activity based on event type and tool name
        if event_type == "ReasoningEvent":
            activity = "reasoning"
        elif event_type == "AssistantEvent":
            activity = "streaming"
        elif event_type == "ToolStreamEvent":
            # Keep the current activity (streaming of tool output)
            # We'll use the stored activity from ToolCallEvent
            activity = _last_status_activity if _last_status_activity else "reasoning"
        elif event_type == "ToolCallEvent":
            # Classify tool as reading or exec
            if tool_name and tool_name in READING_TOOLS:
                activity = "reading"
            elif tool_name and tool_name in EXEC_TOOLS:
                activity = "tool_exec"
            else:
                # Default to tool_exec for unknown tools
                activity = "tool_exec"
    elif event_type == "WaitingForInputEvent":
        state = "waiting"
        detail = "awaiting input"
        activity = ""  # Not applicable for waiting state
    elif event_type == "CompactStartEvent":
        state = "thinking"
        detail = "compacting"
        activity = "reasoning"
        seq_increment = True
    elif event_type in ("CompactEndEvent", "SessionTitleUpdatedEvent", "PlanReviewRequestedEvent"):
        state = "thinking"
        activity = "reasoning"
        seq_increment = True
    elif event_type == "ToolResultEvent":
        state = "thinking"
        activity = "reasoning"
        seq_increment = True
    
    if seq_increment:
        _status_seq += 1
    
    # Store activity for ToolStreamEvent to reference
    if activity:
        _last_status_activity = activity
    
    return state, detail, _status_seq, activity


# Owner-broker manager (lazily initialized on first use).
_broker_mgr: Any = None
_broker_init_attempted = False


def get_or_init_broker():
    """Lazily build and initialize the owner-broker manager.

    On first call: opens the M5Stack port (owner) or connects to an existing
    owner's socket (client). Returns the BrokerManager, or None if init failed
    (in which case the approval path falls back to the ephemeral bridge).
    """
    global _broker_mgr, _broker_init_attempted
    if _broker_mgr is not None:
        return _broker_mgr
    if _broker_init_attempted:
        return None  # already failed once; don't retry on every event
    _broker_init_attempted = True
    try:
        import atexit
        from plugin.broker import BrokerManager

        port = config.resolve_port()
        raw_bridge = M5StackBridge(port=port, auto_connect=False)
        session = _session_mgr.session_name or "default"
        mgr = BrokerManager(raw_bridge, session)
        mgr.initialize()
        _broker_mgr = mgr
        atexit.register(_safe_close_broker)
        logger.info(f"Broker initialized: role={mgr.role}")
        return _broker_mgr
    except Exception as e:
        logger.error(f"Broker init failed: {e}")
        return None


def _safe_close_broker():
    try:
        if _broker_mgr is not None:
            _broker_mgr.close()
    except Exception:
        pass


def _broker_can_approve(mgr) -> bool:
    """True if the broker can actually reach the device for an approval."""
    if mgr is None or mgr.role is None:
        return False
    if mgr.is_owner():
        conn = getattr(mgr.bridge, "serial_conn", None)
        return conn is not None and conn.is_open
    if mgr.is_client():
        return mgr.client is not None and mgr.client.owner_port is not None
    return False


_last_push_state = None
_last_push_activity = None
_last_push_monotonic = 0.0
_PUSH_THROTTLE_S = 0.25  # min interval between same-state+activity pushes


def push_status_to_device(state: str, detail: str = "", seq: int = 0, activity: str = "") -> bool:
    """Push agent status to the M5Stack via the owner-broker (best-effort).

    Streaming events (assistant/tool chunks) can fire hundreds of times per turn;
    we throttle same-state+activity pushes so we don't saturate the (BT) serial link.
    State transitions always go through immediately.
    """
    global _last_push_state, _last_push_activity, _last_push_monotonic
    import time

    now = time.monotonic()
    # Throttle based on (state, activity) tuple - only throttle if both are the same
    if state == _last_push_state and activity == _last_push_activity and (now - _last_push_monotonic) < _PUSH_THROTTLE_S:
        return True
    _last_push_state = state
    _last_push_activity = activity
    _last_push_monotonic = now

    mgr = get_or_init_broker()
    if mgr is None:
        return False
    try:
        return mgr.push_status(state, detail, seq, activity)
    except Exception as e:
        logger.error(f"Failed to push status: {e}")
        return False

class ThreadSafeM5StackBridge:
    """Thread-safe wrapper around M5StackBridge for async/sync boundary."""

    def __init__(self, bridge: M5StackBridge):
        self._bridge = bridge
        self._lock = asyncio.Lock()

    async def request_approval(
        self, title: str, body: str, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        """
        Request approval from M5Stack with thread safety.
        
        Returns:
            dict with 'approved' (bool) and 'cancelled' (bool) keys
            or None on timeout/error
        """
        import threading

        async def _do_request() -> dict[str, Any] | None:
            loop = asyncio.get_event_loop()
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        self._bridge.request_approval,
                        title[:40],  # M5Stack display limit
                        body[:200],
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("M5Stack approval timeout")
                return None
            except Exception as e:
                logger.error(f"M5Stack bridge error: {e}")
                return None

        async with self._lock:
            return await _do_request()

    def is_connected(self) -> bool:
        return self._bridge.is_connected


# Global bridge instance (initialized on first use)
_bridge: ThreadSafeM5StackBridge | None = None


def get_m5stack_bridge() -> ThreadSafeM5StackBridge | None:
    """Get or create the global M5Stack bridge instance.
    
    This function now does lazy initialization - the bridge is only created
    on the first approval request, not at module import time.
    Uses M5STACK_PORT env var if set.
    """
    global _bridge
    return _bridge


def format_tool_info(tool_name: str, args: BaseModel) -> tuple[str, str]:
    """Format tool info for M5Stack display.
    
    Returns:
        (title, body) tuple
    """
    title = tool_name[:40]
    
    # Extract relevant info from args
    body_parts = [f"Tool: {tool_name}"]
    
    if hasattr(args, 'model_dump'):
        args_dict = args.model_dump()
    elif hasattr(args, '__dict__'):
        args_dict = args.__dict__
    else:
        args_dict = {}
    
    # Common patterns for mutable tools
    if 'path' in args_dict:
        path = str(args_dict['path'])
        body_parts.append(f"Path: {path[:60]}")
    
    if 'content' in args_dict:
        content = str(args_dict.get('content', ''))
        preview = content[:50] + '...' if len(content) > 50 else content
        body_parts.append(f"Content: {preview}")
    
    if 'file_path' in args_dict:
        body_parts.append(f"File: {args_dict['file_path'][:60]}")
    
    if 'command' in args_dict:
        cmd = str(args_dict['command'])
        body_parts.append(f"Command: {cmd[:60]}")
    
    body = "\n".join(body_parts[:5])  # Limit to 5 lines
    return title, body


async def m5stack_approval_callback(
    tool_name: str,
    args: BaseModel,
    tool_call_id: str,
    required_permissions: list[RequiredPermission] | None = None,
    request_id: str | None = None,
) -> tuple[ApprovalResponse, str | None] | None:
    """
    Approval callback that forwards to M5Stack device.
    
    This is called as part of a race with the original Textual UI callback.
    
    Returns:
        tuple of (ApprovalResponse, optional_message)
        - YES: operation approved
        - NO: operation rejected
    """
    global _bridge

    title, body = format_tool_info(tool_name, args)
    # Prefix title with session name for multi-session identification
    title = _session_mgr.format_title(title)
    title = title[:40]  # safe truncate pour M5Stack
    logger.info(f"Permission requested: {title}")

    # Preferred path: route through the owner-broker so status + approval share
    # the single persistent connection (and multi-session works).
    # NB : request_id est l'uuid du broker Vibe — il ne passe PAS sur le
    # protocole série (ids int). Le matching série garde ses ids générés ;
    # la résolution Vibe utilise l'uuid via _active_broker_request_id.

    mgr = get_or_init_broker()
    if _broker_can_approve(mgr):
        try:
            if mgr.is_owner():
                # broker.request_approval is blocking (serial) -> off the event loop
                response = await asyncio.to_thread(
                    mgr.broker.request_approval, title, body, None
                )
            else:
                # Use the provided request_id instead of generating a new one
                actual_req_id = int(asyncio.get_event_loop().time() * 1000) % 1_000_000
                response = await mgr.client.request_approval(title, body, actual_req_id)
        except Exception as e:
            logger.error(f"Broker approval error: {e}")
            response = None
    else:
        # Fallback: ephemeral bridge (no broker / device unreachable via broker).
        if _bridge is None:
            try:
                port = config.resolve_port()
                raw_bridge = M5StackBridge(port=port, auto_connect=False)
                _bridge = ThreadSafeM5StackBridge(raw_bridge)
                if raw_bridge.is_connected:
                    logger.info(f"M5Stack port detected (fallback): {raw_bridge.port}")
                else:
                    logger.error("M5Stack auto-detect failed. Set M5STACK_PORT=COMx explicitly.")
            except Exception as e:
                logger.error(f"Failed to initialize M5Stack bridge: {e}")
                return None
        if not _bridge.is_connected():
            return None
        # NB : la signature du wrapper est (title, body, timeout) — surtout ne
        # pas passer un id en 3e position (il partirait en timeout).
        response = await _bridge.request_approval(title, body)

    if response is None:
        logger.warning("M5Stack approval timeout or error - no resolution from device")
        return None

    if response.get("cancelled", False):
        logger.info("Permission DENIED via M5Stack (cancelled)")
        return (
            ApprovalResponse.NO,
            "User rejected via M5Stack - provide an alternative plan",
        )

    if response.get("approved", False):
        logger.info("Permission GRANTED via M5Stack")
        return (ApprovalResponse.YES, None)

    # Response from device but unknown format - treat as no valid response
    logger.warning("Permission: M5Stack returned unknown response format - no resolution")
    return None


# -- Monkey patching --------------------------------------------------------


async def _race_m5stack_approval(agent_loop, ev):
    """Demande au device ; s'il répond avant la TUI, résout via l'API publique."""
    global _active_broker_request_id
    # Publie l'uuid broker de l'approbation en cours pour le reject vocal
    # (l'id série int du device ne peut pas transporter l'uuid).
    _active_broker_request_id = ev.request_id
    try:
        response_feedback = await m5stack_approval_callback(
            ev.tool_name, ev.tool_args, ev.tool_call_id, ev.required_permissions, ev.request_id
        )
        if response_feedback is not None:
            response, feedback = response_feedback
            # Ignoré silencieusement par le broker si la TUI a déjà résolu.
            agent_loop.resolve_approval_request(ev.request_id, response, feedback)
            # Best-effort : signaler à la TUI que le device a tranché (sa
            # modal ne s'auto-ferme pas forcément sur une résolution externe).
            tui = _tui_instance
            if tui is not None:
                try:
                    # Même loop asyncio que la TUI : appel direct (PAS
                    # call_from_thread, qui exige un thread différent).
                    verdict = "approuve" if response == ApprovalResponse.YES else "refuse"
                    tui.notify(f"{ev.tool_name} {verdict} via M5Stack",
                               title="M5Stack", timeout=3)
                except Exception:
                    pass
    except Exception:
        logger.exception("M5Stack approval race failed")  # ne jamais casser le tour
    finally:
        _active_broker_request_id = None


def _patch_tui_capture():
    """Capture l'instance de la TUI à sa construction.

    En >=2.23, AgentLoop.set_approval_callback n'existe plus (c'était notre
    point de capture) : on patche __init__ de la classe d'app TUI (VibeApp,
    ex-TextualUI). Sans capture, les prompts vocaux retomberaient sur
    inject_user_context, qui ne démarre pas de tour.
    """
    try:
        import vibe.cli.textual_ui.app as _appmod
    except Exception as e:
        logger.warning(f"Module TUI introuvable ({e}) - prompts vocaux en mode dégradé")
        return
    app_cls = getattr(_appmod, "VibeApp", None) or getattr(_appmod, "TextualUI", None)
    if app_cls is None:
        logger.warning("Classe d'app TUI introuvable - prompts vocaux en mode dégradé")
        return

    orig_init = app_cls.__init__

    def captured_init(self, *args, **kwargs):
        global _tui_instance
        orig_init(self, *args, **kwargs)
        _tui_instance = self

    app_cls.__init__ = captured_init
    logger.info(f"TUI capture installée sur {app_cls.__name__}")


def patch_act_for_status():
    """Patch AgentLoop.act to observe events and push status."""
    from vibe.core.agent_loop import AgentLoop
    
    _orig_act = AgentLoop.act
    
    async def patched_act(self, msg, *args, **kwargs):
        """Wrapped act that observes events and pushes status."""
        global _status_seq, _last_status_activity, _agent_loop, _asyncio_loop
        # Store agent loop and event loop for voice handler callbacks
        _agent_loop = self
        _asyncio_loop = asyncio.get_running_loop()

        
        # Push thinking state at start of turn
        push_status_to_device("thinking", "", 0, "reasoning")
        _status_seq = 0  # Reset seq for new turn
        _last_status_activity = "reasoning"
        
        try:
            async for ev in _orig_act(self, msg, *args, **kwargs):
                # Handle approval requests - race M5Stack against TUI
                if type(ev).__name__ == "ApprovalRequestEvent":
                    # Observer, ne PAS consommer : on re-yield l'event pour la TUI,
                    # et on lance la course M5Stack en tâche de fond.
                    asyncio.create_task(_race_m5stack_approval(self, ev))
                # Map event to status and push
                state, detail, seq, activity = map_event_to_status(ev)
                push_status_to_device(state, detail, seq, activity)
                yield ev
            
            # Push done state at end of turn
            push_status_to_device("done", "", _status_seq + 1)
        except Exception as e:
            push_status_to_device("error", str(e)[:40], _status_seq + 1)
            raise
    
    AgentLoop.act = patched_act
    logger.info("AgentLoop.act patched for status tracking")





# -- Initialization --------------------------------------------------------

def install_hook():
    """Install the M5Stack approval hook.
    
    Call this before starting Vibe CLI.
    """
    logger.info("Installing Vibe M5Stack approval hook...")

    patch_act_for_status()
    _patch_tui_capture()

    # Setup voice handler callbacks
    try:
        from plugin.voice_handler import get_voice_handler
        handler = get_voice_handler()

        async def _submit_voice_text(tui, text: str):
            # TUI libre : soumettre comme un vrai message (démarre un tour).
            # Agent occupé : injecter dans le tour EN COURS — le drain se fait
            # entre deux étapes LLM, donc la todo en tient compte tout de
            # suite. (La file TUI, elle, ne délivre qu'à la fin de la todo —
            # trop tard pour un commentaire d'approve.)
            if tui._is_busy() and _agent_loop is not None:
                await _agent_loop.inject_user_context(text)
                try:
                    tui.notify(f"Voix -> tour en cours : {text[:60]}",
                               title="M5Stack", timeout=4)
                except Exception:
                    pass
            elif tui._is_busy():
                await tui._handle_queue_submit(text, reject_hint="voice input rejected")
            else:
                await tui._handle_user_message(text)

        def inject_callback(text: str):
            # Chemin préféré : soumettre à la TUI comme un vrai message
            # (visible à l'écran, démarre un tour). inject_user_context seul
            # n'alimente que le contexte du prochain tour sans le démarrer.
            tui = _tui_instance
            if tui is not None:
                try:
                    tui.call_from_thread(_submit_voice_text, tui, text)
                    logger.info(f"Voice prompt soumis à la TUI: {text[:60]}")
                    return
                except Exception:
                    logger.exception("TUI submit failed - fallback inject_user_context")
            if _agent_loop is not None and _asyncio_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    _agent_loop.inject_user_context(text),
                    _asyncio_loop
                )
                logger.info("Voice text injecté au contexte (pas de TUI capturée)")
            else:
                logger.error("Voice text PERDU: ni TUI ni agent_loop disponibles")
        handler.set_inject_callback(inject_callback)

        def resolve_approval_callback(request_id: str | int, approved: bool, text: str):
            """Résout l'approbation pendante depuis le thread de transcription.

            Utilisé par le reject vocal : approved est False, text = consigne.
            `request_id` est l'id SÉRIE (int) du device — la résolution Vibe
            exige l'uuid broker, publié par la course dans
            _active_broker_request_id. Sans approbation en cours, on ne
            résout RIEN (jamais à l'aveugle).
            """
            loop = _asyncio_loop
            agent_loop = _agent_loop
            broker_rid = _active_broker_request_id
            if agent_loop is None or loop is None or broker_rid is None:
                logger.warning(
                    f"Voice resolve dropped (no pending approval): serial_id={request_id}"
                )
                return
            response = ApprovalResponse.YES if approved else ApprovalResponse.NO
            # resolve_approval_request est SYNCHRONE (il complète une Future du
            # broker) : call_soon_threadsafe depuis le thread de transcription.
            loop.call_soon_threadsafe(
                agent_loop.resolve_approval_request, broker_rid, response, text
            )
            logger.info(f"Voice approval resolved: broker_id={broker_rid}, approved={approved}")
        handler.set_resolve_approval_callback(resolve_approval_callback)

        def send_voice_ack_callback(state: str, text: str = ""):
            # Toujours passer par la connexion persistante du broker owner —
            # ouvrir un second port série en parallèle échoue ou vole la
            # connexion. (Les événements voice n'arrivent que chez l'owner.)
            try:
                mgr = get_or_init_broker()
                if mgr is not None and mgr.is_owner() and mgr.broker is not None:
                    mgr.broker.bridge.send_voice_ack(state, text)
                else:
                    logger.debug("voice_ack skipped (no owner broker)")
            except Exception as e:
                logger.warning(f"Could not send voice ack: {e}")
        handler.set_send_voice_ack_callback(send_voice_ack_callback)
        logger.info("Voice handler callbacks installed")
    except ImportError as e:
        logger.debug(f"Voice handler not available: {e}")
    except Exception as e:
        logger.error(f"Error setting up voice handler: {e}")
    
    logger.info("Hook installation complete")


# Auto-install when imported
install_hook()
