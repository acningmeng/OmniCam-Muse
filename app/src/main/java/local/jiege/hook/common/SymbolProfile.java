package local.jiege.hook.common;

import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Which symbol spec this device build should use.
 *
 * The spec that ships in assets/symbols.json describes the Find X9 Ultra camera. A different
 * camera build resolves some symbols to different names, and rewriting the base spec in place
 * makes the two devices mutually exclusive -- the Find X8 Ultra work used to do exactly that.
 * Instead each device carries its own directory:
 *
 *     assets/profiles/x8u/profile.json    {"models": ["PKU110","PKJ110"], "cameraVersion": "…"}
 *     assets/profiles/x8u/symbols.json    the full spec for that build
 *
 * Selection is by ro.product.model, narrowed by the camera's versionName when it can be read
 * (it is not always available in the gallery process). No match means the base spec, which is
 * what the Find X9 Ultra needs; a wrong profile is worse than none, because a symbol that
 * resolves to the wrong member throws at hook time instead of staying quietly missing.
 */
public final class SymbolProfile {
    private static final String TAG = "SymbolProfile";
    private static final String DIR = "assets/profiles/";
    private static final String META = "profile.json";
    public static final String DEFAULT_SPEC = "assets/symbols.json";

    private static volatile String spec;
    private static volatile String id = "default";

    private SymbolProfile() {
    }

    /** Asset path of the spec to load ("assets/symbols.json" when no profile matches). */
    public static String spec() {
        resolve();
        return spec;
    }

    /** Profile id for logs and diagnostics ("default" when no profile matched). */
    public static String id() {
        resolve();
        return id;
    }

    private static void resolve() {
        if (spec != null) return;
        synchronized (SymbolProfile.class) {
            if (spec != null) return;
            String chosen = DEFAULT_SPEC;
            String chosenId = "default";
            String module = Symbols.modulePath();
            if (module != null) {
                try (ZipFile apk = new ZipFile(module)) {
                    Enumeration<? extends ZipEntry> entries = apk.entries();
                    while (entries.hasMoreElements()) {
                        ZipEntry entry = entries.nextElement();
                        String name = entry.getName();
                        if (!name.startsWith(DIR) || !name.endsWith("/" + META)) continue;
                        JSONObject meta;
                        try (InputStream in = apk.getInputStream(entry)) {
                            meta = new JSONObject(new String(readAll(in), "UTF-8"));
                        }
                        if (!matches(meta)) continue;
                        String dir = name.substring(0, name.length() - META.length());
                        chosen = dir + meta.optString("symbols", "symbols.json");
                        chosenId = meta.optString("profileId", dir.substring(DIR.length()));
                        break;
                    }
                } catch (Throwable error) {
                    Log.i(TAG, "profile lookup failed, using the base spec: " + error);
                }
            }
            spec = chosen;
            id = chosenId;
            Log.i(TAG, "symbol profile " + id + " -> " + chosen);
        }
    }

    private static boolean matches(JSONObject meta) {
        JSONArray models = meta.optJSONArray("models");
        boolean model = false;
        String device = Build.MODEL == null ? "" : Build.MODEL;
        if (models != null) {
            for (int i = 0; i < models.length() && !model; i++) {
                model = device.equalsIgnoreCase(models.optString(i, ""));
            }
        }
        if (!model) return false;
        String version = meta.optString("cameraVersion", "");
        if (version.isEmpty()) return true;
        String actual = cameraVersion();
        // A profile keyed to a camera build must not be applied to another one: the obfuscated
        // names drift between builds. If the version cannot be read we still accept the model
        // match, because the alternative (no profile) is a guaranteed miss on every ported symbol.
        return actual.isEmpty() || actual.equals(version);
    }

    private static String cameraVersion() {
        try {
            Context context = currentApplication();
            if (context == null) return "";
            return context.getPackageManager()
                .getPackageInfo("com.oplus.camera", 0).versionName;
        } catch (PackageManager.NameNotFoundException | RuntimeException error) {
            return "";
        }
    }

    /** ActivityThread.currentApplication() is a hidden API, so reflection instead of a direct call. */
    private static Context currentApplication() {
        try {
            Object app = Class.forName("android.app.ActivityThread").getMethod("currentApplication").invoke(null);
            return (Context) app;
        } catch (Throwable error) {
            return null;
        }
    }

    private static byte[] readAll(InputStream in) throws Exception {
        try (InputStream input = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            for (int n; (n = input.read(buffer)) > 0; ) out.write(buffer, 0, n);
            return out.toByteArray();
        }
    }
}
