#!/usr/bin/env bash

set -euo pipefail

# Check if the number of arguments is 1
if [ $# -ne 1 ]; then
    echo "Usage: $0 <architecture>"
    exit 1
fi

# Get the value of the first argument
ARCH="$1"

# Check if the argument value is "arm64" or "x64"
if [ "${ARCH}" != "arm64" ] && [ "${ARCH}" != "x64" ]; then
    echo "Architecture must be 'arm64' or 'x64'"
    exit 1
fi

# If there is 1 argument and its value is "arm64" or "x64", continue with the rest of the script
echo "Valid architecture: ${ARCH}"

XCODE_DEVELOPER_PATH="${XCODE_DEVELOPER_PATH:-$(xcode-select -p)}"
CLANG_BASE_PATH="${XCODE_DEVELOPER_PATH}/Toolchains/XcodeDefault.xctoolchain/usr"
CLANG_VERSION=$(basename "$("${CLANG_BASE_PATH}/bin/clang" -print-resource-dir)")
GN_BIN="${GN:-buildtools/mac/gn}"
NINJA_BIN="${NINJA:-ninja}"

if [ ! -x "${GN_BIN}" ]; then
    echo "GN executable not found: ${GN_BIN}. Set GN=/path/to/gn." >&2
    exit 1
fi

ARGS="target_cpu=\"${ARCH}\"
v8_target_cpu=\"${ARCH}\"
mac_deployment_target=\"10.13\"
mac_min_system_version=\"10.13\"
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
v8_enable_webassembly=true
v8_enable_sandbox=false
v8_enable_partition_alloc=false"

"${GN_BIN}" gen out/mac --args="${ARGS}"

"${NINJA_BIN}" -C out/mac v8_monolith d8
