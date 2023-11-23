#!/bin/bash

export PROJECT_DIR=""
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && cd .. && pwd )"
echo "Project directory is $PROJECT_DIR"

export EXTERNALS_DIR=$PROJECT_DIR/"externals"
export SCRIPTS_DIR=$PROJECT_DIR/"scripts"
