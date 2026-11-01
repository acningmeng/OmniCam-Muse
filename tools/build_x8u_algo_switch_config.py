"""Rebuild the X8 Ultra APS algorithm-switch table so the POP (retroCamera) mode exists.

Why this file decides whether the shutter works
-----------------------------------------------
`/odm/etc/camera/config/oplus_camera_algo_switch_config` is read by
`com.oplus.ocs.camera.configure.AlgoSwitchConfig`, which stores two maps:

    sCaptureConfigMap["<mode>"]        <- aps_capture_configs[]
    sPreviewConfigMap["<mode>@<id>"]   <- aps_preview_configs[]

`BaseMode.m8()` (the shutter path) asks APS for a preview result for the current mode. With no
entry under that mode the lookup returns null, APS produces nothing, and the shutter handler
returns early with its state field still at -1 -- the shutter looks live, taps register, and no
capture request is ever issued. That is exactly what POP does on the Find X8 Ultra: the stock
table carries 21 capture modes and 36 preview modes and `retroCamera` is in neither list, while
the Find X9 Ultra's copy has it in both.

The stock file is not strict JSON: it is JSON with `//` comments, so it is decoded, edited and
re-emitted as plain JSON (the camera's parser accepts both).

Inputs
------
--stock      the device's own oplus_camera_algo_switch_config (still in its `01 01` envelope)
--reference  a table that already carries the retroCamera blocks (the X9 Ultra payload we ship)

Output: plain JSON, same key order, stock file_version, both retroCamera blocks appended right
after the `common` entry of their respective lists.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from Crypto.Cipher import AES

KEY = bytes.fromhex("6f2170406c247525535e4326412a4d28")
ENVELOPE_HEAD = 4
ENVELOPE_TAIL = 4
MODE = "retroCamera"
SECTIONS = ("aps_capture_configs", "aps_preview_configs")


def decode_stock(raw: bytes) -> str:
    if raw[:2] != b"\x01\x01":
        return raw.decode("utf-8")
    body = raw[ENVELOPE_HEAD:len(raw) - ENVELOPE_TAIL]
    plain = AES.new(KEY, AES.MODE_ECB).decrypt(body)
    return plain[:-plain[-1]].decode("utf-8")


def strip_comments(text: str) -> str:
    out: list[str] = []
    index, size, in_string, escaped = 0, len(text), False, False
    while index < size:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < size and text[index + 1] == "/":
            while index < size and text[index] not in "\r\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def load(text: str) -> dict:
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", strip_comments(text)))


def blocks(table: dict, section: str) -> dict:
    for entry in table.get(section, []):
        if entry.get("mode") == MODE:
            return entry
    raise SystemExit(f"reference has no {MODE} block in {section}")


def insert_after_common(table: dict, section: str, entry: dict) -> None:
    items = table.setdefault(section, [])
    if any(item.get("mode") == MODE for item in items):
        return
    index = next((i for i, item in enumerate(items) if item.get("mode") == "common"), 0) + 1
    items.insert(index, entry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    stock_text = decode_stock(args.stock.read_bytes())
    reference_text = decode_stock(args.reference.read_bytes())
    stock, reference = load(stock_text), load(reference_text)

    before = {section: [item.get("mode") for item in stock.get(section, [])] for section in SECTIONS}
    for section in SECTIONS:
        insert_after_common(stock, section, blocks(reference, section))
    after = {section: [item.get("mode") for item in stock.get(section, [])] for section in SECTIONS}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(stock, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")

    print(f"stock file_version {stock.get('file_version')} aps_version {stock.get('aps_version')}")
    for section in SECTIONS:
        print(f"{section}: {len(before[section])} -> {len(after[section])} modes, "
              f"{MODE} at index {after[section].index(MODE)}")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
