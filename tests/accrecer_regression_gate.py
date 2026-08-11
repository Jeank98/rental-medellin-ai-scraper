#!/usr/bin/env python3
"""Acrecer regression gate — named CLI with four modes.

capture            Run health_check on current PORTALS, save canonical JSON.
capture-protected  Hash + diff protected dirty paths (tracked + untracked).
compare            Load baseline/post health JSON, reject regressions.
verify-protected   Regenerate hashes/diffs from manifest, reject changes.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrape.orchestrator

EXPECTED_PORTALS_14 = [
    "accrecer",
    "maxibienes",
    "albertoalvarez",
    "alnago",
    "arrendamientosdelnorte",
    "arrendamientoselcastillo",
    "arrendamientosmonserrate",
    "arrendamientossantafe",
    "arrendamientosvillacruz",
    "coninsa",
    "habitamos",
    "merinohermanos",
    "metrocasas",
    "santillana",
    "lapalmainmobiliaria",
]

RESULT_EXPECTED_KEYS = {"portal", "healthy", "listings", "elapsed", "error"}
REPO_ROOT = Path(__file__).resolve().parent.parent


# ── helpers ────────────────────────────────────────────────────────

def _cmd(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT, **kwargs)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _git_diff_binary(path: Path) -> str:
    """Return binary-safe git diff for a tracked file."""
    proc = _cmd(["git", "diff", "--binary", "--", str(path.relative_to(REPO_ROOT))])
    return proc.stdout if proc.returncode == 0 else ""


def _git_diff_no_index(path: Path) -> str:
    """Return binary-safe git diff for an untracked file vs /dev/null."""
    proc = _cmd(["git", "diff", "--no-index", "--binary", "/dev/null", str(path)])
    return proc.stdout if proc.returncode in (0, 1) else str(proc.stderr)


def _iter_protected_paths(paths: list[str]) -> list[Path]:
    """Recursively enumerate every leaf file under each protected path."""
    leaves: list[Path] = []
    for p in paths:
        full = (REPO_ROOT / p).resolve()
        if not full.exists():
            print(f"  ⚠  protected path does not exist: {p}", file=sys.stderr)
            continue
        if full.is_file():
            leaves.append(full)
        elif full.is_dir():
            for root, _dirs, files in os.walk(full):
                for fn in sorted(files):
                    leaves.append(Path(root) / fn)
    return sorted(leaves)


# ── capture ────────────────────────────────────────────────────────

def cmd_capture(args: argparse.Namespace) -> int:
    """Run health_check on current PORTALS and save canonical JSON."""
    portals = scrape.orchestrator.PORTALS
    actual_keys = sorted(portals.keys())

    expected = args.expected_portals.split(",")
    expected_sorted = sorted(expected)
    if actual_keys != expected_sorted:
        print(f"ERROR: portal key mismatch", file=sys.stderr)
        print(f"  expected ({len(expected_sorted)}): {expected_sorted}", file=sys.stderr)
        print(f"  actual   ({len(actual_keys)}): {actual_keys}", file=sys.stderr)
        return 1
    print(f"  ✅ Portal keys match: {len(actual_keys)} portals")

    # Snapshot results/ directory before health check
    results_dir = REPO_ROOT / "results"
    before_files: set[str] = set()
    if results_dir.is_dir():
        before_files = {f.name for f in results_dir.iterdir() if f.is_file()}

    print(f"  ⏳ Running health_check (this may take a while)...")
    results = scrape.orchestrator.health_check(portals, verbose=False)

    # Validate result schema
    for r in results:
        rkeys = set(r.keys())
        if rkeys != RESULT_EXPECTED_KEYS:
            print(f"ERROR: unexpected keys in health result for {r.get('portal', '?')}: {rkeys}", file=sys.stderr)
            return 1

    # Check no result writes
    if args.assert_no_result_writes:
        after_files: set[str] = set()
        if results_dir.is_dir():
            after_files = {f.name for f in results_dir.iterdir() if f.is_file()}
        new_files = after_files - before_files
        if new_files:
            print(f"ERROR: new files in results/ after health_check: {new_files}", file=sys.stderr)
            return 1
        print(f"  ✅ No result writes: {len(before_files)} before, {len(after_files)} after")

    # Serialize keyed by portal name
    keyed = {r["portal"]: {k: r[k] for k in sorted(r)} for r in results}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(keyed, fh, indent=2, ensure_ascii=False, default=str)
    print(f"  ✅ Saved to {out_path}")

    healthy = sum(1 for r in results if r["healthy"])
    print(f"  ── {healthy}/{len(results)} healthy")
    return 0


# ── capture-protected ──────────────────────────────────────────────

def cmd_capture_protected(args: argparse.Namespace) -> int:
    """Enumerate protected paths, hash + diff each, save manifest."""
    paths = args.paths
    leaves = _iter_protected_paths(paths)
    print(f"  Enumerating {len(leaves)} leaf file(s) across {len(paths)} path(s)...")

    manifest: dict[str, dict] = {}
    tracked = set()
    # Determine tracked files
    proc = _cmd(["git", "ls-files", "--"])
    if proc.returncode == 0:
        tracked = set(proc.stdout.splitlines())

    errors = 0
    for leaf in leaves:
        rel = str(leaf.relative_to(REPO_ROOT))
        print(f"    📄 {rel}")
        entry: dict = {"rel_path": rel, "sha256": _sha256(leaf)}
        if rel in tracked:
            entry["diff_binary"] = _git_diff_binary(leaf)
        else:
            entry["diff_binary"] = _git_diff_no_index(leaf)
        manifest[rel] = entry
        if not entry["diff_binary"] and rel not in tracked:
            print(f"      ⚠  diff empty for untracked file", file=sys.stderr)

    # Check every expected path was covered
    for p in paths:
        full = (REPO_ROOT / p).resolve()
        if not full.exists():
            print(f"  ⚠  MISSING protected path: {p}", file=sys.stderr)
            errors += 1

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_doc = {"paths": paths, "files": manifest}
    with open(out_path, "w") as fh:
        json.dump(manifest_doc, fh, indent=2, ensure_ascii=False)
    print(f"  ✅ Saved manifest to {out_path}")

    return 1 if errors else 0


# ── compare ────────────────────────────────────────────────────────

def cmd_compare(args: argparse.Namespace) -> int:
    """Load baseline + post health JSON, reject regressions."""
    with open(args.baseline) as fh:
        baseline = json.load(fh)
    with open(args.post) as fh:
        post = json.load(fh)

    errors = 0
    existing_unhealthy_before: dict[str, dict] = {}

    # Check every baseline-healthy portal is still healthy
    for portal_name, b in baseline.items():
        p = post.get(portal_name)
        if p is None:
            print(f"ERROR: portal {portal_name} missing from post", file=sys.stderr)
            errors += 1
            continue
        if b["healthy"] and not p["healthy"]:
            print(f"ERROR: {portal_name} was healthy at baseline, now unhealthy", file=sys.stderr)
            print(f"  Before: listings={b['listings']}, error=None", file=sys.stderr)
            print(f"  After:  listings={p['listings']}, error={p.get('error')}", file=sys.stderr)
            errors += 1
        if not b["healthy"]:
            existing_unhealthy_before[portal_name] = b
            print(f"  ⚠  {portal_name}: already unhealthy at baseline — not a regression")

    # Check Acrecer is healthy (only if --new-portal specified)
    new_portal = args.new_portal
    if new_portal:
        if new_portal not in post:
            print(f"ERROR: new portal '{new_portal}' not found in post", file=sys.stderr)
            errors += 1
        elif not post[new_portal]["healthy"]:
            print(f"ERROR: new portal '{new_portal}' is unhealthy", file=sys.stderr)
            print(f"  listings={post[new_portal]['listings']}, error={post[new_portal].get('error')}", file=sys.stderr)
            errors += 1
        else:
            print(f"  ✅ {new_portal}: healthy ({post[new_portal]['listings']} listings)")

    if existing_unhealthy_before:
        print(f"  ⚠  {len(existing_unhealthy_before)} portal(s) already unhealthy at baseline (not regressions)")

    if errors:
        print(f"\n  ❌ COMPARE FAILED: {errors} error(s)")
        return 1
    print(f"\n  ✅ COMPARE PASSED: no regressions detected")
    return 0


# ── verify-protected ───────────────────────────────────────────────

def cmd_verify_protected(args: argparse.Namespace) -> int:
    """Regenerate hashes/diffs from manifest paths, compare exact equality."""
    with open(args.manifest) as fh:
        manifest = json.load(fh)

    paths = manifest["paths"]
    stored_files: dict[str, dict] = manifest["files"]

    errors = 0
    current_leaves = _iter_protected_paths(paths)
    current_rel = {str(leaf.relative_to(REPO_ROOT)) for leaf in current_leaves}
    stored_rel = set(stored_files.keys())

    # Additions
    added = current_rel - stored_rel
    if added:
        for a in sorted(added):
            print(f"ERROR: new file detected: {a}", file=sys.stderr)
        errors += len(added)

    # Deletions
    deleted = stored_rel - current_rel
    if deleted:
        for d in sorted(deleted):
            print(f"ERROR: file deleted: {d}", file=sys.stderr)
        errors += len(deleted)

    # Modifications
    tracked = set()
    proc = _cmd(["git", "ls-files", "--"])
    if proc.returncode == 0:
        tracked = set(proc.stdout.splitlines())

    for rel in sorted(stored_rel & current_rel):
        leaf = REPO_ROOT / rel
        stored = stored_files[rel]

        current_hash = _sha256(leaf)
        if current_hash != stored["sha256"]:
            print(f"ERROR: hash mismatch for {rel}", file=sys.stderr)
            print(f"  stored:  {stored['sha256']}", file=sys.stderr)
            print(f"  current: {current_hash}", file=sys.stderr)
            errors += 1
            continue

        current_diff = ""
        if rel in tracked:
            current_diff = _git_diff_binary(leaf)
        else:
            current_diff = _git_diff_no_index(leaf)

        if current_diff != stored["diff_binary"]:
            print(f"ERROR: diff mismatch for {rel}", file=sys.stderr)
            errors += 1

    if errors:
        print(f"\n  ❌ VERIFY-PROTECTED FAILED: {errors} error(s)")
        return 1
    print(f"\n  ✅ VERIFY-PROTECTED PASSED: {len(stored_rel)} files unchanged")
    return 0


# ── CLI ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="accrecer_regression_gate",
        description="Acrecer regression gate — health snapshots + protected-path hashing",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # capture
    cap = subparsers.add_parser("capture", help="Run health_check and save JSON")
    cap.add_argument("--expected-portals", required=True,
                     help="Comma-separated expected portal keys")
    cap.add_argument("--output", required=True,
                     help="Output JSON path")
    cap.add_argument("--assert-no-result-writes", action="store_true",
                     help="Fail if any file is created in results/")

    # capture-protected
    cpro = subparsers.add_parser("capture-protected",
                                 help="Hash + diff protected paths")
    cpro.add_argument("--output", required=True, help="Output JSON manifest path")
    cpro.add_argument("--paths", nargs="+", required=True,
                      help="Protected file/directory paths")

    # compare
    comp = subparsers.add_parser("compare", help="Compare baseline vs post health")
    comp.add_argument("--baseline", required=True, help="Baseline health JSON")
    comp.add_argument("--post", required=True, help="Post-change health JSON")
    comp.add_argument("--new-portal", default=None,
                      help="New portal name to check for health (optional)")

    # verify-protected
    vpro = subparsers.add_parser("verify-protected",
                                 help="Verify protected paths unchanged")
    vpro.add_argument("--manifest", required=True, help="Protected paths manifest JSON")

    args = parser.parse_args()

    if args.mode == "capture":
        return cmd_capture(args)
    elif args.mode == "capture-protected":
        return cmd_capture_protected(args)
    elif args.mode == "compare":
        return cmd_compare(args)
    elif args.mode == "verify-protected":
        return cmd_verify_protected(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
