"""
[已由 tools/profiles/ 的档案化流水线取代] 这个脚本是第一次移植时的一次性迁移工具：它直接改
module/payload，第二次运行会把上一次的输出当成 base。现在 payload 由 deltas.json + base/ 重新合成
（tools/profiles/build_x8u_payload.py），一致性由 payload-manifest.json 与 check_x8u_package.py 保证。
保留此文件只为追溯当时的增量。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

PROJECT = Path(__file__).resolve().parent.parent
PAYLOAD = PROJECT / "module/payload"
REPORT = PROJECT / "build/x8u/config_port.txt"
GIT = "/Library/Developer/CommandLineTools/usr/bin/git" if Path(
    "/Library/Developer/CommandLineTools/usr/bin/git").exists() else "git"

DECISION = "oplus_camera_preview_decision_config.json"
UNIT = "camera_unit_config"


def config_key(security: Path) -> bytes:
    data = security.read_bytes()
    return bytes(value ^ 0x3F for value in data[0x7AB:0x7AB + 32])[::2]


def decode(path: Path, key: bytes) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\x01\x01":
        if data[-1] != 0xFF:
            raise RuntimeError("unexpected config envelope: %s" % path)
        return unpad(AES.new(key, AES.MODE_ECB).decrypt(data[4:-4]), 16)
    return data


def shipped(name: str) -> bytes:
    """The X9 Ultra file as committed to the repository, so re-running this script stays idempotent."""
    out = subprocess.run([GIT, "show", "HEAD:module/payload/%s" % name], cwd=PROJECT,
                         capture_output=True, check=True)
    return out.stdout


def merge_unit(base: dict, x9: dict) -> dict[str, list[str]]:
    added: dict[str, list[str]] = {}
    for group, entries in x9.items():
        if not isinstance(entries, dict):
            continue
        current = base.get(group)
        if not isinstance(current, dict):
            continue
        new = [name for name in entries if name not in current]
        for name in new:
            current[name] = entries[name]
        if new:
            added[group] = new
    return added


def pop_basictone(text: str) -> str:
    from patch_25mp import pop_basictone as patch
    return patch(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", type=Path, help="device dump directory holding the decoded configs")
    parser.add_argument("--security", type=Path, help="stock libOplusSecurity.so of the target device")
    parser.add_argument("--key", help="AES key as hex, instead of --security")
    parser.add_argument("--revert", action="store_true", help="restore module/payload from git")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.revert:
        subprocess.run([GIT, "checkout", "--", "module/payload"], cwd=PROJECT, check=True)
        print("module/payload restored from git")
        return 0

    if not args.live:
        parser.error("--live is required")
    key = bytes.fromhex(args.key) if args.key else None
    if key is None:
        if not args.security:
            parser.error("--security or --key is required")
        key = config_key(args.security)

    lines = ["target: %s" % args.live, "key: %s" % key.hex(), ""]

    # camera_unit_config: X8 Ultra base, X9 Ultra additions on top.
    live_unit = decode(args.live / UNIT, key)
    base = json.loads(live_unit)
    x9_base = json.loads(decode_bytes(shipped(UNIT), key))
    added = merge_unit(base, x9_base)
    total = sum(len(v) for v in added.values())
    lines.append("%s: %d entries added from the X9 Ultra payload" % (UNIT, total))
    for group, names in added.items():
        lines.append("  %-28s +%d %s" % (group, len(names), ", ".join(names[:8]) + (" ..." if len(names) > 8 else "")))
    unit_out = json.dumps(base, indent=2, ensure_ascii=False).encode()

    # decision config: X8 Ultra base, POP branch and its non-POP guard on SINGLE_ALGO_BASIC_TONE.
    live_dec = decode(args.live / DECISION, key).decode()
    if "paramsHolder->retro_camera_mode" in live_dec:
        decision_out = live_dec.encode()
        lines.append("%s: already carries the POP branch, left as is" % DECISION)
    else:
        patched = pop_basictone(live_dec)
        json.loads(patched)  # fail loudly instead of shipping a broken config
        decision_out = patched.encode()
        lines.append("%s: POP branch + non-POP guard inserted (%d -> %d bytes)" % (DECISION, len(live_dec), len(patched)))

    for name in ("oplus_camera_config", "oplus_camera_aps_config", "oplus_camera_algo_switch_config",
                 "camera_unit_feature_config.protobuf"):
        live = decode(args.live / name, key)
        x9 = decode_bytes(shipped(name), key)
        lines.append("%s: untouched (device %d bytes, X9 Ultra payload %d bytes)" % (name, len(live), len(x9)))

    lines.append("")
    lines.append("written: %s, %s" % (UNIT, DECISION))
    report = "\n".join(lines)

    if not args.dry_run:
        (PAYLOAD / UNIT).write_bytes(unit_out)
        (PAYLOAD / DECISION).write_bytes(decision_out)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0


def decode_bytes(data: bytes, key: bytes) -> bytes:
    if data[:2] == b"\x01\x01":
        return unpad(AES.new(key, AES.MODE_ECB).decrypt(data[4:-4]), 16)
    return data


if __name__ == "__main__":
    sys.exit(main())
