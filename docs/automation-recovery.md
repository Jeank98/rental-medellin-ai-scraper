# Automated Scraper Recovery

The scheduled scraper uses deterministic safety rules first. Hermes may inspect the JSON report and communicate a diagnosis, but it must not bypass the database safeguards or modify code automatically.

The single Hermes cron runs once daily at 02:00 Medellin time. Hermes schedules use UTC, so the configured expression is `0 7 * * *`. Replace the existing scraper job when updating it; do not create a second cron.

## Runtime Flow

1. Run a sample health check for every portal.
2. Retry technical failures once with a delay.
3. Run the full scrape only for portals that pass health.
4. Retry a failed full scrape once.
5. Write only successful scraper results to PostgreSQL.
6. Preserve the previous portal snapshot when its process fails.
7. Export the current PostgreSQL state to Google Sheets.
8. Write a JSON report under `runtime/scraper-runs/`.

Listing volume is not a failure criterion. A portal may legitimately publish 20 listings today and 2,000 tomorrow. Technical execution status, not inventory size, controls retries and writes.

## Hermes Workflow

Hermes should run the normal command and inspect the latest JSON report:

```text
Run `uv run python scripts/run_all.py --workers 18`.
Read the newest file under `runtime/scraper-runs/`.
If a portal failed, report its attempts, error, and whether its previous DB snapshot was preserved.
Do not edit source code, force a database write, or rerun a failed portal outside the retry policy.
```

The report directory is ignored by Git so the phone can retain operational history without creating repository changes. A future maintenance session can inspect the reports, fix a portal in a branch, run tests, and merge the fix through the normal pull request flow.

## Termux Supervisor

Android does not provide a system service manager inside the Ubuntu proot, so Hermes' service installer cannot install the gateway there. The phone uses one persisted Termux job, running every 15 minutes, to start the gateway when it is not running and to check battery status. This is separate from Hermes cron; Hermes still has exactly one scraper cron.

The supervisor sends one notification below 25% battery and rearms after the battery reaches 30%:

```text
termux-job-scheduler --job-id 170214 --script /path/to/termux_supervisor.sh --period-ms 900000 --persisted true --battery-not-low false
```
