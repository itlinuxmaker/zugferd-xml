#!/bin/bash
# Installs the YAML file in the user's home directory.

CONFIG_DIR=$HOME/.config/zugferd-xml
if [ ! -d "$CONFIG_DIR" ]; then
    mkdir -p "$CONFIG_DIR"
fi

cp ../src/invoicedata.yaml $CONFIG_DIR/