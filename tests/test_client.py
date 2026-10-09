import hashlib
import hmac
import io
import json

import pytest
import requests

import pixbin.client as client_module
from pixbin import (
    PixbinAuthError,
    PixbinClient,
    PixbinError,
    PixbinQuotaError,
    PixbinUploadError,
)

from .conftest import BASE_URL, TOKEN

IMAGE_ID = "11111111-2222-3333-4444-555555555555"
S3_URL = "https://s3.test/bucket"


UPLOAD_FIELDS = {
    "Content-Type": "image/jpeg",
    "key": f"uploads/{IMAGE_ID}/photo.jpg",
    "AWSAccessKeyId": "AKIAEXAMPLE",
    "policy": "eyJleHBpcmF0aW9uIjogIjIw",
    "signature": "c2lnbmF0dXJl",
}


def start_body(status="success"):
    return {
        "status": status,
        "data": {
            "image_id": IMAGE_ID,
            "upload_url": S3_URL,
            "upload_fields": UPLOAD_FIELDS,
        },
    }


COMPLETE_BODY = {
    "status": "success",
    "data": {"image_id": IMAGE_ID, "message": "Upload complete. Processing started."},
}

DELETE_BODY = {"status": "success", "data": {"message": "Image deleted"}}

AUTH_FAILED_BODY = {"detail": "Invalid API token"}

QUOTA_BODY = {"error": "Storage quota exceeded", "remaining_bytes": 1024, "plan": "Free"}


def status_body(processing_status, **extra):
    data = {
        "id": IMAGE_ID,
        "original_filename": "photo.jpg",
        "processing_status": processing_status,
        "is_optimized": processing_status == "completed",
        "width": 1920 if processing_status == "completed" else None,
        "height": 1080 if processing_status == "completed" else None,
        "file_size": 123456,
        "format": "JPEG",
        "caption": "",
        "private": False,
        "retention_period": -1,
        "expires_at": None,
        "created_at": "2026-10-09T12:00:00Z",
    }
    data.update(extra)
    return {"status": "success", "data": data}


def mock_upload_flow(mocked, statuses=("completed",)):
    mocked.post(f"{BASE_URL}/api/v1/upload/start", json=start_body(), status=201)
    mocked.post(S3_URL, status=204)
    mocked.post(f"{BASE_URL}/api/v1/upload/complete", json=COMPLETE_BODY)
    for s in statuses:
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", json=status_body(s))


class TestInit:
    def test_strips_trailing_slash(self):
        c = PixbinClient("t", base_url="https://example.com///")
        assert c.base_url == "https://example.com"

    def test_default_base_url_and_timeout(self):
        c = PixbinClient("t")
        assert c.base_url == "https://pixbin.net"
        assert c.timeout == 30

    def test_session_headers(self, client):
        assert client.session.headers["Authorization"] == f"Bearer {TOKEN}"
        assert client.session.headers["Content-Type"] == "application/json"


