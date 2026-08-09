"""Vibe M5Stack - Flags runtime pilotés par le device.

Le mode debug est un réglage du menu config du M5Stack (persisté en NVS).
Le device l'annonce dans ses pings ({"type":"ping","debug":0/1}) et via un
message dédié au changement ({"type":"config","debug":0/1}) ; le reader du
bridge le pousse ici. Défaut : OFF (logs sobres, pas de dump audio).

Override local possible pour déboguer sans device à jour :
    VIBE_M5STACK_DEBUG=1
"""
import os
import threading

_lock = threading.Lock()
_debug = os.environ.get("VIBE_M5STACK_DEBUG") == "1"


def set_debug(enabled):
    global _debug
    with _lock:
        _debug = bool(enabled)


def debug_enabled():
    if os.environ.get("VIBE_M5STACK_DEBUG") == "1":
        return True
    with _lock:
        return _debug
