import httpx
import pytest

import watcher


def make_client(responses, sleeps=None):
    """ApiClient whose HTTP calls are answered by `responses` (a list of callables or
    httpx.Response objects for POST /images). Login always succeeds and is counted."""
    calls = {"login": 0, "upload": 0}
    queue = list(responses)

    def handler(request):
        if request.url.path == "/api/auth/login":
            calls["login"] += 1
            return httpx.Response(200, json={"access_token": f"token-{calls['login']}"})
        calls["upload"] += 1
        calls["last_auth"] = request.headers.get("authorization")
        item = queue.pop(0)
        return item(request) if callable(item) else item

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api/api")
    sleeps = sleeps if sleeps is not None else []
    client = watcher.ApiClient("unused", "ingest@example.com", "pw", http=http, sleep=sleeps.append)
    return client, calls


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "leaf.jpg"
    path.write_bytes(b"fake image bytes")
    return path


def test_201_is_created(image):
    client, calls = make_client([httpx.Response(201, json={"id": 7})])
    result = client.upload(image, {"crop_species": "Wheat"})
    assert (result.outcome, result.image_id, result.ok) == ("created", 7, True)
    assert calls["last_auth"] == "Bearer token-1"


def test_upload_sends_file_and_metadata_fields(image):
    seen = {}

    def capture(request):
        seen["body"] = request.content
        return httpx.Response(201, json={"id": 1})

    client, _ = make_client([capture])
    client.upload(image, {"crop_species": "Wheat", "tags": "drought,leaf"})
    assert b'name="crop_species"' in seen["body"] and b"Wheat" in seen["body"]
    assert b'filename="leaf.jpg"' in seen["body"] and b"fake image bytes" in seen["body"]


def test_409_duplicate_counts_as_success(image):
    duplicate = httpx.Response(409, json={"detail": {"message": "Duplicate image", "image_id": 3}})
    client, _ = make_client([duplicate])
    result = client.upload(image, {})
    assert (result.outcome, result.image_id, result.ok) == ("duplicate", 3, True)


def test_400_is_rejected_without_retry(image):
    sleeps = []
    client, calls = make_client(
        [httpx.Response(400, json={"detail": "File is not a valid JPEG, PNG or TIFF image"})],
        sleeps,
    )
    result = client.upload(image, {})
    assert result.outcome == "rejected" and not result.ok
    assert result.reason == "HTTP 400: File is not a valid JPEG, PNG or TIFF image"
    assert calls["upload"] == 1 and sleeps == []


def test_5xx_is_retried_with_backoff_then_succeeds(image):
    sleeps = []
    client, calls = make_client(
        [httpx.Response(503), httpx.Response(500), httpx.Response(201, json={"id": 9})], sleeps
    )
    result = client.upload(image, {})
    assert result.outcome == "created"
    assert calls["upload"] == 3
    assert sleeps == [1, 2]


def test_network_errors_give_up_after_five_attempts(image):
    def down(request):
        raise httpx.ConnectError("connection refused")

    sleeps = []
    client, calls = make_client([down] * 5, sleeps)
    result = client.upload(image, {})
    assert result.outcome == "unavailable"
    assert "after 5 attempts" in result.reason and "ConnectError" in result.reason
    assert calls["upload"] == 5
    assert sleeps == [1, 2, 4, 8]


def test_401_logs_in_again_once_and_retries(image):
    client, calls = make_client(
        [httpx.Response(401, json={"detail": "Invalid or expired token"}),
         httpx.Response(201, json={"id": 4})]
    )  # fmt: skip
    client.token = "expired"
    result = client.upload(image, {})
    assert result.outcome == "created"
    assert calls["login"] == 1 and calls["last_auth"] == "Bearer token-1"


def test_second_401_is_rejected(image):
    unauthorized = httpx.Response(401, json={"detail": "Invalid or expired token"})
    client, calls = make_client([unauthorized, unauthorized])
    result = client.upload(image, {})
    assert result.outcome == "rejected"
    assert calls["upload"] == 2


def test_rejected_login_is_not_retried(image):
    def handler(request):
        return httpx.Response(401, json={"detail": "Invalid email or password"})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api/api")
    sleeps = []
    client = watcher.ApiClient("unused", "x@example.com", "bad", http=http, sleep=sleeps.append)
    result = client.upload(image, {})
    assert result.outcome == "rejected"
    assert "login failed" in result.reason and sleeps == []
