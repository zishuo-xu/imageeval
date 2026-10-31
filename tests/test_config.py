from pathlib import Path

from imageeval.config import DEFAULT_RUBRIC, load_config


def test_load_config_reads_all_sections(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[server]
host = "0.0.0.0"
port = 9000

[judge]
base_url = "http://example.test/v1"
model = "vision-test"
api_key_env = "MY_TEST_KEY"
temperature = 0.3
image_max_edge = 1024

[pipeline]
max_concurrency = 2
rpm = 30
max_retries = 2

[reviewer]
default_name = "alice"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_TEST_KEY", "secret")

    cfg = load_config(cfg_file, data_dir=tmp_path / "data")

    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.db_path == tmp_path / "data" / "imageeval.db"
    assert cfg.judge.model == "vision-test"
    assert cfg.judge.temperature == 0.3
    assert cfg.judge.image_max_edge == 1024
    assert cfg.pipeline.max_concurrency == 2
    assert cfg.pipeline.rpm == 30
    assert cfg.reviewer_name == "alice"
    assert cfg.api_key() == "secret"


def test_defaults_without_config_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("IMAGEEVAL_API_KEY", raising=False)
    cfg = load_config(None, data_dir=tmp_path)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765
    assert cfg.rubric_path == DEFAULT_RUBRIC
    assert cfg.reviewer_name == "local"
    assert cfg.api_key() is None
