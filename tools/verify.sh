#!/usr/bin/env bash
# One gate for everything that can be checked without a phone.
#
#   tools/verify.sh            syntax + tests + payload reproducibility
#   tools/verify.sh --full     the above, plus regenerate the profiles from a dump
#
# Any failure stops the script with a non-zero exit code, so it is safe to use as a pre-commit hook.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-$HOME/AndroidTools/pyenv/bin/python}
DUMP=${MUSE_DUMP:-$HOME/Downloads/OmniCam-Handoff-FULL-20261101/x8u-dump/20261101-183522}

cd "$ROOT"
say() { printf '\n== %s ==\n' "$1"; }

say "shell syntax"
for f in module/*.sh tools/*.sh tools/offline_tests/run.sh; do
    [ -f "$f" ] || continue
    bash -n "$f"
    printf '  ok  %s\n' "$f"
done

say "python syntax"
"$PY" -m compileall -q tools >/dev/null
printf '  ok  tools/\n'

say "offline tests"
bash tools/offline_tests/run.sh | tail -3

say "config envelope"
"$PY" tools/offline_tests/envelope_roundtrip.py | tail -1

say "symbol profiles"
"$PY" tools/symbols/make_profile.py --check | tail -1

say "payload reproducibility"
"$PY" tools/profiles/build_x8u_payload.py --check | tail -2

if [ "${1:-}" = "--full" ]; then
    say "profile regeneration"
    "$PY" tools/profiles/gen_x8u_profiles.py --dump "$DUMP" | tail -5
    say "payload after regeneration"
    "$PY" tools/profiles/build_x8u_payload.py | tail -2
    "$PY" tools/profiles/build_x8u_payload.py --check | tail -2
fi

say "result"
echo "verify: ok"
