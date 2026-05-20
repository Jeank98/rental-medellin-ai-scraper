"""
Report formatting module for the scraper orchestrator.
Generates a box-drawn console report summarising health checks,
scrape results, validation, backup, and total elapsed time.
"""

from datetime import datetime


INNER_WIDTH = 50  # content width between box borders
TOTAL_WIDTH = INNER_WIDTH + 2  # including ║ borders


def _status_icon(ok: bool) -> str:
    return "\u2705" if ok else "\u274c"


def _format_time(seconds: float) -> str:
    if seconds < 0:
        return "0s"
    if seconds < 1:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining}s"


def _pad_section(label: str, value: str) -> str:
    """Left-align label, right-align value, padding between them."""
    total_content = len(label) + len(value) + 2  # 2 spaces between
    if total_content >= INNER_WIDTH:
        return f" {label} {value}"
    padding = INNER_WIDTH - total_content
    return f" {label}{' ' * (padding + 1)}{value}"


def _border_line(left: str, mid: str, right: str) -> str:
    return f"{left}{mid * INNER_WIDTH}{right}"


def _top_border() -> str:
    return _border_line("\u2554", "\u2550", "\u2557")


def _bot_border() -> str:
    return _border_line("\u255a", "\u2550", "\u255d")


def _sep_border() -> str:
    return _border_line("\u2560", "\u2550", "\u2563")


def _content_line(text: str) -> str:
    """Wrap text in vertical box borders, centering it."""
    available = INNER_WIDTH - 2  # 1 space padding each side
    if len(text) > available:
        text = text[:available]
    left_pad = (INNER_WIDTH - len(text)) // 2
    right_pad = INNER_WIDTH - len(text) - left_pad
    return f"\u2551{' ' * left_pad}{text}{' ' * right_pad}\u2551"


def _section_header(title: str) -> str:
    return _content_line(title)


def _result_line(healthy: bool, portal: str, detail: str) -> str:
    icon = _status_icon(healthy)
    portal_text = f"{icon} {portal}"
    inner = _pad_section(portal_text, detail)
    return f"\u2551{inner}\u2551"


def _generate_health_section(health_results: list[dict]) -> list[str]:
    lines: list[str] = []
    lines.append(_sep_border())
    lines.append(_section_header("HEALTH CHECK"))
    if not health_results:
        lines.append(_content_line("(no portals checked)"))
        return lines
    for r in health_results:
        portal = r.get("portal", "?")
        ok = r.get("healthy", False)
        listings = r.get("listings", 0)
        elapsed = r.get("elapsed", 0.0)
        error = r.get("error")
        if ok:
            detail = f"{listings} listings    {_format_time(elapsed)}"
        else:
            detail = f"({error or 'timeout'})       -"
        lines.append(_result_line(ok, portal, detail))
    return lines


def _generate_scrape_section(scrape_results: list[dict]) -> list[str]:
    lines: list[str] = []
    lines.append(_sep_border())
    lines.append(_section_header("SCRAPE RESULTS"))
    if not scrape_results:
        lines.append(_content_line("(no portals scraped)"))
        return lines
    for r in scrape_results:
        portal = r.get("portal", "?")
        ok = r.get("success", False)
        listings = r.get("listings", 0)
        elapsed = r.get("elapsed", 0.0)
        error = r.get("error")
        if ok:
            detail = f"{listings} listings    {_format_time(elapsed)}"
        else:
            detail = f"({error or 'failed'})"
        lines.append(_result_line(ok, portal, detail))
    return lines


def _generate_validation_section(validation: dict) -> list[str]:
    lines: list[str] = []
    lines.append(_sep_border())
    passed = validation.get("passed", False)
    status = "PASSED" if passed else "FAILED"
    lines.append(_section_header(f"VALIDATION: {status}"))
    if not passed:
        warnings = validation.get("warnings", [])
        if warnings:
            for w in warnings:
                lines.append(_content_line(w[:INNER_WIDTH]))
        else:
            lines.append(_content_line("(no warnings)"))
    return lines


def _generate_summary_section(
    backup_path: str | None,
    scrape_results: list[dict],
    total_time: float,
) -> list[str]:
    lines: list[str] = []
    lines.append(_sep_border())
    if backup_path is None:
        lines.append(_content_line("BACKUP: SKIPPED"))
    else:
        lines.append(_content_line(f"BACKUP: {backup_path}"[:INNER_WIDTH]))

    total_listings = sum(r.get("listings", 0) for r in scrape_results)
    total_portals = len(set(r.get("portal", "?") for r in scrape_results))
    db_line = f"DB UPDATE: {total_listings:,} listings across {total_portals} portals"
    lines.append(_content_line(db_line))

    time_line = f"TOTAL TIME: {_format_time(total_time)}"
    lines.append(_content_line(time_line))
    return lines


def generate_report(
    health_results: list[dict],
    scrape_results: list[dict],
    validation: dict,
    backup_path: str | None,
    total_time: float,
) -> str:
    """Generate a box-drawn console report for the orchestrator.

    Args:
        health_results: List of health check results per portal.
        scrape_results: List of scrape results per portal.
        validation: Dict with 'passed' (bool) and 'warnings' (list[str]).
        backup_path: Path to backup file, or None if skipped.
        total_time: Total elapsed seconds.

    Returns:
        Formatted string suitable for printing to a terminal.
    """
    lines: list[str] = []

    # Header
    lines.append(_top_border())
    lines.append(_content_line("SCRAPER ORCHESTRATOR REPORT"))
    lines.append(_content_line(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    # Health check
    lines.extend(_generate_health_section(health_results))

    # Scrape results
    lines.extend(_generate_scrape_section(scrape_results))

    # Validation
    lines.extend(_generate_validation_section(validation))

    # Summary (backup, db update, total time)
    lines.extend(_generate_summary_section(backup_path, scrape_results, total_time))

    # Footer
    lines.append(_bot_border())

    return "\n".join(lines) + "\n"
