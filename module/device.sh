#!/system/bin/sh
# Device gate: decides which profile this module may apply, before anything is mounted.
#
# The payload carries two different bodies of device data (the Find X9 Ultra files this module was
# written for, and the Find X8 Ultra table rebuilt here). Binding the wrong one is not a cosmetic
# problem: the vendor tag table names sensors, the feature table decides which modes exist, and the
# APS table decides whether APS answers at all, which is what the shutter waits on. So the model is
# checked first, the firmware and camera build are reported next to it, and an unrecognised device
# gets the LUT/hook layers only.
#
# Exports:
#   MUSE_PROFILE        x8u | x9u | unknown
#   MUSE_CONFIG_BINDS   1 when the config binds may run, 0 when they must not
#   MUSE_EXPECTED_CAMERA  camera version the profile was verified against

MUSE_MODEL=$(getprop ro.product.model)
MUSE_FIRMWARE=$(getprop ro.build.display.id)
MUSE_PROFILE=unknown
MUSE_CONFIG_BINDS=1
MUSE_EXPECTED_CAMERA=

case "$MUSE_MODEL" in
    PKU110|PKJ110)
        MUSE_PROFILE=x8u
        MUSE_EXPECTED_CAMERA=7.006.123
        ;;
    PMA110)
        MUSE_PROFILE=x9u
        MUSE_EXPECTED_CAMERA=7.006.119
        ;;
    *)
        MUSE_PROFILE=unknown
        MUSE_CONFIG_BINDS=0
        ;;
esac

# A firmware jump moves the vendor tables this payload was diffed against. Keep binding (the files are
# rebased on the device's own tables, so a new build still only gains entries) and say so in bind.log.
MUSE_CAMERA=$(dumpsys package com.oplus.camera 2>/dev/null | sed -n 's/.*versionName=\([0-9.]*\).*/\1/p' | head -n 1)

case "$MUSE_PROFILE" in
    unknown)
        echo "device $MUSE_MODEL / $MUSE_FIRMWARE: no profile, config binds skipped" >> "${LOG:-/dev/null}"
        ;;
    x8u|x9u)
        echo "device $MUSE_MODEL / $MUSE_FIRMWARE: profile $MUSE_PROFILE, camera ${MUSE_CAMERA:-unknown} (verified against $MUSE_EXPECTED_CAMERA)" >> "${LOG:-/dev/null}"
        if [ -n "$MUSE_CAMERA" ] && [ "$MUSE_CAMERA" != "$MUSE_EXPECTED_CAMERA" ]; then
            echo "camera build differs from the verified one; config binds still apply, hooks may miss symbols" >> "${LOG:-/dev/null}"
        fi
        ;;
esac

if [ -f "$MODDIR/disable_config_binds" ]; then
    MUSE_CONFIG_BINDS=0
fi
