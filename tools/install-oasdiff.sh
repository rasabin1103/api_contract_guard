#!/usr/bin/env sh
set -eu
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
case "$(uname -s)" in Linux) os=linux;; Darwin) os=darwin;; *) echo 'Use the PowerShell installer on Windows'; exit 2;; esac
case "$(uname -m)" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) exit 2;; esac
if [ "$os" = darwin ]; then arch=all; fi
mkdir -p "$root/tools/bin"
cd "$root/tools/bin"
archive="oasdiff_1.34.0_${os}_${arch}.tar.gz"
release=https://github.com/oasdiff/oasdiff/releases/download/v1.34.0
curl -fLsS "$release/$archive" -o "$archive"
curl -fLsS "$release/checksums.txt" -o checksums.txt
awk -v name="$archive" '$2 == name { print }' checksums.txt > selected-checksum.txt
test -s selected-checksum.txt
if command -v sha256sum >/dev/null; then sha256sum -c selected-checksum.txt; else shasum -a 256 -c selected-checksum.txt; fi
tar -xzf "$archive"
./oasdiff --version
