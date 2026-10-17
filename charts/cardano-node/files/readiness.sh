#!/bin/sh
set -eu

config=${CARDANO_CONFIG:?CARDANO_CONFIG is required}
genesis=${READINESS_SHELLEY_GENESIS_PATH:-}
if [ -z "$genesis" ]; then
    genesis=$(jq -er '.ShelleyGenesisFile | select(type == "string" and length > 0)' "$config")
fi
case "$genesis" in
    /*) ;;
    *) genesis=$(dirname "$config")/$genesis ;;
esac
network=$(jq -er '.networkId | select(. == "Mainnet" or . == "Testnet")' "$genesis")
if [ "$network" = Mainnet ]; then
    set -- --mainnet
else
    magic=$(jq -er '.networkMagic | select(type == "number" and . >= 0 and . <= 4294967295 and . == floor)' "$genesis")
    set -- --testnet-magic "$magic"
fi

query() {
    timeout --kill-after=1 "${READINESS_CLI_TIMEOUT_SECONDS:?}" \
        cardano-cli latest query "$@" --socket-path "${CARDANO_NODE_SOCKET_PATH:?}"
}

tip=$(query tip "$@")
# query tip can fall back to chain-sync when local state is unavailable.
slot=$(printf '%s' "$tip" | jq -er '
    select((.era | type) == "string" and (.era | length) > 0)
    | select((.syncProgress | type) == "string")
    | select((.syncProgress | tonumber) >= 0 and (.syncProgress | tonumber) <= 100)
    | .slot | select(type == "number" and . >= 0 and . == floor and . <= 9007199254740991)')
start=$(jq -er '.systemStart | select(type == "string")' "$genesis")
start=$(date -u -d "$start" +%s)
cutoff=$(($(date +%s) - READINESS_MAX_TIP_AGE_SECONDS))
if [ "$cutoff" -lt "$start" ]; then
    cutoff=$start
fi
cutoff=$(date -u -d "@$cutoff" +%Y-%m-%dT%H:%M:%SZ)
minimum=$(query slot-number "$@" "$cutoff")
printf '%s' "$minimum" | jq -e 'type == "number" and . >= 0 and . <= 9007199254740991 and . == floor' >/dev/null
jq -en --argjson slot "$slot" --argjson minimum "$minimum" '$slot >= $minimum' >/dev/null
