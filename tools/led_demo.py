#!/usr/bin/env python3
"""
led_demo.py — Pilotage manuel du M5Stack pour valider les animations LED
sans lancer Vibe.

Envoie des messages `status` (et `approval`) sur le port série du M5Stack, exactement
comme le ferait le broker. Permet de déclencher chaque état / sous-activité à la demande.

Prérequis :
  - AUCUNE session `vibe-m5stack` ne doit tourner (le port COM est exclusif :
    l'owner-broker le tient. Ferme la session vibe d'abord).
  - pyserial installé (déjà une dépendance du projet).
  - Port : variable d'env M5STACK_PORT (ex. COM10 en Bluetooth) ou option --port.

Exemples :
  python tools/led_demo.py tour                 # visite guidée de tous les états
  python tools/led_demo.py set thinking reading # fige un état jusqu'à Ctrl-C
  python tools/led_demo.py set dead              # force l'état DEAD (scanner rouge)
  python tools/led_demo.py repl                  # mode interactif
  python tools/led_demo.py approval "Demo" "Coucou"  # affiche un écran d'approbation
  python tools/led_demo.py --port COM10 tour

États : thinking | waiting | done | error | dead | stuck
Activités (seulement si thinking) : reasoning | tool_exec | reading | streaming
"""

import argparse
import json
import os
import sys
import threading
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant. Installe-le (ex: pip install pyserial) ou utilise "
             "le python du venv mistral-vibe qui l'a déjà.")

BAUD = 115200

# Détail affiché à l'écran selon l'activité (cosmétique).
ACTIVITY_DETAIL = {
    "reasoning": "thinking",
    "tool_exec": "bash",
    "reading": "read_file",
    "streaming": "writing",
}


class Device:
    """Connexion série + heartbeat qui ré-émet le statut courant (comme le broker)."""

    def __init__(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=0.2)
        self._lock = threading.Lock()
        self._seq = 0
        self._cur = None          # dernier (state, activity, detail) envoyé
        self._running = True
        self._hb = threading.Thread(target=self._heartbeat, daemon=True)
        self._hb.start()

    def _send(self, obj):
        line = (json.dumps(obj) + "\n").encode("utf-8")
        with self._lock:
            self.ser.write(line)
            self.ser.flush()

    def status(self, state, activity=None, detail=None):
        """Envoie un status et le mémorise pour le heartbeat."""
        self._seq += 1
        if detail is None:
            detail = ACTIVITY_DETAIL.get(activity or "", state)
        msg = {"type": "status", "state": state, "seq": self._seq, "detail": detail}
        if state == "thinking" and activity:
            msg["activity"] = activity
        self._cur = (state, activity, detail)
        self._send(msg)

    def _heartbeat(self):
        """Ré-émet le statut courant toutes les 2 s (seq++), pour éviter un DEAD/STUCK
        accidentel pendant qu'on tient un état. Vide aussi le buffer d'entrée (pings)."""
        while self._running:
            time.sleep(2.0)
            try:
                if self.ser.in_waiting:
                    self.ser.read(self.ser.in_waiting)  # drop pings du device
            except Exception:
                pass
            if self._cur is not None:
                state, activity, detail = self._cur
                self._seq += 1
                msg = {"type": "status", "state": state, "seq": self._seq, "detail": detail}
                if state == "thinking" and activity:
                    msg["activity"] = activity
                self._send(msg)

    def approval(self, title, body, timeout=35.0):
        """Affiche un écran d'approbation (rainbow Mistral) et attend A/B/C."""
        # Pause le heartbeat pendant l'approval (le device est en SHOWING_REQUEST).
        prev, self._cur = self._cur, None
        req_id = int(time.monotonic() * 1000) % 1_000_000
        self._send({"type": "approval", "id": req_id, "title": title[:40], "body": body[:200]})
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            try:
                buf += self.ser.read(self.ser.in_waiting or 1)
            except Exception:
                pass
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                try:
                    m = json.loads(ln.decode("utf-8", "ignore"))
                except Exception:
                    continue
                if m.get("type") == "response" and m.get("id") == req_id:
                    self._cur = prev
                    return m
        self._cur = prev
        return None

    def close(self):
        self._running = False
        try:
            self._hb.join(timeout=1.0)
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass


def resolve_port(arg_port):
    port = arg_port or os.environ.get("M5STACK_PORT")
    if not port:
        sys.exit("Port introuvable. Définis M5STACK_PORT (ex. COM10) ou passe --port COMx.")
    return port


