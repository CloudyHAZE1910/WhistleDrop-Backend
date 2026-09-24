"""Validation and privacy-cleaning of uploaded evidence images."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_FILES_PER_REPORT = 3

# Reject absurdly large images (decompression bombs) instead of eating all memory.
Image.MAX_IMAGE_PIXELS = 25_000_000


class InvalidEvidence(ValueError):
    pass


def sanitize_image(data: bytes) -> tuple[bytes, str]:
    """Check that `data` is a real PNG or JPEG and return (clean_bytes, content_type).

    Photos often contain hidden metadata: GPS position, camera model, timestamps.
    That could identify the reporter. So the image is rebuilt from its raw pixels only,
    which drops every piece of metadata.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            image_format = img.format
            if image_format not in ("PNG", "JPEG"):
                raise InvalidEvidence("Only PNG and JPEG images are accepted.")

            img = ImageOps.exif_transpose(img)  # keep the picture upright before metadata is dropped
            if image_format == "JPEG":
                pixels = img.convert("RGB")
                out_format, content_type = "JPEG", "image/jpeg"
            else:
                pixels = img.convert("RGBA")
                out_format, content_type = "PNG", "image/png"

            clean = Image.frombytes(pixels.mode, pixels.size, pixels.tobytes())
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise InvalidEvidence("The file is not a valid PNG or JPEG image.") from exc

    out = io.BytesIO()
    save_options = {"quality": 90} if out_format == "JPEG" else {}
    clean.save(out, format=out_format, **save_options)
    return out.getvalue(), content_type
