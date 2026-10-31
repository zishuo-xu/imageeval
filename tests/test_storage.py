import base64
import io

import pytest
from PIL import Image

from imageeval.storage import (
    downscale_bytes,
    image_data_url,
    make_thumbnail,
    resolve_under,
    validate_image,
)


def test_validate_image_returns_size(make_image) -> None:
    path = make_image("a.png", (300, 200))
    assert validate_image(path) == (300, 200)


def test_validate_image_rejects_text(tmp_path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(ValueError, match="invalid image"):
        validate_image(bad)


def test_resolve_under_rejects_traversal(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.png").write_bytes(b"x")
    assert resolve_under(root, "ok.png") == (root / "ok.png").resolve()
    with pytest.raises(ValueError):
        resolve_under(root, "../escape.png")


def test_make_thumbnail_limits_edge(make_image, tmp_path) -> None:
    src = make_image("big.png", (2000, 1000))
    dst = tmp_path / "thumb.jpg"
    make_thumbnail(src, dst, max_edge=480)
    with Image.open(dst) as im:
        assert max(im.size) == 480


def test_downscale_bytes_and_data_url(make_image) -> None:
    src = make_image("wide.png", (2000, 1000))
    data, mime = downscale_bytes(src, 640)
    assert mime in {"image/jpeg", "image/png"}
    with Image.open(io.BytesIO(data)) as im:
        assert max(im.size) == 640

    url = image_data_url(src, 640)
    assert url.startswith("data:image/")
    assert ";base64," in url
    raw = base64.b64decode(url.split(",", 1)[1])
    assert len(raw) > 100
