# LegislaPR manual/API-key export dropzone

Place operator-exported LegislaPR Puerto Rico session records here. Do not commit raw credentialed exports unless they are explicitly public and cleared for repository storage.

Recommended layout:

```text
data/manual/legislapr/
  README.md
  exports/
    <operator_export_files>.csv|json|xlsx
  manifests/
    export_manifest.csv
```

Manifest columns:

```csv
file_name,exported_at,session_label,source_system,record_count,sha256,operator_notes
```

API key handling:

```text
LEGISLAPR_API_KEY=<local only>
```

The API key must stay in `.env` or the operator secret store. It must never be committed.
