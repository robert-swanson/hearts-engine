#!/bin/bash

set -e

if [ -z "$PROJECT_DIR" ]; then
    source ./scripts/env_vars.sh
fi


BOOST_DIR="$EXTERNALS_DIR/boost"
BOOST_VERSION_TAG="boost-1.83.0"

# Check if Boost directory exists
if [ ! -d "$BOOST_DIR" ]; then
    git clone --recursive https://github.com/boostorg/boost.git "$BOOST_DIR"
fi

# Checkout Version
cd "$BOOST_DIR"
git pull origin "$BOOST_BOOST_VERSION_TAG"
git checkout "$BOOST_VERSION_TAG"
cd -

# Build Boost
mkdir -p "$BOOST_DIR/__build"
cd "$BOOST_DIR/__build"
cmake ..
cmake --build . --target install
cd -
