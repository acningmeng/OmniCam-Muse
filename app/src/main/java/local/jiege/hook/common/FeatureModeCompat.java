package local.jiege.hook.common;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import java.util.LinkedHashMap;

/**
 * Port guard for the X8 Ultra feature table swap.
 *
 * ProtobufParser.initFeatureInfo walks every mode the feature table lists and asks
 * CameraConfigHelper.getFeatureOperationMode(mode) for that mode's operation table. The ported
 * table lists modes whose block is absent from the device's camera_unit_config (the X9 Ultra set
 * and the X8 Ultra set do not cover the same mode names), and getFeatureOperationMode then returns
 * null, which initFeatureInfo feeds straight into a HashMap copy:
 *
 *   java.lang.NullPointerException: Map.size() on a null object reference
 *     at java.util.HashMap.putMapEntries
 *     at CameraConfigHelper.getFeatureOperationMode(CameraConfigHelper.java:468)
 *     at ProtobufParser.initFeatureInfo(ProtobufParser.java:222)
 *
 * An empty table is the right answer for those modes: the mode keeps its feature entry but brings
 * no operation overrides, which is exactly what the X8 Ultra's own table does for a mode that has
 * no overrides. Everything the table does know is returned untouched.
 */
public final class FeatureModeCompat {
    private static final String TAG = "FeatureModeCompat";
    private static final String HELPER = "com.oplus.ocs.camera.producer.info.CameraConfigHelper";
    private static final String METHOD = "getFeatureOperationMode";

    private FeatureModeCompat() {}

    public static void installCamera(ClassLoader classLoader) {
        try {
            Class<?> helper = Class.forName(HELPER, false, classLoader);
            XposedBridge.hookAllMethods(helper, METHOD, new XC_MethodHook() {
                @Override protected void afterHookedMethod(MethodHookParam param) {
                    if (param.getResult() == null) {
                        param.setResult(new LinkedHashMap<>());
                        Log.i(TAG, "empty operation table for a mode the config does not carry");
                    }
                }
            });
            Log.i(TAG, "installed");
        } catch (Throwable error) {
            Log.e(TAG, "feature mode compat unavailable", error);
        }
    }
}
