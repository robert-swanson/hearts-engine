#!/bin/bash

set -o xtrace

# Make externals if it doesn't exist
externals_dir="externals"
if [ ! -d "$gtest_dir" ]; then
    mkdir $externals_dir
fi

# Set the directory for Google Test
gtest_dir="externals/googletest"

# Check if the Google Test directory exists
if [ ! -d "$gtest_dir" ]; then
    # Google Test directory doesn't exist, so clone it
    git clone https://github.com/google/googletest.git "$gtest_dir"
else
    # Google Test directory already exists, so update it
    cd "$gtest_dir"
    git pull
    cd -
fi

# Build Google Test
mkdir -p "$gtest_dir/build"
cd "$gtest_dir/build"
cmake ..
make
cd -

echo "Google Test integration complete."
