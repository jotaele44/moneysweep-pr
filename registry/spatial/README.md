# Spatial Registry

Expected file:

```text
pr_grid_full_cell_index_saturated.csv
```

Expected SHA-256:

```text
17733f3f18c8a644e31c1eb25fb27b73b4bf353c6de57d5203c4311e05d64483
```

The full CSV is 6,807,952 bytes and contains 98,304 grid cells.

Validation command:

```bash
python scripts/validate_pr_grid.py --require-sha
```
