#!/usr/bin/env bash
set -euo pipefail
ROOT="$RUNNER_TEMP/recovered"
ARCHIVE="$RUNNER_TEMP/moneysweep_exact.tar.gz"
rm -rf "$ROOT"; mkdir -p "$ROOT"
base64 -d .recovery/moneysweep-exact/payload.tar.gz.b64 > "$ARCHIVE"
echo "64ea47f4d62852f07e4e47a930003119f9d14821002bcc2bb7f5049135340d4d  $ARCHIVE" | sha256sum -c -
tar -xzf "$ARCHIVE" -C "$ROOT"
python - <<'PY'
from pathlib import Path
import hashlib, os
root=Path(os.environ['RUNNER_TEMP'])/'recovered'
manifest=Path('.recovery/moneysweep-exact/member_manifest.txt')
expected={}
for line in manifest.read_text().splitlines():
    if line.strip():
        sha,size,path=line.split('  ',2); expected[path]=(int(size),sha)
actual=sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
assert set(actual)==set(expected),(len(actual),len(expected))
for rel in actual:
    data=(root/rel).read_bytes(); size,sha=expected[rel]
    assert len(data)==size and hashlib.sha256(data).hexdigest()==sha, rel
assert len(actual)==223,len(actual)
print('EXACT_MEMBER_VERIFICATION=PASS'); print('RECOVERED_FILE_COUNT=223')
PY
cd "$ROOT"
cp package.json package.original.json
sha256sum package.original.json > recovery-package-hashes.txt
export NPM_CONFIG_LEGACY_PEER_DEPS=true
npm install --no-audit --no-fund --ignore-scripts
npm install --save-dev --no-audit --no-fund --ignore-scripts vitest@3.2.4 jsdom@26.1.0 @testing-library/react@16.2.0 @testing-library/dom@10.4.1
sha256sum package.json package-lock.json >> recovery-package-hashes.txt
node -v > recovery-environment.txt; npm -v >> recovery-environment.txt; printf 'NPM_CONFIG_LEGACY_PEER_DEPS=true\n' >> recovery-environment.txt
cp "$GITHUB_WORKSPACE/.recovery/moneysweep-exact/recovery.vitest.config.mts" recovery.vitest.config.mts
cp "$GITHUB_WORKSPACE/.recovery/moneysweep-exact/recovery.vitest.setup.mjs" recovery.vitest.setup.mjs
sha256sum recovery.vitest.config.mts recovery.vitest.setup.mjs > recovery-harness-hashes.txt
find helpers -type f \( -name '*.spec.ts' -o -name '*.spec.tsx' \) -print | sort > recovery-spec-files.txt
count=$(wc -l < recovery-spec-files.txt | tr -d ' '); echo "RECOVERED_SPEC_FILE_COUNT=$count"; test "$count" = "17"
printf 'helpers/useDebounce.spec.tsx\tEMPTY_SPEC_NONEXECUTABLE\n' > recovery-spec-classification.tsv
set +e
npx vitest run --config recovery.vitest.config.mts --reporter=verbose 2>&1 | tee recovery-vitest.log
status=${PIPESTATUS[0]}; set -e
echo "$status" > recovery-test-exit.txt
exit 0