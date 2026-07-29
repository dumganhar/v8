#!/usr/bin/env bash

set -euo pipefail
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

: "${NDK_ROOT:?Set NDK_ROOT to an Android NDK r28c directory}"
echo "NDK_ROOT=${NDK_ROOT}"
if [ "$(uname -s)" != "Linux" ]; then
    echo "Android builds require a Linux host." >&2
    exit 1
fi
GN_BIN="${GN:-buildtools/linux64/gn}"
NINJA_BIN="${NINJA:-ninja}"
CLANG_BASE_PATH="${NDK_ROOT}/toolchains/llvm/prebuilt/linux-x86_64"
CLANG_VERSION=$(basename "$("${CLANG_BASE_PATH}/bin/clang" -print-resource-dir)")

if [ ! -x "${GN_BIN}" ]; then
    echo "GN executable not found: ${GN_BIN}. Set GN=/path/to/gn." >&2
    exit 1
fi

ARGS="target_os=\"android\"
target_cpu=\"${ARCH}\"
v8_target_cpu=\"${ARCH}\"
enable_stripping=false
use_thin_lto=false
use_lld=true
clang_use_chrome_plugins=false
enable_rust=false
chrome_pgo_phase=0
is_component_build=false
v8_monolithic=true
v8_standalone_source_snapshot=true
use_custom_libcxx=false
use_clang_modules=false
is_debug=false
v8_use_external_startup_data=false
is_official_build=true
v8_enable_i18n_support=false
v8_enable_fuzztest=false
v8_enable_temporal_support=false
icu_use_data_file=false
treat_warnings_as_errors=false
symbol_level=0
v8_enable_webassembly=true
v8_enable_sandbox=false
v8_enable_partition_alloc=false
android_ndk_root=\"${NDK_ROOT}\"
clang_base_path=\"${CLANG_BASE_PATH}\"
clang_version=\"${CLANG_VERSION}\"
android_ndk_version=\"r28c\"
android_ndk_major_version=28
android32_ndk_api_level=21
android64_ndk_api_level=21
use_custom_libunwind=false
use_ml_inliner=false
llvm_android_mainline=true
"


"${GN_BIN}" gen out/android --args="${ARGS}"

"${NINJA_BIN}" -C out/android v8_monolith d8
