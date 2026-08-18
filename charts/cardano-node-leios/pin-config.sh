#!/usr/bin/env bash
#
# Refreshes files/musashi/* from the canonical musashi testnet config source.
# Run this after a musashi network reset/hard-fork, then `git diff` the
# result and commit. Adapted from input-output-hk/ouroboros-leios's own
# testnet/pin-config.sh (same source, same file list) — this repo pins the
# files into the chart itself since the upstream cardano-node-leios image
# has no config baked in.

set -euo pipefail

SOURCE_URL="${1:-https://book.play.dev.cardano.org/environments-pre/leios}"
DEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/files/musashi"

FILES=(
  config.json
  byron-genesis.json
  shelley-genesis.json
  alonzo-genesis.json
  conway-genesis.json
  dijkstra-genesis.json
  peer-snapshot.json
)

mkdir -p "$DEST_DIR"

for f in "${FILES[@]}"; do
  tmp="$(mktemp)"
  curl -fsSL "${SOURCE_URL}/${f}" -o "$tmp"
  if ! jq empty "$tmp" 2>/dev/null; then
    echo "error: ${f} is not valid JSON, leaving ${DEST_DIR}/${f} untouched" >&2
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "${DEST_DIR}/${f}"
  echo "${f} ($(wc -c < "${DEST_DIR}/${f}") bytes)"
done

echo "source: ${SOURCE_URL}"
