"""
Pixbin Python SDK

Simple client library for interacting with the Pixbin Image API.

Usage:
    from pixbin import PixbinClient

    # Initialize client
    client = PixbinClient(
        api_token="your_api_token",
        base_url="https://pixbin.net"  # optional, defaults to https://pixbin.net
    )

    # Upload image
    image_id = client.upload_file("photo.jpg", caption="My photo", private=False)

    # Get image status
    status = client.get_status(image_id)

    # Generate transformation URL
    url = client.transform_url(image_id, "resize:300x300:fit,quality:85,format:webp")

    # Download transformed image
    image_bytes = client.download_transformed(image_id, "resize:300x300:fit")
"""

from .client import (
    PixbinClient,
    PixbinError,
    PixbinAuthError,
    PixbinQuotaError,
    PixbinUploadError,
    thumbnail,
    crop_square,
    optimize_web,
)

__version__ = "0.1.0"

__all__ = [
    "PixbinClient",
    "PixbinError",
    "PixbinAuthError",
    "PixbinQuotaError",
    "PixbinUploadError",
    "thumbnail",
    "crop_square",
    "optimize_web",
]
