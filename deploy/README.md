# Server deployment

Entry: http://47.107.187.18:8878/ (HTTP, browser username/password login).
The backend listens only on 127.0.0.1:8877. Caddy protects all pages, images,
exports and API routes. HTTP does not encrypt login credentials or content;
use a trusted network, or add HTTPS before sharing across untrusted networks.
The existing port 80 redirect to SnapKcal is unchanged.

- Code: `/opt/imageeval/releases/20261102-strict-final`, symlink `/opt/imageeval/current`.
- Runtime: Python 3.14, frozen `uv.lock`, installed wheel including web assets.
- Config: `/etc/imageeval/config.toml`.
- Model credentials: `/etc/imageeval/runtime.env` (root-only, loaded by systemd).
- Login hash: `/etc/imageeval/web.env` (root-only; do not shell-source bcrypt hashes).
- Data: `/var/lib/imageeval`, owned by the dedicated `imageeval` service user.
- Caddy: Ubuntu security-maintained package binary under `/opt/imageeval/caddy`.
- Model smoke test: `/opt/imageeval/verification`, separate from production jobs.

```sh
ssh aliyun 'systemctl status imageeval imageeval-web --no-pager'
ssh aliyun 'journalctl -u imageeval -n 100 --no-pager'
ssh aliyun 'systemctl restart imageeval'
```

The application uses in-process job execution: restarting during generation or
scoring interrupts that work. Finish active jobs before updating/restarting.
For a new release, upload source into a new release directory, install with
`uv sync --frozen --no-dev --no-editable`, run a backup, switch `current`, and
restart the application. Retain the previous release for rollback. Frontend
files are installed into the wheel, so rebuild/reinstall for frontend changes.

## Backup and restore

`imageeval-backup.timer` runs daily at 04:15 Asia/Shanghai; keeps the last seven
archives under `/opt/imageeval/backups`. SQLite is captured via its backup API.
Backups are on the same server, not an off-site disaster recovery copy.

Run manually: `systemctl start imageeval-backup`.
To restore, stop `imageeval`, preserve the existing data directory, extract a
chosen archive into a fresh `/var/lib/imageeval`, set owner `imageeval:imageeval`,
and start the service. Do not unpack over a live database or leave old WAL files.

The initial deployment copied local history via SQLite's backup API; no local
model credentials or data files are committed to Git. Login details are delivered
separately and must not be added to this directory.

## Strict rating policy

`strict-v1` requires an explicit delivery decision and outstanding evidence for the top category. Required edits cap the rating; partial explicit requirements cannot be rated satisfied. Model explanations must point to visible evidence and must not invent defects in occluded regions. Each run records the rating policy, prompt hash, JSON mode, and output token limit.

The connected DeepSeek judge uses JSON Object mode and a 32768-token output budget, with a 240-second request timeout. This budget includes reasoning and avoids the observed truncation at 8192. Configuration is kept in `/etc/imageeval/config.toml`. Other providers must support JSON Object mode before enabling `json_mode`.
