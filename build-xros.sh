#!/bin/bash

set -e

XCODE_DEVELOPER_PATH=$(xcode-select -p)

ARCH=$1
TARGET_ENV=$2

ARGS="target_os=\"ios\"
v8_enable_pointer_compression=false
target_cpu=\"${ARCH}\"
v8_target_cpu=\"${ARCH}\"
enable_dsyms=false
use_thin_lto=false
use_lld=false
clang_base_path=\"${XCODE_DEVELOPER_PATH}/Toolchains/XcodeDefault.xctoolchain/usr\"
clang_use_chrome_plugins=false
chrome_pgo_phase=0
is_component_build=false
v8_monolithic=true
use_custom_libcxx=false
is_debug=false
v8_use_external_startup_data=false
is_official_build=true
v8_enable_i18n_support=false
treat_warnings_as_errors=false
symbol_level=0
v8_enable_webassembly=false
use_cxx17=true
v8_enable_sandbox=false
ios_deployment_target=\"11.0\"
ios_enable_code_signing=false"

if [[ "${TARGET_ENV}" == "" ]]; then
	FINAL_ARGS=${ARGS}
else
	FINAL_ARGS="${ARGS}
target_environment=\"${TARGET_ENV}\""
fi


echo "FINAL_ARGS:${FINAL_ARGS}"


gn gen out/ios --args="${FINAL_ARGS}"

ninja -C out/ios v8_monolith d8 -v