#!/usr/bin/env bash
set -euo pipefail
ROOT="$RUNNER_TEMP/recovered"
ARCHIVE="$RUNNER_TEMP/moneysweep_exact.tar.gz"
rm -rf "$ROOT"
mkdir -p "$ROOT"

PAYLOAD=".recovery/moneysweep-exact/payload"
EXPECTED_ARCHIVE_SHA="64ea47f4d62852f07e4e47a930003119f9d14821002bcc2bb7f5049135340d4d"
EXPECTED_CHUNK004_SHA="ee6e2502bfbd53dfbef846f5d7d7e93ec6966131a1037c79e41bfa528f2f0a60"

python - <<'PY'
from pathlib import Path
import hashlib, os
p=Path(".recovery/moneysweep-exact/payload/chunk-004.b64")
s="".join(p.read_text().split())
expected="ee6e2502bfbd53dfbef846f5d7d7e93ec6966131a1037c79e41bfa528f2f0a60"
if hashlib.sha256(s.encode()).hexdigest()!=expected:
    if len(s)!=15001:
        raise SystemExit(f"chunk-004 unexpected length {len(s)}")
    matches=[]
    for i in range(len(s)):
        c=s[:i]+s[i+1:]
        if hashlib.sha256(c.encode()).hexdigest()==expected:
            matches.append((i,c))
    if len(matches)!=1:
        raise SystemExit(f"chunk-004 repair candidates={len(matches)}")
    i,s=matches[0]
    print(f"CHUNK004_SELF_REPAIR=PASS removed_index={i}")
else:
    print("CHUNK004_ALREADY_EXACT=PASS")
Path(os.environ["RUNNER_TEMP"]).joinpath("chunk-004.exact.b64").write_text(s)
PY

build_candidate() {
  local label="$1"; shift
  local b64="$RUNNER_TEMP/$label.b64"
  : > "$b64"
  for f in "$@"; do
    test -f "$PAYLOAD/$f"
    if [ "$f" = "chunk-004.b64" ]; then
      tr -d '\\r\\n' < "$RUNNER_TEMP/chunk-004.exact.b64" >> "$b64"
    else
      tr -d '\\r\\n' < "$PAYLOAD/$f" >> "$b64"
    fi
  done
  base64 -d "$b64" > "$ARCHIVE" 2>/dev/null || return 1
  test "$(sha256sum "$ARCHIVE" | awk '{print $1}')" = "$EXPECTED_ARCHIVE_SHA"
}

matched=0
build_candidate split_tail chunk-000.b64 chunk-001.b64 chunk-002.b64 chunk-003.b64 chunk-004.b64 chunk-005.b64 chunk-006.b64 chunk-007.b64 chunk-008a.b64 chunk-008b.b64 chunk-008c.b64 chunk-009a.b64 chunk-009b.b64 chunk-009c.b64 chunk-010.b64 && matched=1 || true
if [ "$matched" = 0 ]; then
  build_candidate full_008_split_009 chunk-000.b64 chunk-001.b64 chunk-002.b64 chunk-003.b64 chunk-004.b64 chunk-005.b64 chunk-006.b64 chunk-007.b64 chunk-008.b64 chunk-009a.b64 chunk-009b.b64 chunk-009c.b64 chunk-010.b64 && matched=1 || true
fi
test "$matched" = 1
echo "$EXPECTED_ARCHIVE_SHA  $ARCHIVE" | sha256sum -c -
tar -xzf "$ARCHIVE" -C "$ROOT"

python - <<'PY'
from pathlib import Path
import hashlib, os
root=Path(os.environ["RUNNER_TEMP"])/"recovered"
rows=[]
for p in sorted(root.rglob("*")):
    if p.is_file():
        data=p.read_bytes()
        rows.append(f"{hashlib.sha256(data).hexdigest()}  {len(data)}  {p.relative_to(root).as_posix()}")
manifest=("\\n".join(rows)+"\\n").encode()
if len(rows)!=223:
    raise SystemExit(f"expected 223 files, got {len(rows)}")
got=hashlib.sha256(manifest).hexdigest()
expected="759cac6dc72b29f622e925dff1844c5ce0ec1fddad1832101a868fbbd6d70490"
if got!=expected:
    raise SystemExit(f"member manifest hash mismatch: {got}")
Path(".recovery/moneysweep-exact/member_manifest.txt").write_bytes(manifest)
print("RECOVERY_ARCHIVE_AND_MANIFEST_RECONSTRUCTION=PASS")
PY

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
