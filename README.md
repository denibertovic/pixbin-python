# Pixbin Python SDK

Official Python client library for the Pixbin Image API.

## Installation

```bash
uv add git+https://github.com/denibertovic/pixbin-python.git
```

Or with pip:

```bash
pip install git+https://github.com/denibertovic/pixbin-python.git
```

For dimension extraction support (recommended):

```bash
uv add "pixbin[dimensions] @ git+https://github.com/denibertovic/pixbin-python.git"
```

## Quick Start

```python
from pixbin import PixbinClient

# Initialize client with your API token
client = PixbinClient(api_token="your_api_token_here")

# Upload an image
image_id = client.upload_file("photo.jpg", caption="My awesome photo")
print(f"Uploaded: {image_id}")

# Generate transformation URL
thumbnail_url = client.transform_url(image_id, "resize:300x300:fit,quality:85")
print(f"Thumbnail: {thumbnail_url}")
```

## Authentication

Get your API token from your Pixbin account settings (Pro plan required):

1. Go to **Account Settings** → **API Access**
2. Click **Generate API Token**
3. Copy the token and keep it secure

```python
client = PixbinClient(
    api_token="your_api_token",
    base_url="https://pixbin.net"  # optional, defaults to https://pixbin.net
)
```

## Uploading Images

### Upload from File Path

```python
# Simple upload
image_id = client.upload_file("photo.jpg")

# With options
image_id = client.upload_file(
    "photo.jpg",
    caption="Sunset over mountains",
    private=False,  # Public image (default)
    retention_hours=-1  # Permanent (-1 is default for API)
)
```

### Upload from File Object

```python
with open("photo.jpg", "rb") as f:
    image_id = client.upload_file(f, caption="My photo")
```

### Upload from BytesIO

```python
from io import BytesIO
from PIL import Image

# Create image in memory
img = Image.new("RGB", (800, 600), color="red")
buffer = BytesIO()
img.save(buffer, format="JPEG")
buffer.seek(0)

# Upload
image_id = client.upload_file(buffer, caption="Generated image")
```

## Image Transformations

### Generate Transformation URLs

```python
# Resize to thumbnail
url = client.transform_url(image_id, "resize:300x300:fit")

# Multiple transformations
url = client.transform_url(
    image_id,
    "resize:800x600:fill,quality:85,format:webp"
)

# Complex transformation
url = client.transform_url(
    image_id,
    "crop:center,resize:500x500:exact,blur:2,quality:90"
)
```

### Transformation Parameters

| Transformation | Format            | Description          | Example                       |
| -------------- | ----------------- | -------------------- | ----------------------------- |
| **Resize**     | `resize:WxH:MODE` | Resize image         | `resize:300x300:fit`          |
| **Crop**       | `crop:MODE`       | Crop image           | `crop:center` or `crop:smart` |
| **Quality**    | `quality:N`       | JPEG quality (1-100) | `quality:85`                  |
| **Format**     | `format:TYPE`     | Convert format       | `format:webp`                 |
| **Blur**       | `blur:RADIUS`     | Blur effect (0-50)   | `blur:5`                      |
| **Sharpen**    | `sharpen:FACTOR`  | Sharpen (0-10)       | `sharpen:2`                   |
| **Grayscale**  | `grayscale`       | Convert to grayscale | `grayscale`                   |

#### Resize Modes

- **`fit`**: Fit inside dimensions (maintain aspect ratio, no cropping)
- **`fill`**: Fill dimensions (maintain aspect ratio, crop excess)
- **`exact`**: Exact dimensions (may distort image)

#### Crop Modes

- **`center`**: Simple geometric center crop
- **`smart`**: Content-aware crop (preserves faces/important areas)

### Download Transformed Images

```python
# Download transformed image bytes
image_bytes = client.download_transformed(
    image_id,
    "resize:300x300:fit,format:webp"
)

# Save to file
with open("thumbnail.webp", "wb") as f:
    f.write(image_bytes)
```

### Convenience Helpers

```python
from pixbin import thumbnail, crop_square, optimize_web

# Generate common transformation params
params = thumbnail(300, 300, quality=85)
# → "resize:300x300:fit,quality:85"

params = crop_square(200, mode="center")
# → "crop:center,resize:200x200:exact"

params = optimize_web(max_width=1920, quality=85)
# → "resize:1920x1920:fit,quality:85,format:webp"
```

## Image Status

Check image processing status:

```python
status = client.get_status(image_id)

print(status["processing_status"])  # "completed", "processing", "failed"
print(status["width"], status["height"])  # 1920 1080
print(status["file_size"])  # File size in bytes
print(status["is_optimized"])  # True if optimized
```

