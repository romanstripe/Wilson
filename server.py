"""
server.py — Runs detection.py as a subprocess, parses its stdout,
and streams state updates to the browser via Server-Sent Events (SSE).

Usage:
    pip install flask
    python server.py
Then open http://localhost:5000
"""

from flask import Flask, Response
import subprocess
import threading
import queue
import re
import json
import sys
import os
import time
from typing import Optional

app = Flask(__name__)

_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()
_last_payload: Optional[dict] = None

_STATE_MSG = {
    "SAFE":     "No Activity Detected",
    "DETECTED": "Presence Suspected",
    "ALERT":    "Movement Detected",
}

# Parses lines like:
# [18:40:25] 🔴 ALERT    | Movement Detected | RSSI=-44.0 | score=12.13 rel=2.60 bg=4.32
_LOG_RE = re.compile(
    r"\[(\d{2}:\d{2}:\d{2})\]"
    r".*?(SAFE|DETECTED|ALERT)"
    r".*?RSSI=([-\d.]+)"
    r".*?score=([\d.]+)"
    r".*?rel=([\d.]+)"
    r".*?bg=([\d.]+)",
)

# Parses warmup lines
_CALIB_RE = re.compile(r"워밍업|warmup", re.IGNORECASE)
_CALIB_DONE_RE = re.compile(r"\[완료\]")


def _parse(line: str) -> Optional[dict]:
    if _CALIB_RE.search(line) and not _CALIB_DONE_RE.search(line):
        return {"state": "CALIBRATING", "message": "Warming up — please leave the room…", "rssi": None, "motion": None, "rel": None, "bg": None}

    m = _LOG_RE.search(line)
    if not m:
        return None
    state = m.group(2)
    return {
        "state":   state,
        "message": _STATE_MSG[state],
        "rssi":    float(m.group(3)),
        "motion":  float(m.group(4)),
        "rel":     float(m.group(5)),
        "bg":      float(m.group(6)),
    }


def _broadcast(payload: dict) -> None:
    global _last_payload
    _last_payload = payload
    msg = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def _keepalive() -> None:
    """Send SSE comment every 20 s so browsers don't close idle connections."""
    while True:
        time.sleep(20)
        with _clients_lock:
            for q in _clients:
                try:
                    q.put_nowait(": keepalive\n\n")
                except queue.Full:
                    pass


def _run_detection() -> None:
    script = os.path.join(os.path.dirname(__file__), "detection.py")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"   # disable Python stdout buffering inside subprocess
    env["PYTHONIOENCODING"] = "utf-8"  # force utf-8 for all print()

    while True:
        _broadcast({"state": "CALIBRATING", "message": "Starting detection.py…", "rssi": None, "motion": None})
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", script],  # -u = force unbuffered
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                print("[subprocess]", line)   # visible in server terminal for debugging
                data = _parse(line)
                if data:
                    _broadcast(data)
            proc.wait()
            print(f"[server] detection.py exited with code {proc.returncode}, restarting in 3 s…")
        except Exception as exc:
            print(f"[server] subprocess error: {exc}")
            _broadcast({"state": "CALIBRATING", "message": f"Error: {exc}", "rssi": None, "motion": None})
        time.sleep(3)


@app.route("/events")
def events():
    q: queue.Queue = queue.Queue(maxsize=60)
    # Immediately send last known state so the browser doesn't wait
    if _last_payload:
        try:
            q.put_nowait(f"data: {json.dumps(_last_payload, ensure_ascii=False)}\n\n")
        except queue.Full:
            pass
    with _clients_lock:
        _clients.append(q)

    def stream():
        try:
            while True:
                yield q.get()
        except GeneratorExit:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    return Response(
        stream(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/")
def index():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    threading.Thread(target=_run_detection, daemon=True).start()
    threading.Thread(target=_keepalive, daemon=True).start()
    print("Dashboard  →  http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
