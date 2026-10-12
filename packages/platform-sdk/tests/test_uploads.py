import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from wasifyai_platform_sdk import (
    InMemoryUploadLimiter,
    InMemoryUploadStore,
    UploadError,
    new_upload,
    process_image,
)


def encode(im: Image.Image, fmt: str, **kw) -> bytes:
    out = io.BytesIO()
    im.save(out, fmt, **kw)
    return out.getvalue()


def exif_with_gps_and_orientation(orientation: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = orientation  # orientation
    exif[0x010F] = "SecretCameraMaker"  # make
    exif[0x0132] = "2026:10:08 12:00:00"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (48.0, 51.0, 24.0), "E", (2.0, 21.0, 8.0)
    return exif


def opened(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_a_photo_comes_back_as_a_clean_png_with_no_metadata():
    photo = Image.new("RGB", (300, 200), (200, 30, 30))
    jpeg = encode(photo, "JPEG", exif=exif_with_gps_and_orientation(), icc_profile=b"profile-bytes")
    assert b"SecretCameraMaker" in jpeg  # the original really does carry it
    out = process_image(jpeg)
    assert out.png[:8] == b"\x89PNG\r\n\x1a\n" and (out.width, out.height) == (300, 200)
    assert b"SecretCameraMaker" not in out.png and b"Exif" not in out.png
    im = opened(out.png)
    assert im.format == "PNG" and not im.getexif() and "icc_profile" not in im.info
    assert {k for k in im.info} <= {"dpi", "gamma"}  # nothing identifying


@pytest.mark.parametrize(
    ("orientation", "size"), [(1, (100, 50)), (6, (50, 100)), (8, (50, 100)), (3, (100, 50))]
)
def test_the_exif_rotation_is_applied_before_the_tag_is_dropped(orientation, size):
    jpeg = encode(
        Image.new("RGB", (100, 50)), "JPEG", exif=exif_with_gps_and_orientation(orientation)
    )
    out = process_image(jpeg)
    assert (out.width, out.height) == size


def test_large_pictures_are_scaled_down_keeping_their_shape():
    out = process_image(encode(Image.new("RGB", (4000, 3000), (1, 2, 3)), "PNG"))
    assert max(out.width, out.height) == 2048 and (out.width, out.height) == (2048, 1536)
    out = process_image(encode(Image.new("RGB", (400, 300)), "PNG"), max_side=100)
    assert (out.width, out.height) == (100, 75)


def test_transparency_is_flattened_onto_white_not_black():
    rgba = Image.new("RGBA", (10, 10), (255, 0, 0, 0))  # fully transparent red
    px = opened(process_image(encode(rgba, "PNG")).png).convert("RGB").getpixel((5, 5))
    assert px == (255, 255, 255)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_png_jpeg_and_webp_are_accepted(fmt):
    assert process_image(encode(Image.new("RGB", (32, 32), (9, 9, 9)), fmt)).width == 32


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (encode(Image.new("P", (8, 8)), "GIF"), 415),
        (encode(Image.new("RGB", (8, 8)), "BMP"), 415),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", 422),
        (b"%PDF-1.7 not an image", 422),
        (b"plain text", 422),
        (b"", 422),
        (encode(Image.new("RGB", (64, 64), (5, 5, 5)), "JPEG")[:200], 422),  # truncated
    ],
)
def test_anything_that_is_not_a_plain_image_is_refused(data, status):
    with pytest.raises(UploadError) as caught:
        process_image(data)
    assert caught.value.status == status and caught.value.message


def test_a_picture_with_too_many_pixels_is_refused_before_it_is_decoded():
    big = encode(Image.new("1", (6000, 5000)), "PNG")  # small file, 30 megapixels
    with pytest.raises(UploadError) as caught:
        process_image(big)
    assert caught.value.status == 422 and "pixels" in caught.value.message


async def test_the_limiter_counts_per_user_per_hour():
    now = [1_000_000.0]
    limiter = InMemoryUploadLimiter(per_hour=2, clock=lambda: now[0])
    assert [await limiter.allow("t", "ann") for _ in range(3)] == [True, True, False]
    assert await limiter.allow("t", "bob")  # another user is not affected
    assert await limiter.allow("other", "ann")  # nor another tenant
    now[0] += 3600
    assert await limiter.allow("t", "ann")  # a new hour


async def test_the_store_finds_only_the_owners_unused_upload_and_forgets_it_when_used():
    store = InMemoryUploadStore()
    up = new_upload("t", "p", "ann", 123)
    assert up.key == f"uploads/{up.id}.png"
    await store.add(up)
    assert await store.find("t", "p", "ann", up.key) is not None
    for other in [("t", "p", "bob"), ("t", "q", "ann"), ("x", "p", "ann")]:
        assert await store.find(*other, up.key) is None  # someone else's key finds nothing
    found = await store.find("t", "p", "ann", up.key)
    assert found
    await store.consume(found)
    assert await store.find("t", "p", "ann", up.key) is None


async def test_only_uploads_older_than_a_day_count_as_expired():
    store = InMemoryUploadStore()
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    old, fresh = new_upload("t", "p", "ann", 1), new_upload("t", "p", "ann", 1)
    await store.add(old)
    await store.add(fresh)
    store.rows[old.id] = store.rows[old.id].__class__(
        **{**store.rows[old.id].__dict__, "created_at": now - timedelta(hours=25)}
    )
    store.rows[fresh.id] = store.rows[fresh.id].__class__(
        **{**store.rows[fresh.id].__dict__, "created_at": now - timedelta(hours=23)}
    )
    assert [u.id for u in await store.expired(now)] == [old.id]
