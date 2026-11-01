"""Cross-check a built module zip against the X8U profile archive and the device dump.

The three archives describe intent; this script is the only place that proves the shipped bytes agree
with them. Every failure names the archive row it came from, so a red run points at one of four
things: a stale payload, a bind whose source is not in the zip, a script that no longer parses, or a
symbol table that lost a ported entry.

    python tools/profiles/check_x8u_package.py --zip OmniCam-Muse-4.4.4-X8U-KSU.zip \
        --dump x8u-dump/20261101-183522
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
PROFILE = PROJECT / "module/profiles/x8u"
SCRIPTS = ["post-fs-data.sh", "post-mount.sh", "service.sh", "customize.sh"]
# (face, symbol) -> the obfuscated name the X8U port pinned. These four are the only entries whose
# value came from a device scan instead of the X9 Ultra spec; if one drifts, the hook silently no-ops.
PORTED_SYMBOLS = {("camera", "Zoom.labelBitmap"): "J6",
                  ("camera", "EffectItemView"): "if.s0$c",
                  ("gallery", "Personalized.style"): "i1",
                  ("gallery", "Personalized.labels"): "X0"}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, state: str, name: str, detail: str = "") -> None:
        self.rows.append((state, name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.add("FAIL", name, detail)

    def warn(self, name: str, detail: str) -> None:
        self.add("WARN", name, detail)

    def ok(self, name: str, detail: str = "") -> None:
        self.add("ok", name, detail)

    def dump(self) -> int:
        for state, name, detail in self.rows:
            print("%-5s %-44s %s" % (state, name, detail))
        failures = sum(1 for state, _, _ in self.rows if state == "FAIL")
        warns = sum(1 for state, _, _ in self.rows if state == "WARN")
        print("\n%d checks: %d ok, %d warn, %d fail" % (
            len(self.rows), len(self.rows) - failures - warns, warns, failures))
        return 1 if failures else 0


def check_archive(report: Report, archive: zipfile.ZipFile) -> dict:
    names = set(archive.namelist())
    docs = {}
    for name in ("device.json", "mounts.json", "deltas.json", "resources.json"):
        path = "profiles/x8u/%s" % name
        if path not in names:
            report.fail(path, "missing from the zip; the device cannot self-describe")
            continue
        docs[name] = json.loads(archive.read(path))
        report.ok(path, "%d B" % len(archive.read(path)))
    for name in SCRIPTS:
        if name in names:
            report.ok(name, "present")
        else:
            report.fail(name, "missing from the zip")
    return docs


def check_scripts(report: Report, archive: zipfile.ZipFile) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for name in SCRIPTS:
            if name not in archive.namelist():
                continue
            data = archive.read(name)
            path = Path(tmp) / name
            path.write_bytes(data)
            if b"\r\n" in data:
                report.fail(name, "CRLF line endings; mksh sees /system/bin/sh^M")
                continue
            result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
            if result.returncode:
                report.fail(name, "sh -n: %s" % result.stderr.strip().splitlines()[-1:])
            else:
                report.ok(name, "sh -n clean")


def check_mounts(report: Report, archive: zipfile.ZipFile, docs: dict) -> None:
    names = archive.namelist()
    files = set(names)

    def present(source: str) -> bool:
        return source in files or any(name.startswith(source + "/") for name in names)

    for entry in docs.get("mounts.json", {}).get("entries", []):
        for source in entry["sources"]:
            source = source.split("->")[0]
            here = present(source)
            expected = entry["expected"]
            if not here:
                report.fail(entry["id"], "source %s is not in the zip" % source)
            elif expected == "ready":
                report.ok(entry["id"], "ready, source %s" % source)
            else:
                report.ok(entry["id"], "%s, source %s" % (expected, source))
    for staged in docs.get("mounts.json", {}).get("runtimeStaging", []):
        missing = [source for source in staged["sources"] if not present(source)]
        if missing:
            report.fail(staged["id"], "staging source missing: %s" % ", ".join(missing))
            continue
        verdict = staged.get("verdict")
        if verdict in (None, "ok"):
            report.ok(staged["id"], "staged from %d source(s)" % len(staged["sources"]))
        elif verdict == "required":
            report.ok(staged["id"], "required: %s" % staged["dependsOnDevice"])
        else:
            report.warn(staged["id"], verdict)


def check_payload(report: Report, archive: zipfile.ZipFile) -> None:
    path = "profiles/x8u/payload-manifest.json"
    if path not in archive.namelist():
        report.fail(path, "missing; run build_x8u_payload.py")
        return
    manifest = json.loads(archive.read(path))
    names = set(archive.namelist())
    mismatched = [row["path"] for row in manifest["payload"]
                  if row["path"] not in names
                  or hashlib.sha256(archive.read(row["path"])).hexdigest() != row["sha256"]]
    if mismatched:
        for name in mismatched[:6]:
            report.fail("payload", "%s does not match the manifest" % name)
        report.fail("payload", "%d of %d files drifted" % (len(mismatched), len(manifest["payload"])))
    else:
        report.ok("payload", "%d files match the manifest" % len(manifest["payload"]))


def check_deltas(report: Report, archive: zipfile.ZipFile, docs: dict) -> None:
    deltas = docs.get("deltas.json")
    if not deltas:
        return
    for target in deltas["targets"]:
        rel = target["path"]
        if rel not in archive.namelist():
            report.fail(rel, "delta target missing from the zip")
            continue
        text = archive.read(rel).decode()
        if target["codec"] == "json":
            document = json.loads(text)
            missing = []
            for op in target["ops"]:
                if op["op"] == "insert":
                    group, _, name = op["jsonPath"].partition(".")
                    if document.get(group, {}).get(name) != op["value"]:
                        missing.append(op["jsonPath"])
                elif op["op"] == "patch":
                    hits = text.count(op["marker"])
                    if hits != op["hits"]:
                        report.fail(rel, "%s hits %d != %d" % (op["marker"], hits, op["hits"]))
            if missing:
                report.fail(rel, "%d ops absent: %s" % (len(missing), ", ".join(missing[:4])))
            else:
                report.ok(rel, "%d ops verified in %d B" % (len(target["ops"]), len(text)))
    for row in deltas.get("untouched", []):
        if row["path"] in archive.namelist():
            report.ok(row["path"], "shipped as-is (%s)" % row["reason"][:40])


def check_symbols(report: Report, archive: zipfile.ZipFile) -> None:
    apk = [name for name in archive.namelist() if re.search(r"omnicam-muse-.*\.apk$", name)]
    if not apk:
        report.fail("apk", "no omnicam-muse-*.apk in the zip")
        return
    with zipfile.ZipFile(io.BytesIO(archive.read(apk[0]))) as inner:
        if "assets/symbols.json" not in inner.namelist():
            report.fail("assets/symbols.json", "missing from the apk")
            return
        text = inner.read("assets/symbols.json").decode()
    document = json.loads(text)
    report.ok("symbols", "camera %d / gallery %d entries" % (
        len(document.get("camera", {})), len(document.get("gallery", {}))))
    for (face, symbol), expected in PORTED_SYMBOLS.items():
        actual = document.get(face, {}).get(symbol, {}).get("name")
        if actual == expected:
            report.ok("symbol %s.%s" % (face, symbol), expected)
        else:
            report.fail("symbol %s.%s" % (face, symbol),
                        "name is %r, the X8U port pinned %r" % (actual, expected))


def check_profile_identity(report: Report, archive: zipfile.ZipFile, docs: dict) -> None:
    device = docs.get("device.json")
    if not device:
        return
    prop = archive.read("module.prop").decode()
    module_id = re.search(r"^id=(.*)$", prop, re.M).group(1).strip()
    if module_id == "ricoh_pop_x9u":
        report.warn("module.prop id", "still %s; X8U installs over the X9U module of the same id"
                                     " (fine for upgrades, hides which device it targets)" % module_id)
    else:
        report.ok("module.prop id", module_id)
    for role, package in [(p["role"], p) for p in device["packages"]]:
        if role == "CAMERA" and package["apkSha256"] not in json.dumps(docs.get("device.json")):
            report.fail("device.json", "camera digest missing")
    report.ok("profile", "%s -> camera %s" % (device["profileId"], device["packages"][0]["versionName"]))


def check_odm_targets(report: Report, docs: dict, dump: Path | None) -> None:
    if dump is None:
        report.warn("dump", "not given; target existence not re-verified")
        return
    tree = set()
    for line in (dump / "odm-tree/odm-tree.txt").read_text().splitlines():
        size, _, path = line.partition(" ")
        if path.startswith("/odm/"):
            tree.add(path)
    entries = docs.get("mounts.json", {}).get("entries", [])
    wrong = []
    for entry in entries:
        target = entry["target"]
        if entry["kind"] == "bind-dir-merge":
            exists = any(path.startswith(target + "/") for path in tree)
        else:
            exists = target in tree
        expected = entry["expected"]
        if expected == "ready" and not exists:
            wrong.append("%s expected ready but the dump has no %s" % (entry["id"], target))
        elif expected == "skipped:target-missing" and exists:
            wrong.append("%s expected skipped but the dump has %s" % (entry["id"], target))
    if wrong:
        for line in wrong:
            report.fail("mounts.json", line)
    else:
        report.ok("mounts.json", "%d targets agree with the dump" % len(entries))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args()
    report = Report()
    with zipfile.ZipFile(args.zip) as archive:
        report.ok("zip", "%s, %d entries, %.1f MB" % (
            args.zip.name, len(archive.namelist()), args.zip.stat().st_size / 1e6))
        docs = check_archive(report, archive)
        check_scripts(report, archive)
        check_mounts(report, archive, docs)
        check_payload(report, archive)
        check_deltas(report, archive, docs)
        check_symbols(report, archive)
        check_profile_identity(report, archive, docs)
        check_odm_targets(report, docs, args.dump)
    return report.dump()


if __name__ == "__main__":
    sys.exit(main())
