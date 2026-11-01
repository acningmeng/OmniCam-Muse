package local.jiege.hook.composition;

/**
 * Framing heuristics for the stock "inspiration composition" (灵感构图) panel.
 *
 * <p>The camera asks an {@code com.oplus.aiunit.core.base.FrameDetector} for a suggestion and draws
 * whatever comes back; on this device the detector is never downloaded (the aiunit composition unit
 * is not part of the shipped capability package), so the panel stays empty. Instead of talking to
 * that cloud unit we score the preview ourselves and hand the same shape of answer back.
 *
 * <p>Everything here is pure integer maths over ARGB pixels: no Android types, no native code, no
 * network, so it can be unit tested on a desktop JVM (see tools/offline_tests/CompositionHeuristicTest.java).
 */
public final class CompositionHeuristic {

    /** Result of one analysis pass. Box coordinates are normalised to 0..1. */
    public static final class Suggestion {
        public final int score;          // 0..100, higher is better framed
        public final String tip;         // one short line for the panel
        public final float left, top, right, bottom;

        Suggestion(int score, String tip, float left, float top, float right, float bottom) {
            this.score = score;
            this.tip = tip;
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
        }

        public String boxJson() {
            return String.format(java.util.Locale.US,
                    "{\"x\":%.3f,\"y\":%.3f,\"w\":%.3f,\"h\":%.3f}",
                    left, top, right - left, bottom - top);
        }
    }

    /** Below this the panel shows "move a little" instead of a score. */
    public static final int SCORE_OK = 62;

    private static final int GRID = 3;

    private CompositionHeuristic() {
    }

    /**
     * Analyses one frame.
     *
     * @param width  frame width in pixels, must be &gt; 8
     * @param height frame height in pixels, must be &gt; 8
     * @param argb   row-major ARGB pixels, {@code width * height} entries
     */
    public static Suggestion plan(int width, int height, int[] argb) {
        if (width < 8 || height < 8 || argb == null || argb.length < width * height) {
            return new Suggestion(0, "画面还没准备好", 0.25f, 0.25f, 0.75f, 0.75f);
        }

        // 1. Luma + Sobel magnitude, downsampled by stepping so a 4K preview still costs ~nothing.
        int step = Math.max(1, Math.min(width, height) / 240);
        int gw = (width + step - 1) / step;
        int gh = (height + step - 1) / step;
        int[] luma = new int[gw * gh];
        for (int y = 0; y < gh; y++) {
            int sy = Math.min(height - 1, y * step);
            for (int x = 0; x < gw; x++) {
                int sx = Math.min(width - 1, x * step);
                int p = argb[sy * width + sx];
                int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
                luma[y * gw + x] = (r * 77 + g * 151 + b * 28) >> 8;
            }
        }

        // 2. Edge energy centroid and per-cell energy (3x3 cells for the rule of thirds).
        double sumW = 0, sumX = 0, sumY = 0;
        int[] cell = new int[GRID * GRID];
        for (int y = 1; y < gh - 1; y++) {
            for (int x = 1; x < gw - 1; x++) {
                int gx = luma[y * gw + x + 1] - luma[y * gw + x - 1];
                int gy = luma[(y + 1) * gw + x] - luma[(y - 1) * gw + x];
                int mag = Math.abs(gx) + Math.abs(gy);
                if (mag < 24) {
                    continue;
                }
                sumW += mag;
                sumX += (double) mag * x;
                sumY += (double) mag * y;
                int cx = Math.min(GRID - 1, x * GRID / gw);
                int cy = Math.min(GRID - 1, y * GRID / gh);
                cell[cy * GRID + cx] += mag;
            }
        }

        if (sumW <= 0) {
            return new Suggestion(0, "把要拍的东西放进取景框", 0.25f, 0.25f, 0.75f, 0.75f);
        }

        float cx = (float) (sumX / sumW) / gw;   // 0..1
        float cy = (float) (sumY / sumW) / gh;

        // 3. Nearest thirds intersection, and how far the centroid sits from it.
        float thirdX = nearestThird(cx);
        float thirdY = nearestThird(cy);
        float dx = cx - thirdX;
        float dy = cy - thirdY;
        float off = (float) Math.sqrt(dx * dx + dy * dy);   // 0..~0.47

        // 4. How much of the frame the busy area covers (cells above 12% of total energy).
        int busy = 0;
        for (int c : cell) {
            if (c > sumW * 0.12) {
                busy++;
            }
        }

        int score = 100 - Math.round(off * 210f);          // 0.1 off -> ~79
        if (busy >= 7) {
            score -= 12;                                    // everything is busy: no clear subject
        }
        score = Math.max(0, Math.min(100, score));

        String tip;
        if (off <= 0.055f) {
            tip = busy >= 7 ? "画面有点满，退后一点" : "构图不错，可以拍";
        } else if (Math.abs(dx) > Math.abs(dy)) {
            tip = dx > 0 ? "把主体往左挪一点" : "把主体往右挪一点";
        } else {
            tip = dy > 0 ? "把主体往上挪一点" : "把主体往下挪一点";
        }

        // 5. Suggested box: a square-ish window centred on the centroid, clamped into the frame.
        float half = 0.22f;
        float l = clamp01(cx - half), r = clamp01(cx + half);
        float t = clamp01(cy - half), b = clamp01(cy + half);
        return new Suggestion(score, tip, l, t, r, b);
    }

    /** The camera panel expects a description string; keep it short and in the UI language. */
    public static String describe(Suggestion s) {
        if (s.score >= SCORE_OK) {
            return s.tip;
        }
        // Below the bar the panel should coach the move, not show a number that means nothing to the user.
        return s.tip + "（先调整再拍）";
    }

    private static float nearestThird(float v) {
        float best = 1f / 3f;
        float d = Math.abs(v - best);
        for (float cand : new float[]{1f / 3f, 2f / 3f, 0.5f}) {
            float cd = Math.abs(v - cand);
            if (cd < d) {
                d = cd;
                best = cand;
            }
        }
        return best;
    }

    private static float clamp01(float v) {
        return v < 0f ? 0f : (v > 1f ? 1f : v);
    }
}
