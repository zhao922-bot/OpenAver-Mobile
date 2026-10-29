#!/usr/bin/env bash
set -euo pipefail

target="${1:?usage: tools/apply_patches.sh <clean-upstream-python-root>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -d "$target" ]; then
    echo "target does not exist: $target" >&2
    exit 2
fi

if ! git -C "$target" rev-parse --git-dir >/dev/null 2>&1; then
    git -C "$target" init -q
fi

for patch in "$repo_root"/patches/*.patch; do
    name="$(basename "$patch")"
    if git -C "$target" -c core.autocrlf=false apply --check "$patch" 2>/dev/null; then
        git -C "$target" -c core.autocrlf=false apply --whitespace=nowarn "$patch"
        echo "applied $name"
    elif git -C "$target" -c core.autocrlf=false apply --reverse --check "$patch" 2>/dev/null; then
        echo "already applied $name"
    else
        echo "cannot apply $name (tree is neither clean nor already patched)" >&2
        exit 1
    fi
done
