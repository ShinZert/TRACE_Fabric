"""
Server-side validation for image uploads. Sniffs the actual bytes (rather than
trusting the client-declared MIME or filename) so we don't ship arbitrary
attacker-controlled payloads to OpenAI as "image/png".
"""

import base64
import io

from PIL import Image, UnidentifiedImageError


# OpenAI's vision input accepts these formats.
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}

_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def validate_image_bytes(raw_bytes):
    """
    Verify `raw_bytes` is a real image in an allowed format.

    Returns (mime, error). On success: (mime_string, None). On failure:
    (None, human-readable error string suitable for surfacing to the client).
    """
    if not raw_bytes:
        return None, "Image is empty."
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img.verify()
            fmt = (img.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError):
        return None, "Uploaded file is not a recognised image."

    if fmt not in ALLOWED_FORMATS:
        return None, f"Unsupported image format: {fmt or 'unknown'}."
    return _FORMAT_TO_MIME[fmt], None


def validate_image_base64(image_b64):
    """
    Decode a base64 string from the client and validate it.

    Returns (mime, error). The base64 itself is returned unchanged on success;
    callers re-use the original string to avoid a re-encode round-trip.
    """
    if not isinstance(image_b64, str):
        return None, "image_base64 must be a string."
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (ValueError, TypeError):
        return None, "image_base64 is not valid base64."
    return validate_image_bytes(raw)
