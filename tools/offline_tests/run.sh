#!/bin/bash
# run.ps1 的 macOS 移植：纯 JVM 离线测试（滤镜目录、分组注入、预设选择）。
# 差异：classpath 分隔符 ';' -> ':'；dexkit AAR / kotlin-stdlib 从 ~/.gradle 缓存里找（路径同一套）。
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=$(cd "$HERE/../.." && pwd)
SDK=$(sed -n 's/^sdk\.dir=//p' "$PROJECT/local.properties")
[ -n "$SDK" ] || { echo "local.properties 缺 sdk.dir" >&2; exit 1; }

ANDROID_JAR=$(ls -1 "$SDK"/platforms/*/android.jar 2>/dev/null | sort -V | tail -1)
[ -f "$ANDROID_JAR" ] || { echo "找不到 android.jar" >&2; exit 1; }
XPOSED="$PROJECT/app/libs/api-82.jar"
OUT=${TMPDIR:-/tmp}/jiege_offline_tests
rm -rf "$OUT"; mkdir -p "$OUT"

# api-82.jar 只是编译期桩，测试先用反射替身（shim/）编译。
javac -encoding UTF-8 -d "$OUT" -cp "$XPOSED" "$HERE/shim/de/robv/android/xposed/XposedHelpers.java"

SRC=()
for f in "$PROJECT"/app/src/main/java/local/jiege/hook/filters/*.java; do SRC+=("$f"); done
SRC+=("$PROJECT/app/src/main/java/local/jiege/hook/common/Log.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/hook/common/Diagnostics.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/DiagnosticsContract.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/hook/common/Settings.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/hook/common/Symbols.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/hook/common/SymbolSearch.java")

DEXKIT=$(find "$HOME/.gradle/caches/modules-2/files-2.1/org.luckypray/dexkit" -name 'dexkit-*.aar' ! -name '*sources*' 2>/dev/null | sort -V | tail -1)
[ -n "$DEXKIT" ] || { echo "DexKit AAR 不在 Gradle 缓存里（先跑一次 Gradle 构建）" >&2; exit 1; }
unzip -o -q "$DEXKIT" classes.jar -d "$OUT"
KOTLIN=$(find "$HOME/.gradle/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib" -name 'kotlin-stdlib-2*.jar' ! -name '*sources*' 2>/dev/null | sort -V | tail -1)
[ -n "$KOTLIN" ] || { echo "kotlin-stdlib 不在 Gradle 缓存里" >&2; exit 1; }

CP="$OUT:$XPOSED:$OUT/classes.jar:$KOTLIN"

for f in "$PROJECT"/app/src/main/java/local/jiege/lut/*.java; do SRC+=("$f"); done
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/MasterFilterContract.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/MasterFilterStore.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/ModuleSettings.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/LaunchModes.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/ModelPresets.java")
SRC+=("$HERE/MasterLooksOfflineTest.java")
SRC+=("$PROJECT/app/src/main/java/local/jiege/settings/MasterLooks.java")
SRC+=("$HERE/StoreOfflineTest.java")
SRC+=("$HERE/FiltersOfflineTest.java")
SRC+=("$HERE/LutBakerOfflineTest.java")

javac -encoding UTF-8 -d "$OUT" -cp "$CP:$ANDROID_JAR" "${SRC[@]}"

java -Dfile.encoding=UTF-8 -cp "$CP:$ANDROID_JAR" FiltersOfflineTest
java -Dfile.encoding=UTF-8 -cp "$CP:$ANDROID_JAR" LutBakerOfflineTest "$PROJECT"
java -Dfile.encoding=UTF-8 -cp "$CP:$ANDROID_JAR" StoreOfflineTest "$PROJECT"
java -cp "$OUT" MasterLooksOfflineTest
echo "offline tests: ok"