class TestErrorHandling:
    def test_401_raises_auth_error(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", status=401, json=AUTH_FAILED_BODY)
        with pytest.raises(PixbinAuthError, match=r"Authentication failed: .*Invalid API token"):
            client.get_status(IMAGE_ID)

    def test_413_raises_quota_error(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", status=413, json=QUOTA_BODY)
        with pytest.raises(PixbinQuotaError, match=r"Quota exceeded: .*Storage quota exceeded"):
            client.get_status(IMAGE_ID)

    def test_4xx_with_json_error_field(self, client, mocked):
        mocked.get(
            f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status",
            status=404,
            json={"error": "Image not found"},
        )
        with pytest.raises(PixbinError, match=r"API error \(404\): Image not found"):
            client.get_status(IMAGE_ID)

    def test_5xx_with_non_json_body(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", status=502, body="bad gateway")
        with pytest.raises(PixbinError, match=r"API error \(502\): bad gateway"):
            client.get_status(IMAGE_ID)

    def test_2xx_does_not_raise(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", json=status_body("completed"))
        client.get_status(IMAGE_ID)


class TestGetStatus:
    def test_returns_data_field(self, client, mocked):
        body = status_body("completed")
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", json=body)
        result = client.get_status(IMAGE_ID)
        assert result == body["data"]
        assert result["processing_status"] == "completed"
        assert (result["width"], result["height"]) == (1920, 1080)

    def test_private_image_forbidden(self, client, mocked):
        mocked.get(
            f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status",
            status=403,
            json={"error": "You do not have permission to access this private image"},
        )
        with pytest.raises(PixbinError, match=r"API error \(403\): You do not have permission"):
            client.get_status(IMAGE_ID)

    def test_missing_data_returns_empty_dict(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", json={"status": "success"})
        assert client.get_status(IMAGE_ID) == {}

    def test_sends_auth_header(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", json=status_body("completed"))
        client.get_status(IMAGE_ID)
        assert mocked.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


class TestDelete:
    def test_issues_delete_request(self, client, mocked):
        mocked.delete(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/delete", json=DELETE_BODY)
        assert client.delete(IMAGE_ID) is None
        assert mocked.calls[0].request.method == "DELETE"

    def test_not_found(self, client, mocked):
        mocked.delete(
            f"{BASE_URL}/api/v1/image/{IMAGE_ID}/delete",
            status=404,
            json={"error": "Image not found or does not belong to you"},
        )
        with pytest.raises(PixbinError, match="does not belong to you"):
            client.delete(IMAGE_ID)


class TestTransformUrl:
    PARAMS = "resize:300x300:fit,quality:85"

    def expected_signature(self):
        message = f"{IMAGE_ID}:{self.PARAMS}".encode()
        return hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest()[:16]

    def test_full_url(self, client):
        sig = self.expected_signature()
        assert client.transform_url(IMAGE_ID, self.PARAMS) == (
            f"{BASE_URL}/api/v1/image/{sig}/{self.PARAMS}/{IMAGE_ID}"
        )

    def test_path_only(self, client):
        sig = self.expected_signature()
        assert client.transform_url(IMAGE_ID, self.PARAMS, include_host=False) == (
            f"/api/v1/image/{sig}/{self.PARAMS}/{IMAGE_ID}"
        )

    def test_signature_depends_on_token(self):
        a = PixbinClient("token-a", base_url=BASE_URL)
        b = PixbinClient("token-b", base_url=BASE_URL)
        assert a.transform_url(IMAGE_ID, self.PARAMS) != b.transform_url(IMAGE_ID, self.PARAMS)

    def test_signature_depends_on_params(self, client):
        assert client.transform_url(IMAGE_ID, "a") != client.transform_url(IMAGE_ID, "b")


class TestDownloadOriginal:
    def test_returns_bytes(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}", body=b"\x89PNG")
        assert client.download_original(IMAGE_ID) == b"\x89PNG"

    def test_auth_error(self, client, mocked):
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}", status=401)
        with pytest.raises(PixbinAuthError):
            client.download_original(IMAGE_ID)


class TestDownloadTransformed:
    PARAMS = "resize:100x100:fit"

    def url(self, client):
        return client.transform_url(IMAGE_ID, self.PARAMS)

    def test_success_first_try(self, client, mocked, clock):
        mocked.get(self.url(client), body=b"jpeg")
        assert client.download_transformed(IMAGE_ID, self.PARAMS) == b"jpeg"
        assert clock.sleeps == []

    def placeholder_202(self, client, mocked):
        # The server answers 202 with a blurred JPEG placeholder, not JSON.
        mocked.get(
            self.url(client),
            status=202,
            body=b"\xff\xd8placeholder",
            content_type="image/jpeg",
            headers={"X-Pixbin-Status": "processing", "Cache-Control": "no-cache, no-store"},
        )

    def test_retries_on_202_then_succeeds(self, client, mocked, clock):
        self.placeholder_202(client, mocked)
        self.placeholder_202(client, mocked)
        mocked.get(self.url(client), body=b"jpeg", content_type="image/webp")
        result = client.download_transformed(IMAGE_ID, self.PARAMS, retry_delay=0.5)
        assert result == b"jpeg"
        assert clock.sleeps == [0.5, 0.5]
        assert len(mocked.calls) == 3

    def test_202_json_fallback_also_retries(self, client, mocked, clock):
        mocked.get(
            self.url(client),
            status=202,
            json={"error": "Variant is being generated. Please retry in a few seconds.", "status": "processing"},
        )
        mocked.get(self.url(client), body=b"jpeg")
        assert client.download_transformed(IMAGE_ID, self.PARAMS) == b"jpeg"

    def test_gives_up_after_max_retries(self, client, mocked, clock):
        for _ in range(3):
            self.placeholder_202(client, mocked)
        with pytest.raises(PixbinError, match="still processing"):
            client.download_transformed(IMAGE_ID, self.PARAMS, max_retries=3)
        assert len(mocked.calls) == 3
        assert len(clock.sleeps) == 2

    def test_http_error_propagates(self, client, mocked, clock):
        mocked.get(self.url(client), status=500, json={"error": "Error fetching image"})
        with pytest.raises(requests.HTTPError):
            client.download_transformed(IMAGE_ID, self.PARAMS)

    def test_bad_signature_propagates(self, client, mocked, clock):
        mocked.get(self.url(client), status=403, json={"error": "Invalid signature"})
        with pytest.raises(requests.HTTPError):
            client.download_transformed(IMAGE_ID, self.PARAMS)

    def test_does_not_send_auth_header(self, client, mocked, clock):
        mocked.get(self.url(client), body=b"jpeg")
        client.download_transformed(IMAGE_ID, self.PARAMS)
        assert "Authorization" not in mocked.calls[0].request.headers


class TestExtractDimensions:
    def test_without_pil(self, client, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        assert client._extract_dimensions(b"anything") == (0, 0)

    def test_invalid_image_data(self, client):
        assert client._extract_dimensions(b"not an image") == (0, 0)

    def test_real_image(self, client):
        PIL = pytest.importorskip("PIL.Image")
        buf = io.BytesIO()
        PIL.new("RGB", (12, 7)).save(buf, format="PNG")
        assert client._extract_dimensions(buf.getvalue()) == (12, 7)


class TestUploadFile:
    def test_missing_file(self, client, tmp_path):
        with pytest.raises(PixbinUploadError, match="File not found"):
            client.upload_file(tmp_path / "nope.jpg")

    def test_full_flow_from_path(self, client, mocked, clock, tmp_path, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        path = tmp_path / "photo.jpg"
        path.write_bytes(b"\xff\xd8fake-jpeg")
        mock_upload_flow(mocked)

        image_id = client.upload_file(path, caption="hi", private=True, retention_hours=24)

        assert image_id == IMAGE_ID
        start, s3, complete, status = mocked.calls

        assert json.loads(start.request.body) == {
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": len(b"\xff\xd8fake-jpeg"),
            "caption": "hi",
            "private": True,
            "retention_hours": 24,
        }

        assert s3.request.url == S3_URL
        assert "Authorization" not in s3.request.headers
        assert s3.request.headers["Content-Type"].startswith("multipart/form-data")
        body = s3.request.body
        for field, value in UPLOAD_FIELDS.items():
            assert f'name="{field}"'.encode() in body
            assert value.encode() in body
        assert b'filename="photo.jpg"' in body and b"fake-jpeg" in body

        assert json.loads(complete.request.body) == {"image_id": IMAGE_ID}
        assert status.request.method == "GET"

    def test_file_like_object(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mock_upload_flow(mocked)
        f = io.BytesIO(b"png-bytes")
        f.name = "pic.png"

        client.upload_file(f)

        start = json.loads(mocked.calls[0].request.body)
        assert start["filename"] == "pic.png"
        assert start["content_type"] == "image/png"
        assert start["file_size"] == len(b"png-bytes")

    def test_file_like_without_name_uses_default(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mock_upload_flow(mocked)

        client.upload_file(io.BytesIO(b"data"))

        start = json.loads(mocked.calls[0].request.body)
        assert start["filename"] == "image.jpg"
        assert start["content_type"] == "image/jpeg"

    def test_unknown_extension_uses_octet_stream(self, client, mocked, clock, tmp_path, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        path = tmp_path / "blob.unknownext"
        path.write_bytes(b"x")
        mock_upload_flow(mocked)

        client.upload_file(path)

        start = json.loads(mocked.calls[0].request.body)
        assert start["content_type"] == "application/octet-stream"

    def test_dimensions_sent_when_available(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(PixbinClient, "_extract_dimensions", lambda self, data: (640, 480))
        mock_upload_flow(mocked)

        client.upload_file(io.BytesIO(b"img"))

        complete = json.loads(mocked.calls[2].request.body)
        assert complete == {"image_id": IMAGE_ID, "width": 640, "height": 480}

    def test_dimensions_omitted_when_unknown(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(PixbinClient, "_extract_dimensions", lambda self, data: (0, 0))
        mock_upload_flow(mocked)

        client.upload_file(io.BytesIO(b"img"))

        complete = json.loads(mocked.calls[2].request.body)
        assert complete == {"image_id": IMAGE_ID}

    def test_start_failure_status(self, client, mocked, clock):
        mocked.post(f"{BASE_URL}/api/v1/upload/start", json={"status": "error", "data": {}})
        with pytest.raises(PixbinUploadError, match="Upload start failed"):
            client.upload_file(io.BytesIO(b"img"))

    def test_start_validation_error(self, client, mocked, clock):
        # DRF serializer errors come back as a 400 with field names as keys.
        mocked.post(
            f"{BASE_URL}/api/v1/upload/start",
            status=400,
            json={"content_type": ["Unsupported content type"]},
        )
        with pytest.raises(PixbinError, match=r"API error \(400\)"):
            client.upload_file(io.BytesIO(b"img"))

    def test_start_auth_error(self, client, mocked, clock):
        mocked.post(f"{BASE_URL}/api/v1/upload/start", status=401, json=AUTH_FAILED_BODY)
        with pytest.raises(PixbinAuthError):
            client.upload_file(io.BytesIO(b"img"))

    def test_start_quota_error(self, client, mocked, clock):
        mocked.post(f"{BASE_URL}/api/v1/upload/start", status=413, json=QUOTA_BODY)
        with pytest.raises(PixbinQuotaError):
            client.upload_file(io.BytesIO(b"img"))

    def test_s3_http_error(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mocked.post(f"{BASE_URL}/api/v1/upload/start", json=start_body(), status=201)
        mocked.post(S3_URL, status=403, body="<Error><Code>AccessDenied</Code></Error>")
        with pytest.raises(PixbinUploadError, match="S3 upload failed"):
            client.upload_file(io.BytesIO(b"img"))

    def test_s3_connection_error(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mocked.post(f"{BASE_URL}/api/v1/upload/start", json=start_body(), status=201)
        mocked.post(S3_URL, body=requests.ConnectionError("reset"))
        with pytest.raises(PixbinUploadError, match="S3 upload failed"):
            client.upload_file(io.BytesIO(b"img"))

    def test_complete_failure_status(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mocked.post(f"{BASE_URL}/api/v1/upload/start", json=start_body(), status=201)
        mocked.post(S3_URL, status=204)
        mocked.post(f"{BASE_URL}/api/v1/upload/complete", json={"status": "error"})
        with pytest.raises(PixbinUploadError, match="Upload completion failed"):
            client.upload_file(io.BytesIO(b"img"))

    @pytest.mark.parametrize(
        "code,error",
        [
            (404, "Image not found or does not belong to you"),
            (410, "Upload window expired. Please start a new upload."),
            (400, "File not found in storage. Upload may have failed."),
        ],
    )
    def test_complete_server_errors(self, client, mocked, clock, monkeypatch, code, error):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mocked.post(f"{BASE_URL}/api/v1/upload/start", json=start_body(), status=201)
        mocked.post(S3_URL, status=204)
        mocked.post(f"{BASE_URL}/api/v1/upload/complete", status=code, json={"error": error})
        with pytest.raises(PixbinError, match=rf"API error \({code}\): {error}"):
            client.upload_file(io.BytesIO(b"img"))

    def test_max_wait_zero_skips_polling(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mock_upload_flow(mocked, statuses=())

        assert client.upload_file(io.BytesIO(b"img"), max_wait=0) == IMAGE_ID
        assert len(mocked.calls) == 3

    def test_polls_until_completed(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mock_upload_flow(mocked, statuses=("uploaded", "processing", "completed"))

        client.upload_file(io.BytesIO(b"img"), poll_interval=0.25)

        assert len(mocked.calls) == 6
        assert clock.sleeps == [0.25, 0.25]

    @pytest.mark.parametrize("terminal", ["failed", "expired"])
    def test_processing_failure(self, client, mocked, clock, monkeypatch, terminal):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mock_upload_flow(mocked, statuses=(terminal,))
        with pytest.raises(PixbinUploadError, match=f"Processing failed: {terminal}"):
            client.upload_file(io.BytesIO(b"img"))

    def test_processing_timeout(self, client, mocked, clock, monkeypatch):
        monkeypatch.setattr(client_module, "HAS_PIL", False)
        mocked.post(f"{BASE_URL}/api/v1/upload/start", json=start_body(), status=201)
        mocked.post(S3_URL, status=204)
        mocked.post(f"{BASE_URL}/api/v1/upload/complete", json=COMPLETE_BODY)
        # Not all registered responses fire here, so register one reusable status.
        mocked.get(f"{BASE_URL}/api/v1/image/{IMAGE_ID}/status", json=status_body("processing"))
        mocked.assert_all_requests_are_fired = False

        with pytest.raises(PixbinUploadError, match="Processing timeout after 3s"):
            client.upload_file(io.BytesIO(b"img"), poll_interval=1.0, max_wait=3)

        assert clock.sleeps == [1.0, 1.0, 1.0]


class TestConvenienceFunctions:
    def test_thumbnail(self):
        assert client_module.thumbnail(300, 200) == "resize:300x200:fit,quality:85"
        assert client_module.thumbnail(300, 200, quality=50) == "resize:300x200:fit,quality:50"

    def test_crop_square(self):
        assert client_module.crop_square(100) == "crop:center,resize:100x100:exact"
        assert client_module.crop_square(100, mode="top") == "crop:top,resize:100x100:exact"

    def test_optimize_web(self):
        assert client_module.optimize_web() == "resize:1920x1920:fit,quality:85,format:webp"
        assert client_module.optimize_web(800, 70) == "resize:800x800:fit,quality:70,format:webp"


def test_package_exports():
    import pixbin

    for name in pixbin.__all__:
        assert hasattr(pixbin, name)
    assert isinstance(pixbin.__version__, str)
