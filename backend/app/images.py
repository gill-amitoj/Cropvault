"""Image validation, checksum, thumbnail and EXIF helpers (plain functions, no I/O)."""

import datetime as dt
import hashlib
import io
import math
import warnings

from PIL import ExifTags, Image, ImageOps
from PIL.TiffImagePlugin import IFDRational

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
THUMBNAIL_WIDTH = 320

# Pillow format name -> (content type we store, file extension for the storage key)
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "TIFF": ("image/tiff", ".tif"),
}

# Readable EXIF tags worth keeping. Binary blobs (MakerNote etc.) are skipped.
EXIF_TAGS = {
    "Make",
    "Model",
    "Software",
    "DateTimeOriginal",
    "Orientation",
    "ExposureTime",
    "FNumber",
    "ISOSpeedRatings",
    "FocalLength",
}

# EXIF orientations 5-8 rotate by 90/270 degrees, so displayed width and height swap.
SWAPS_WIDTH_HEIGHT = {5, 6, 7, 8}


class InvalidImage(ValueError):
    """Not a real JPEG/PNG/TIFF (-> 400)."""


class ImageTooLarge(ValueError):
    """Pixel dimensions trip Pillow's decompression-bomb protection (-> 413)."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_image(data: bytes) -> Image.Image:
    """Open AND fully decode the bytes with Pillow. Never trusts the extension or Content-Type:
    Pillow detects the format from the file's own bytes."""
    try:
        with warnings.catch_warnings():
            # Pillow warns above MAX_IMAGE_PIXELS and errors above 2x; we treat both as errors.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in ALLOWED_FORMATS:
                raise InvalidImage(f"Unsupported image format: {img.format}")
            img.load()  # decode the pixels; catches truncated or corrupt files
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageTooLarge("Image dimensions are too large") from None
    except InvalidImage:
        raise
    except Exception:
        raise InvalidImage("File is not a valid JPEG, PNG or TIFF image") from None
    return img


def display_size(img: Image.Image) -> tuple[int, int]:
    """Width and height as the image is displayed (after EXIF orientation is applied).
    Crops and annotations use this orientation."""
    width, height = img.size
    if img.getexif().get(ExifTags.Base.Orientation) in SWAPS_WIDTH_HEIGHT:
        return height, width
    return width, height


def _to_rgb(img: Image.Image) -> Image.Image:
    """Convert any supported mode to 8-bit RGB for a JPEG thumbnail."""
    if img.mode in ("I;16", "I;16L", "I;16B", "I", "F"):
        # 16/32-bit scientific TIFFs: stretch the real value range to 0-255,
        # otherwise convert() clips everything above 255 and the thumbnail is white.
        if img.mode != "F":
            img = img.convert("I")
        low, high = img.getextrema()
        scale = 255 / (high - low) if high > low else 1
        return img.point(lambda v: (v - low) * scale).convert("L").convert("RGB")
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        return background
    return img.convert("RGB")


def make_thumbnail(img: Image.Image) -> bytes:
    """320 px wide JPEG, EXIF orientation applied. Works on a copy; never changes the original.
    Images narrower than 320 px are not upscaled."""
    thumb = _to_rgb(ImageOps.exif_transpose(img))
    if thumb.width > THUMBNAIL_WIDTH:
        height = max(1, round(thumb.height * THUMBNAIL_WIDTH / thumb.width))
        thumb = thumb.resize((THUMBNAIL_WIDTH, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    thumb.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def _json_safe(value):
    """Turn an EXIF value into something JSON can store, or None to skip it."""
    if isinstance(value, IFDRational):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int | bool):
        return value
    if isinstance(value, str):
        return value.strip("\x00 ").strip() or None
    if isinstance(value, tuple):
        items = [_json_safe(v) for v in value]
        return items if all(v is not None for v in items) else None
    return None  # bytes and anything else


def extract_exif(img: Image.Image) -> dict:
    """Whitelisted, JSON-safe EXIF tags from the main IFD and the Exif sub-IFD."""
    exif = img.getexif()
    tags = dict(exif)
    tags.update(exif.get_ifd(ExifTags.IFD.Exif))
    result = {}
    for tag_id, value in tags.items():
        name = ExifTags.TAGS.get(tag_id)
        if name in EXIF_TAGS:
            safe = _json_safe(value)
            if safe is not None:
                result[name] = safe
    return result


def capture_date_from_exif(exif: dict) -> dt.date | None:
    """DATE part of EXIF DateTimeOriginal ('YYYY:MM:DD HH:MM:SS'). EXIF has no timezone,
    so we keep only the date (trap #12). Returns None if missing or malformed."""
    value = exif.get("DateTimeOriginal")
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value[:10], "%Y:%m:%d").date()
    except ValueError:
        return None
