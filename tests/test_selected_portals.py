"""Deterministic regression tests for the selected southern-portal runner."""

import json
from types import SimpleNamespace

import pytest

from scripts import run_selected as runner
from scrape.cities import CITY_LABELS, normalize_city, resolve_city

PORTALS = ("escalainmobiliaria", "lonjainmobiliariadelsur")
CITIES = ("medellin", "la-estrella")


def _rows(portal: str, city: str, count: int = 2) -> list[dict]:
    return [
        {
            "id": f"{portal}-{city}-{index}",
            "portal": portal,
            "tipo": "apartamento",
            "precio": 1_500_000 + index,
            "area": 55,
            "habitaciones": 2,
            "banos": 1,
            "parqueaderos": 0,
            "estrato": 3,
            "barrio": "Centro",
            "url": f"https://example.test/{portal}/{city}/{index}",
        }
        for index in range(count)
    ]


class FakeScrapers:
    """Load one fake module per portal and record every scrape call."""

    def __init__(self, batches: dict, failures=(), events: list | None = None):
        self.batches = batches
        self.failures = set(failures)
        self.calls: list[dict] = []
        self.events = events if events is not None else []

    def __call__(self, portal: str):
        def scrape_cities(ciudades, sample_only=False, max_pages=None, verbose=False):
            self.events.append(("scrape", portal))
            self.calls.append(
                {
                    "portal": portal,
                    "cities": list(ciudades),
                    "sample_only": sample_only,
                    "max_pages": max_pages,
                    "verbose": verbose,
                }
            )
            if portal in self.failures:
                raise RuntimeError(f"{portal} listed a malformed response")
            return self.batches[portal]

        return SimpleNamespace(scrape_cities=scrape_cities)


class Recorder:
    def __init__(
        self,
        result=None,
        error: Exception | None = None,
        events: list | None = None,
        name: str | None = None,
    ):
        self.result = result
        self.error = error
        self.calls: list[tuple[tuple, dict]] = []
        self.events = events if events is not None else []
        self.name = name

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.name:
            self.events.append((self.name,))
        if self.error is not None:
            raise self.error
        return self.result


class WriteRecorder:
    def __init__(self, fail_at: tuple[str, str] | None = None, mode: str = "raise"):
        self.fail_at = fail_at
        self.mode = mode
        self.calls: list[tuple[str, str]] = []

    def __call__(self, rows, portal: str, ciudad: str):
        self.calls.append((portal, ciudad))
        if self.fail_at == (portal, ciudad):
            if self.mode == "raise":
                raise RuntimeError("database unavailable")
            return 0
        return len(rows)


def _harness(*, portals=PORTALS, cities=CITIES, batches=None, failures=()):
    batches = batches or {
        portal: {city: _rows(portal, city) for city in cities} for portal in portals
    }
    events: list = []
    loader = FakeScrapers(batches, failures=failures, events=events)
    backup = Recorder(
        result={
            "status": "success",
            "path": "/tmp/backup.sql",
            "error": None,
            "reason": None,
        },
        events=events,
        name="backup",
    )
    writer = WriteRecorder()
    exporter = Recorder(result={"success": True}, events=events, name="export")
    report_writer = Recorder(result="/tmp/report.json")
    environment = Recorder(events=events, name="environment")
    return {
        "batches": batches,
        "events": events,
        "loader": loader,
        "environment": environment,
        "backup": backup,
        "writer": writer,
        "exporter": exporter,
        "report_writer": report_writer,
    }


def _run(harness, **overrides):
    values = {
        "portals": list(PORTALS),
        "cities": list(CITIES),
        "workers": 1,
        "loader": harness["loader"],
        "environment_loader": harness["environment"],
        "backup": harness["backup"],
        "writer": harness["writer"],
        "exporter": harness["exporter"],
        "report_writer": harness["report_writer"],
    }
    values.update(overrides)
    return runner.run_selected(**values)


def test_city_aliases_share_the_existing_la_estrella_storage_key():
    assert CITY_LABELS == {
        "medellin": "Medellín",
        "envigado": "Envigado",
        "itagui": "Itagüí",
        "la-estrella": "La Estrella",
        "sabaneta": "Sabaneta",
    }
    for alias in ("La Estrella", "la_estrella", "LA-ESTRELLA", "  la   estrella  "):
        assert resolve_city(alias) == "la-estrella"
    assert resolve_city("Itagüí") == "itagui"
    assert resolve_city("Medellín") == "medellin"
    assert normalize_city("Bello") == "bello"
    with pytest.raises(ValueError, match="unsupported city"):
        resolve_city("Bello")


def test_run_selected_canonicalizes_spaced_city_alias_before_scraping():
    portal = PORTALS[0]
    harness = _harness(
        portals=(portal,),
        cities=("la-estrella",),
        batches={portal: {"la-estrella": _rows(portal, "la-estrella")}},
    )

    report = _run(
        harness,
        portals=[portal],
        cities=["La Estrella"],
        sample_only=True,
        max_pages=1,
    )

    assert report["exit_code"] == 0
    assert report["cities"] == ["la-estrella"]
    assert harness["loader"].calls[0]["cities"] == ["la-estrella"]


