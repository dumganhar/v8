#!/bin/bash

set -e

pushd out
rm -rf v8-xros-fat
mkdir v8-xros-fat
lipo -create ./v8-xros-arm64/obj/libv8_monolith.a ./v8-xros-x64/obj/libv8_monolith.a -output ./v8-xros-fat/libv8_monolith.a
lipo -create ./v8-xros-arm64/obj/d8 ./v8-xros-x64/obj/d8 -output ./v8-xros-fat/d8
cp -r ../include ./v8-xros-fat/

popd
