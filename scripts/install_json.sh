#!/bin/bash

set -e

if [ -z "$PROJECT_DIR" ]; then
    source ./scripts/env_vars.sh
fi

JSON_DIR="$EXTERNALS_DIR/json"
JSON_VERSION_TAG="v3.11.2"

# Check if Boost directory exists
if [ ! -d "$JSON_DIR" ]; then
    # Clone Boost into the externals directory
    git clone https://github.com/nlohmann/json.git "${JSON_DIR}"
fi

# Checkout Version
cd "$JSON_DIR"
git pull origin "$JSON_VERSION_TAG"
git checkout "$JSON_VERSION_TAG"
cd -