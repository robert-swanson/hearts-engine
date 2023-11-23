#!/bin/bash

set -e

if [ -z "$PROJECT_DIR" ]; then
    source ./scripts/env_vars.sh
fi

GTEST_DIR="$EXTERNALS_DIR/googletest"
GTEST_VERSION_TAG="v1.14.0"

# Check if the Google Test directory exists
if [ ! -d "$GTEST_DIR" ]; then
    # Google Test directory doesn't exist, so clone it
    git clone https://github.com/google/googletest.git "$GTEST_DIR"
fi

# Checkout Version
cd "$GTEST_DIR"
git pull origin $GTEST_VERSION_TAG
git checkout "$GTEST_VERSION_TAG"
cd -

# Build Google Test
BUILD="$GTEST_DIR/__build"
mkdir -p "$BUILD"
cd "$BUILD"
cmake ..
make
cd -

echo "Google Test integration complete."
