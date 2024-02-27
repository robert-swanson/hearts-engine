#!/bin/bash

BIN=$1
CONFIG=$2

if [ -z $BIN ] || [ -z $CONFIG ]; then
    echo "Usage: $0 <bin> <config>"
    exit 1
fi

if [ ! -f $BIN ]; then
    echo "Usage: $0 <bin> <config>"
    exit 1
fi

if [ ! -f $CONFIG ]; then
    echo "Config file $CONFIG not found"
    exit 1
fi

# assert current working directory is hearts-engine
if [[ "$PWD" != *hearts-engine ]]; then
    echo "Please run this script from the hearts-engine directory"
    exit 1
fi

LOG_DIR=log/server/instances
mkdir -p $LOG_DIR

while true; do
    LOG_NAME=$LOG_DIR/$(date +"%Y-%m-%d_%H:%M:%S")
    echo "Starting $BIN with config $CONFIG, logging to $LOG_NAME.log"

    ./$BIN $CONFIG 2>&1 | tee $LOG_NAME.log

    echo "Restarting $BIN in 5 seconds"
    sleep 5
done
