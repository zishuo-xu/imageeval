from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_RUBRIC_PATH = Path(__file__).parent / "v1.yaml"

QUALITY_KEYS = ("clarity", "artifacts", "text_render", "physics", "consistency")
AESTHETICS_KEYS = ("composition", "color", "lighting", "texture", "appeal")
DIMENSION_KEYS = ("adherence", "quality", "aesthetics")


@dataclass(frozen=True)
class Rubric:
    version: str
    anchors: dict[int, str]
    dimension_weights: dict[str, float]
    subscore_weights: dict[str, dict[str, float]]


def _check_sum(weights: dict[str, float], label: str) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{label} weights must sum to 1.0, got {total}")


def load_rubric(path: Path | None = None) -> Rubric:
    path = Path(path) if path is not None else DEFAULT_RUBRIC_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rubric must be a mapping")

    version = str(data.get("version", "")).strip()
    if not version:
        raise ValueError("rubric.version is required")

    anchors = {int(k): str(v) for k, v in (data.get("anchors") or {}).items()}
    if set(anchors) != {1, 2, 3, 4, 5}:
        raise ValueError("rubric.anchors must define keys 1..5")

    dims = data.get("dimensions") or {}
    if set(dims) != set(DIMENSION_KEYS):
        raise ValueError(f"rubric.dimensions must be {DIMENSION_KEYS}")

    dimension_weights = {key: float(dims[key]["weight"]) for key in DIMENSION_KEYS}
    _check_sum(dimension_weights, "dimension")

    subscore_weights: dict[str, dict[str, float]] = {}
    for dim, expected in (("quality", QUALITY_KEYS), ("aesthetics", AESTHETICS_KEYS)):
        raw = dims[dim].get("subscores") or {}
        weights = {str(k): float(v) for k, v in raw.items()}
        if set(weights) != set(expected):
            raise ValueError(f"{dim} subscores must be {expected}")
        _check_sum(weights, dim)
        subscore_weights[dim] = weights

    return Rubric(
        version=version,
        anchors=anchors,
        dimension_weights=dimension_weights,
        subscore_weights=subscore_weights,
    )
