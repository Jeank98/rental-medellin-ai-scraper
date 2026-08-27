# Scraper Operations Runbook

Use the production scripts for routine runs. They provide health checks, retry
technical failures, city-scoped database replacement, a pre-write backup, and a
JSON execution report. This runbook does not replace the per-portal field
mappings in `reference/portals/`.

## Quick path

```bash
uv sync
uv run python scripts/check_runtime.py
uv run python scripts/run_all.py --workers 4 --ciudad medellin
```

Inspect the printed report and the newest JSON file under
`runtime/scraper-runs/` before sharing the Sheets URL. The runtime check only
imports dependencies; it does not read `.env` or contact a service.

## Normal and fail-fast runs

| Command | Use when |
|---|---|
| `uv run python scripts/run_all.py --workers 4` | Normal run: collect every portal result, then validate. |
| `uv run python scripts/run_all.py --workers 4 --fail-fast` | Stop scheduling after the first technical failure. A health failure aborts before backup/scrape; a scrape failure skips Sheets. |
| `uv run python scripts/run_all.py --skip-backup` | Only when an operator intentionally accepts no pre-write backup. The report records `SKIPPED`. |
| `uv run python scripts/run_all.py --skip-health` | Controlled maintenance run when health probes are unavailable. |
| `uv run python scripts/run_all.py --skip-sheet` | DB-only run; the report records that Sheets was skipped. |

Add `--ciudad CITY` for another city and `--report-dir DIR` to choose a report
location. Use a per-portal script with `--sample-only` for a bounded diagnostic;
sample mode never writes CSV, DB, or Sheets.

## Phase and failure matrix

| Phase | Success | Failure or skip | Downstream effect |
|---|---|---|---|
| Health | Portal emits `SCRAPER_RESULT` with `status=success` and a positive listing count. | Missing/malformed marker, process error, or zero listings fails that portal. | Normal mode validates the warning and continues healthy portals. Fail-fast stops before backup. |
| Backup | `status=success` and a `.sql` path. | `status=failed` means `pg_dump` did not complete. `status=skipped` is explicit operator/configuration choice. | A required backup failure blocks all scraper DB writes and Sheets, returns exit 1, and renders `BACKUP: FAILED`. |
| Scrape | Each process emits one structured result marker. | Process error, failed marker, or missing marker. | DB writer preserves the prior portal snapshot on a failed atomic replacement. Fail-fast skips Sheets. |
| Validation | No technical warnings. | Health, scrape, backup, or Sheets warning. | Exit status is 1; inspect report before retrying. |
| Sheets | Active DB rows pass city, price, and type filters and are written. | OAuth, database, API, or permission failure. | Validation fails; retry only after inspecting the error. |
| Report | Console report and timestamped JSON are written. | A report write error is itself a failed run. | Preserve the console output and repair the report directory before rerunning. |

A low listing count is not a failure by itself after a successful marker. A
zero-result health probe is intentionally stricter: it fails health because a
healthy portal sample must prove that extraction returned data.

## Backup and restore

Backups are written by `pg_dump` to `~/Projects/Backups` by default, with names
such as `rental_scraper_YYYYMMDD_HHMMSS.sql`. The JSON report keeps the legacy
`backup_path` field and also records `backup.status`, `backup.path`,
`backup.error`, and `backup.reason`.

Before a restore, stop writes and verify the target database URL. A typical
operator restore is:

```bash
psql "$DATABASE_URL" --file ~/Projects/Backups/rental_scraper_YYYYMMDD_HHMMSS.sql
```

Never restore over production data without confirming the file, destination,
and a rollback plan. A failed backup is not equivalent to an intentional
`--skip-backup`; do not proceed with scraper writes until the failure is
understood or the operator explicitly chooses the skip flag.

## Reports and structured results

Each portal CLI emits exactly one stdout line beginning with
`SCRAPER_RESULT ` followed by JSON containing `portal`, `status`, and
`listings`; failed runs may include `error`. The orchestrator parses this line,
not human-readable `Sample:` or `Scraped` wording. Missing or malformed JSON is
an explicit execution failure.

Reports are timestamped under `runtime/scraper-runs/` (ignored by Git):

```bash
python -m json.tool runtime/scraper-runs/scrape_*.json
```

Prefer the newest file whose `created_at` is closest to the run. Check
`validation.warnings`, `backup`, and `sheet` before diagnosing individual
portals.

## Sheets and OAuth recovery

Sheets is a live mirror of the database's **active** rows only. The export also
requires the requested city (case-insensitive), `precio >= 200000`, and an
allowed residential `tipo` (`apartamento`, `apto`, `casa`, `casa-finca`, or
`casa unifamiliar`). Inactive or delisted DB rows remain available for history
but are not exported.

If OAuth fails, confirm `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` without
printing their values, then remove or re-authorize the token at
`~/.config/gworkspace-tools/token.json` as appropriate. Confirm the target
`GOOGLE_SHEET_ID` permissions. A DB or Sheets failure must be visible in the
report before retrying; do not manually edit the mirror as a recovery shortcut.

## Zero-result policy

- **Sample/health mode:** zero listings or a missing/malformed structured
  marker is a failure (`SystemExit(2)` for a direct zero-row CLI; health marks
  the portal unhealthy). No output writers run.
- **Full scraper mode:** a successful structured marker may report a low but
  nonzero count. A failed marker, missing marker, process error, or DB write
  error fails the portal and preserves its previous DB snapshot.
- **Pipeline:** health and scrape technical failures are validated according to
  the selected fail-fast mode. A required backup failure always blocks DB and
  Sheets writes regardless of fail-fast mode.
