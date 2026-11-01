package local.jiege.hook.composition;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedHelpers;
import local.jiege.hook.common.Log;
import local.jiege.hook.common.Settings;
import local.jiege.settings.ModuleSettings;

/**
 * AI composition (灵感构图). The whole feature ships in the camera app: 534 types under
 * com.oplus.camera.feature.aicomposition (view / inspiration / state), four entry guide videos in
 * /odm/etc/camera/apk_resources/mp4, and the six DataKeys of AICompositionFeatureKeys
 * (key_ai_composition, ai_composition_last_mode, ...). What is missing on this device is the
 * advertisement of "com.oplus.camera.feature.ai_composition" in the camera feature table, so the
 * master gate answers false and the entry stays hidden.
 *
 * <p>The gate is a debug adapter, not a device whitelist: AndroidTestAdapter.isSupportAIComposition
 * is six instructions - a feature lookup and a null check. getAICompositionState asks the same table
 * before it reads the switch state, so both are forced on here. The switch state itself stays the
 * stock DataKey key_ai_composition, staged by service.sh, so the in-camera toggle keeps writing to
 * the same place it always did.
 *
 * <p>Scope: this hook only opens the entry. The composition inference runs in com.oplus.aiunit
 * (separate updatable apk, AIUnitService / IUnit over its own AIDL) and pulls the inspiration library
 * from the network under the account, none of which is touched here. Without that service the entry
 * opens and the analysis never returns.
 */
public final class AiComposition {
    private static final String TAG = "AiComposition";
    /** Unobfuscated on PKU110 / camera 7.006.123 (source file AndroidTestAdapter.java). */
    private static final String ADAPTER = "com.oplus.camera.util.AndroidTestAdapter";

    private AiComposition() {}

    public static void installCamera(ClassLoader classLoader) {
        if (!Settings.get(ModuleSettings.AI_COMPOSITION)) {
            Log.i(TAG, "off");
            return;
        }
        Log.guard(TAG, "support gate", () -> hookGate(classLoader));
    }

    private static void hookGate(ClassLoader classLoader) {
        Class<?> adapter = XposedHelpers.findClass(ADAPTER, classLoader);
        XposedHelpers.findAndHookMethod(adapter, "isSupportAIComposition", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam param) {
                param.setResult(Boolean.TRUE);
            }
        });
        XposedHelpers.findAndHookMethod(adapter, "getAICompositionState", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam param) {
                param.setResult(Boolean.TRUE);
            }
        });
        Log.i(TAG, "installed");
    }
}
