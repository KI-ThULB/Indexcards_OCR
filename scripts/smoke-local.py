"""Run with apps/backend/.venv/bin/python after npm run setup in a fresh clone."""
import io
import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from PIL import Image
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
KEYS = {provider: f"synthetic-{provider}-secret" for provider in ("ollama", "openrouter", "gpustack")}


class ProviderMock(BaseHTTPRequestHandler):
    available = True

    def log_message(self, *args):
        pass

    def respond(self, payload):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        if not self.available:
            self.send_error(503)
            return
        assert self.path == "/ollama/models"
        assert self.headers["Authorization"] == f"Bearer {KEYS['ollama']}"
        self.respond({"data": [{"id": "synthetic-vl"}]})

    def do_POST(self):
        provider, endpoint = self.path.strip("/").split("/", 1)
        expected_endpoint = "v1/chat/completions" if provider == "gpustack" else "chat/completions"
        assert endpoint == expected_endpoint
        assert self.headers["Authorization"] == f"Bearer {KEYS[provider]}"
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert payload["model"] == f"{provider}-vl"
        fields = json.dumps({"fields": {"value": f"OCR from {provider}"}})
        self.respond({"choices": [{"message": {"content": fields}, "finish_reason": "stop"}]})


def wait(check):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for the local application")


def test_http(client, cards, frontend):
    def ready():
        try:
            return client.get("/api/v1/config", timeout=1).is_success
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    wait(ready)
    config = client.get("/api/v1/config").raise_for_status()
    client_javascript = client.get("/src/api/client.ts").raise_for_status().text
    for value in (*KEYS.values(), "synthetic-legacy-token", "synthetic-browser-token"):
        assert value not in config.text and value not in client_javascript
    ollama = client.get("/api/v1/config/ollama/models").raise_for_status().json()
    assert ollama["reachable"] and ollama["models"][0]["value"] == "synthetic-vl"
    assert client.get("/api/v1/config", headers={"Origin": "https://outside.invalid"}).status_code == 403

    image = (cards / "card.jpg").read_bytes()
    for provider in KEYS:
        uploaded = client.post("/api/v1/upload/", files={"files": ("card.jpg", image, "image/jpeg")}).raise_for_status().json()
        batch = client.post("/api/v1/batches/", json={
            "session_id": uploaded["session_id"], "custom_name": provider, "fields": ["value"],
        }).raise_for_status().json()["batch_name"]
        client.post(f"/api/v1/batches/{batch}/start", json={"provider": provider}).raise_for_status()

        def results():
            return client.get(f"/api/v1/batches/{batch}/results").raise_for_status().json()["results"]

        assert wait(results)[0]["data"]["value"] == f"OCR from {provider}"
        assert client.get(f"/batches-static/{batch}/card.jpg").raise_for_status().content == image
        if provider == "ollama":
            ws_url = frontend.replace("http:", "ws:") + f"/api/v1/ws/task/{batch}"
            with connect(ws_url, origin=frontend, proxy=None) as ws:
                assert json.loads(ws.recv(timeout=5))

    template = client.post("/api/v1/templates/", json={"name": "Smoke", "fields": ["value"]}).raise_for_status().json()
    run = client.post("/api/v1/bulk/runs", json={
        "name": "Smoke", "template_id": template["id"], "folders": ["cards"], "provider": "ollama",
    }).raise_for_status().json()["bulk_run_id"]
    path = f"/api/v1/bulk/runs/{run}"
    client.post(f"{path}/start").raise_for_status()
    wait(lambda: client.get(path).raise_for_status().json()["status"] == "completed")
    assert "OCR from ollama" in client.get(f"{path}/export.csv").raise_for_status().text


def main():
    # Pick distinct loopback ports without using any existing development server.
    with socket.socket() as frontend_socket, socket.socket() as api_socket:
        frontend_socket.bind(("127.0.0.1", 0))
        api_socket.bind(("127.0.0.1", 0))
        frontend_port = frontend_socket.getsockname()[1]
        api_port = api_socket.getsockname()[1]
    frontend = f"http://127.0.0.1:{frontend_port}"

    with tempfile.TemporaryDirectory() as tmp, ThreadingHTTPServer(("127.0.0.1", 0), ProviderMock) as mock:
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        path = Path(tmp)
        cards = path / "import/cards"
        cards.mkdir(parents=True)
        image = io.BytesIO()
        Image.new("RGB", (80, 60), "white").save(image, format="JPEG")
        (cards / "card.jpg").write_bytes(image.getvalue())
        mock_url = f"http://127.0.0.1:{mock.server_port}"
        env_file = path / "smoke.env"
        env_file.write_text(f"""DATA_DIR={path / 'data'}
BULK_IMPORT_ROOT={cards.parent}
BULK_IMPORT_MODE=copy
AUTH_TOKEN=synthetic-legacy-token
VITE_API_TOKEN=synthetic-browser-token
OLLAMA_API_ENDPOINT_OVERRIDE={mock_url}/ollama/chat/completions
OLLAMA_MODEL_NAME=ollama-vl
OLLAMA_API_KEY={KEYS['ollama']}
API_BASE_URL={mock_url}/openrouter/
MODEL_NAME=openrouter-vl
OPENROUTER_API_KEY={KEYS['openrouter']}
GPUSTACK_ENABLED=true
GPUSTACK_BASE_URL={mock_url}/gpustack
GPUSTACK_DEFAULT_MODEL=gpustack-vl
GPUSTACK_API_KEY={KEYS['gpustack']}
""")
        env = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "PYTHONPATH", "UV_CACHE_DIR", "TMPDIR"}
        }
        env.update(
            INDEXCARDS_ENV_FILE=str(env_file), VITE_API_TOKEN="synthetic-browser-token",
            INDEXCARDS_API_PORT=str(api_port), INDEXCARDS_DEV_PORT=str(frontend_port),
        )
        with (path / "startup.log").open("w+") as log:
            proc = subprocess.Popen(["npm", "run", "dev"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                    env=env, start_new_session=True)
            try:
                with httpx.Client(base_url=frontend, trust_env=False) as client:
                    test_http(client, cards, frontend)
                    ProviderMock.available = False
                    unavailable = client.get("/api/v1/config/ollama/models").raise_for_status().json()
                    assert not unavailable["reachable"] and unavailable["error"]
                    client.get("/api/v1/config").raise_for_status()
                log.seek(0)
                startup = log.read()
                assert f"http://127.0.0.1:{api_port}" in startup
                assert frontend in startup
            except Exception:
                log.seek(0)
                print(log.read())
                raise
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
                mock.shutdown()
    print("PASS: npm run dev, local HTTP/WS/image/CSV, three mocked providers and credential isolation")


if __name__ == "__main__":
    main()
