"""Audit alias coverage of ACT-family contractor names against the live overrides.

Reads a structured CSV extraction of ACT/ACUDEN transition-contract publications
(default: the curated synthetic fixture at
``tests/fixtures/act_transition/sample_rows.csv``; full operator drop expected at
``data/raw/act_transition/transition_contracts_extracted.csv``) and reports which
contractor names already collapse via ``contract_sweeper.runtime.alias_overrides``
and which still produce distinct normalized forms that should become candidates
for new override entries.

Outputs:

* ``reports/act_transition_alias_audit.md`` — human-readable Markdown report.
* ``reports/act_transition_alias_audit.csv`` — machine-readable cluster table.

Pure reporter. Reads CSV; writes only under ``reports/``. Not chained from
``run_all.py`` and not subject to the pause-lock processed-dir restriction.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.alias_overrides import apply as apply_override
from contract_sweeper.runtime.alias_overrides import load_overrides
from contract_sweeper.runtime.name_normalization import normalize_name
from scripts.config import PROJECT_ROOT, setup_logging


DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "act_transition" / "transition_contracts_extracted.csv"
FALLBACK_INPUT = PROJECT_ROOT / "tests" / "fixtures" / "act_transition" / "sample_rows.csv"
DEFAULT_OUTPUT_MD = PROJECT_ROOT / "reports" / "act_transition_alias_audit.md"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "reports" / "act_transition_alias_audit.csv"


@dataclass
class ClusterStats:
    canonical: str
    overridden: bool
    raw_names: set[str] = field(default_factory=set)
    normalized_forms: set[str] = field(default_factory=set)
    occurrences_by_source: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def total_occurrences(self) -> int:
        return sum(self.occurrences_by_source.values())

    @property
    def source_count(self) -> int:
        return len(self.occurrences_by_source)

    @property
    def needs_override(self) -> bool:
        """True if the cluster has ≥2 distinct normalized forms — i.e. the default
        normalizer alone cannot collapse them and an explicit alias entry is needed."""
        return len(self.normalized_forms) >= 2


def _resolve_input(arg_path: Path | None) -> Path:
    """Return the input CSV path, falling back to the synthetic fixture."""
    if arg_path is not None:
        return arg_path
    if DEFAULT_INPUT.exists():
        return DEFAULT_INPUT
    return FALLBACK_INPUT


def _build_clusters(rows: list[dict[str, str]], overrides: dict[str, str]) -> dict[str, ClusterStats]:
    clusters: dict[str, ClusterStats] = {}
    for row in rows:
        raw = (row.get("contractor_name") or "").strip()
        if not raw:
            continue
        canonical, overridden = apply_override(raw, overrides)
        if not canonical:
            continue
        stats = clusters.setdefault(canonical, ClusterStats(canonical=canonical, overridden=overridden))
        # If any raw form was overridden into this canonical, the cluster is "matched".
        stats.overridden = stats.overridden or overridden
        stats.raw_names.add(raw)
        stats.normalized_forms.add(normalize_name(raw))
        source = (row.get("source_dataset") or "UNKNOWN").strip() or "UNKNOWN"
        stats.occurrences_by_source[source] += 1
    return clusters


def _municipio_evidence(clusters: dict[str, ClusterStats]) -> list[tuple[str, str, set[str]]]:
    """Pair Spanish 'MUNICIPIO DE X' canonicals with English 'MUNICIPALITY OF X' canonicals.

    Returns a list of (town, spanish_canonical, english_raw_forms) triples.
    Evidence for the deferred normalizer-rule PR.
    """
    spanish_prefix = "MUNICIPIO DE "
    english_prefix = "MUNICIPALITY OF "
    sp_map: dict[str, ClusterStats] = {}
    en_map: dict[str, ClusterStats] = {}
    for canonical, stats in clusters.items():
        upper = canonical.upper()
        if upper.startswith(spanish_prefix):
            sp_map[upper[len(spanish_prefix):].strip()] = stats
        elif upper.startswith(english_prefix):
            en_map[upper[len(english_prefix):].strip()] = stats
    pairs: list[tuple[str, str, set[str]]] = []
    for town, sp_stats in sorted(sp_map.items()):
        if town in en_map:
            en_stats = en_map[town]
            pairs.append((town, sp_stats.canonical, en_stats.raw_names | sp_stats.raw_names))
    return pairs


def _write_markdown(
    out_path: Path,
    input_path: Path,
    total_rows: int,
    clusters: dict[str, ClusterStats],
    overrides_count: int,
) -> None:
    matched = [c for c in clusters.values() if c.overridden]
    unmatched = [c for c in clusters.values() if not c.overridden]
    cross_source = [c for c in clusters.values() if c.source_count >= 2]

    # Recommendations: unmatched clusters with ≥2 distinct raw forms OR cross-source clusters.
    # Exclude municipio canonicals from recommendations (deferred to normalizer PR).
    def _is_municipio(c: ClusterStats) -> bool:
        upper = c.canonical.upper()
        return upper.startswith("MUNICIPIO DE ") or upper.startswith("MUNICIPALITY OF ")

    # A cluster needs an alias override only when default normalization can't
    # already collapse its raw forms. Cross-source clusters with even one shared
    # normalized form still surface because they're high-value cross-references.
    recommended = [
        c
        for c in unmatched
        if c.needs_override and not _is_municipio(c)
    ]
    recommended.sort(key=lambda c: (-c.source_count, -c.total_occurrences, c.canonical))

    municipio_pairs = _municipio_evidence(clusters)

    lines: list[str] = []
    lines.append("# ACT-family alias coverage audit")
    lines.append("")
    lines.append(f"- Input: `{input_path.relative_to(PROJECT_ROOT)}`")
    lines.append(f"- Rows scanned: {total_rows}")
    lines.append(f"- Distinct canonical clusters: {len(clusters)}")
    lines.append(f"- Alias overrides loaded: {overrides_count}")
    lines.append("")

    lines.append("## Coverage summary")
    lines.append("")
    lines.append(f"- Matched (cluster has at least one override hit): **{len(matched)}**")
    lines.append(f"- Unmatched (no override hit; default-normalized canonical): **{len(unmatched)}**")
    lines.append(f"- Cross-source clusters (appear in ≥2 source_dataset values): **{len(cross_source)}**")
    lines.append("")

    # Per-source-year breakdown
    per_source_clusters: dict[str, set[str]] = defaultdict(set)
    per_source_rows: dict[str, int] = defaultdict(int)
    for stats in clusters.values():
        for source, count in stats.occurrences_by_source.items():
            per_source_clusters[source].add(stats.canonical)
            per_source_rows[source] += count

    lines.append("## Per-source-year breakdown")
    lines.append("")
    lines.append("| source_dataset | rows | distinct canonical clusters |")
    lines.append("|---|---|---|")
    for source in sorted(per_source_clusters):
        lines.append(
            f"| `{source}` | {per_source_rows[source]} | {len(per_source_clusters[source])} |"
        )
    lines.append("")

    lines.append("## Recommended new overrides")
    lines.append("")
    lines.append(
        "Unmatched clusters whose raw forms produce ≥2 distinct normalized values "
        "(i.e. default normalization can't collapse them — an explicit alias entry "
        "is required). Municipios are excluded (see normalizer-rule follow-up below)."
    )
    lines.append("")
    if not recommended:
        lines.append("_None — every multi-form cluster is already covered by the default normalizer or by an explicit override._")
    else:
        lines.append("| rank | sources | total rows | distinct normalized | proposed canonical | raw forms |")
        lines.append("|---|---|---|---|---|---|")
        for i, c in enumerate(recommended, start=1):
            forms = " · ".join(sorted(c.raw_names))
            sources = ", ".join(sorted(c.occurrences_by_source))
            lines.append(
                f"| {i} | {sources} | {c.total_occurrences} | {len(c.normalized_forms)} | `{c.canonical}` | {forms} |"
            )
    lines.append("")

    # All unmatched canonicals — for human review. Manual semantic clustering
    # (e.g. "JUAN O VIRELLA S NCHEZ" + "ING JUAN O VIRELLA S NCHEZ" are the same
    # person) cannot be detected automatically by string normalization; this
    # section gives the reviewer the full list to scan.
    lines.append("## All unmatched canonicals (for manual review)")
    lines.append("")
    lines.append(
        "Every cluster where no alias override fired. The reviewer should scan for "
        "semantic duplicates that the normalizer can't auto-detect (typos, DBA chains, "
        "credential prefixes, bilingual labels, etc.) and add explicit alias entries."
    )
    lines.append("")
    unmatched_for_review = sorted(
        (c for c in unmatched if not _is_municipio(c)),
        key=lambda c: c.canonical,
    )
    if not unmatched_for_review:
        lines.append("_None._")
    else:
        lines.append("| canonical | rows | distinct raw forms | sources |")
        lines.append("|---|---|---|---|")
        for c in unmatched_for_review:
            forms = " · ".join(sorted(c.raw_names))
            sources = ", ".join(sorted(c.occurrences_by_source))
            lines.append(
                f"| `{c.canonical}` | {c.total_occurrences} | {forms} | {sources} |"
            )
    lines.append("")

    lines.append("## Cross-source clusters (entities in both ACT_2020 and ACUDEN_2024)")
    lines.append("")
    cross = [c for c in cross_source if not _is_municipio(c)]
    if not cross:
        lines.append("_None._")
    else:
        cross.sort(key=lambda c: (-c.total_occurrences, c.canonical))
        lines.append("| canonical | total rows | by source |")
        lines.append("|---|---|---|")
        for c in cross:
            per_src = ", ".join(f"{s}={n}" for s, n in sorted(c.occurrences_by_source.items()))
            lines.append(f"| `{c.canonical}` | {c.total_occurrences} | {per_src} |")
    lines.append("")

    lines.append("## Bilingual municipio collapse evidence (deferred to normalizer-rule PR)")
    lines.append("")
    lines.append(
        "Pairs of `MUNICIPIO DE X` (Spanish) and `MUNICIPALITY OF X` (English) canonicals that "
        "refer to the same PR municipio. These are intentionally NOT in `recommended` above — "
        "the right fix is a single normalizer rule, not 78 alias entries."
    )
    lines.append("")
    if not municipio_pairs:
        lines.append("_None observed in this input._")
    else:
        lines.append("| town | spanish canonical | raw forms |")
        lines.append("|---|---|---|")
        for town, sp_canonical, raw_forms in municipio_pairs:
            forms = " · ".join(sorted(raw_forms))
            lines.append(f"| {town} | `{sp_canonical}` | {forms} |")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(out_path: Path, clusters: dict[str, ClusterStats]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "canonical_cluster",
                "overridden",
                "distinct_raw_forms",
                "total_occurrences",
                "source_count",
                "sources",
                "raw_forms",
            ]
        )
        for canonical, stats in sorted(clusters.items(), key=lambda kv: (-kv[1].total_occurrences, kv[0])):
            writer.writerow(
                [
                    canonical,
                    "yes" if stats.overridden else "no",
                    len(stats.raw_names),
                    stats.total_occurrences,
                    stats.source_count,
                    "|".join(sorted(stats.occurrences_by_source)),
                    "|".join(sorted(stats.raw_names)),
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            f"CSV input path. Default: {DEFAULT_INPUT} if it exists, "
            f"else {FALLBACK_INPUT}."
        ),
    )
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    args = parser.parse_args(argv)

    logger = setup_logging("audit_act_alias_coverage")
    input_path = _resolve_input(args.input)
    if not input_path.exists():
        logger.error("Input CSV not found: %s", input_path)
        return 2

    logger.info("Reading %s", input_path)
    with input_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    overrides = load_overrides()
    clusters = _build_clusters(rows, overrides)

    _write_markdown(args.output_md, input_path, len(rows), clusters, len(overrides))
    _write_csv(args.output_csv, clusters)

    matched = sum(1 for c in clusters.values() if c.overridden)
    logger.info(
        "Wrote %s and %s — %d clusters (%d matched, %d unmatched) across %d rows",
        args.output_md.relative_to(PROJECT_ROOT),
        args.output_csv.relative_to(PROJECT_ROOT),
        len(clusters),
        matched,
        len(clusters) - matched,
        len(rows),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
