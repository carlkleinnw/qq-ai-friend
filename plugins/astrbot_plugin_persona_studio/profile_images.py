"""Validate uploaded local-display avatars; never upload to QQ or accept SVG."""
import base64
import binascii
from io import BytesIO
import re
import warnings

MAX_UPLOAD = 2 * 1024 * 1024
PREFIX = 'data:image/png;base64,'


def normalize_avatar(value):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not isinstance(value, str) or len(value) > (MAX_UPLOAD * 4 // 3 + 200):
        raise ValueError('头像文件不得超过 2 MB。')
    match = re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise ValueError('请上传 PNG、JPEG 或 WebP 图片，不支持 SVG 或其他文件。')
    try:
        content = base64.b64decode(match[1], validate=True)
        if len(content) > MAX_UPLOAD:
            raise ValueError('头像文件不得超过 2 MB。')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or getattr(image, 'is_animated', False):
                    raise ValueError('请使用静态 PNG、JPEG 或 WebP 图片。')
                if image.width * image.height > 16_000_000:
                    raise ValueError('头像图片不得超过 1600 万像素。')
                image.load()
                image = ImageOps.exif_transpose(image).convert('RGBA')
                image.thumbnail((512, 512))
                output = BytesIO()
                image.save(output, format='PNG')
        return PREFIX + base64.b64encode(output.getvalue()).decode('ascii')
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError('图片无效、损坏或尺寸过大，请更换静态图片。') from None


def local_avatar(record):
    value = record.get('local_avatar_data', '')
    if isinstance(value, str) and len(value) <= 2 * 1024 * 1024 and re.fullmatch(r'data:image/png;base64,[A-Za-z0-9+/=]+', value):
        return value
    return ''
