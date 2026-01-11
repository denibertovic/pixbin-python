"""
Pixbin client implementation.

This module contains the PixbinClient class and related exceptions.
For usage examples, see the package docstring: help(pixbin)
"""

import io
import mimetypes
import requests
import time
from pathlib import Path
from typing import Dict, Any, BinaryIO, Union, Tuple

# Optional PIL for dimension extraction
try:
    from PIL import Image as PILImage

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class PixbinError(Exception):
    """Base exception for Pixbin SDK errors."""

    pass


class PixbinAuthError(PixbinError):
    """Authentication/authorization error."""

    pass


class PixbinQuotaError(PixbinError):
    """Quota exceeded error."""

    pass


class PixbinUploadError(PixbinError):
    """Upload error."""

    pass


class PixbinClient:
    """
    Pixbin API client for uploading and transforming images.

    Args:
        api_token: Your API token (generate in account settings)
        base_url: Base URL of Pixbin API (default: https://pixbin.net)
        timeout: Request timeout in seconds (default: 30)
    """

    def __init__(
        self, api_token: str, base_url: str = "https://pixbin.net", timeout: int = 30
    ):
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            }
        )

    def _get(self, endpoint: str, **kwargs) -> requests.Response:
        """Make GET request."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self._handle_errors(response)
        return response

    def _post(self, endpoint: str, **kwargs) -> requests.Response:
        """Make POST request."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.post(url, timeout=self.timeout, **kwargs)
        self._handle_errors(response)
        return response

    def _handle_errors(self, response: requests.Response):
        """Handle HTTP errors."""
        if response.status_code == 401:
            raise PixbinAuthError(f"Authentication failed: {response.text}")
        elif response.status_code == 413:
            raise PixbinQuotaError(f"Quota exceeded: {response.text}")
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", response.text)
            except Exception:
                error_msg = response.text
            raise PixbinError(f"API error ({response.status_code}): {error_msg}")

    def _extract_dimensions(self, file_data: bytes) -> Tuple[int, int]:
        """
        Extract image dimensions from file data using PIL.

        Returns (width, height) tuple, or (0, 0) if extraction fails.
        """
        if not HAS_PIL:
            return (0, 0)

        try:
            with PILImage.open(io.BytesIO(file_data)) as img:
                return img.size  # (width, height)
        except Exception:
            return (0, 0)

    def upload_file(
        self,
        file_path: Union[str, Path, BinaryIO],
        caption: str = "",
        private: bool = False,
        retention_hours: int = -1,
        poll_interval: float = 1.0,
        max_wait: int = 60,
    ) -> str:
        """
        Upload image file with automatic 3-phase flow.

        Args:
            file_path: Path to image file or file-like object
            caption: Optional caption for the image
            private: Whether image should be private (default: False)
            retention_hours: Retention period (-1 for permanent, default)
            poll_interval: Seconds between status polls (default: 1.0)
            max_wait: Maximum seconds to wait for processing (default: 60)

        Returns:
            Image ID (UUID string)

        Raises:
            PixbinUploadError: If upload fails
            PixbinQuotaError: If quota is exceeded
            PixbinAuthError: If authentication fails

        Example:
            >>> client = PixbinClient("your_token")
            >>> image_id = client.upload_file("photo.jpg", caption="My photo")
            >>> print(f"Uploaded: {image_id}")
        """
        # Open file and get metadata
        if isinstance(file_path, (str, Path)):
            file_path = Path(file_path)
            if not file_path.exists():
                raise PixbinUploadError(f"File not found: {file_path}")

            filename = file_path.name
            file_size = file_path.stat().st_size
            content_type = (
                mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            )

            with open(file_path, "rb") as f:
                file_data = f.read()
        else:
            # File-like object
            filename = getattr(file_path, "name", "image.jpg")
            file_data = file_path.read()
            file_size = len(file_data)
            content_type = (
                mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )

        # Phase 1: Start upload
        start_response = self._post(
            "/api/v1/upload/start",
            json={
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
                "caption": caption,
                "private": private,
                "retention_hours": retention_hours,
            },
        )

        start_data = start_response.json()
        if start_data.get("status") != "success":
            raise PixbinUploadError(f"Upload start failed: {start_data}")

        image_id = start_data["data"]["image_id"]
        upload_url = start_data["data"]["upload_url"]
        upload_fields = start_data["data"]["upload_fields"]

        # Phase 2: Upload to S3
        try:
            files = {"file": (filename, file_data, content_type)}
            s3_response = requests.post(
                upload_url, data=upload_fields, files=files, timeout=self.timeout
            )
            s3_response.raise_for_status()
        except requests.RequestException as e:
            raise PixbinUploadError(f"S3 upload failed: {e}")

        # Extract dimensions for immediate availability (enables skeleton layouts)
        width, height = self._extract_dimensions(file_data)

        # Phase 3: Complete upload with dimensions
        complete_payload = {"image_id": image_id}
        if width > 0 and height > 0:
            complete_payload["width"] = width
            complete_payload["height"] = height

        complete_response = self._post("/api/v1/upload/complete", json=complete_payload)

        complete_data = complete_response.json()
        if complete_data.get("status") != "success":
            raise PixbinUploadError(f"Upload completion failed: {complete_data}")

        # Poll for completion
        if max_wait > 0:
            self._wait_for_completion(image_id, poll_interval, max_wait)

        return image_id

    def _wait_for_completion(self, image_id: str, poll_interval: float, max_wait: int):
        """Wait for image processing to complete."""
        start_time = time.time()
        while time.time() - start_time < max_wait:
            status_data = self.get_status(image_id)
            processing_status = status_data.get("processing_status")

            if processing_status == "completed":
                return
            elif processing_status in ("failed", "expired"):
                raise PixbinUploadError(f"Processing failed: {processing_status}")

            time.sleep(poll_interval)

        raise PixbinUploadError(f"Processing timeout after {max_wait}s")

    def get_status(self, image_id: str) -> Dict[str, Any]:
        """
        Get image processing status.

        Args:
            image_id: Image UUID

        Returns:
            Status dictionary

        Example:
            >>> status = client.get_status(image_id)
            >>> print(status["processing_status"])  # "completed"
            >>> print(status["width"], status["height"])  # 1920 1080
        """
        response = self._get(f"/api/v1/image/{image_id}/status")
        data = response.json()
        return data.get("data", {})

    def _generate_signature(self, image_id: str, params: str) -> str:
        """
        Generate HMAC-SHA256 signature for transformation URL.

        Uses the API token as the signing key.
        """
        import hmac
        import hashlib

        message = f"{image_id}:{params}"
        signature = hmac.new(
            self.api_token.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        # Return first 16 chars for shorter URLs
        return signature[:16]

    def transform_url(
        self, image_id: str, params: str, include_host: bool = True
    ) -> str:
        """
        Generate signed transformation URL.

        Args:
            image_id: Image UUID
            params: Transformation parameters string
            include_host: Include full URL (default) or just path

        Returns:
            Transformation URL

        Example:
            >>> url = client.transform_url(
            ...     image_id,
            ...     "resize:300x300:fit,quality:85,format:webp"
            ... )
            >>> print(url)
            https://pixbin.net/api/v1/image/abc123/resize:300x300:fit,.../uuid
        """
        signature = self._generate_signature(image_id, params)
        path = f"/api/v1/image/{signature}/{params}/{image_id}"

        if include_host:
            return f"{self.base_url}{path}"
        return path

    def download_transformed(
        self, image_id: str, params: str, max_retries: int = 3, retry_delay: float = 2.0
    ) -> bytes:
        """
        Download transformed image bytes.

        Automatically retries if variant is still being generated.

        Args:
            image_id: Image UUID
            params: Transformation parameters
            max_retries: Maximum retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 2.0)

        Returns:
            Image bytes

        Example:
            >>> image_bytes = client.download_transformed(
            ...     image_id,
            ...     "resize:300x300:fit"
            ... )
            >>> with open("thumbnail.jpg", "wb") as f:
            ...     f.write(image_bytes)
        """
        url = self.transform_url(image_id, params)

        for attempt in range(max_retries):
            response = requests.get(url, timeout=self.timeout)

            if response.status_code == 200:
                return response.content
            elif response.status_code == 202:
                # Variant being generated, retry
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    raise PixbinError(
                        "Transformation timeout - variant still processing"
                    )
            else:
                response.raise_for_status()

        raise PixbinError("Failed to download transformed image")

    def download_original(self, image_id: str) -> bytes:
        """
        Download original (or optimized) image bytes.

        Args:
            image_id: Image UUID

        Returns:
            Image bytes
        """
        response = self._get(f"/api/v1/image/{image_id}")
        return response.content


# Convenience functions for common transformations


def thumbnail(width: int, height: int, quality: int = 85) -> str:
    """Generate thumbnail transformation params."""
    return f"resize:{width}x{height}:fit,quality:{quality}"


def crop_square(size: int, mode: str = "center") -> str:
    """Generate square crop transformation params."""
    return f"crop:{mode},resize:{size}x{size}:exact"


def optimize_web(max_width: int = 1920, quality: int = 85) -> str:
    """Generate web optimization transformation params."""
    return f"resize:{max_width}x{max_width}:fit,quality:{quality},format:webp"
