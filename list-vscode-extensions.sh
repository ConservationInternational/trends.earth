#!/usr/bin/env bash

EXT_DIR=".vscode-extensions"

find "$EXT_DIR" -maxdepth 1 -mindepth 1 -type d | while read -r dir; do
    pkg="$dir/package.json"
    if [[ -f "$pkg" ]]; then
        name=$(jq -r '.name' < "$pkg")
        publisher=$(jq -r '.publisher' < "$pkg")
        version=$(jq -r '.version' < "$pkg")
        echo "--install-extension ${publisher}.${name}@${version} \\"
    fi
done

