#!/usr/bin/env bash
set -euo pipefail
ROOT="$RUNNER_TEMP/recovered"
ARCHIVE="$RUNNER_TEMP/moneysweep_exact.tar.gz"
rm -rf "$ROOT"
mkdir -p "$ROOT"

test -f .recovery/moneysweep-exact/moneysweep_exact.tar.gz
cp .recovery/moneysweep-exact/moneysweep_exact.tar.gz "$ARCHIVE"
echo "64ea47f4d62852f07e4e47a930003119f9d14821002bcc2bb7f5049135340d4d  $ARCHIVE" | sha256sum -c -
tar -xzf "$ARCHIVE" -C "$ROOT"

python - <<'PY'
from pathlib import Path
import hashlib, os, json
root=Path(os.environ["RUNNER_TEMP"])/"recovered"
manifest=Path(".recovery/moneysweep-exact/member_manifest.txt")
assert manifest.exists(), "member manifest missing"
expected={}
for line in manifest.read_text().splitlines():
    if not line.strip(): continue
    sha,size,path=line.split("  ",2)
    expected[path]=(int(size),sha)
actual=sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
if set(actual)!=set(expected): raise SystemExit("member-set mismatch")
for rel in actual:
    data=(root/rel).read_bytes(); size,sha=expected[rel]
    if len(data)!=size or hashlib.sha256(data).hexdigest()!=sha:
        raise SystemExit(f"member mismatch: {rel}")
if len(actual)!=223: raise SystemExit(f"expected 223 files, got {len(actual)}")
print("EXACT_MEMBER_VERIFICATION=PASS")
print("RECOVERED_FILE_COUNT=223")
PY

cd "$ROOT"
cp package.json package.original.json
node - <<'NODE'
const fs=require("fs");
const p=JSON.parse(fs.readFileSync("package.json","utf8"));
const snap=JSON.parse(fs.readFileSync("static/__dev/dependencies.json","utf8"));
p.devDependencies=p.devDependencies||{};
for(const [k,v] of Object.entries(snap)){
  if(!(k in (p.dependencies||{})) && !(k in p.devDependencies)) p.devDependencies[k]=v;
}
fs.writeFileSync("package.json",JSON.stringify(p,null,2)+"\n");
NODE
export NPM_CONFIG_LEGACY_PEER_DEPS=true
npm install --no-audit --no-fund --ignore-scripts
npm install --save-dev --no-audit --no-fund --ignore-scripts vitest@3.2.4 jsdom@26.1.0 @testing-library/dom@10.4.1
cp "$GITHUB_WORKSPACE/.recovery/moneysweep-exact/recovery.vitest.config.mts" recovery.vitest.config.mts
cp "$GITHUB_WORKSPACE/.recovery/moneysweep-exact/recovery.vitest.setup.mjs" recovery.vitest.setup.mjs
sha256sum package.original.json package.json package-lock.json recovery.vitest.config.mts recovery.vitest.setup.mjs > recovery-hashes.txt
node -v > recovery-environment.txt
npm -v >> recovery-environment.txt

find . -type f \( -name '*.spec.ts' -o -name '*.spec.tsx' \) -not -path './node_modules/*' -print | sed 's#^./##' | sort > recovery-spec-files.txt
count=$(wc -l < recovery-spec-files.txt | tr -d ' ')
echo "RECOVERED_SPEC_FILE_COUNT=$count"
test "$count" = "17"

: > recovery-spec-classification.tsv
mapfile -t exec_specs < <(while read -r f; do
  if grep -Eq '(^|[^A-Za-z])(it|test)[[:space:]]*\(' "$f"; then
    printf '%s\tEXECUTABLE\n' "$f" >> recovery-spec-classification.tsv
    printf '%s\n' "$f"
  else
    printf '%s\tEMPTY_SPEC_NONEXECUTABLE\n' "$f" >> recovery-spec-classification.tsv
  fi
done < recovery-spec-files.txt)

set +e
npx vitest run --config recovery.vitest.config.mts --reporter=verbose "${exec_specs[@]}" 2>&1 | tee recovery-vitest.log
status=${PIPESTATUS[0]}
set -e
echo "$status" > recovery-test-exit.txt
exit 0
