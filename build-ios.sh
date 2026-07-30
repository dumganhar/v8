#!/usr/bin/env bash

set -euo pipefail

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <arm64|x64> [device|simulator]" >&2
    exit 1
fi

ARCH=$1
TARGET_ENV=${2:-}

if [ "${ARCH}" != "arm64" ] && [ "${ARCH}" != "x64" ]; then
    echo "Architecture must be 'arm64' or 'x64'" >&2
    exit 1
fi

if [ -z "${TARGET_ENV}" ]; then
    if [ "${ARCH}" = "x64" ]; then
        TARGET_ENV=simulator
    else
        TARGET_ENV=device
    fi
fi

if [ "${TARGET_ENV}" != "device" ] && [ "${TARGET_ENV}" != "simulator" ]; then
    echo "Target environment must be 'device' or 'simulator'" >&2
    exit 1
fi

if [ "${ARCH}" = "x64" ] && [ "${TARGET_ENV}" != "simulator" ]; then
    echo "x64 is only supported for the iOS simulator" >&2
    exit 1
fi

XCODE_DEVELOPER_PATH="${XCODE_DEVELOPER_PATH:-$(xcode-select -p)}"
CLANG_BASE_PATH="${XCODE_DEVELOPER_PATH}/Toolchains/XcodeDefault.xctoolchain/usr"
CLANG_VERSION=$(basename "$("${CLANG_BASE_PATH}/bin/clang" -print-resource-dir)")
GN_BIN="${GN:-buildtools/mac/gn}"
NINJA_BIN="${NINJA:-ninja}"

if [ ! -x "${GN_BIN}" ]; then
    echo "GN executable not found: ${GN_BIN}. Set GN=/path/to/gn." >&2
    exit 1
fi

ARGS="target_os=\"ios\"
v8_enable_pointer_compression=false
target_cpu=\"${ARCH}\"
v8_target_cpu=\"${ARCH}\"
enable_dsyms=false
enable_stripping=false
use_thin_lto=false
use_lld=false
clang_base_path=\"${CLANG_BASE_PATH}\"
clang_version=\"${CLANG_VERSION}\"
clang_use_chrome_plugins=false
standalone_use_xcode_clang=true
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
v8_enable_webassembly=false
v8_enable_sandbox=false
v8_enable_partition_alloc=false
ios_deployment_target=\"11.0\"
ios_enable_code_signing=false
target_environment=\"${TARGET_ENV}\""

"${GN_BIN}" gen out/ios --args="${ARGS}"

"${NINJA_BIN}" -C out/ios v8_monolith d8
