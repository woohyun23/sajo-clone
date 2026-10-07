#!/usr/bin/env python3

"""Account Service 의존성을 고정 응답으로 격리하는 부하 테스트 전용 스텁."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    response = {
        "quantity": 10,
        "avgPurchasePrice": 65000.0,
        "profitLossRate": 0.0,
    }

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/actuator/health":
            self._json(200, {"status": "UP"})
            return

        if self.path.startswith("/internal/v1/accounts/") and "/holdings/" in self.path and self.path.endswith("/position"):
            self._json(200, self.response)
            return

        self._json(404, {"message": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Account stub listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
