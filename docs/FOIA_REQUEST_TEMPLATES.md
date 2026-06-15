# FOIA / Public-Records Request Templates

Standardized request templates for the targets tracked in
[`reports/foia_priority_queue.csv`](../reports/foia_priority_queue.csv) (produced
by `scripts/build_foia_tracker.py`). Each open request in that queue carries a
`jurisdiction` (`PR` or `US`) and a `statute` — use the matching template below
and fill the `{{placeholders}}` from the queue row.

Yield and unresolved gaps for each request are tracked in
[`reports/foia_yield_tracking.csv`](../reports/foia_yield_tracking.csv).

---

## Template A — Puerto Rico public records (`jurisdiction = PR`)

Statute: **PR Ley 141-2019** (Ley de Transparencia y Procedimiento Expedito para
el Acceso a la Información Pública) and the constitutional right of access to
public information (Art. II, PR Constitution).

```
To: {{target_agency}} — Oficial de Acceso a la Información Pública
Re: Solicitud de acceso a información pública — Ley 141-2019

Estimado/a Oficial de Acceso:

Al amparo de la Ley 141-2019 y del derecho constitucional de acceso a la
información pública, solicito copia de los siguientes records:

  - Tipo de récord: {{record_type}}
  - Periodo: 2016 al presente (o el periodo disponible más amplio)
  - Formato preferido: datos estructurados (CSV o Excel); de no ser posible,
    PDF con datos tabulados.

Solicito que la entrega se realice de forma electrónica. De existir algún costo
de reproducción, favor notificarlo previamente. La Ley 141-2019 establece un
término expedito de diez (10) días laborables para responder.

Propósito: investigación de interés público sobre el uso de fondos públicos en
Puerto Rico. Esta solicitud forma parte del expediente {{request_id}}.

Atentamente,
{{requester_name}} — {{requester_contact}}
```

Applies to the PR targets in the queue (PRASA, OCPR / Oficina del Contralor,
COR3, OEG cabilderos, CEE donaciones, compras.pr.gov, and the infrastructure
revenue/contract targets: ACT/AutoExpreso, DTOP, Autoridad de los Puertos, AMA,
and Tren Urbano / ATI).

---

## Template B — Federal FOIA (`jurisdiction = US`)

Statute: **5 U.S.C. § 552** (Freedom of Information Act).

```
To: {{target_agency}} — FOIA Officer
Re: Freedom of Information Act request (5 U.S.C. § 552)

Dear FOIA Officer:

Under the Freedom of Information Act, 5 U.S.C. § 552, I request copies of the
following records:

  - Record type: {{record_type}}
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

This request corresponds to internal tracking id {{request_id}}.

Sincerely,
{{requester_name}} — {{requester_contact}}
```

Applies to the federal targets in the queue (HUD DRGR, GSA FSRS, SAM.gov).

---

## Filling a template from the queue

For each row of `reports/foia_priority_queue.csv`:

| Placeholder | Source column |
|-------------|---------------|
| `{{target_agency}}` | `target_agency` |
| `{{record_type}}` | `record_type` |
| `{{request_id}}` | `request_id` |
| template choice | `jurisdiction` → A (PR) or B (US); cross-check `statute` |

After submitting, update the request's `request_status` (and later
`records_received` / `yield_status` in the yield tracker) as responses arrive.