# --- Visite guidée ----------------------------------------------------------
TOUR = [
    ("thinking", "reasoning", 8, "REASONING -> scintillement cyan diffus (sparkle)"),
    ("thinking", "reading",   8, "READING   -> radar cyan/violet qui tourne (anneau ext.)"),
    ("thinking", "tool_exec", 8, "TOOL_EXEC -> onde radiale bleue centre->exterieur"),
    ("thinking", "streaming", 8, "STREAMING -> remplissage par anneaux centre->ext."),
    ("waiting",  None,        7, "WAITING   -> pulse ambre (attend ta saisie)"),
    ("done",     None,        6, "DONE      -> vert (flourish puis fixe)"),
    ("error",    None,        5, "ERROR     -> scanner rouge KITT"),
    ("stuck",    None,        5, "STUCK     -> scanner rouge (figé)"),
    ("dead",     None,        5, "DEAD      -> scanner rouge (PC mort)"),
]


def run_tour(dev):
    print("\nVisite guidée — Ctrl-C pour arrêter.\n")
    print("(Note : l'état IDLE vert ne se montre qu'au boot du device, AVANT tout")
    print(" message ; impossible à injecter — reboote le M5Stack pour le voir.)\n")
    for state, activity, hold, label in TOUR:
        print(f"  ▶ {label}   [{hold}s]")
        dev.status(state, activity)
        time.sleep(hold)
    print("\nFin de la visite. Le script s'arrête → plus de heartbeat → le device")
    print("passera DEAD tout seul (~12 s) via son watchdog, puis tu peux le rebooter.")


def run_repl(dev):
    print("\nMode interactif. Tape un état (+ activité si thinking), 'a' pour approval, 'q' pour quitter.")
    print("  états     : thinking | waiting | done | error | dead | stuck")
    print("  activités : reasoning | tool_exec | reading | streaming")
    print("  ex: 'thinking reading'  |  'waiting'  |  'a Demo Coucou'  |  'q'\n")
    while True:
        try:
            raw = input("led> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()
        if cmd in ("q", "quit", "exit"):
            break
        if cmd == "a":
            title = parts[1] if len(parts) > 1 else "Demo"
            body = " ".join(parts[2:]) if len(parts) > 2 else "Appuie sur A / B / C"
            print("  approval envoyé, attends A/B/C sur le device…")
            resp = dev.approval(title, body)
            print(f"  réponse: {resp}")
            continue
        state = cmd
        activity = parts[1].lower() if len(parts) > 1 else None
        if state not in ("thinking", "waiting", "done", "error", "dead", "stuck"):
            print(f"  état inconnu: {state}")
            continue
        dev.status(state, activity)
        print(f"  -> {state}" + (f" / {activity}" if activity else "") + " (maintenu, tape autre chose)")


def main():
    ap = argparse.ArgumentParser(description="Pilotage manuel des LEDs du M5Stack (sans Vibe).")
    ap.add_argument("--port", help="Port série (déf: $M5STACK_PORT)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("tour", help="visite guidée de tous les états")
    sub.add_parser("repl", help="mode interactif")
    p_set = sub.add_parser("set", help="fige un état jusqu'à Ctrl-C")
    p_set.add_argument("state")
    p_set.add_argument("activity", nargs="?")
    p_app = sub.add_parser("approval", help="affiche un écran d'approbation")
    p_app.add_argument("title", nargs="?", default="Demo")
    p_app.add_argument("body", nargs="?", default="Appuie sur A / B / C")

    args = ap.parse_args()
    port = resolve_port(args.port)

    try:
        dev = Device(port)
    except serial.SerialException as e:
        sys.exit(f"Impossible d'ouvrir {port}: {e}\n"
                 "→ Une session vibe-m5stack tient sûrement le port. Ferme-la d'abord.")

    print(f"Connecté sur {port}.")
    try:
        if args.cmd == "repl":
            run_repl(dev)
        elif args.cmd == "set":
            dev.status(args.state, args.activity)
            print(f"État '{args.state}'" + (f"/{args.activity}" if args.activity else "")
                  + " maintenu. Ctrl-C pour arrêter.")
            while True:
                time.sleep(1)
        elif args.cmd == "approval":
            print("Approval envoyé — appuie sur A / B / C sur le device…")
            print("réponse:", dev.approval(args.title, args.body))
        else:  # défaut = tour
            run_tour(dev)
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
