"""Patches app/src/main/assets/symbols.json for the Find X8 Ultra camera 7.006.123 build.

The shipped symbols.json is newer than the sym_*.py sources (309 camera / 31 gallery entries vs
246 / 29 when rebuilt), so this port rewrites only the affected entries in place instead of
regenerating the whole file:

  Zoom.labelBitmap        ZoomSeekBar keeps two Bitmap caches: H6 (icon, also read by drawIcon)
                          and J6 (label strip, drawn through Canvas.drawBitmap).
  EffectItemView et al.   the master-effect menu is intact, but its item holder no longer logs
                          "MasterEffectContainer"+"expand".  The families are if.b2 (Reno),
                          if.s2 (Vibe), if.y (GR) and if.s0 (Master); each has a $a/$c item
                          holder plus a $d/$f value holder that adds a TextView.
  Personalized.style      g1 is now the AppUiResponder; setup writes the style id into i1.
  Personalized.labels     Y0 became a boolean; setup writes the label list into X0.

  python port_x8u.py            patch, then report what changed
  python port_x8u.py --revert   restore the 7.006.119 entries
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "..", "..", "app", "src", "main", "assets", "symbols.json")

NEW = {
    ("camera", "Zoom.labelBitmap"): {"kind": "field", "name": "J6"},
    ("camera", "EffectItemView"): {"kind": "class", "name": "if.s0$c"},
    ("gallery", "Personalized.style"): {"kind": "field", "name": "i1"},
    ("gallery", "Personalized.labels"): {"kind": "field", "name": "X0"},
}
OLD = {
    ("camera", "Zoom.labelBitmap"): {"kind": "field", "name": "I6"},
    ("camera", "EffectItemView"): {"kind": "class", "strings": ["MasterEffectContainer", "expand"]},
    ("gallery", "Personalized.style"): {"kind": "field", "name": "g1"},
    ("gallery", "Personalized.labels"): {"kind": "field", "name": "Y0"},
}

spec = json.load(open(SPEC, encoding="utf-8"))
table = OLD if "--revert" in sys.argv else NEW
for (app, sid), patch in table.items():
    entry = spec[app].get(sid)
    if entry is None:
        print("MISSING", app, sid)
        continue
    before = dict(entry)
    if "strings" in entry and "strings" not in patch:
        del entry["strings"]
    entry.update(patch)
    if entry != before:
        print("patched", app, sid, {k: before.get(k) for k in ("name", "strings") if k in before},
              "->", {k: entry.get(k) for k in ("name", "strings") if k in entry})
json.dump(spec, open(SPEC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("written", SPEC)
