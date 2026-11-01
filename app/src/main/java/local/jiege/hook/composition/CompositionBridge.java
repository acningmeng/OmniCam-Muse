package local.jiege.hook.composition;

import android.graphics.Bitmap;
import android.util.Log;

import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Locale;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;

/**
 * Feeds the stock inspiration-composition panel with an answer computed on the device.
 *
 * <p>Why this shape: the camera talks to an {@code com.oplus.aiunit.core.base.FrameDetector} that this
 * firmware never downloads, so the panel stays empty even when the entry is visible. We do not talk to
 * the cloud unit and we do not ship a detector class (that would need the aiunit SDK at compile time);
 * instead we watch the camera's own composition helper, steal the preview frame it was going to send,
 * score it with {@link CompositionHeuristic}, and put the answer back into whatever result object the
 * helper exposes.
 *
 * <p>Everything is fail-open: if the helper class, the frame field or the result setter is missing on a
 * future build, we log one line and leave the stock behaviour untouched. The gate is the module marker
 * file {@code enable_composition}, read once per process, so the phone can switch it off without a
 * rebuild.
 */
public final class CompositionBridge {

    private static final String TAG = "MuseComposition";
    private static final String HELPER = "com.oplus.ocs.camera.OplusAICompositionHelper";
    private static final String ALT_HELPER = "com.oplus.camera.aicomposition.OplusAIComposition";
    private static final String GATE = "/data/adb/modules/ricoh_pop_x9u/enable_composition";

    private static final long INTERVAL_MS = 500L;
    private static long sLastRun;
    private static boolean sReportedFrameClass;

    private CompositionBridge() {
    }

    public static void installCamera(ClassLoader loader) {
        if (!new File(GATE).exists()) {
            Log.i(TAG, "local composition off (" + GATE + " missing)");
            return;
        }
        int hooked = hookHelper(loader, HELPER) + hookHelper(loader, ALT_HELPER);
        Log.i(TAG, hooked > 0 ? "local composition installed on " + hooked + " method(s)"
                : "local composition: helper class not found, stock path untouched");
    }

    private static int hookHelper(ClassLoader loader, String name) {
        Class<?> helper;
        try {
            helper = XposedHelpers.findClass(name, loader);
        } catch (Throwable t) {
            return 0;
        }
        int n = 0;
        for (Method m : helper.getDeclaredMethods()) {
            Class<?>[] params = m.getParameterTypes();
            boolean interesting = false;
            for (Class<?> p : params) {
                if (p == Bitmap.class || Bitmap.class.isAssignableFrom(p) || p.getName().contains("Frame")) {
                    interesting = true;
                    break;
                }
            }
            if (!interesting) {
                continue;
            }
            try {
                XposedBridge.hookMethod(m, new XC_MethodHook() {
                    @Override
                    protected void afterHookedMethod(MethodHookParam param) {
                        try {
                            handle(param);
                        } catch (Throwable t) {
                            Log.w(TAG, "analysis skipped: " + t);
                        }
                    }
                });
                n++;
            } catch (Throwable t) {
                Log.w(TAG, "hook failed on " + m.getName() + ": " + t);
            }
        }
        if (n > 0) {
            Log.i(TAG, "hooked " + name + " x" + n);
        }
        return n;
    }

    private static void handle(XC_MethodHook.MethodHookParam param) {
        long now = System.currentTimeMillis();
        if (now - sLastRun < INTERVAL_MS) {
            return;
        }
        Bitmap frame = findBitmap(param.thisObject, param.args);
        if (frame == null) {
            return;
        }
        sLastRun = now;

        int w = frame.getWidth();
        int h = frame.getHeight();
        int[] pixels = new int[w * h];
        frame.getPixels(pixels, 0, w, 0, 0, w, h);
        CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(w, h, pixels);

        Object result = param.getResult();
        boolean written = putIntoResult(result, s);
        if (!sReportedFrameClass) {
            sReportedFrameClass = true;
            Log.i(TAG, String.format(Locale.US, "first frame %dx%d score=%d tip=%s box=%s result=%s written=%s",
                    w, h, s.score, s.tip, s.boxJson(), result == null ? "null" : result.getClass().getName(), written));
        }
    }

    /** Looks for a preview frame in the call arguments first, then in the helper's own fields. */
    private static Bitmap findBitmap(Object self, Object[] args) {
        if (args != null) {
            for (Object a : args) {
                Bitmap b = asBitmap(a);
                if (b != null) {
                    return b;
                }
            }
        }
        if (self != null) {
            for (Field f : self.getClass().getDeclaredFields()) {
                if (!Bitmap.class.isAssignableFrom(f.getType())) {
                    continue;
                }
                try {
                    f.setAccessible(true);
                    Bitmap b = (Bitmap) f.get(self);
                    if (b != null && !b.isRecycled()) {
                        return b;
                    }
                } catch (Throwable ignored) {
                    // field is not readable; try the next one
                }
            }
        }
        return null;
    }

    private static Bitmap asBitmap(Object o) {
        if (o instanceof Bitmap) {
            Bitmap b = (Bitmap) o;
            return b.isRecycled() ? null : b;
        }
        if (o == null) {
            return null;
        }
        // Frame wrappers usually keep the bitmap in a field called bitmap/frame/mImage.
        for (Field f : o.getClass().getDeclaredFields()) {
            if (!Bitmap.class.isAssignableFrom(f.getType())) {
                continue;
            }
            try {
                f.setAccessible(true);
                Bitmap b = (Bitmap) f.get(o);
                if (b != null && !b.isRecycled()) {
                    return b;
                }
            } catch (Throwable ignored) {
                // same as above
            }
        }
        return null;
    }

    /** Best-effort write-back: score/description fields and any JSON-ish setter we can find. */
    private static boolean putIntoResult(Object result, CompositionHeuristic.Suggestion s) {
        if (result == null) {
            return false;
        }
        boolean wrote = false;
        for (Field f : result.getClass().getDeclaredFields()) {
            String n = f.getName().toLowerCase(Locale.US);
            try {
                f.setAccessible(true);
                if (f.getType() == int.class && (n.contains("score") || n.contains("mark"))) {
                    f.setInt(result, s.score);
                    wrote = true;
                } else if (f.getType() == String.class && (n.contains("desc") || n.contains("tip"))) {
                    f.set(result, CompositionHeuristic.describe(s));
                    wrote = true;
                }
            } catch (Throwable ignored) {
                // read-only field; keep going
            }
        }
        return wrote;
    }
}
