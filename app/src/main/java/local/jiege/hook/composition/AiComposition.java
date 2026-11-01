package local.jiege.hook.composition;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedHelpers;
import local.jiege.hook.common.Log;
import local.jiege.hook.common.Settings;
import local.jiege.settings.ModuleSettings;

/**
 * AI composition (灵感构图). The feature ships in the camera app: 534 types under
 * com.oplus.camera.feature.aicomposition (view / inspiration / state), four entry guide videos in
 * /odm/etc/camera/apk_resources/mp4, six DataKeys of AICompositionFeatureKeys (key_ai_composition,
 * ai_composition_last_mode, ...). This device's camera 7.006.123 has all of it, but its config does
 * not advertise the feature, so the entry stays collapsed.
 *
 * <p>Two gates, both config reads - not a device whitelist:
 *
 * <ol>
 *   <li>the feature table (camera_unit_feature_config.protobuf) must carry
 *       com.oplus.camera.feature.ai_composition - the module binds that table, so this is satisfied
 *       without a hook;</li>
 *   <li>aicomposition/view/y2 and the account manager call
 *       CameraConfig.d("com.oplus.feature.aicomposition.realscene.support", false, false) and the
 *       inspiration counterpart. Neither tag exists in this device's oplus_camera_config, so both
 *       answer false and the button never leaves GONE.</li>
 * </ol>
 *
 * <p>service.sh already stages both tags into override_config_data.xml; this hook is the belt to that
 * brace - the camera rewrites its prefs on some mode switches, and a single hook keeps the bits on
 * for the life of the process. AndroidTestAdapter.isSupportAIComposition is deliberately not hooked:
 * camera 7.006.123 defines it but never calls it (verified over all 33 dex files), so hooking it does
 * nothing.
 *
 * <p>Scope: this opens the entry only. Inference runs in com.oplus.aiunit (separate updatable apk,
 * AIUnitService / IUnit over its own AIDL) and the inspiration library comes from the network under
 * the logged-in account; without that service the entry opens and no suggestion ever arrives.
 */
public final class AiComposition {
    private static final String TAG = "AiComposition";
    private static final String CONFIG = "com.oplus.camera.configure.CameraConfig";

    private static final String KEY_REALSCENE = "com.oplus.feature.aicomposition.realscene.support";
    private static final String KEY_INSPIRATION = "com.oplus.feature.aicomposition.inspiration.support";
    private static final int HASH_REALSCENE = KEY_REALSCENE.hashCode();
    private static final int HASH_INSPIRATION = KEY_INSPIRATION.hashCode();

    private AiComposition() {}

    public static void installCamera(ClassLoader classLoader) {
        if (!Settings.get(ModuleSettings.AI_COMPOSITION)) {
            Log.i(TAG, "off");
            return;
        }
        Log.guard(TAG, "config bits", () -> hookConfig(classLoader));
    }

    private static void hookConfig(ClassLoader classLoader) {
        XposedHelpers.findAndHookMethod(CONFIG, classLoader, "d",
                String.class, boolean.class, boolean.class, new XC_MethodHook() {
                    @Override protected void beforeHookedMethod(MethodHookParam param) {
                        Object key = param.args[0];
                        if (!(key instanceof String)) {
                            return;
                        }
                        int hash = key.hashCode();
                        if (hash == HASH_REALSCENE || hash == HASH_INSPIRATION) {
                            param.setResult(Boolean.TRUE);
                        }
                    }
                });
        Log.i(TAG, "installed");
    }
}
