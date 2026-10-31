import json

from imageeval.importer import import_file


def test_import_csv_with_bad_row(db, cfg, make_image, tmp_path) -> None:
    img1 = make_image("one.png", (100, 80))
    img2 = make_image("two.png", (120, 90))
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "external_id,query,image,model_name,tags\n"
        f"a1,一只红猫,{img1.name},m1,tag1;tag2\n"
        "a2,坏图,missing.png,m1,\n"
        f"a3,一只蓝狗,{img2.name},m1,\n",
        encoding="utf-8",
    )

    result = import_file(db, cfg, csv_path)

    assert result.imported == 2
    assert result.rejected == 1
    assert result.report[0]["external_id"] == "a2"
    rows = db.query("SELECT * FROM samples WHERE batch_id = ? ORDER BY external_id", (result.batch_id,))
    assert [row["external_id"] for row in rows] == ["a1", "a3"]
    assert json.loads(rows[0]["tags_json"]) == ["tag1", "tag2"]
    assert (cfg.images_dir / rows[0]["image_path"]).exists()
    assert (cfg.thumbs_dir / rows[0]["thumb_path"]).exists()


def test_import_jsonl_and_duplicate_id(db, cfg, make_image, tmp_path) -> None:
    img = make_image("dup.png", (50, 50))
    jsonl = tmp_path / "data.jsonl"
    rows = [
        {"external_id": "x", "query": "q1", "image": img.name},
        {"external_id": "x", "query": "q2", "image": img.name},
    ]
    jsonl.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    result = import_file(db, cfg, jsonl)

    assert result.imported == 1
    assert result.rejected == 1
    assert "duplicate" in result.report[0]["error"]


def test_import_requires_rows(db, cfg, tmp_path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("external_id,query,image\n", encoding="utf-8")
    try:
        import_file(db, cfg, empty)
    except ValueError as exc:
        assert "no rows" in str(exc)
    else:
        raise AssertionError("expected ValueError")
