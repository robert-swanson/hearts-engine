#!/bin/bash

set -e
set -o xtrace
source ./scripts/env_vars.sh

if [ ! -d "$EXTERNALS_DIR" ]; then
  mkdir -p "$EXTERNALS_DIR"
fi

source "$SCRIPTS_DIR"/install_gtest.sh
source "$SCRIPTS_DIR"/install_boost.sh
source "$SCRIPTS_DIR"/install_json.sh


echo "All external dependencies installed to $EXTERNALS_DIR!"