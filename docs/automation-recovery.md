# Automated Scraper Recovery

The scraper uses deterministic safety rules first. External supervisors may inspect the JSON report and communicate a diagnosis, but they must not bypass database safeguards or modify code automatically.

## Runtime Flow

1. Run a sample health check for every portal.
2. Retry technical failures once with a delay.
3. Run the full scrape only for portals that pass health.
4. Retry a failed full scrape once.
5. Write only successful scraper results to PostgreSQL.
6. Preserve the previous portal snapshot when its process fails.
7. Export the current PostgreSQL state to Google Sheets.
8. Write a JSON report under `runtime/scraper-runs/`.

Listing volume is not a failure criterion for a successful full scrape: a portal
may legitimately publish 20 listings today and 2,000 tomorrow. Health probes
are intentionally stricter: a zero-result sample fails health because it cannot
prove that extraction is working. Technical execution status, not inventory
size, controls full-run retries and writes. A missing or malformed
`SCRAPER_RESULT` marker is always a technical failure.

The report directory is ignored by Git so operational history does not create repository changes. A maintenance session can inspect the reports, fix a portal in a branch, run tests, and merge the fix through the normal pull request flow.
