"""Security regression tests for the pentest remediation (W-01…W-08)."""
from conftest import make_jpeg_bytes


# --------------------------------------------------------------------------- #
# W-08 — security headers
# --------------------------------------------------------------------------- #
def test_security_headers_present(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
    assert r.headers["Referrer-Policy"] == "no-referrer"


# --------------------------------------------------------------------------- #
# W-02 — path traversal in upload session_id
# --------------------------------------------------------------------------- #
def test_upload_rejects_traversal_session_id(client, tmp_path):
    files = {"files": ("evil.jpg", make_jpeg_bytes(), "image/jpeg")}
    r = client.post(
        "/api/v1/upload/",
        files=files,
        data={"session_id": "../../../../tmp/pwned"},
    )
    assert r.status_code == 400


def test_upload_rejects_non_image(client):
    files = {"files": ("evil.html", b"<script>alert(1)</script>", "text/html")}
    r = client.post("/api/v1/upload/", files=files)
    # Rejected either on extension whitelist or magic-byte check.
    assert r.status_code == 400


def test_upload_accepts_valid_jpeg(client):
    files = {"files": ("card.jpg", make_jpeg_bytes(), "image/jpeg")}
    r = client.post("/api/v1/upload/", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["filenames"] == ["card.jpg"]
    assert body["session_id"]


# --------------------------------------------------------------------------- #
# W-02/W-05 — traversal in batch delete path parameter
# --------------------------------------------------------------------------- #
def test_delete_batch_rejects_traversal(client):
    # %2F-encoded traversal should not resolve to a parent dir delete.
    r = client.delete("/api/v1/batches/..%2f..%2fetc")
    assert r.status_code in (400, 404)


# --------------------------------------------------------------------------- #
# W-03 — image serving never returns uploaded HTML as text/html
# --------------------------------------------------------------------------- #
def test_image_route_rejects_non_image_extension(client):
    r = client.get("/batches-static/somebatch/evil.html")
    assert r.status_code == 404  # .html not in the image whitelist


def test_image_route_rejects_traversal(client):
    r = client.get("/batches-static/..%2f..%2fetc/passwd")
    assert r.status_code in (400, 404)


# --------------------------------------------------------------------------- #
# W-01 — bearer-token auth (off by default, enforced when AUTH_TOKEN set)
# --------------------------------------------------------------------------- #
def test_api_open_when_token_unset(client):
    # Default config has AUTH_TOKEN="" → API reachable without a header.
    r = client.get("/api/v1/batches/")
    assert r.status_code == 200


def test_api_401_without_token_when_enabled(client, auth_token):
    r = client.get("/api/v1/batches/")
    assert r.status_code == 401


def test_api_200_with_valid_token(client, auth_token):
    r = client.get("/api/v1/batches/", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200


def test_api_401_with_wrong_token(client, auth_token):
    r = client.get("/api/v1/batches/", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# W-07 — docs disabled by default
# --------------------------------------------------------------------------- #
def test_openapi_disabled_by_default(client):
    assert client.get("/api/v1/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
