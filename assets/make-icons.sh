#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$root/build/icon-module-cache"
compiler=/Library/Developer/CommandLineTools/usr/bin/swiftc
if [ ! -x "$compiler" ]; then compiler=/usr/bin/swiftc; fi
"$compiler" -target arm64-apple-macos11.0 -sdk /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk -module-cache-path "$root/build/icon-module-cache" "$root/assets/render-icon.swift" -o "$root/build/render-icon"
"$root/build/render-icon" "$root"
python3 "$root/assets/pack-icons.py" "$root"
