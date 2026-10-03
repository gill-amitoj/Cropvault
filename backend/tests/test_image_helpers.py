"""Unit tests for app/images.py (no DB, no storage)."""

import io

import pytest
from PIL import ExifTags, Image

from app import images
from tests.conftest import image_bytes


def thumb_of(data):
    return Image.open(io.BytesIO(images.make_thumbnail(images.open_image(data))))


def exif_with(orientation=None, date_taken=None):
    exif = Image.Exif()
    if orientation:
        exif[ExifTags.Base.Orientation] = orientation
    if date_taken:
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = date_taken
    return exif


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "TIFF"])
def test_open_image_accepts_supported_formats(fmt):
    assert images.open_image(image_bytes(fmt)).format == fmt


def test_open_image_rejects_text_pretending_to_be_jpeg():
    with pytest.raises(images.InvalidImage):
        images.open_image(b"this is not an image, just text named leaf.jpg")


def test_open_image_rejects_real_but_unsupported_format():
    with pytest.raises(images.InvalidImage, match="Unsupported image format: GIF"):
        images.open_image(image_bytes("GIF", mode="P", color=1))


def test_open_image_rejects_truncated_jpeg():
    data = image_bytes("JPEG", size=(400, 400))
    with pytest.raises(images.InvalidImage):
        images.open_image(data[: len(data) // 2])


@pytest.mark.parametrize("size", [(40, 40), (100, 100)])  # warning range and error range
def test_open_image_rejects_decompression_bombs(monkeypatch, size):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    data = image_bytes("PNG", size=size)
    with pytest.raises(images.ImageTooLarge):
        images.open_image(data)


def test_thumbnail_is_320_wide_jpeg_with_same_aspect_ratio():
    thumb = thumb_of(image_bytes("PNG", size=(1600, 1200)))
    assert thumb.format == "JPEG"
    assert thumb.size == (320, 240)


def test_small_image_is_not_upscaled():
    assert thumb_of(image_bytes("JPEG", size=(200, 100))).size == (200, 100)


def test_thumbnail_applies_exif_orientation():
    # Stored 400x200 but EXIF says "rotate 90", so it displays as 200x400.
    data = image_bytes("JPEG", size=(400, 200), exif=exif_with(orientation=6))
    img = images.open_image(data)
    assert images.display_size(img) == (200, 400)
    assert thumb_of(data).size == (200, 400)


def test_sixteen_bit_tiff_thumbnail_is_not_washed_out():
    img = Image.new("I;16", (64, 64))
    img.putdata([x * 60 for x in range(64)] * 64)  # values 0..3780, all above 255 except a few
    buffer = io.BytesIO()
    img.save(buffer, "TIFF")
    low, high = thumb_of(buffer.getvalue()).convert("L").getextrema()
    assert low < 20 and high > 235  # full range, not all white


def test_rgba_png_thumbnail_works():
    thumb = thumb_of(image_bytes("PNG", mode="RGBA", color=(0, 0, 0, 0)))
    assert thumb.mode == "RGB"
    assert thumb.getpixel((0, 0)) == (255, 255, 255)  # transparent -> white


def test_extract_exif_keeps_whitelisted_json_safe_tags_and_date():
    data = image_bytes("JPEG", exif=exif_with(orientation=1, date_taken="2026:05:14 10:30:00"))
    exif = images.extract_exif(images.open_image(data))
    assert exif == {"Orientation": 1, "DateTimeOriginal": "2026:05:14 10:30:00"}
    assert str(images.capture_date_from_exif(exif)) == "2026-05-14"


@pytest.mark.parametrize("value", [None, "", "0000:00:00 00:00:00", "garbage", 12])
def test_capture_date_from_bad_exif_is_none(value):
    assert images.capture_date_from_exif({"DateTimeOriginal": value}) is None
