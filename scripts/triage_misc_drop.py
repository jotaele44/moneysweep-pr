"""Triage the data/raw/misc. drop folder.

A user dropped a ~6 GB mixed folder at data/raw/misc. (literal trailing dot in
the dirname). Triage showed ~97% of it is duplicate clutter, bulk low-value
GrantsDBExtract XML, or files from a different project. The genuinely-new,
Contract-Sweeper-relevant content is a small subset: unique government PDFs,
the Federal Register PR-document index, and one CRS report text file.

This script keeps ONLY that content via an explicit allow-list, relocates it
into data/raw/documents/ with a manifest, deletes everything else, and removes
the now-empty misc folder.

Safety:
  * The whole data/raw/misc. tree is untracked in git and is never read by the
    pipeline, so deletion is git-safe.
  * The allow-list is positive: anything not explicitly kept is deleted, so a
    mis-classified file can never be deleted by accident — it is simply not kept.
  * Content-hash de-dup drops PDFs that already exist elsewhere under data/raw/
    (e.g. the HigherGov PDFs) and intra-folder duplicates (the " 2" download
    copies), keeping one of each.

Usage:
  python3 scripts/triage_misc_drop.py            # dry-run (default)
  python3 scripts/triage_misc_drop.py --apply    # execute
  python3 scripts/triage_misc_drop.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
from pathlib import Path

MISC_REL = "data/raw/misc."
DOCS_REL = "data/raw/documents"

# Allow-list: only these survive triage. Everything else in misc. is deleted.
KEEP_EXACT = {"CRS_R46788_2022_FULL.txt", "documents_matching_puerto_rico.csv"}
KEEP_SUFFIX = ".pdf"

# documents_matching_puerto_rico.csv is relocated under this name, unthemed.
FEDREG_SRC = "documents_matching_puerto_rico.csv"
FEDREG_DEST = "federal_register_pr_index.csv"

# Theme classification — first matching rule wins; keyword match on the
# lowercased, sanitized filename stem.
THEME_RULES = [
    ("audits", ["audit"]),
    ("fiscal_oversight", ["fomb", "prasa", "fiscal plan", "budget",
                          "compliance certification", "presupuesto"]),
    ("energy_procurement", ["rfq", "request for qualifications", "generation",
                            "grid", "renewable", "lng", " h2", "capacity"]),
    ("congressional_research", ["crs", "r46788", "chrg", "congressional",
                                "congress report", "rs20458"]),
    ("contractor_listings", ["contractor listing", "active contractor", "arcadis"]),
    ("solicitations", ["solicitation", "nofa", "pridco"]),
    ("legal_filings", ["hearing", "examiner", "noi", "pac", " order"]),
]
DEFAULT_THEME = "uncategorized"

MANIFEST_COLS = ["filename", "theme", "title", "source_hint",
                 "file_size_bytes", "sha256", "original_name"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize(name: str) -> str:
    """Clean a (possibly newline-containing) filename for use on disk."""
    p = Path(name)
    stem, ext = p.stem, p.suffix.lower()
    stem = re.sub(r"[\n\r\t?]+", " ", stem)        # control chars / ? -> space
    stem = re.sub(r"\s+", " ", stem).strip()       # collapse whitespace
    stem = re.sub(r" \d{1,2}$", "", stem).strip()  # drop " N" download-dup suffix
    return (stem or "document") + ext


def classify(stem_lower: str) -> str:
    # Normalize separators so "Active_Contractor" / "Active-Contractor" match
    # the same keywords as "active contractor".
    norm = re.sub(r"[_\-]+", " ", stem_lower)
    for theme, kws in THEME_RULES:
        if any(kw in norm for kw in kws):
            return theme
    return DEFAULT_THEME


def source_hint(s: str) -> str:
    if "fomb" in s:
        return "FOMB"
    if "audit of sba" in s:
        return "SBA OIG"
    if "crs" in s or "r46788" in s:
        return "Congressional Research Service"
    if "chrg" in s:
        return "U.S. Congress"
    if "prasa" in s:
        return "PRASA / FOMB"
    if "pridco" in s:
        return "PRIDCO"
    if "federal_register" in s or "puerto_rico" in s:
        return "Federal Register"
    return ""


def existing_repo_hashes(raw_dir: Path, misc_dir: Path) -> set[str]:
    """sha256 of every PDF already under data/raw/ outside the misc. folder."""
    hashes: set[str] = set()
    for p in raw_dir.rglob("*.pdf"):
        if misc_dir == p.parent or misc_dir in p.parents:
            continue
        try:
            hashes.add(sha256(p))
        except OSError:
            pass
    return hashes


def triage(root: Path, apply: bool) -> int:
    misc_dir = root / MISC_REL
    docs_dir = root / DOCS_REL
    raw_dir = root / "data" / "raw"

    if not misc_dir.exists():
        print(f"[triage] {MISC_REL} not present — nothing to do (idempotent).")
        return 0

    all_files = [p for p in misc_dir.rglob("*") if p.is_file()]
    total_bytes = sum(p.stat().st_size for p in all_files)
    repo_hashes = existing_repo_hashes(raw_dir, misc_dir)

    kept: list[dict] = []
    seen_hashes: set[str] = set()
    skipped_dup = 0

    for p in sorted(all_files):
        name = p.name
        if not (name in KEEP_EXACT or name.lower().endswith(KEEP_SUFFIX)):
            continue
        h = sha256(p)
        if h in repo_hashes or h in seen_hashes:
            skipped_dup += 1  # already in the repo, or a duplicate within misc.
            continue
        seen_hashes.add(h)

        if name == FEDREG_SRC:
            clean, theme, rel = FEDREG_DEST, "federal_register_index", FEDREG_DEST
        else:
            clean = sanitize(name)
            theme = classify(clean.rsplit(".", 1)[0].lower())
            rel = f"{theme}/{clean}"

        kept.append({
            "filename": rel,
            "theme": theme,
            "title": clean.rsplit(".", 1)[0],
            "source_hint": source_hint(clean.lower()),
            "file_size_bytes": p.stat().st_size,
            "sha256": h,
            "original_name": name.replace("\n", "\\n").replace("\r", ""),
            "_src": p,
        })

    kept_bytes = sum(r["file_size_bytes"] for r in kept)
    del_bytes = total_bytes - kept_bytes
    del_count = len(all_files) - len(kept)

    print(f"[triage] root={root}")
    print(f"[triage] {MISC_REL}: {len(all_files)} files, {total_bytes / 1e9:.2f} GB")
    print(f"[triage] KEEP {len(kept)} files -> {DOCS_REL}/ ({kept_bytes / 1e6:.1f} MB)")
    by_theme: dict[str, int] = {}
    for r in kept:
        by_theme[r["theme"]] = by_theme.get(r["theme"], 0) + 1
    for theme in sorted(by_theme):
        print(f"           {theme}: {by_theme[theme]}")
    print(f"[triage] DELETE {del_count} files ({del_bytes / 1e9:.2f} GB freed) "
          f"[{skipped_dup} were content-duplicates]")

    if not apply:
        print("\n[triage] DRY-RUN — nothing written. Re-run with --apply to execute.")
        for r in sorted(kept, key=lambda x: x["filename"]):
            print(f"  keep: {r['original_name'][:68]!r} -> {r['filename']}")
        return 0

    # Relocate kept files.
    docs_dir.mkdir(parents=True, exist_ok=True)
    for r in kept:
        dest = docs_dir / r["filename"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():  # distinct content, colliding sanitized name
            stem, suf, n = dest.stem, dest.suffix, 2
            while dest.exists():
                dest = dest.parent / f"{stem} ({n}){suf}"
                n += 1
            r["filename"] = str(dest.relative_to(docs_dir))
        shutil.move(str(r["_src"]), str(dest))

    # Write the manifest.
    manifest = docs_dir / "documents_manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(kept, key=lambda x: x["filename"]):
            w.writerow(r)

    # Delete everything that remains, then the empty misc. directory.
    shutil.rmtree(misc_dir)

    print("\n[triage] APPLIED.")
    print(f"  relocated {len(kept)} files into {DOCS_REL}/")
    print(f"  wrote {manifest.relative_to(root)} ({len(kept)} rows)")
    print(f"  removed {MISC_REL} ({del_count} files, {del_bytes / 1e9:.2f} GB freed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path,
                    default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--apply", action="store_true",
                    help="execute the triage (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op flag; dry-run is the default")
    a = ap.parse_args(argv)
    return triage(a.root.resolve(), a.apply and not a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
