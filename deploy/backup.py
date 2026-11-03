"""Daily application snapshot; SQLite uses its online backup API."""
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

source = Path('/var/lib/imageeval')
backups = Path('/opt/imageeval/backups')
backups.mkdir(parents=True, exist_ok=True)
name = 'imageeval-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.tar.gz'
with tempfile.TemporaryDirectory() as temp:
    database = Path(temp) / 'imageeval.db'
    with sqlite3.connect(source / 'imageeval.db') as live, sqlite3.connect(database) as snapshot:
        live.backup(snapshot)
    pending = backups / (name + '.partial')
    with tarfile.open(pending, 'w:gz') as archive:
        archive.add(database, arcname='imageeval.db')
        for entry in source.iterdir():
            if not entry.name.startswith('imageeval.db'):
                archive.add(entry, arcname=entry.name)
    pending.replace(backups / name)
for old in sorted(backups.glob('imageeval-*.tar.gz'))[:-7]:
    old.unlink()
print(name)
