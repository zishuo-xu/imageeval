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

    run_parser = subparsers.add_parser("run", help="执行一次评测")
    group = run_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", default=None)
    group.add_argument("--new", action="store_true")
    run_parser.add_argument("--batch-id", default=None)
    run_parser.add_argument("--name", default="CLI run")

    subparsers.add_parser("serve", help="启动本地 Web 服务")

    args = parser.parse_args(argv)
    cfg = load_config(args.config, args.data_dir)

    import asyncio

    from .judge import build_provider
    from .pipeline import execute_run
    from .rubric.loader import load_rubric
    from .runs import create_run

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

    if args.command == "run":
        db = Database(cfg.db_path)
        migrate(db.conn)
        rubric = load_rubric(cfg.rubric_path)
        if args.new:
            if not args.batch_id:
                parser.error("--new requires --batch-id")
            run_id = create_run(db, cfg, rubric, args.batch_id, args.name)
        else:
            run_id = args.run_id
        provider = build_provider(cfg, rubric)
        asyncio.run(execute_run(db, cfg, provider, rubric, run_id))
        run = db.query_one("SELECT status, done, failed, total FROM runs WHERE id = ?", (run_id,))
        print(json.dumps(dict(run), ensure_ascii=False))
        db.close()
        return 0

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
