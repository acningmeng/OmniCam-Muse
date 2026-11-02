package local.jiege.hook.composition;

import android.graphics.Bitmap;
import android.util.Log;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

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
    /** Same switch the settings page writes; read through the shared prefs helper, not a marker file. */
    private static final String SETTING = local.jiege.settings.ModuleSettings.AI_COMPOSITION;

    private static final long INTERVAL_MS = 500L;
    /** How long a computed suggestion may be reused while the next frame is still being scored. */
    private static final long RESULT_TTL_MS = 1500L;
    private static volatile long sLastRun;
    private static boolean sReportedFrameClass;

    /**
     * Scoring runs on its own thread and the result is applied to the <em>next</em> callback.
     *
     * The helper calls us on the preview thread, and {@link CompositionHeuristic#plan} walks every pixel,
     * so doing it inline added ~10 ms to a 30 fps path. A result one frame late is invisible on a panel
     * that updates twice a second, and the single worker with a busy flag coalesces frames: while one is
     * being scored the rest are dropped instead of queued.
     */
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "muse-composition");
        thread.setDaemon(true);
        return thread;
    });
    private static final AtomicBoolean BUSY = new AtomicBoolean();
    private static final AtomicReference<CompositionHeuristic.Suggestion> LATEST = new AtomicReference<>();
    private static volatile long sLatestAt;

    private CompositionBridge() {
    }

    public static void installCamera(ClassLoader loader) {
        if (!local.jiege.hook.common.Settings.get(SETTING)) {
            Log.i(TAG, "local composition off (setting " + SETTING + ")");
            return;
        }
        // Two halves: the entry has to be visible before there is a panel to score, so open the config
        // bits first (AiComposition), then watch the helper that renders the suggestion.
        try {
            AiComposition.installCamera(loader);
        } catch (Throwable t) {
            Log.w(TAG, "entry opener unavailable: " + t);
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

        // Apply whatever the worker finished last; fail-open when it has nothing or it is stale.
        CompositionHeuristic.Suggestion cached = LATEST.get();
        if (cached != null && now - sLatestAt <= RESULT_TTL_MS) {
            Object result = param.getResult();
            boolean written = putIntoResult(result, cached);
            if (!sReportedFrameClass) {
                sReportedFrameClass = true;
                Log.i(TAG, String.format(Locale.US, "reused score=%d tip=%s box=%s result=%s written=%s",
                        cached.score, cached.tip, cached.boxJson(),
                        result == null ? "null" : result.getClass().getName(), written));
            }
        }

        if (now - sLastRun < INTERVAL_MS) {
            return;
        }
        Bitmap frame = findBitmap(param.thisObject, param.args);
        if (frame == null) {
            return;
        }
        if (!BUSY.compareAndSet(false, true)) {
            return; // a frame is already being scored; drop this one instead of queueing it
        }
        sLastRun = now;

        // Copy on the caller's thread: the camera owns this bitmap and may reuse it as soon as we return.
        int[] pixels;
        int w;
        int h;
        try {
            int sw = Math.min(frame.getWidth(), 320);
            int sh = Math.max(8, frame.getHeight() * sw / Math.max(1, frame.getWidth()));
            Bitmap small = null;
            Bitmap src = frame;
            if (frame.getWidth() > sw) {
                small = Bitmap.createScaledBitmap(frame, sw, sh, false);
                src = small;
            }
            w = src.getWidth();
            h = src.getHeight();
            pixels = new int[w * h];
            src.getPixels(pixels, 0, w, 0, 0, w, h);
            if (small != null && small != frame) {
                small.recycle();
            }
        } catch (Throwable t) {
            Log.w(TAG, "frame copy skipped: " + t);
            BUSY.set(false);
            return;
        }

        final int fw = w;
        final int fh = h;
        final int[] data = pixels;
        try {
            WORKER.execute(() -> {
                try {
                    CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(fw, fh, data);
                    LATEST.set(s);
                    sLatestAt = System.currentTimeMillis();
                } catch (Throwable t) {
                    Log.w(TAG, "analysis failed: " + t);
                } finally {
                    BUSY.set(false);
                }
            });
        } catch (Throwable t) {
            Log.w(TAG, "worker rejected the frame: " + t);
            BUSY.set(false);
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

    private static java.util.List<Field> allFields(Class<?> type) {
        java.util.List<Field> out = new java.util.ArrayList<>();
        for (Class<?> c = type; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Field f : c.getDeclaredFields()) {
                out.add(f);
            }
        }
        return out;
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
        for (Field f : allFields(result.getClass())) {
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