## Error Handling

```python
from pixbin import (
    PixbinError,
    PixbinAuthError,
    PixbinQuotaError,
    PixbinUploadError
)

try:
    image_id = client.upload_file("photo.jpg")
except PixbinAuthError:
    print("Invalid API token")
except PixbinQuotaError:
    print("Storage or API quota exceeded")
except PixbinUploadError as e:
    print(f"Upload failed: {e}")
except PixbinError as e:
    print(f"API error: {e}")
```

## Advanced Usage

### Batch Upload

```python
import os
from pathlib import Path

def upload_directory(directory: str):
    """Upload all images in a directory."""
    image_ids = []

    for file_path in Path(directory).glob("*.jpg"):
        try:
            image_id = client.upload_file(
                str(file_path),
                caption=file_path.stem
            )
            image_ids.append(image_id)
            print(f"✓ Uploaded {file_path.name}: {image_id}")
        except PixbinError as e:
            print(f"✗ Failed {file_path.name}: {e}")

    return image_ids

# Upload all JPGs in a folder
ids = upload_directory("/path/to/photos")
```

### Generate Gallery Thumbnails

```python
def generate_gallery_thumbnails(image_ids: list, sizes=[300, 600, 1200]):
    """Generate multiple thumbnail sizes for gallery."""
    thumbnails = {}

    for image_id in image_ids:
        thumbnails[image_id] = {}
        for size in sizes:
            params = f"resize:{size}x{size}:fit,quality:85,format:webp"
            url = client.transform_url(image_id, params)
            thumbnails[image_id][size] = url

    return thumbnails

# Usage
gallery_urls = generate_gallery_thumbnails([
    "abc-123-def-456",
    "xyz-789-ghi-012"
])

# Output:
# {
#     "abc-123-def-456": {
#         300: "https://pixbin.net/api/v1/image/sig/.../abc-123-def-456",
#         600: "https://pixbin.net/api/v1/image/sig/.../abc-123-def-456",
#         1200: "https://pixbin.net/api/v1/image/sig/.../abc-123-def-456"
#     }
# }
```

### Custom Retry Logic

```python
# Download with custom retry settings
image_bytes = client.download_transformed(
    image_id,
    "resize:1920x1080:fit",
    max_retries=5,  # Try 5 times
    retry_delay=3.0  # Wait 3 seconds between retries
)
```

## Examples

### Profile Picture Pipeline

```python
def upload_profile_picture(file_path: str, user_id: str):
    """Upload and generate profile picture variants."""

    # Upload original
    image_id = client.upload_file(
        file_path,
        caption=f"Profile picture for user {user_id}",
        private=False  # Public for avatar display
    )

    # Generate variants
    variants = {
        "thumb": client.transform_url(image_id, "crop:smart,resize:64x64:exact"),
        "small": client.transform_url(image_id, "crop:smart,resize:128x128:exact"),
        "medium": client.transform_url(image_id, "crop:smart,resize:256x256:exact"),
        "large": client.transform_url(image_id, "crop:smart,resize:512x512:exact"),
    }

    return {
        "image_id": image_id,
        "urls": variants
    }

# Usage
profile = upload_profile_picture("avatar.jpg", "user_123")
print(profile["urls"]["medium"])  # Use in <img> tag
```

### Product Image Optimization

```python
def optimize_product_images(images: list):
    """Optimize product images for e-commerce."""

    results = []

    for img_path in images:
        image_id = client.upload_file(img_path, private=False)

        # Generate variants for product pages
        urls = {
            "thumbnail": client.transform_url(
                image_id,
                "resize:300x300:fill,quality:85,format:webp"
            ),
            "medium": client.transform_url(
                image_id,
                "resize:800x800:fit,quality:90,format:webp"
            ),
            "large": client.transform_url(
                image_id,
                "resize:1500x1500:fit,quality:95,format:webp"
            ),
            "zoom": client.transform_url(
                image_id,
                "resize:3000x3000:fit,quality:90"
            ),
        }

        results.append({
            "image_id": image_id,
            "filename": Path(img_path).name,
            "urls": urls
        })

    return results
```

## API Limits

**Pro Plan:**

- API Requests: 10,000/day
- Storage: 75GB
- Max file size: 20MB
- Transformations: Unlimited (cached)

Check your current usage in the Pixbin dashboard.

## Support

- **Documentation**: https://pixbin.net/docs
- **API Reference**: https://pixbin.net/api/docs
- **Issues**: https://github.com/pixbin/pixbin-python/issues
- **Contact**: https://pixbin.net/contact/

## License

MIT License - see LICENSE file for details.
