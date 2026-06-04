#!/usr/bin/env bash
set -euo pipefail

URI="neo4j://127.0.0.1:7687"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/prepa_neo4j_import.cypher"

if command -v cypher-shell >/dev/null 2>&1; then
  CYPHER_SHELL="$(command -v cypher-shell)"
else
  CYPHER_SHELL="$(find "$HOME/Library/Application Support/Neo4j Desktop" -type f -name cypher-shell 2>/dev/null | head -1)"
fi

if [ -z "${CYPHER_SHELL:-}" ]; then
  echo "FAIL: cypher-shell not found"
  exit 1
fi

echo "Using cypher-shell: $CYPHER_SHELL"
echo "Target URI: $URI"
echo "Cypher script: $SCRIPT"
echo "This will mutate the local Neo4j database."

read -r -p "Type LOAD_PREPA to proceed: " CONFIRM
if [ "$CONFIRM" != "LOAD_PREPA" ]; then
  echo "Cancelled."
  exit 0
fi

"$CYPHER_SHELL" -a "$URI" -f "$SCRIPT"
