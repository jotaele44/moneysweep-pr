"""Build per-target populated FOIA / public-records request letters (Gate ``foia``).

Reads the committed priority queue (``reports/foia_priority_queue.csv``) and the
requester config (``data/reference/foia_requester.json``), then writes one
ready-to-send letter per request to ``docs/foia_letters/FOIA_<request_id>.md``.

The letter bodies are derived from the two templates defined in
``docs/FOIA_REQUEST_TEMPLATES.md`` (Template A for jurisdiction=PR, Template B
for jurisdiction=US). All placeholders except ``{{requester_name}}`` and
``{{requester_contact}}`` are filled from the queue row; those two come from the
requester config. When the config still contains ``{{`` values (stub / operator
not yet filled), the letters are written with literal placeholders — the
validator ``scripts/validate_foia_submission_ready.py`` will reject that state.

Deterministic: given the same queue and config the output is byte-identical.
No network access required.

CLI::

    python scripts/build_foia_letters.py            # write all letters + manifest
    python scripts/build_foia_letters.py --check     # validate without writing
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[1]

PRIORITY_QUEUE = "reports/foia_priority_queue.csv"
REQUESTER_CONFIG = "data/reference/foia_requester.json"
OUT_DIR = "docs/foia_letters"
MANIFEST_OUT = "data/manifests/foia_letters.json"

# Template A — Puerto Rico public records (Ley 141-2019)
_TEMPLATE_A = """\
To: {target_agency} — Oficial de Acceso a la Información Pública
Re: Solicitud de acceso a información pública — Ley 141-2019

Estimado/a Oficial de Acceso:

Al amparo de la Ley 141-2019 y del derecho constitucional de acceso a la
información pública, solicito copia de los siguientes records:

  - Tipo de récord: {record_type}
  - Periodo: 2016 al presente (o el periodo disponible más amplio)
  - Formato preferido: datos estructurados (CSV o Excel); de no ser posible,
    PDF con datos tabulados.

Solicito que la entrega se realice de forma electrónica. De existir algún costo
de reproducción, favor notificarlo previamente. La Ley 141-2019 establece un
término expedito de diez (10) días laborables para responder.

Propósito: investigación de interés público sobre el uso de fondos públicos en
Puerto Rico. Esta solicitud forma parte del expediente {request_id}.

Atentamente,
{requester_name} — {requester_contact}
"""

# Template B — Federal FOIA (5 U.S.C. § 552)
_TEMPLATE_B = """\
To: {target_agency} — FOIA Officer
Re: Freedom of Information Act request (5 U.S.C. § 552)

Dear FOIA Officer:

Under the Freedom of Information Act, 5 U.S.C. § 552, I request copies of the
following records:

  - Record type: {record_type}
  - Time period: 2016 to present (or the broadest available period)
  - Geographic scope: records relating to Puerto Rico where applicable
  - Preferred format: machine-readable structured data (CSV, JSON, or a bulk
    database extract). If a bulk/API extract exists, please provide it in lieu
    of individual documents.

Fee waiver: I request a fee waiver because disclosure is in the public interest
— the records concern the operations and spending of government and are sought
for noncommercial public-interest research, not commercial use. If the request
cannot be granted in full, please release all reasonably segregable portions and
cite the specific exemption for any withholding.

This request corresponds to internal tracking id {request_id}.

Sincerely,
{requester_name} — {requester_contact}
"""

_TEMPLATES: dict[str, str] = {"PR": _TEMPLATE_A, "US": _TEMPLATE_B}


def _read_queue(root: Path) -> list[dict[str, str]]:
    with (root / PRIORITY_QUEUE).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_config(root: Path) -> dict[str, str]:
    return json.loads((root / REQUESTER_CONFIG).read_text(encoding="utf-8"))


def _letter_path(root: Path, request_id: str) -> Path:
    return root / OUT_DIR / f"{request_id}.md"


def _render_letter(row: dict[str, str], config: dict[str, str]) -> str:
    """Render the full letter markdown for one request row."""
    jur = row["jurisdiction"].strip().upper()
    template = _TEMPLATES.get(jur, _TEMPLATE_B)
    body = template.format(
        target_agency=row["target_agency"],
        record_type=row["record_type"],
        request_id=row["request_id"],
        requester_name=config.get("requester_name", "{{requester_name}}"),
        requester_contact=config.get("requester_contact", "{{requester_contact}}"),
    )
    statute_label = "PR Ley 141-2019" if jur == "PR" else "5 U.S.C. § 552 (Federal FOIA)"
    header = (
        f"# FOIA Request — {row['request_id']}\n\n"
        f"**Agency:** {row['target_agency']}  \n"
        f"**Record type:** {row['record_type']}  \n"
        f"**Jurisdiction:** {jur} ({statute_label})  \n"
        f"**Priority:** {row['priority']}  \n"
        f"**Status:** {row['request_status']}  \n\n"
        "---\n\n"
    )
    return header + body


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return one metadata entry per letter (does not write files)."""
    root = root or REPO_ROOT
    queue = _read_queue(root)
    config = _read_config(root)
    entries: list[dict[str, Any]] = []
    for row in queue:
        request_id = row["request_id"]
        path = f"{OUT_DIR}/{request_id}.md"
        content = _render_letter(row, config)
        entries.append(
            {
                "request_id": request_id,
                "target_source_id": row["target_source_id"],
                "target_agency": row["target_agency"],
                "jurisdiction": row["jurisdiction"],
                "priority": row["priority"],
                "request_status": row["request_status"],
                "path": path,
                "content": content,
            }
        )
    return entries


def check(entries: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not entries:
        problems.append("no FOIA letter entries produced")
        return problems
    for e in entries:
        content = e["content"]
        jur = e["jurisdiction"].strip().upper()
        # correct statute in the body
        if jur == "PR" and "Ley 141-2019" not in content:
            problems.append(f"{e['request_id']}: PR letter missing Ley 141-2019 citation")
        if jur == "US" and "5 U.S.C." not in content:
            problems.append(f"{e['request_id']}: US letter missing 5 U.S.C. citation")
        # all non-requester substitutions filled
        for key in ("target_agency", "record_type", "request_id"):
            if "{{" + key + "}}" in content:
                problems.append(f"{e['request_id']}: placeholder {{{{{key}}}}} was not substituted")
        # request_id appears in the body
        if e["request_id"] not in content:
            problems.append(f"{e['request_id']}: request_id missing from letter body")
    return problems


def _write(entries: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for e in entries:
        (out_dir / f"{e['request_id']}.md").write_text(e["content"], encoding="utf-8")


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the FOIA letters + manifest."""
    root = root or REPO_ROOT
    entries = build_rows(root)
    problems = check(entries, root)
    if problems:
        raise ValueError("build_foia_letters check failed: " + "; ".join(problems))
    _write(entries, root / OUT_DIR)
    manifest = {
        "producer_script": "scripts/build_foia_letters.py",
        "producer_phase": "TOP_FORM_FOIA_LETTERS",
        "source_inputs": [PRIORITY_QUEUE, REQUESTER_CONFIG],
        "output": OUT_DIR,
        "letter_count": len(entries),
        "jurisdictions": sorted({e["jurisdiction"] for e in entries}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build per-target FOIA request letters.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        entries = build_rows(root)
        problems = check(entries, root)
        print(
            json.dumps(
                {"ok": not problems, "letter_count": len(entries), "problems": problems}, indent=2
            )
        )
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
