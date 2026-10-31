import pytest

from imageeval.rubric.loader import AESTHETICS_KEYS, QUALITY_KEYS, load_rubric


def test_load_v1_rubric() -> None:
    rubric = load_rubric()
    assert rubric.version == "v1"
    assert set(rubric.dimension_weights) == {"adherence", "quality", "aesthetics"}
    assert sum(rubric.dimension_weights.values()) == pytest.approx(1.0)
    assert set(rubric.subscore_weights["quality"]) == set(QUALITY_KEYS)
    assert set(rubric.subscore_weights["aesthetics"]) == set(AESTHETICS_KEYS)
    assert sum(rubric.subscore_weights["quality"].values()) == pytest.approx(1.0)
    assert set(rubric.anchors) == {1, 2, 3, 4, 5}


def test_invalid_weights_rejected(tmp_path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
version: bad
anchors:
  1: a
  2: b
  3: c
  4: d
  5: e
dimensions:
  adherence: {weight: 0.5}
  quality: {weight: 0.5, subscores: {clarity: 1.0}}
  aesthetics: {weight: 0.5, subscores: {composition: 1.0}}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_rubric(path)
