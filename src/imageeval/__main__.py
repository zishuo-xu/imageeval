from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .db import Database, migrate
from .importer import import_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="imageeval")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="导入 CSV/JSONL")
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument("--image-root", type=Path, default=None)
    import_parser.add_argument("--download", action="store_true")

    args = parser.parse_args(argv)
    cfg = load_config(args.config, args.data_dir)

    if args.command == "import":
        db = Database(cfg.db_path)
        migrate(db.conn)
        result = import_file(db, cfg, args.file, args.image_root, args.download)
        print(
            json.dumps(
                {
                    "batch_id": result.batch_id,
                    "imported": result.imported,
                    "rejected": result.rejected,
                    "report": result.report,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        db.close()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
