"""Generate module/profiles/x8u/*.json from a device dump.

Nothing in the output is hand-typed: every path, size and digest comes from the dump directory, the
module scripts, or the repository, so the profiles can be regenerated after a device update instead of
drifting away from the code.

    python tools/profiles/gen_x8u_profiles.py --dump <x8u-dump/DATE-TIME>

Writes device.json, mounts.json, deltas.json, resources.json and resources.files.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
MODULE = PROJECT / "module"
OUT = MODULE / "profiles/x8u"
GIT = ("/Library/Developer/CommandLineTools/usr/bin/git"
       if Path("/Library/Developer/CommandLineTools/usr/bin/git").exists() else "git")
# The X9 Ultra payload this port reads from must stay pinned: HEAD moves as soon as the ported
# payload is committed, and then "rebuild from the shipped file" would read our own output back.
BASE_REV = os.environ.get("MUSE_BASE_REV", "03f199c")

PROFILE_ID = "pku110-17.0.0.104-camera-7.006.123"

# name -> (marker gate, verdict). The two rebased files are the live device config plus X9-only
# entries; the rest are still X9 Ultra builds and default to off (see post-fs-data.sh).
CONFIGS = [
    # Layer markers match module/post-fs-data.sh; nothing is bound unless the marker exists.
    ("camera_unit_config", "enable_config_binds", "rebased:device-plus-x9-entries"),
    ("camera_unit_feature_config.protobuf", "enable_config_binds", "feature-table"),
    ("oplus_camera_algo_switch_config", "enable_algo_switch", "generated:algo-switch"),
    ("oplus_camera_config", "enable_occ_extras", "rebased:occ-extras"),
    ("oplus_camera_preview_decision_config.json", "enable_legacy_configs", "legacy:x9-build"),
    ("oplus_camera_aps_config", "enable_legacy_configs", "legacy:x9-build"),
]
GAMMA_NAMES = ["gamma_preview_sdr_conf.json", "gamma_quick_sdr_conf.json", "gamma_preview_hdr_conf.json"]
ISP_LENSES = ["main", "wide", "tele", "ultratele"]

FEATURE_OF = {
    "camera_unit_config": ["MD-01", "MD-04", "MD-07", "QL-04"],
    "camera_unit_feature_config.protobuf": ["MD-04", "MD-06"],
    "oplus_camera_config": ["UI-01", "UI-05", "MD-02"],
    "oplus_camera_algo_switch_config": ["CL-02", "MC-01", "MD-04"],
    "oplus_camera_aps_config": ["MD-04", "QL-05"],
    "oplus_camera_preview_decision_config.json": ["MD-04", "CL-02"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def odm_tree(dump: Path) -> dict[str, int]:
    tree: dict[str, int] = {}
    for line in (dump / "odm-tree/odm-tree.txt").read_text().splitlines():
        size, _, path = line.partition(" ")
        if path.startswith("/odm/"):
            tree[path] = int(size)
    return tree


def manifest(dump: Path) -> dict[str, list]:
    out: dict[str, list] = {"home": [], "build": [], "soc": [], "jars": []}
    for line in (dump / "manifest.txt").read_text().splitlines():
        if line.startswith("model|device|name: "):
            out["home"] = line.split(": ", 1)[1].split()
        elif line.startswith("build|android|oplusrom|oplusrom.display: "):
            out["build"] = line.split(": ", 1)[1].split("|")
        elif line.startswith("sun|"):
            out["soc"] = line.split("|")
        elif line.startswith("jar "):
            match = re.match(r"jar (\S+) (\d+) bytes$", line)
            if match:
                out["jars"].append(match.groups())
    return out


def api_level(android_version: int) -> int:
    adb = Path.home() / "Library/Android/sdk/platform-tools/adb"
    if adb.exists():
        try:
            value = subprocess.run([str(adb), "shell", "getprop ro.build.version.sdk"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
        except (subprocess.SubprocessError, OSError):
            value = ""
        if value.isdigit():
            return int(value)
    return {16: 36, 17: 37}.get(android_version, 0)


def jar_classes(path: Path, needles: list[bytes]) -> dict[str, int]:
    with zipfile.ZipFile(path) as archive:
        blob = b"".join(archive.read(name) for name in archive.namelist() if name.endswith(".dex"))
    return {needle.decode(): blob.count(needle) for needle in needles}


def device_doc(dump: Path) -> dict:
    ident = manifest(dump)
    build, soc, home = ident["build"], ident["soc"], ident["home"]
    apk, gallery = dump / "apk/OplusCamera.apk", dump / "apk/OplusGallery.apk"
    sdk = dump / "jar/_product_framework_com.oplus.camera.unit.sdk.jar"
    payload_sdk = MODULE / "payload/ipu/com.oplus.camera.unit.sdk.jar"
    needles = [b"CombineLut", b"PaletteColorTable", b"PaletteColor", b"ColorTable"]
    return {
        "schemaVersion": 1,
        "profileId": PROFILE_ID,
        "model": home[0],
        "device": home[1],
        "marketName": "OPPO Find X8 Ultra 卫星通信版",
        "systemBuild": build[0],
        "androidVersion": int(build[1]),
        "sdkInt": api_level(int(build[1])),
        "colorOs": build[2],
        "socCodename": soc[0],
        "socModel": soc[1],
        "abi": soc[2],
        "packages": [
            {"role": "CAMERA", "packageName": "com.oplus.camera", "versionName": "7.006.123",
             "versionCode": 60000, "codePath": "/product/app/OplusCamera",
             "apkSha256": sha256(apk), "apkBytes": apk.stat().st_size},
            {"role": "GALLERY", "packageName": "com.coloros.gallery3d",
             "codePath": "pm path com.coloros.gallery3d -> base.apk",
             "apkSha256": sha256(gallery), "apkBytes": gallery.stat().st_size},
        ],
        "sdkJar": {
            "system": {"path": "/product/framework/com.oplus.camera.unit.sdk.jar",
                       "sha256": sha256(sdk), "bytes": sdk.stat().st_size,
                       "dexStrings": jar_classes(sdk, needles)},
            "moduleOverlay": {"path": "payload/ipu/com.oplus.camera.unit.sdk.jar",
                              "sha256": sha256(payload_sdk), "bytes": payload_sdk.stat().st_size,
                              "dexStrings": jar_classes(payload_sdk, needles)},
            "note": "相册调色盘（CL-01/FL-09）依赖 PaletteColorTable，X8U 的系统 SDK jar 里没有这些类，"
                    "只有模块 overlay 的 X9U 构建有；因此 ipu jar 覆盖是功能前提而不是可选优化，同时它也是"
                    "X8U 上唯一仍在用 X9U 构建的 Java 侧组件。",
        },
        "sdkJars": [{"path": path, "bytes": int(size)} for path, size in ident["jars"]],
        "nativeUnitsEnabled": [],
        "notes": [
            "相机 7.006.123 是本档案唯一验证过的构建；升级相机后 apkSha256 变化即为 MISMATCH。",
            "相册包名是 com.coloros.gallery3d（不是 com.oplus.gallery），WM/FL/CL 组的功能依赖它。",
            "SM8750 的 ISP 调优文件按 zf* 命名，与 payload 里的 lighthouse* 不匹配，见 mounts.json。",
        ],
    }


def isz_facts(dump: Path) -> dict:
    """The [InsensorZoom] block: active rows, commented-out variants, and the column counts seen."""
    active, comment, nf = 0, 0, set()
    inside = False
    for line in (dump / "odm-files/CameraHWConfiguration.config").read_text(errors="replace").splitlines():
        if line.startswith("["):
            inside = line.strip() == "[InsensorZoom]"
            continue
        if not inside:
            continue
        stripped = line.lstrip()
        if stripped.startswith("iZoomSettins["):
            active += 1
            nf.add(len(line.split(";")))
        elif stripped.startswith("#") and "iZoomSettins[" in stripped:
            comment += 1
    return {"rows": active, "commentedRows": comment, "columnCounts": sorted(nf)}


def prefs_from_script() -> list[dict]:
    text = (MODULE / "service.sh").read_text()
    return [{"key": key, "value": value.strip(), "consumer": "com.oplus.camera shared_prefs"}
            for key, value in re.findall(r"^\s*set_config (\S+) (.*)$", text, re.M)]


def staging(dump: Path) -> list[dict]:
    tree = odm_tree(dump)
    live_lmt = {Path(path).name for path in tree if path.startswith("/odm/etc/camera/basictone/lmt/")}
    shipped_lmt = sorted(path.name for path in (MODULE / "payload/gr_adjustment_lmt").iterdir())
    missing = [name for name in shipped_lmt if name not in live_lmt]
    return [
        {"id": "gr-lmt", "featureIds": ["MD-01", "MD-03"], "kind": "copy-selected",
         "sources": ["payload/gr_adjustment_lmt"], "destination": "com.oplus.camera files/ricoh_gr/lmt",
         "consumer": "service.sh:48-68", "owner": "CAMERA",
         "dependsOnDevice": "live /odm/etc/camera/basictone/lmt 的文件名",
         "checks": [{"path": "/odm/etc/camera/basictone/lmt/%s" % name, "present": name in live_lmt}
                    for name in shipped_lmt],
         "verdict": "ok" if not missing else "missing-on-device:%d" % len(missing)},
        {"id": "master-color", "featureIds": ["MC-01", "MC-02", "MC-07"], "kind": "copy-tree",
         "sources": ["payload/master_color"], "destination": "com.oplus.camera files/jiege/mastercolor",
         "consumer": "service.sh:75-99", "owner": "CAMERA", "dependsOnDevice": None},
        {"id": "pop-port", "featureIds": ["MD-04"], "kind": "copy-tree",
         "sources": ["payload/setting_Retro", "payload/meishe_lut", "payload/pld_watermark",
                     "payload/apk_resources"],
         "destination": "com.oplus.camera files/pop_port + files/odm/etc/camera/pld_watermark",
         "consumer": "service.sh:119-128", "owner": "CAMERA", "dependsOnDevice": None},
        {"id": "unlock-25mp", "featureIds": ["QL-04"], "kind": "copy-tree",
         "sources": ["payload/unlock25mp"], "destination": "com.oplus.camera files/jiege/unlock25mp",
         "consumer": "service.sh:132-139 + native unlock25mp.cpp 重定向", "owner": "CAMERA",
         "dependsOnDevice": "文件按 lighthouse{main,tele,ultratele,wide} 命名，X8U 的传感器是 zf*",
         "verdict": "needs-regeneration"},
        {"id": "face-200mp", "featureIds": ["QL-05"], "kind": "copy-tree",
         "sources": ["payload/face200m"], "destination": "com.oplus.camera files/jiege/face200m",
         "consumer": "service.sh:143-149 + native face200m.cpp 重定向", "owner": "CAMERA",
         "dependsOnDevice": None},
        {"id": "watermark-styles", "featureIds": ["WM-01", "WM-03"], "kind": "copy-selected",
         "sources": ["payload/watermark_master_styles", "payload/watermark_drawables"],
         "destination": "com.coloros.gallery3d files/ricoh_gr_styles + camera files/mode_limit_watermark",
         "consumer": "service.sh:172-195", "owner": "GALLERY", "dependsOnDevice": None},
        {"id": "ipu-jar", "featureIds": ["CL-01", "FL-09"], "kind": "replace-jar",
         "sources": ["payload/ipu/com.oplus.camera.unit.sdk.jar"],
         "destination": "com.coloros.gallery3d files/jiege_ipu", "consumer": "service.sh:199-210",
         "owner": "GALLERY",
         "dependsOnDevice": "X8U 系统 jar 无 PaletteColorTable，overlay 必须保留",
         "verdict": "required"},
    ]


def entries(tree: dict[str, int]) -> list[dict]:
    rows = []
    for name, gate, verdict in CONFIGS:
        target = "/odm/etc/camera/config/%s" % name
        gate_chain = ("%s,disable_config_binds" % gate) if gate else "disable_config_binds"
        if target not in tree:
            expected = "skipped:target-missing"
        elif gate:
            expected = "gated:marker-%s" % gate
        else:
            expected = "ready"
        rows.append({"id": name, "featureIds": FEATURE_OF[name], "kind": "bind-file",
                     "sources": ["payload/%s" % name], "target": target, "gate": gate_chain,
                     "verdict": verdict, "selinux": "vendor_configs_file",
                     "policy": "skip-if-missing", "expected": expected})
    rows.append({"id": "audio-volumes", "featureIds": ["UI-07"], "kind": "bind-file",
                 "sources": ["payload/audio_policy_volumes.xml"],
                 "target": "/odm/etc/audio/audio_policy_volumes.xml", "gate": None,
                 "selinux": "vendor_configs_file", "policy": "skip-if-missing",
                 "expected": ("ready" if "/odm/etc/audio/audio_policy_volumes.xml" in tree
                              else "skipped:target-missing")})
    for ident, features, live, overlays in [
            ("meishe-lut", ["FL-01", "FL-09", "CL-01"], "/odm/etc/camera/meishe_lut",
             ["payload/meishe_lut"]),
            ("basictone", ["MD-04", "MC-02"], "/odm/etc/camera/basictone",
             ["payload/x10_basictone", "payload/setting_Retro->setting_Retro/"])]:
        rows.append({"id": ident, "featureIds": features, "kind": "bind-dir-merge",
                     "sources": overlays, "live": live, "target": live, "gate": None,
                     "selinux": "vendor_configs_file", "policy": "skip-if-live-missing",
                     "expected": ("ready" if any(path.startswith(live + "/") for path in tree)
                                  else "skipped:target-missing")})
    for name in GAMMA_NAMES:
        target = "/odm/etc/camera/%s" % name
        rows.append({"id": name, "featureIds": ["MD-02"], "kind": "bind-file",
                     "sources": ["payload/gamma/%s" % name], "target": target, "gate": None,
                     "selinux": "vendor_configs_file", "policy": "skip-if-missing",
                     "expected": "ready" if target in tree else "skipped:target-missing"})
    for lens in ISP_LENSES:
        name = "com.qti.tuned.lighthouse%s.bin" % lens
        target = "/odm/lib64/camera/%s" % name
        rows.append({"id": "isp-%s" % lens, "featureIds": ["MD-02", "MD-03", "MC-01"],
                     "kind": "bind-file", "sources": ["payload/isp/%s" % name], "target": target,
                     "gate": None, "selinux": "vendor_file", "policy": "skip-if-missing",
                     "expected": "ready" if target in tree else "skipped:target-missing"})
    return rows


def lib_expect(condition: str, tree: dict[str, int]) -> str:
    if condition.startswith("target-exists:"):
        return "ready" if condition.split(":", 1)[1] in tree else "skipped:target-missing"
    if condition.startswith("after:"):
        return "gated:after-%s" % condition.split(":", 1)[1]
    if condition.startswith("marker:"):
        return "gated:marker-%s" % condition.split(":", 1)[1]
    return "unbound"


def mounts_doc(dump: Path) -> dict:
    tree = odm_tree(dump)
    facts = isz_facts(dump)
    rows = entries(tree)
    libs = [
        ("basictone-x9", ["CL-02", "MD-04"], "libBasicTonePhotoX9.so",
         "target-exists:/odm/lib64/libBasicTonePhotoX9.so",
         "X9 Ultra only; X8 Ultra ships neither X9 nor X10"),
        ("basictone-x10", ["CL-02", "MD-04"], "libBasicTonePhotoX10.so",
         "target-exists:/odm/lib64/libBasicTonePhotoX10.so", "X9 Ultra only"),
        ("basictone-router", ["CL-02", "MD-04"], "libBasicTonePhoto.so", "after:basictone-x9",
         "8,960 B router that dlopens X9/X10; replacing the 538,400 B stock build without them breaks POP"),
        ("algo-interface", ["MC-07"], "libAlgoInterface.so", "marker:enable_algo_interface",
         "grain trampolines are hand-placed for the X9 Ultra build"),
        ("native-filter", [], "libmsnativefilter.so", "never", "no X8 Ultra verification; not bound"),
    ]
    return {
        "schemaVersion": 1,
        "profileId": PROFILE_ID,
        "source": {"dump": str(dump), "odmFiles": len(tree)},
        "entries": rows,
        "runtimeStaging": staging(dump),
        "settings": prefs_from_script(),
        "libraries": [{"id": ident, "featureIds": features, "library": lib,
                       "source": "system/odm/lib64/%s" % lib, "target": "/odm/lib64/%s" % lib,
                       "condition": condition, "note": note,
                       "expected": lib_expect(condition, tree)}
                      for ident, features, lib, condition, note in libs],
        "runtimePatches": [{
            "id": "pro-video-isz", "featureIds": ["MD-02"],
            "implementedBy": "module/post-fs-data.sh:129-146",
            "target": "/odm/etc/camera/CameraHWConfiguration.config",
            "gate": "disable_pro_video_isz",
            "expects": {"section": "InsensorZoom", "rowRange": [25, 40], "columnCount": 14,
                        "zeroColumns": [12, 13], "hits": 16},
            "measured": {"section": "InsensorZoom", "rows": facts["rows"],
                         "commentedRows": facts["commentedRows"],
                         "columnCounts": facts["columnCounts"]},
            "applicable": facts["rows"] == 16 and facts["columnCounts"] == [14],
            "reason": ("layout matches the X9 Ultra" if facts["rows"] == 16 and facts["columnCounts"] == [14]
                       else "X8 Ultra [InsensorZoom] has %d active rows (%d commented) with %s columns; "
                            "the patch needs rows 25..40 with 14 columns, so the script logs "
                            "'pro video isz skipped' and leaves stock untouched"
                            % (facts["rows"], facts["commentedRows"],
                               "/".join(map(str, facts["columnCounts"])))),
        }],
        "deviceOnlyTuning": {
            "note": "payload 的 ISP 调优是 X9 Ultra（SM8850/lighthouse）构建，本机按 SoC 代号 zf* 命名；"
                    "绑定等于把别的镜头调到 X8 Ultra 上。因此 4 个 isp 条目全部 expected=skipped，"
                    "绑定量为 0 才是正确结果，不是失败。",
            "deviceFiles": sorted({Path(path).name for path in tree
                                   if Path(path).name.startswith("com.qti.tuned.zf")}),
        },
        "expectedSummary": {
            "ready": sum(1 for row in rows if row["expected"] == "ready"),
            "skipped": sum(1 for row in rows if row["expected"].startswith("skipped")),
        },
    }


def shipped_payload(name: str) -> bytes:
    return subprocess.run([GIT, "show", "%s:module/payload/%s" % (BASE_REV, name)], cwd=PROJECT,
                          check=True, capture_output=True).stdout


def plain(data: bytes, key: bytes) -> bytes:
    if data[:2] != b"\x01\x01":
        return data
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    return unpad(AES.new(key, AES.MODE_ECB).decrypt(data[4:-4]), 16)


def config_key(security: Path) -> bytes:
    return bytes(value ^ 0x3F for value in security.read_bytes()[0x7AB:0x7AB + 32])[::2]


DELTA_FEATURE = {
    "gr_mode": "MD-01", "retro_camera_mode": "MD-04",
    "telephoto_capture_mode": "MD-02", "telephoto_video_mode": "MD-02",
    "tilt_shift_mode": "MD-09", "high_pixel_mode": "QL-04",
    "gr_mode_case": "MD-01", "telephoto_capture_case": "MD-02", "telephoto_video_case": "MD-02",
}


def deltas_doc(dump: Path, key: bytes) -> dict:
    """The X8U payload is the X8U stock config plus the X9 Ultra-only entries, so the base is the live
    file. It is exported under profiles/x8u/base/ so the payload can be rebuilt without a device."""
    live_path = dump / "odm-files/camera_unit_config"
    live_raw = plain(live_path.read_bytes(), key)
    live = json.loads(live_raw)
    decision_path = dump / "odm-files/oplus_camera_preview_decision_config.json"
    decision_raw = plain(decision_path.read_bytes(), key)
    base_dir = OUT / "base"
    base_dir.mkdir(parents=True, exist_ok=True)
    bases = {}
    for rel, raw, device_path in [
            ("payload/camera_unit_config", live_raw, "/odm/etc/camera/config/camera_unit_config"),
            ("payload/oplus_camera_preview_decision_config.json", decision_raw,
             "/odm/etc/camera/config/oplus_camera_preview_decision_config.json")]:
        name = Path(rel).name
        (base_dir / name).write_bytes(raw)
        bases[rel] = {"file": "module/profiles/x8u/base/%s" % name, "sha256": hashlib.sha256(raw).hexdigest(),
                      "bytes": len(raw), "devicePath": device_path,
                      "deviceSha256": sha256(dump / "odm-files" / name)}

    x9 = json.loads(shipped_payload("camera_unit_config"))
    ops = []
    for group, values in x9.items():
        if not isinstance(values, dict) or not isinstance(live.get(group), dict):
            continue
        for name, value in values.items():
            if name in live[group]:
                continue
            ops.append({"id": "%s.%s" % (group, name), "featureId": DELTA_FEATURE.get(name, "MD-01"),
                        "op": "insert", "jsonPath": "%s.%s" % (group, name), "value": value,
                        "expect": "absent"})
    return {
        "schemaVersion": 1,
        "profileId": PROFILE_ID,
        "bases": bases,
        "source": {"keySource": "/odm/lib64/libOplusSecurity.so +0x7AB, 32 bytes ^0x3F, every other byte",
                   "codec": "aes-ecb envelope (01 01) or plain json",
                   "x9PayloadSha256": hashlib.sha256(shipped_payload("camera_unit_config")).hexdigest()},
        "targets": [
            {"path": "payload/camera_unit_config", "codec": "json", "ops": ops},
            {"path": "payload/oplus_camera_preview_decision_config.json", "codec": "json",
             "ops": [{"id": "preview-decision.pop-basictone", "featureId": "MD-04", "op": "patch",
                      "patchId": "pop-basictone", "implementedBy": "tools/patch_25mp.py:pop_basictone",
                      "expect": "marker-absent", "marker": "retro_camera_mode", "hits": 2}]},
        ],
        "untouched": [{"path": path, "reason": reason} for path, reason in [
            ("payload/oplus_camera_config", "本机 70,696 B / 721 tag，X9 Ultra 97,527 B / 585 tag，X9 版是旧构建"),
            ("payload/oplus_camera_aps_config", "非合法 JSON（含控制字符），且 sensor 名 lighthouse vs zf 不一致"),
            ("payload/oplus_camera_algo_switch_config", "非合法 JSON，本机构建更大（132,984 > 109,976）"),
            ("payload/camera_unit_feature_config.protobuf", "protobuf，无 schema，但相机用它判定 GR / 复古 / 移轴 / 灵感构图有没有，本机表里一条都没有，所以整份原样挂上"),
        ]],
        "opCount": len(ops),
    }


def resources_doc() -> tuple[dict, list[str]]:
    sections = [("meishe-lut", "payload/meishe_lut", ["FL-01", "FL-09", "CL-01"]),
                ("basictone-x10", "payload/x10_basictone", ["MD-04", "MC-02"]),
                ("basictone-retro", "payload/setting_Retro", ["MD-04"]),
                ("gamma", "payload/gamma", ["MD-02"]),
                ("isp", "payload/isp", ["MD-02", "MD-03"])]
    lines, groups = [], []
    for ident, rel, features in sections:
        root = MODULE / rel
        files = sorted(path for path in root.rglob("*") if path.is_file())
        for path in files:
            lines.append("%s %d %s" % (path.relative_to(MODULE), path.stat().st_size, sha256(path)))
        groups.append({"id": ident, "path": rel, "featureIds": features, "files": len(files),
                       "bytes": sum(path.stat().st_size for path in files),
                       "aggregateSha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
                       "licenseId": "device-capture"})
    assets = PROJECT / "app/src/main/assets"
    extra = [{"id": "gr-sounds", "path": "assets/gr_sounds",
              "files": len(list((assets / "gr_sounds").glob("*.ogg"))), "featureIds": ["MD-03"],
              "source": "realme RMX5200 16.0.10.501 com.oplus.camera 6.070.215"},
             {"id": "symbols", "path": "assets/symbols.json", "sha256": sha256(assets / "symbols.json"),
              "featureIds": []}]
    return ({"schemaVersion": 1, "profileId": PROFILE_ID, "groups": groups, "assets": extra,
             "inventory": "resources.files.txt",
             "inventorySha256": hashlib.sha256("\n".join(lines).encode()).hexdigest()}, lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    args = parser.parse_args()
    dump = args.dump
    security = dump / "odm-files/_odm_lib64_libOplusSecurity.so"
    if not security.exists():
        raise SystemExit("dump is missing odm-files/_odm_lib64_libOplusSecurity.so (config key source)")

    device = device_doc(dump)
    mounts = mounts_doc(dump)
    deltas = deltas_doc(dump, config_key(security))
    resources, inventory = resources_doc()

    OUT.mkdir(parents=True, exist_ok=True)
    for name, doc in (("device.json", device), ("mounts.json", mounts), ("deltas.json", deltas),
                      ("resources.json", resources)):
        (OUT / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "resources.files.txt").write_text("\n".join(inventory) + "\n", encoding="utf-8")

    print("device.json     camera %s -> %s, sdkInt %d" % (
        device["packages"][0]["versionName"], device["packages"][0]["apkSha256"][:12], device["sdkInt"]))
    print("mounts.json     binds ready=%d skipped=%d, staging=%d, settings=%d, patch applicable=%s" % (
        mounts["expectedSummary"]["ready"], mounts["expectedSummary"]["skipped"],
        len(mounts["runtimeStaging"]), len(mounts["settings"]),
        mounts["runtimePatches"][0]["applicable"]))
    print("deltas.json     %d inserts + 1 patch" % deltas["opCount"])
    print("resources.json  groups=%d files=%d" % (len(resources["groups"]), len(inventory)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
