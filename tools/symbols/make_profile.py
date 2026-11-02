"""Derive per-device symbol profiles from the shipped spec.

`assets/symbols.json` describes the Find X9 Ultra builds (309 camera + 31 gallery symbols). The
Find X8 Ultra camera is a different build: six symbols resolve to different names or lose the
string anchors the X9 spec relies on. Rather than rewriting the base spec in place (which makes a
second device impossible and hides the difference from review), this tool emits a profile:

    app/src/main/assets/profiles/x8u/profile.json    which models this profile applies to
    app/src/main/assets/profiles/x8u/symbols.json    the spec the app loads on those models

The app picks a profile in `SymbolProfile` by Build.MODEL (and the camera's versionName when the
context is available), falling back to `assets/symbols.json`.

    python tools/symbols/make_profile.py            write the profile
    python tools/symbols/make_profile.py --check    fail if the files on disk are stale

Why each override exists is recorded next to it below: the values are the whole point of the
profile, so they are readable without digging through git history.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
BASE = PROJECT / "app/src/main/assets/symbols.json"
ASSETS = PROJECT / "app/src/main/assets/profiles"

PROFILES = {
    "x8u": {
        "profileId": "pku110-17.0.0.104-camera-7.006.123",
        "models": ["PKU110", "PKJ110"],
        "cameraVersion": "7.006.123",
        "note": "Find X8 Ultra (PKU110/PKJ110), OplusCamera 7.006.123",
        "overrides": {
            # ZoomSeekBar keeps two Bitmap caches: H6 (icon, read by drawIcon) and J6 (label).
            ("camera", "Zoom.labelBitmap"): {"kind": "field", "name": "J6"},
            # The master-effect menu lost the "MasterEffectContainer"+"expand" anchors; if.s0 is the
            # Master family container and $c its item holder.
            ("camera", "EffectItemView"): {"kind": "class", "name": "if.s0$c"},
            # g1 became the AppUiResponder; setup writes the style id into i1.
            ("gallery", "Personalized.style"): {"kind": "field", "name": "i1"},
            # Y0 became a boolean; setup writes the label list into X0.
            ("gallery", "Personalized.labels"): {"kind": "field", "name": "X0"},
        },
    },
}


def render(name: str, base: dict) -> tuple[str, dict]:
    profile = PROFILES[name]
    spec = json.loads(json.dumps(base))  # deep copy, keep the base untouched
    for (section, symbol), patch in profile["overrides"].items():
        entry = spec.get(section, {}).get(symbol)
        if entry is None:
            raise SystemExit(f"{name}: {section}.{symbol} is not in the base spec")
        entry.pop("strings", None) if "strings" not in patch else None
        entry.update(patch)
    meta = {key: profile[key] for key in ("profileId", "models", "cameraVersion", "note")}
    meta["symbols"] = "symbols.json"
    meta["sections"] = sorted(spec)
    return name, (meta, spec)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify the committed profile is current")
    args = parser.parse_args()

    base = json.loads(BASE.read_text(encoding="utf-8"))
    problems = 0
    for name in PROFILES:
        _, (meta, spec) = render(name, base)
        directory = ASSETS / name
        files = {
            directory / "profile.json": json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
            directory / "symbols.json": json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
        }
        for path, text in files.items():
            if args.check:
                if not path.exists():
                    print(f"STALE {path}: missing")
                    problems += 1
                elif path.read_text(encoding="utf-8") != text:
                    print(f"STALE {path}: differs from the base spec")
                    problems += 1
                else:
                    print(f"ok    {path.relative_to(PROJECT)}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                print(f"wrote {path.relative_to(PROJECT)} ({len(text)} chars)")

    if args.check and problems:
        print(f"profile check: {problems} stale file(s); run tools/symbols/make_profile.py")
        return 1
    print("profile check: ok" if args.check else "profiles written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
