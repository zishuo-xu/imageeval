from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx

from .config import AppConfig
from .db import Database
from .storage import ensure_data_dirs, make_thumbnail, validate_image

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@dataclass
class ImportResult:
    batch_id: str
    imported: int
    rejected: int
    report: list[dict]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row_no, row in enumerate(csv.DictReader(fh), start=2):
                yield row_no, dict(row)
        return
    if suffix in (".jsonl", ".ndjson"):
        for row_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("row must be a JSON object")
                yield row_no, row
            except Exception as exc:
                yield row_no, {"__error__": str(exc)}
        return
    raise ValueError(f"unsupported file type: {path.suffix}")


def _parse_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in str(value).replace("，", ";").split(";") if part.strip()]


def _parse_metadata(value: Any) -> dict:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")
    return parsed


def _safe_suffix(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return suffix if suffix in ALLOWED_SUFFIXES else ".png"


def _prepare_image(
    image: str,
    batch_id: str,
    cfg: AppConfig,
    base_dir: Path,
    download: bool,
) -> Path:
    target_dir = cfg.images_dir / batch_id
    target_dir.mkdir(parents=True, exist_ok=True)

    if image.startswith(("http://", "https://")):
        if not download:
            raise ValueError("URL image requires download=true")
        response = httpx.get(image, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        content = response.content
        suffix = _safe_suffix(urlparse(image).path)
    else:
        source = Path(image)
        if not source.is_absolute():
            source = base_dir / source
        source = source.expanduser().resolve()
        if not source.exists():
            raise ValueError(f"image not found: {image}")
        content = source.read_bytes()
        suffix = _safe_suffix(source.name)

    digest = hashlib.sha256(content).hexdigest()[:12]
    destination = target_dir / f"{digest}{suffix}"
    if not destination.exists():
        destination.write_bytes(content)
    try:
        validate_image(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def import_file(
    db: Database,
    cfg: AppConfig,
    source_path: Path,
    image_root: Path | None = None,
    download: bool = False,
    *,
    source_name: str | None = None,
) -> ImportResult:
    ensure_data_dirs(cfg)
    source_path = Path(source_path)
    batch_id = str(uuid.uuid4())
    base_dir = Path(image_root).expanduser().resolve() if image_root else source_path.parent.resolve()
    now = utcnow()

    rows = list(_iter_rows(source_path))

    db.execute(
        "INSERT INTO import_batches (id, source_name, created_at, sample_count, rejected_count, report_json) "
        "VALUES (?, ?, ?, 0, 0, '[]')",
        (batch_id, source_name or source_path.name, now),
    )

    imported = 0
    rejected = 0
    report: list[dict] = []
    seen: set[str] = set()

    for row_no, row in rows:
        try:
            if "__error__" in row:
                raise ValueError(row["__error__"])
            external_id = str(row.get("external_id") or "").strip()
            query = str(row.get("query") or "").strip()
            image = str(row.get("image") or "").strip()
            if not external_id:
                raise ValueError("external_id is required")
            if external_id in seen:
                raise ValueError(f"duplicate external_id: {external_id}")
            if not query:
                raise ValueError("query is required")
            if not image:
                raise ValueError("image is required")

            destination = _prepare_image(image, batch_id, cfg, base_dir, download)
            width, height = validate_image(destination)
            image_rel = destination.relative_to(cfg.images_dir).as_posix()
            thumb_rel = f"{batch_id}/{destination.stem}.jpg"
            make_thumbnail(destination, cfg.thumbs_dir / thumb_rel)

            db.execute(
                "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, thumb_path, "
                "ref_image_path, model_name, width, height, tags_json, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    batch_id,
                    external_id,
                    query,
                    image_rel,
                    thumb_rel,
                    str(row.get("ref_image") or "").strip() or None,
                    str(row.get("model_name") or "").strip() or None,
                    width,
                    height,
                    json.dumps(_parse_tags(row.get("tags")), ensure_ascii=False),
                    json.dumps(_parse_metadata(row.get("metadata")), ensure_ascii=False),
                    now,
                ),
            )
            seen.add(external_id)
            imported += 1
        except Exception as exc:
            rejected += 1
            report.append(
                {
                    "row": row_no,
                    "external_id": str(row.get("external_id") or ""),
                    "error": str(exc),
                }
            )

    if imported == 0 and rejected == 0:
        db.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
        raise ValueError("no rows found in file")

    db.execute(
        "UPDATE import_batches SET sample_count = ?, rejected_count = ?, report_json = ? WHERE id = ?",
        (imported, rejected, json.dumps(report, ensure_ascii=False), batch_id),
    )
    return ImportResult(batch_id=batch_id, imported=imported, rejected=rejected, report=report)
