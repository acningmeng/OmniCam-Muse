import local.jiege.hook.composition.CompositionHeuristic;

/**
 * Offline checks for the framing heuristic. No Android types: feed synthetic ARGB frames and look at
 * the suggestion. Run through tools/offline_tests/run.sh, which compiles the shim and this file with
 * the platform android.jar on the classpath.
 */
public final class CompositionHeuristicTest {

    private static int failures = 0;

    public static void main(String[] args) {
        emptyFrame();
        flatFrame();
        subjectOnLeftThird();
        subjectOnRightThird();
        centredSubject();
        System.out.println(failures == 0 ? "CompositionHeuristic: ok" : "CompositionHeuristic: " + failures + " failure(s)");
        if (failures != 0) {
            throw new AssertionError("CompositionHeuristicTest failed");
        }
    }

    /** A blank frame must not divide by zero and must ask the user to point at something. */
    private static void emptyFrame() {
        int[] px = new int[64 * 48];
        CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(0, 0, px);
        check("empty frame keeps score 0", s.score == 0);
    }

    /** Uniform colour = no edges: the panel should ask for a subject instead of scoring. */
    private static void flatFrame() {
        int w = 240, h = 180;
        int[] px = new int[w * h];
        java.util.Arrays.fill(px, 0xFF808080);
        CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(w, h, px);
        check("flat frame asks for a subject", s.score == 0 && s.tip.contains("取景框"));
    }

    /** A bright vertical bar sitting on the left third should be reported as well framed. */
    private static void subjectOnLeftThird() {
        int w = 300, h = 200;
        int[] px = new int[w * h];
        java.util.Arrays.fill(px, 0xFF303030);
        int barX = w / 3;
        for (int y = 20; y < h - 20; y++) {
            for (int x = barX - 4; x <= barX + 4; x++) {
                px[y * w + x] = 0xFFFFFFFF;
            }
        }
        CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(w, h, px);
        check("left third scores well (" + s.score + ")", s.score >= 70);
        check("left third needs no horizontal nudge", !s.tip.contains("往左") && !s.tip.contains("往右"));
    }

    /** The same bar pushed to the right edge must produce a "move left" hint. */
    private static void subjectOnRightThird() {
        int w = 300, h = 200;
        int[] px = new int[w * h];
        java.util.Arrays.fill(px, 0xFF303030);
        for (int y = 20; y < h - 20; y++) {
            for (int x = w - 30; x < w - 22; x++) {
                px[y * w + x] = 0xFFFFFFFF;
            }
        }
        CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(w, h, px);
        check("right edge is a low score (" + s.score + ")", s.score < 70);
        check("right edge suggests moving left (" + s.tip + ")", s.tip.contains("往左"));
    }

    /** Dead centre is acceptable but not ideal: we accept either a nudge or approval, not a crash. */
    private static void centredSubject() {
        int w = 300, h = 200;
        int[] px = new int[w * h];
        java.util.Arrays.fill(px, 0xFF303030);
        for (int y = 40; y < 160; y++) {
            for (int x = 140; x < 160; x++) {
                px[y * w + x] = 0xFFFFFFFF;
            }
        }
        CompositionHeuristic.Suggestion s = CompositionHeuristic.plan(w, h, px);
        check("centre still produces a box", s.right > s.left && s.bottom > s.top);
        check("box stays inside the frame", s.left >= 0f && s.right <= 1f && s.top >= 0f && s.bottom <= 1f);
    }

    private static void check(String what, boolean ok) {
        System.out.println((ok ? "  [ok]   " : "  [FAIL] ") + what);
        if (!ok) {
            failures++;
        }
    }
}