def test_unsupported_city_rejected_before_any_scrape_or_write():
    harness = _harness()
    report = _run(harness, cities=["Bogotá"])

    assert report["exit_code"] == 2
    assert report["status"] == "failed"
    assert harness["loader"].calls == []
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []
    assert harness["report_writer"].calls == []
    assert any("unsupported city" in error for error in report["errors"])


def test_full_run_rejects_a_page_cap_before_any_side_effect():
    harness = _harness()
    report = _run(harness, max_pages=2)

    assert report["exit_code"] == 2
    assert harness["loader"].calls == []
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []
    assert "sample cap" in " ".join(report["errors"])


def test_sample_mode_makes_no_backup_database_or_sheet_calls():
    harness = _harness()
    report = _run(harness, sample_only=True, max_pages=2)

    assert report["exit_code"] == 0
    assert report["status"] == "success"
    assert harness["backup"].calls == []
    assert harness["environment"].calls == []
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []


def test_full_run_collects_every_batch_before_backup_then_writes_then_mirror():
    harness = _harness()
    report = _run(harness, skip_sheet=False)

    assert report["exit_code"] == 0
    events = harness["events"]
    scrape_events = [event for event in events if event[0] == "scrape"]
    assert scrape_events == [("scrape", portal) for portal in PORTALS]
    assert events.index(("environment",)) < events.index(("backup",))
    assert events.index(("backup",)) > events.index(scrape_events[-1])
    assert events[-1] == ("export",)
    assert len(harness["backup"].calls) == 1
    assert harness["writer"].calls == [
        (portal, city) for portal in PORTALS for city in CITIES
    ]
    assert report["backup"]["status"] == "success"
    assert all(entry["status"] == "written" for entry in report["writes"])


def test_scraper_exception_blocks_backup_writes_and_sheet():
    harness = _harness(failures=("lonjainmobiliariadelsur",))
    report = _run(harness)

    assert report["exit_code"] == 1
    assert report["status"] == "failed"
    assert harness["environment"].calls == []
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []
    failures = [result for result in report["results"] if result["status"] == "failed"]
    assert [result["portal"] for result in failures] == ["lonjainmobiliariadelsur"]
    assert "malformed response" in failures[0]["error"]


def test_backup_failure_blocks_database_and_sheet_writes():
    harness = _harness()
    harness["backup"].result = {
        "status": "failed",
        "path": "/tmp/attempt.sql",
        "error": "pg_dump failed with exit code 1",
        "reason": "pg_dump_failed",
    }
    report = _run(harness)

    assert report["exit_code"] == 1
    assert report["backup"]["status"] == "failed"
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []


def test_backup_skip_is_not_treated_as_success():
    harness = _harness()
    harness["backup"].result = {
        "status": "skipped",
        "path": None,
        "error": "DATABASE_URL not set",
        "reason": "missing_database_url",
    }
    report = _run(harness)

    assert report["exit_code"] == 1
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []


def test_backup_exception_blocks_database_and_sheet_writes():
    harness = _harness()
    harness["backup"].error = RuntimeError("pg_dump missing")
    report = _run(harness)

    assert report["exit_code"] == 1
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []
    assert "backup_exception" in report["backup"]["reason"]


def test_write_count_mismatch_stops_remaining_writes_and_sheet():
    harness = _harness()
    harness["writer"] = WriteRecorder(
        fail_at=(PORTALS[0], CITIES[0]), mode="return_zero"
    )
    report = _run(harness, writer=harness["writer"])

    assert report["exit_code"] == 1
    assert harness["writer"].calls == [(PORTALS[0], CITIES[0])]
    assert harness["exporter"].calls == []
    assert "wrote 0/" in " ".join(report["errors"])


def test_write_exception_stops_remaining_writes_and_sheet():
    harness = _harness()
    harness["writer"] = WriteRecorder(fail_at=(PORTALS[0], CITIES[0]), mode="raise")
    report = _run(harness, writer=harness["writer"])

    assert report["exit_code"] == 1
    assert harness["writer"].calls == [(PORTALS[0], CITIES[0])]
    assert harness["exporter"].calls == []
    assert "database unavailable" in " ".join(report["errors"])


def test_empty_city_is_reported_and_never_replaces_its_snapshot():
    portal = PORTALS[0]
    harness = _harness(
        portals=(portal,),
        cities=("medellin", "envigado"),
        batches={
            portal: {
                "medellin": _rows(portal, "medellin"),
                "envigado": [],
            }
        },
    )
    report = _run(
        harness,
        portals=[portal],
        cities=["medellin", "envigado"],
    )

    assert report["exit_code"] == 0
    assert harness["writer"].calls == [(portal, "medellin")]
    empty_entries = [entry for entry in report["writes"] if entry["status"] == "empty"]
    assert [(entry["portal"], entry["ciudad"]) for entry in empty_entries] == [
        (portal, "envigado")
    ]
    assert harness["exporter"].calls


