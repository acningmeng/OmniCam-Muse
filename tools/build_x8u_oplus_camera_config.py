"""Rebuild the X8 Ultra vendor-tag table so the modes and the palette exist.

`/odm/etc/camera/config/oplus_camera_config` is the flat vendor tag table the camera reads through
CameraConfig: one record per tag, `{"VendorTag": ..., "Type": ..., "Count": ..., "Value": ...}`.
The X9 Ultra payload we used to ship is a different build (721 tags, lighthouse* sensors); binding it
onto this device would downgrade it. Instead this script starts from the device's own table and adds
only the tags the port needs, copying each record verbatim from a reference table that already
carries it -- so nothing is retyped and no sensor name is transplanted.

Tags added (all present in the reference, none in the stock table):

  com.oplus.feature.retro.camera.support                  POP as a mode
  com.oplus.feature.retro.camera.livephoto.output.size    Live photo sizes POP needs
  com.oplus.camera.retro.fisheye.enable                   fisheye inside POP
  com.oplus.camera.livephoto.grmode.support               GR keeps Live photo off
  com.oplus.camera.gr.raw.capture_defer.not.support       GR raw without deferral
  com.oplus.gr.mode.support                               GR mode itself
  com.oplus.available.gr.mode.zoomvalues                  GR zoom stops
  com.oplus.gr.mode.marked.zoomvalues                     GR marked stops
  com.oplus.flashlevel.configurable.support               flash level menu
  com.oplus.feature.color.palette.support                 master palette
  com.oplus.ipu.color.palette.texture.support             palette textures through IPU
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import oplus_config

KEY = bytes.fromhex("6f2170406c247525535e4326412a4d28")
WANTED = [
    "com.oplus.feature.retro.camera.support",
    "com.oplus.feature.retro.camera.livephoto.output.size",
    "com.oplus.camera.retro.fisheye.enable",
    "com.oplus.camera.livephoto.grmode.support",
    "com.oplus.camera.gr.raw.capture_defer.not.support",
    "com.oplus.gr.mode.support",
    "com.oplus.available.gr.mode.zoomvalues",
    "com.oplus.gr.mode.marked.zoomvalues",
    "com.oplus.flashlevel.configurable.support",
    "com.oplus.feature.color.palette.support",
    "com.oplus.ipu.color.palette.texture.support",
]


def decode(raw: bytes) -> str:
    return oplus_config.decode(raw, KEY)


def records(text: str) -> dict:
    table = {}
    for entry in json.loads(text):
        table[entry["VendorTag"]] = entry
    return table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", required=True, type=Path, help="the device's own oplus_camera_config")
    parser.add_argument("--reference", required=True, type=Path, help="a table that already has the tags")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--envelope", action="store_true",
                        help="wrap the result in the 01 01 envelope instead of writing plain text")
    args = parser.parse_args()

    stock = records(decode(args.stock.read_bytes()))
    reference = records(decode(args.reference.read_bytes()))

    added, missing = [], []
    for tag in WANTED:
        if tag in stock:
            continue
        if tag not in reference:
            missing.append(tag)
            continue
        stock[tag] = reference[tag]
        added.append((tag, reference[tag]["Value"]))

    ordered = sorted(stock.values(), key=lambda entry: entry["VendorTag"])
    text = json.dumps(ordered, ensure_ascii=False, indent=4, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    oplus_config.write(args.out, text, envelope=args.envelope)

    print(f"stock {len(stock) - len(added)} tags -> {len(stock)} tags, added {len(added)}")
    for tag, value in added:
        print(f"  + {tag} = {value}")
    if missing:
        print("reference is missing: " + ", ".join(missing))
        return 1
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
