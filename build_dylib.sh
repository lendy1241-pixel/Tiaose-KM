#!/bin/bash
# ==============================================================
# build_dylib.sh — 编译 Kubelka-Munk 引擎 dylib (macOS)
# ==============================================================
# 用法:  ./build_dylib.sh
# 产出:  build/KMEngine.dylib
#
# 需要:  Xcode + Command Line Tools
# ==============================================================

set -e

SDK=$(xcrun --sdk iphoneos --show-sdk-path 2>/dev/null)
if [ -z "$SDK" ]; then
    echo "ERROR: 找不到 iPhoneOS SDK。请安装 Xcode。"
    exit 1
fi

echo "SDK: $SDK"

TARGET="arm64"
MIN_IOS="12.0"
OUTPUT="build/KMEngine.dylib"

mkdir -p build

echo "Compiling KM Engine dylib for $TARGET (iOS $MIN_IOS)..."

xcrun --sdk iphoneos clang \
    -arch $TARGET \
    -dynamiclib \
    -o "$OUTPUT" \
    -miphoneos-version-min=$MIN_IOS \
    -framework UIKit \
    -framework Foundation \
    -fobjc-arc \
    -O2 \
    -Wl,-undefined,dynamic_lookup \
    KMPigment.m \
    KMEngine.m \
    KMPigmentDatabase.m \
    KMHooks.m

echo ""
echo "[OK] dylib compiled: $OUTPUT"
echo ""
ls -lh "$OUTPUT"

# 检查
echo ""
echo "Load commands:"
xcrun otool -L "$OUTPUT" 2>/dev/null || otool -L "$OUTPUT"

echo ""
echo "Dependencies:"
xcrun nm -u "$OUTPUT" 2>/dev/null | grep -E "objc_msgSend|UIApplication|NSBundle|NSLog" | head -10 || true
