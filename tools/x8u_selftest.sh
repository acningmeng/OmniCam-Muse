#!/system/bin/sh
# x8u_selftest.sh - read-only checks for the layered X8U port. Nothing here writes to /odm,
# restarts a process, or touches LSPosed: run it as root (su -c 'sh /data/local/tmp/x8u_selftest.sh <cmd>').
#
#   gate     device profile, firmware, camera version, module markers
#   hooks    whether the LSPosed module is injected into camera and gallery
#   mounts   which of our binds are live, and whether the merged dirs look complete
#   shoot    media counter before/after one shutter press (needs a human to press, or an awake screen)
#   all      gate + hooks + mounts
#
# Exit code: 0 when every executed check passes, 1 otherwise.

MODDIR=${MODDIR:-/data/adb/modules/ricoh_pop_x9u}
FAIL=0

say()  { echo "$1"; }
ok()   { echo "  [ok]   $1"; }
warn() { echo "  [warn] $1"; }
bad()  { echo "  [FAIL] $1"; FAIL=1; }

cfg() { echo "$1"; }

profile() {
    MODEL=$(getprop ro.product.model)
    FW=$(getprop ro.build.display.id)
    CAM=$(dumpsys package com.oplus.camera 2>/dev/null | grep -m1 versionName | tr -d ' ')
    case "$MODEL" in
        PKU110|PKJ110) P=x8u ;;
        PMA110)        P=x9u ;;
        *)             P=unknown ;;
    esac
    say "device: model=$MODEL profile=$P firmware=$FW $CAM"
    [ "$P" = "unknown" ] && bad "unknown model, config layers must stay off"
    for m in enable_config_binds enable_algo_switch enable_occ_extras enable_legacy_configs enable_composition; do
        [ -f "$MODDIR/$m" ] && say "  marker: $m"
    done
    return 0
}

hooks() {
    say "hooks:"
    for pkg in com.oplus.camera com.coloros.gallery3d; do
        N=$(grep -c "($pkg)\[local.jiege.camera" /data/adb/lspd/log/verbose_*.log 2>/dev/null | tail -1)
        [ -n "$N" ] && [ "$N" -gt 0 ] && ok "$pkg injected ($N frames)" || bad "$pkg not injected"
    done
    return 0
}

mounted() { # path -> prints "bound" or "stock"
    if grep -q " $1 " /proc/self/mountinfo 2>/dev/null; then echo bound; else echo stock; fi
}

mounts() {
    say "mounts:"
    for f in camera_unit_config camera_unit_feature_config.protobuf oplus_camera_algo_switch_config oplus_camera_config; do
        echo "  $f: $(mounted /odm/etc/camera/config/$f)"
    done
    echo "  basictone dirs: $(ls /odm/etc/camera/basictone 2>/dev/null | wc -l)"
    echo "  meishe_lut files: $(ls /odm/etc/camera/meishe_lut 2>/dev/null | wc -l)"
    [ "$(ls /odm/etc/camera/meishe_lut 2>/dev/null | wc -l)" -gt 100 ] && ok "meishe_lut complete" || bad "meishe_lut looks short"
    [ -d /odm/etc/camera/basictone/lmt ] && ok "basictone/lmt present" || bad "basictone/lmt missing"
    return 0
}

shoot() {
    B=$(content query --uri content://media/external/images/media --projection _id --sort 'date_added DESC' 2>/dev/null | head -1)
    say "media head before: $B"
    say "press the shutter within 10s..."
    sleep 10
    A=$(content query --uri content://media/external/images/media --projection _id --sort 'date_added DESC' 2>/dev/null | head -1)
    say "media head after:  $A"
    [ "$B" != "$A" ] && ok "capture landed" || bad "no new media row"
    return 0
}

case "${1:-all}" in
    gate)   profile ;;
    hooks)  hooks ;;
    mounts) mounts ;;
    shoot)  shoot ;;
    all)    profile; hooks; mounts ;;
    *)      say "usage: $0 {gate|hooks|mounts|shoot|all}"; exit 2 ;;
esac
exit $FAIL
