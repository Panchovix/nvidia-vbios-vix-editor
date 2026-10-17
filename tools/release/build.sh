#!/bin/bash
# Linux release build from the committed tree of this checkout, in a podman container
# (tools/release/Containerfile). Published as tools/release/build.sh of the public repository.
# Usage: tools/release/build.sh VERSION (numeric X.Y.Z with optional -/+ suffix).
set -euo pipefail
if [ "$#" -ne 1 ]; then echo 'usage: tools/release/build.sh VERSION' >&2; exit 2; fi
version=$1
version_pattern='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?(\+[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?$'
valid_version() { local LC_ALL=C; [[ "$1" =~ $version_pattern ]]; }
if ! valid_version "$version"; then echo 'invalid release version: expected X.Y.Z with optional -/+ suffix' >&2; exit 2; fi
root=$(git rev-parse --show-toplevel)
cd "$root"
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo 'release builds require a clean tracked checkout' >&2; exit 1
fi
out="$root/dist/release-$version"
if [ -e "$out" ]; then echo "refusing to overwrite $out" >&2; exit 1; fi
# The container gets the committed tree only, never untracked or ignored files.
scratch=$(mktemp -d -t nvbios-release-input.XXXXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
git archive --format=zip --prefix="nvidia-vbios-editor-$version/" -o "$scratch/source.zip" HEAD
mkdir -p "$out"
podman build --network=host -q -t nvbios-release-linux -f tools/release/Containerfile tools/release
podman run --rm --network=host --security-opt=label=disable -e VERSION="$version" \
    -v "$scratch/source.zip:/in/export.zip:ro" -v "$root/tools/release:/tools:ro" -v "$out:/out" \
    nvbios-release-linux /tools/build-linux.sh
