"""감지 프로세스의 출력을 브라우저로 전달하는 SSE 서버."""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from flask import Flask, Response, send_file

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
RESTART_DELAY = 3
KEEPALIVE_INTERVAL = 20
CLIENT_QUEUE_SIZE = 60

_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()
_last_payload: Optional[dict] = None

_STATE_MSG = {
    "SAFE":     "No Activity Detected",
    "DETECTED": "Presence Suspected",
    "ALERT":    "Movement Detected",
}

# detection.py 로그 형식.
# [18:40:25] 🔴 ALERT    | Movement Detected | RSSI=-44.0 | score=12.13 rel=2.60 bg=4.32
_LOG_RE = re.compile(
    r"\[(\d{2}:\d{2}:\d{2})\]"
    r".*?(SAFE|DETECTED|ALERT)"
    r".*?RSSI=([-\d.]+)"
    r".*?score=([\d.]+)"
    r".*?rel=([\d.]+)"
    r".*?bg=([\d.]+)",
)

# 워밍업 로그 구분.
_CALIB_RE = re.compile(r"워밍업|warmup", re.IGNORECASE)
_CALIB_DONE_RE = re.compile(r"\[완료\]")


def _empty_payload(state: str, message: str) -> dict:
    return {
        "state": state,
        "message": message,
        "rssi": None,
        "motion": None,
        "rel": None,
        "bg": None,
    }


def _parse_log(line: str) -> Optional[dict]:
    if _CALIB_RE.search(line) and not _CALIB_DONE_RE.search(line):
        return _empty_payload(
            "CALIBRATING", "Warming up — please leave the room…"
        )

    match = _LOG_RE.search(line)
    if not match:
        return None

    state = match.group(2)
    return {
        "state": state,
        "message": _STATE_MSG[state],
        "rssi": float(match.group(3)),
        "motion": float(match.group(4)),
        "rel": float(match.group(5)),
        "bg": float(match.group(6)),
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _broadcast(payload: dict) -> None:
    global _last_payload
    _last_payload = payload
    message = _sse(payload)
    with _clients_lock:
        disconnected_clients = []
        for client_queue in _clients:
            try:
                client_queue.put_nowait(message)
            except queue.Full:
                disconnected_clients.append(client_queue)

        for client_queue in disconnected_clients:
            _clients.remove(client_queue)


def _send_keepalives() -> None:
    """유휴 SSE 연결 유지."""
    while True:
        time.sleep(KEEPALIVE_INTERVAL)
        with _clients_lock:
            for client_queue in _clients:
                try:
                    client_queue.put_nowait(": keepalive\n\n")
                except queue.Full:
                    pass


def _run_detection() -> None:
    script = BASE_DIR / "detection.py"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # stdout 버퍼링 비활성화.
    env["PYTHONIOENCODING"] = "utf-8"  # 출력 인코딩 고정.

    while True:
        _broadcast(_empty_payload("CALIBRATING", "Starting detection.py…"))
        try:
            process = subprocess.Popen(
                [sys.executable, "-u", str(script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            assert process.stdout is not None
            for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                print("[detection]", line)
                payload = _parse_log(line)
                if payload:
                    _broadcast(payload)

            process.wait()
            print(
                f"[server] detection.py exited with code {process.returncode}, "
                f"restarting in {RESTART_DELAY} s…"
            )
        except Exception as exc:
            print(f"[server] subprocess error: {exc}")
            _broadcast(_empty_payload("CALIBRATING", f"Error: {exc}"))
        time.sleep(RESTART_DELAY)


@app.route("/events")
def events():
    client_queue: queue.Queue = queue.Queue(maxsize=CLIENT_QUEUE_SIZE)

    # 신규 접속자에게 마지막 상태 즉시 전송.
    if _last_payload:
        try:
            client_queue.put_nowait(_sse(_last_payload))
        except queue.Full:
            pass

    with _clients_lock:
        _clients.append(client_queue)

    def stream():
        try:
            while True:
                yield client_queue.get()
        except GeneratorExit:
            with _clients_lock:
                if client_queue in _clients:
                    _clients.remove(client_queue)

    return Response(
        stream(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/")
def index():
    return send_file(BASE_DIR / "index.html")


if __name__ == "__main__":
    threading.Thread(target=_run_detection, daemon=True).start()
    threading.Thread(target=_send_keepalives, daemon=True).start()
    print("Dashboard  →  http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
