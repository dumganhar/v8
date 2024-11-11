#!/bin/bash

set -e

# Check if the number of arguments is 1
if [ $# -ne 1 ]; then
    echo "Usage: $0 <architecture>"
    exit 1
fi

# Get the value of the first argument
ARCH="$1"

# Check if the argument value is "arm64", "arm", "x86" or "x64"
if [ "${ARCH}" != "arm64" ] && [ "${ARCH}" != "arm" ] && [ "${ARCH}" != "x64" ] && [ "${ARCH}" != "x86" ]; then
    echo "Architecture must be 'arm64', 'arm', 'x86' or 'x64'"
    exit 1
fi

# If there is 1 argument and its value is "arm64" or "x64", continue with the rest of the script
echo "Valid architecture: ${ARCH}"

echo "NDK_ROOT=${NDK_ROOT}"

ARGS="target_os=\"android\"
target_cpu=\"${ARCH}\"
v8_target_cpu=\"${ARCH}\"
use_thin_lto=false
use_lld=true
clang_use_chrome_plugins=false
chrome_pgo_phase=0
is_component_build=false
v8_monolithic=true
use_custom_libcxx=false
is_debug=false
v8_use_external_startup_data=false
is_official_build=true
v8_enable_i18n_support=true
icu_use_data_file=false
treat_warnings_as_errors=false
symbol_level=0
v8_enable_webassembly=true
use_cxx17=true
v8_enable_sandbox=false
android_ndk_root=\"${NDK_ROOT}\"
clang_base_path=\"${NDK_ROOT}/toolchains/llvm/prebuilt/linux-x86_64\"
android_ndk_version=\"r23c\"
android_ndk_major_version=21
android32_ndk_api_level=19
android64_ndk_api_level=21
use_ml_inliner=false"


gn gen out/android --args="${ARGS}"

ninja -C out/android v8_monolith d8 -v
