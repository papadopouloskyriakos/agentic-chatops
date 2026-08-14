"""Tiny stdlib HTTP server used to fake Ollama and Anthropic API responses.

Usage (from a test):
    port=$(python3 scripts/qa/lib/mock_http.py start --behavior=ollama-ok)
    # ... run code that hits $port ...
    python3 scripts/qa/lib/mock_http.py stop $port

The 'start' command daemonises a background thread, prints the chosen port
to stdout, and writes its PID + port to /tmp/qa_mock_http_<port>.pid so the
'stop' command can find it.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BEHAVIORS = {
    # ollama-ok: respond as if gemma3:12b produced a coherent summary.
    "ollama-ok": {
        "path": "/api/generate",
        "status": 200,
        "body": lambda body: json.dumps({
            "response": "The prior T1 agent checked NetBox for nl-pve01 and found it at 192.168.181.x. SSH revealed CPU at 98% and a runaway process. Open question: is the process a cron job or manual? Next step: inspect systemd journal.",
            "done": True,
            "prompt_eval_count": 200,
            "eval_count": 50,
        }).encode(),
    },
    # ollama-500: simulate a 500 so the compact-handoff script falls through.
    "ollama-500": {
        "path": "/api/generate",
        "status": 500,
        "body": lambda body: b'{"error":"simulated failure"}',
    },
    # anthropic-ok: mimic a Haiku messages API response.
    "anthropic-ok": {
        "path": "/v1/messages",
        "status": 200,
        "body": lambda body: json.dumps({
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "text",
                "text": "Prior agent discovered NetBox entry + SSH CPU 98%. Open: is the process scheduled? Next: journalctl.",
            }],
            "usage": {"input_tokens": 200, "output_tokens": 50},
        }).encode(),
    },
}


def make_handler(behaviors: dict):
    class H(BaseHTTPRequestHandler):
        def _respond(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(n) if n else b""
            # Match by path
            for spec in behaviors.values():
                if spec["path"] == self.path:
                    self._respond(spec["status"], spec["body"](body))
                    return
            self._respond(404, b'{"error":"no mock for this path"}')

        def do_GET(self):
            self._respond(200, b'{"status":"ok"}')

        def log_message(self, fmt, *args):
            pass  # silence access log

    return H


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cmd_start(args):
    behaviors = [b.strip() for b in args.behavior.split(",") if b.strip()]
    chosen = {k: BEHAVIORS[k] for k in behaviors}
    if not chosen:
        print("no valid behaviors", file=sys.stderr)
        return 2
    port = args.port or find_free_port()

    # Fork a child that owns the server so the parent exits promptly.
    # We use double-fork so the child is orphaned to init and won't become
    # a zombie if the test script aborts.
    pid = os.fork()
    if pid > 0:
        # Parent — wait briefly for the server to be ready, then report.
        pidfile = f"/tmp/qa_mock_http_{port}.pid"
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if os.path.exists(pidfile):
                print(port)
                return 0
            time.sleep(0.05)
        print(f"mock server didn't start in time on port {port}", file=sys.stderr)
        return 1

    # Child
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        sys.exit(0)
    # Grandchild — detach stdio so the parent's subprocess harness doesn't
    # keep the pipe open and block its caller.
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(chosen))
    pidfile = f"/tmp/qa_mock_http_{port}.pid"
    with open(pidfile, "w") as f:
        f.write(f"{os.getpid()}\n{port}\n")
    # Serve until killed.
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            os.unlink(pidfile)
        except OSError:
            pass
    sys.exit(0)


def cmd_stop(args):
    pidfile = f"/tmp/qa_mock_http_{args.port}.pid"
    if not os.path.exists(pidfile):
        return 0
    try:
        with open(pidfile) as f:
            pid = int(f.readline().strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError, PermissionError) as e:
        print(f"could not stop: {e}", file=sys.stderr)
    try:
        os.unlink(pidfile)
    except OSError:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--behavior", default="ollama-ok",
                         help="comma-sep subset of: " + ",".join(BEHAVIORS))
    p_start.add_argument("--port", type=int, default=0,
                         help="specific port; 0 = pick free")
    p_stop = sub.add_parser("stop")
    p_stop.add_argument("port", type=int)
    args = ap.parse_args()
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "stop":
        return cmd_stop(args)


if __name__ == "__main__":
    sys.exit(main())
