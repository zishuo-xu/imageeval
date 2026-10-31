from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from .config import AppConfig


def ensure_data_dirs(cfg: AppConfig) -> None:
    for path in (
        cfg.data_dir,
        cfg.images_dir,
        cfg.thumbs_dir,
        cfg.exports_dir,
        cfg.reports_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def resolve_under(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes root: {relative}")
    return target


def validate_image(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return im.size
    except Exception as exc:
        raise ValueError(f"invalid image: {path.name}") from exc


def make_thumbnail(src: Path, dst: Path, max_edge: int = 480) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge))
        im.save(dst, format="JPEG", quality=85)


def downscale_bytes(path: Path, max_edge: int) -> tuple[bytes, str]:
    with Image.open(path) as im:
        has_alpha = im.mode in ("RGBA", "LA") or (
            im.mode == "P" and "transparency" in im.info
        )
        im.thumbnail((max_edge, max_edge))
        buffer = io.BytesIO()
        if has_alpha:
            im.convert("RGBA").save(buffer, format="PNG")
            return buffer.getvalue(), "image/png"
        im.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue(), "image/jpeg"


def image_data_url(path: Path, max_edge: int) -> str:
    data, mime = downscale_bytes(path, max_edge)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
