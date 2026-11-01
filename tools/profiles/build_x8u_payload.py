"""Synthesise module/payload from module/profiles/x8u/deltas.json, then record what was produced.

The payload used to be edited in place by tools/port_x8u_config.py, which made the package
irreproducible: a second run saw its own output as the base. This script always starts from the X9
Ultra file committed at HEAD (git show HEAD:module/payload/<name>), applies the deltas archive in
order, and writes a manifest with the digest of every payload file. `--check` recomputes and compares,
so CI (and the packaging check) can tell a stale payload from a fresh one.

    python tools/profiles/build_x8u_payload.py            # build payload + payload-manifest.json
    python tools/profiles/build_x8u_payload.py --check     # verify the tree matches the manifest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
MODULE = PROJECT / "module"
PROFILE = MODULE / "profiles/x8u"
GIT = ("/Library/Developer/CommandLineTools/usr/bin/git"
       if Path("/Library/Developer/CommandLineTools/usr/bin/git").exists() else "git")

sys.path.insert(0, str(PROJECT / "tools"))
from patch_25mp import pop_basictone  # noqa: E402  (POP branch is shared with the X9 pipeline)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base_of(rel: str, bases: dict) -> bytes:
    """The X8U stock config exported by the generator, digested so a stale base cannot slip in."""
    entry = bases[rel]
    data = (PROJECT / entry["file"]).read_bytes()
    if sha256(data) != entry["sha256"]:
        raise RuntimeError("%s does not match the digest in deltas.json" % entry["file"])
    return data


def insert(target: dict, path: str, value, expect: str) -> None:
    group, _, name = path.partition(".")
    if group not in target:
        raise RuntimeError("group %s is not in the base payload" % group)
    if expect == "absent" and name in target[group]:
        raise RuntimeError("%s is already present; the deltas archive is stale" % path)
    target[group][name] = value


def apply_deltas() -> tuple[dict[str, bytes], list[dict]]:
    deltas = json.loads((PROFILE / "deltas.json").read_text(encoding="utf-8"))
    outputs: dict[str, bytes] = {}
    applied: list[dict] = []
    for target in deltas["targets"]:
        rel = target["path"]
        raw = base_of(rel, deltas["bases"])
        if target["codec"] == "json":
            document = json.loads(raw)
            for op in target["ops"]:
                if op["op"] == "insert":
                    insert(document, op["jsonPath"], op["value"], op["expect"])
                    applied.append({"target": rel, "id": op["id"], "op": "insert"})
                elif op["op"] == "patch" and op["patchId"] == "pop-basictone":
                    text = json.dumps(document, ensure_ascii=False, indent=2)
                    patched = pop_basictone(text)
                    document = json.loads(patched)
                    applied.append({"target": rel, "id": op["id"], "op": "patch",
                                    "hits": patched.count("retro_camera_mode")})
                else:
                    raise RuntimeError("unknown op %s" % op)
            outputs[rel] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        else:
            raise RuntimeError("unknown codec %s" % target["codec"])
    return outputs, applied


def payload_inventory() -> list[dict]:
    root = MODULE / "payload"
    return [{"path": str(path.relative_to(MODULE)), "bytes": path.stat().st_size,
             "sha256": sha256(path.read_bytes())}
            for path in sorted(root.rglob("*")) if path.is_file()]


def build() -> int:
    deltas = json.loads((PROFILE / "deltas.json").read_text(encoding="utf-8"))
    outputs, applied = apply_deltas()
    for target in deltas["targets"]:
        rel = target["path"]
        path = MODULE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        before = sha256(path.read_bytes()) if path.exists() else "absent"
        path.write_bytes(outputs[rel])
        print("%-52s %s -> %d B (%s)" % (rel, before[:12], len(outputs[rel]),
                                         sha256(outputs[rel])[:12]))
    manifest = {
        "schemaVersion": 1,
        "profileId": json.loads((PROFILE / "device.json").read_text(encoding="utf-8"))["profileId"],
        "deltasSha256": sha256((PROFILE / "deltas.json").read_bytes()),
        "applied": applied,
        "payload": payload_inventory(),
    }
    (PROFILE / "payload-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("applied %d ops, manifest covers %d payload files" % (len(applied), len(manifest["payload"])))
    return 0


def check() -> int:
    manifest = json.loads((PROFILE / "payload-manifest.json").read_text(encoding="utf-8"))
    problems = []
    if sha256((PROFILE / "deltas.json").read_bytes()) != manifest["deltasSha256"]:
        problems.append("deltas.json changed after the payload was built")
    recorded = {row["path"]: row for row in manifest["payload"]}
    current = {row["path"]: row for row in payload_inventory()}
    for path in sorted(set(recorded) | set(current)):
        if path not in current:
            problems.append("%s is in the manifest but missing on disk" % path)
        elif path not in recorded:
            problems.append("%s is on disk but not in the manifest" % path)
        elif recorded[path]["sha256"] != current[path]["sha256"]:
            problems.append("%s digest %s != manifest %s"
                            % (path, current[path]["sha256"][:12], recorded[path]["sha256"][:12]))
    # Re-synthesis must reproduce the same bytes, otherwise the payload carries hand edits again.
    outputs, _ = apply_deltas()
    for rel, data in outputs.items():
        if (MODULE / rel).read_bytes() != data:
            problems.append("%s does not match a fresh synthesis from HEAD + deltas" % rel)
    for line in problems:
        print("MISMATCH %s" % line)
    print("payload check: %s (%d files)" % ("PASS" if not problems else "FAIL", len(current)))
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return check() if parser.parse_args().check else build()


if __name__ == "__main__":
    sys.exit(main())
