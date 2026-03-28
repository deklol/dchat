from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from PIL import Image, UnidentifiedImageError

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif"}
ALLOWED_IMAGE_FORMATS = {
    "PNG": {".png"},
    "JPEG": {".jpg", ".jpeg"},
    "GIF": {".gif"},
}


def sanitize_original_name(filename: str) -> str:
    base_name = Path(filename or "").name.strip()
    return (base_name or "upload").replace("\x00", "")[:255]


@deconstructible
class SanitizedUploadPath:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def __call__(self, _instance, filename: str) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            suffix = ".bin"
        if suffix == ".jpeg":
            suffix = ".jpg"
        stamp = datetime.utcnow().strftime("%Y/%m")
        return f"{self.prefix}/{stamp}/{uuid4().hex}{suffix}"


def sanitized_upload_path(prefix: str):
    return SanitizedUploadPath(prefix)


def validate_uploaded_image(file, *, max_bytes: int, max_mb: int):
    safe_name = sanitize_original_name(getattr(file, "name", "upload"))
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Only PNG, JPG/JPEG, and GIF files are allowed.")
    if getattr(file, "size", 0) > max_bytes:
        raise ValidationError(f"Max upload size is {max_mb} MB.")

    try:
        current_position = file.tell()
    except (AttributeError, OSError):
        current_position = 0

    try:
        file.seek(0)
        image = Image.open(file)
        detected_format = (image.format or "").upper()
        image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ValidationError("Upload must be a valid PNG, JPG/JPEG, or GIF image.")
    finally:
        try:
            file.seek(current_position)
        except (AttributeError, OSError):
            pass

    allowed_suffixes = ALLOWED_IMAGE_FORMATS.get(detected_format)
    if not allowed_suffixes or suffix not in allowed_suffixes:
        raise ValidationError("File extension does not match the uploaded image format.")
    return file
