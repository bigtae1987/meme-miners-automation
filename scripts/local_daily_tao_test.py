"""Run the TAO earnings reporter against a local mock API/webhook."""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List
from urllib.parse import urlparse


def start_mock_server() -> tuple[HTTPServer, int, List[Dict[str, str]]]:
    """Start a simple HTTP server that mocks both Taostats and Discord."""
    captured_messages: List[Dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802  (http.server naming)
            parsed = urlparse(self.path)
            if parsed.path.endswith("/miners/earnings"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                payload = {
                    "earnings": [
                        {"address": "miner1", "amount": 1.2345},
                        {"address": "miner2", "amount": 0.5678},
                    ]
                }
                self.wfile.write(json.dumps(payload).encode("utf-8"))
            else:
                self.send_error(404, "Not Found")

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.endswith("/webhook"):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8") if length else ""
                captured_messages.append({"body": body, "path": parsed.path})
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404, "Not Found")

        def log_message(self, format, *args):  # noqa: A003, D401
            """Silence default stdout logging for test clarity."""
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, captured_messages


def run_local_report() -> List[Dict[str, str]]:
    server, port, messages = start_mock_server()
    base = f"http://127.0.0.1:{port}"

    os.environ.setdefault("DISCORD_WEBHOOK_URL", f"{base}/webhook")
    os.environ.setdefault("TAOSTATS_BASE_URL", f"{base}")
    os.environ.setdefault("MINER_ADDRESSES", "miner1,miner2")
    os.environ.setdefault("TAO_LOOKBACK_DAYS", "1")
    os.environ.setdefault("TAOSTATS_API_KEY", "local-test-api-key")

    try:
        sys.path.append(os.path.dirname(__file__))
        from daily_tao_to_discord import DailyTaoReporter

        reporter = DailyTaoReporter()
        exit_code = reporter.run()
        if exit_code != 0:
            raise SystemExit(exit_code)
    finally:
        server.shutdown()

    return messages


def main() -> None:
    messages = run_local_report()
    if not messages:
        raise SystemExit("Reporter did not post to the mock Discord webhook")

    print("Captured Discord payload:\n")
    for idx, message in enumerate(messages, start=1):
        print(f"Message {idx}: {message['body']}")


if __name__ == "__main__":
    main()
