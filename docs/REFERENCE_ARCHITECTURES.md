# REFERENCE ARCHITECTURES

## Purpose
This document captures architecture references used as conceptual inspiration only.

## Reference Patterns
- Open Contracting Data Standard (OCDS): procurement lifecycle concepts.
- Frictionless Data: table schemas and output contracts.
- OpenLineage / Marquez-style patterns: lineage event modeling and dataset provenance.
- Great Expectations / Soda-style patterns: validation gates and data quality controls.
- dbt-style layering: `raw -> staging -> normalized -> resolved -> linked -> graph_ready -> exports`.
- OCDS ontology concepts: graph semantics and procurement relationships.
- NetworkX / GEXF / GraphML: graph model and export formats.
- GeoPandas / GeoJSON: GIS-linked outputs and geometry exchange.

## Scope Guardrail
External repositories are references only. Do not copy code or add dependencies without license review and explicit approval.

## Implementation Posture
- Preserve local pipeline behavior unless an approved phase explicitly changes implementation.
- Prefer internal contracts and registries over ad-hoc source scripts.
- Treat reference architectures as vocabulary and design constraints, not copy/paste implementation sources.