def test_extra_city_in_a_scraped_batch_blocks_all_writes():
    batches = {
        PORTALS[0]: {
            "medellin": _rows(PORTALS[0], "medellin"),
            "bello": _rows(PORTALS[0], "bello"),
        },
        PORTALS[1]: {"medellin": _rows(PORTALS[1], "medellin")},
    }
    harness = _harness(
        portals=(PORTALS[0], PORTALS[1]),
        cities=("medellin",),
        batches=batches,
    )
    report = _run(harness, cities=["medellin"])

    assert report["exit_code"] == 1
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert "city scope mismatch" in " ".join(report["errors"])


def test_wrong_portal_row_cannot_be_written_under_the_selected_portal():
    batches = {
        PORTALS[0]: {"medellin": _rows("otalroportal", "medellin")},
        PORTALS[1]: {"medellin": _rows(PORTALS[1], "medellin")},
    }
    harness = _harness(portals=PORTALS, cities=("medellin",), batches=batches)
    report = _run(harness, cities=["medellin"])

    assert report["exit_code"] == 1
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert "belongs to" in " ".join(report["errors"])


def test_mirror_export_is_unscoped_and_selected_scope_only_replaces_its_snapshots():
    harness = _harness()
    report = _run(harness, skip_sheet=False)

    assert report["exit_code"] == 0
    assert len(harness["exporter"].calls) == 1
    args, kwargs = harness["exporter"].calls[0]
    assert args == ()
    assert "ciudad" not in kwargs and "portal" not in kwargs
    assert set(harness["writer"].calls) == {
        (portal, city) for portal in PORTALS for city in CITIES
    }


def test_sheet_failure_fails_the_run_after_writes_are_complete():
    harness = _harness()
    harness["exporter"].result = {"success": False, "error": "quota exceeded"}
    report = _run(harness)

    assert report["exit_code"] == 1
    assert len(harness["writer"].calls) == len(PORTALS) * len(CITIES)
    assert report["sheet"]["success"] is False
    assert "quota exceeded" in " ".join(report["errors"])


def test_skip_sheet_keeps_writes_and_reports_the_skip():
    harness = _harness()
    report = _run(harness, skip_sheet=True)

    assert report["exit_code"] == 0
    assert harness["exporter"].calls == []
    assert report["sheet"] == {"skipped": True, "reason": "operator"}


def test_duplicate_id_across_city_batches_blocks_backup_and_every_write():
    portal = PORTALS[0]
    medellin = _rows(portal, "medellin", 1)
    la_estrella = _rows(portal, "la-estrella", 1)
    medellin[0]["id"] = la_estrella[0]["id"] = "ESC-shared-code"
    harness = _harness(
        portals=(portal,),
        cities=CITIES,
        batches={portal: {"medellin": medellin, "la-estrella": la_estrella}},
    )

    report = _run(harness, portals=[portal], cities=list(CITIES))

    assert report["exit_code"] == 1
    assert harness["environment"].calls == []
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []
    assert len(harness["report_writer"].calls) == 1
    errors = " ".join(report["errors"])
    assert "duplicate id 'ESC-shared-code'" in errors
    assert f"{portal}/medellin" in errors and f"{portal}/la-estrella" in errors


def test_explicit_empty_portal_selection_is_rejected_before_collection():
    harness = _harness()
    report = _run(harness, portals=[])

    assert report["exit_code"] == 2
    assert report["portals"] == []
    assert harness["loader"].calls == []
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert "portals must not be empty" in " ".join(report["errors"])


def test_explicit_empty_city_selection_is_rejected_before_collection():
    harness = _harness()
    report = _run(harness, cities=[])

    assert report["exit_code"] == 2
    assert report["cities"] == []
    assert harness["loader"].calls == []
    assert harness["backup"].calls == []
    assert harness["writer"].calls == []
    assert "cities must not be empty" in " ".join(report["errors"])


def test_backup_exception_report_never_echoes_connection_credentials():
    harness = _harness()
    harness["backup"].error = ValueError(
        "netloc 'scraper:s3cret-pw@db.example:5432' contains invalid characters"
    )
    report = _run(harness)

    assert report["exit_code"] == 1
    assert report["backup"]["reason"] == "backup_exception"
    assert report["backup"]["error"] == "database backup raised ValueError"
    assert harness["writer"].calls == []
    assert harness["exporter"].calls == []
    serialized = json.dumps(report)
    assert "s3cret-pw" not in serialized
    assert "db.example" not in serialized


def test_report_writer_failure_fails_the_run_without_hiding_counts():
    harness = _harness()
    harness["report_writer"].error = OSError("disk full")
    report = _run(harness, sample_only=True, max_pages=1)

    assert report["exit_code"] == 1
    assert report["status"] == "failed"
    assert report["results"][0]["total"] == 4
    assert "report write failed" in " ".join(report["errors"])
