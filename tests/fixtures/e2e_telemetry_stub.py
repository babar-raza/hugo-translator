#!/usr/bin/env python
"""
Minimal telemetry stub server for E2E testing.
Runs on localhost:8765 and logs all received events to a JSONL file.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import uvicorn
    from fastapi import FastAPI, Request
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Fallback to simple HTTP server
    from http.server import BaseHTTPRequestHandler, HTTPServer

# Output file for telemetry events
TELEMETRY_LOG = Path("reports/e2e/20260116_225809/LOGS/telemetry_events.jsonl")
TELEMETRY_LOG.parent.mkdir(parents=True, exist_ok=True)

def log_event(event: dict[str, Any]) -> None:
    """Log telemetry event to JSONL file."""
    with open(TELEMETRY_LOG, "a", encoding="utf-8") as f:
        json.dump(event, f)
        f.write("\n")

if FASTAPI_AVAILABLE:
    # FastAPI implementation
    app = FastAPI()

    @app.post("/api/v1/telemetry/session/start")
    async def start_session(request: Request):
        """Start telemetry session."""
        data = await request.json()
        log_event({"endpoint": "session_start", "timestamp": datetime.now().isoformat(), "data": data})
        return {"session_id": "e2e-test-session-001", "status": "started"}

    @app.post("/api/v1/telemetry/session/{session_id}/event")
    async def log_session_event(session_id: str, request: Request):
        """Log session event."""
        data = await request.json()
        log_event({"endpoint": "session_event", "session_id": session_id, "timestamp": datetime.now().isoformat(), "data": data})
        return {"status": "logged"}

    @app.post("/api/v1/telemetry/session/{session_id}/end")
    async def end_session(session_id: str, request: Request):
        """End telemetry session."""
        data = await request.json()
        log_event({"endpoint": "session_end", "session_id": session_id, "timestamp": datetime.now().isoformat(), "data": data})
        return {"status": "ended"}

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "service": "e2e-telemetry-stub"}

    def run_server():
        print("Starting E2E telemetry stub on http://localhost:8765")
        print(f"Logging events to: {TELEMETRY_LOG}")
        uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")

else:
    # Simple HTTP server fallback
    class TelemetryHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body}

            log_event({
                "endpoint": self.path,
                "method": "POST",
                "timestamp": datetime.now().isoformat(),
                "data": data
            })

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "service": "e2e-telemetry-stub"}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress request logging

    def run_server():
        print("Starting E2E telemetry stub (simple HTTP) on http://localhost:8765")
        print(f"Logging events to: {TELEMETRY_LOG}")
        server = HTTPServer(('127.0.0.1', 8765), TelemetryHandler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down telemetry stub")
            server.shutdown()

if __name__ == "__main__":
    run_server()
