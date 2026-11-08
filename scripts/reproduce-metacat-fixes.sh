#!/bin/sh
# Runs Metacat/tests/reproduce-failures.ss on the patched Metacat in Docker, one fresh container per case.
# Usage (from anywhere):  bash scripts/reproduce-metacat-fixes.sh [case-key ...]     (no key: every case)
# Exit 0 only when every case does what its record says (KNOWN-FAILURES.md); the output goes to stdout.
# Docker must be running, the image metacat:1.2 built, and Metacat/build/source the patched build.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
METACAT="$ROOT/Metacat"
HERE="$METACAT/tests"
python3 "$METACAT/tools/reconstruct.py" --verify "$METACAT/build/source" || exit 1
if [ $# -gt 0 ]; then KEYS="$*"; else
  KEYS=$(grep -oE '\("[a-z0-9-]+" (run|trial|command-line|mcat-form)' "$HERE/reproduce-failures.ss" | sed 's/^("\([a-z0-9-]*\)".*/\1/'); fi
status=0
for key in $KEYS; do
  echo "=== $key"
  docker run --rm --platform linux/amd64 --network none --read-only --cpus 1 --memory 2g \
    --mount "type=bind,src=$METACAT/build/source,dst=/metacat,readonly" \
    --mount "type=bind,src=$HERE,dst=/tests,readonly" \
    --workdir /metacat --entrypoint env metacat:1.2 \
    -u DISPLAY scheme -q --script /tests/reproduce-failures.ss "$key"
  code=$?
  echo "exit $code"
  [ $code -eq 0 ] || status=1
done
echo "all cases: exit $status"
exit $status
