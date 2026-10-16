#!/bin/sh
set -eu
# Initial Alonzo/Conway states need their era's parameter counts, before extensions.
for era in alonzo conway; do
    if [ "$era" = alonzo ]; then field=costModels; else field=plutusV3CostModel; fi
    jq --arg field "$field" --slurpfile mainnet "/opt/cardano/config/mainnet/$era-genesis.json" \
        '.[$field] = $mainnet[0][$field]' "/opt/cardano/config/devnet/$era-genesis.json" > /tmp/genesis.json
    mv /tmp/genesis.json "/opt/cardano/config/devnet/$era-genesis.json"
done
start=$(date +%s)
jq --argjson start "$start" '.startTime = $start' /opt/cardano/config/devnet/byron-genesis.json > /tmp/genesis.json
mv /tmp/genesis.json /opt/cardano/config/devnet/byron-genesis.json
jq --arg start "$(date -u -d "@$start" +%Y-%m-%dT%H:%M:%SZ)" '.systemStart = $start' /opt/cardano/config/devnet/shelley-genesis.json > /tmp/genesis.json
mv /tmp/genesis.json /opt/cardano/config/devnet/shelley-genesis.json
printf '%s\n' '{"localRoots":[],"publicRoots":[],"useLedgerAfterSlot":-1}' > /tmp/topology.json
mkdir -p /ipc /data/db
chmod 0400 /opt/cardano/config/devnet/keys/*.skey
exec cardano-node run --config /opt/cardano/config/devnet/config.json \
    --database-path /data/db --socket-path /ipc/node.socket --topology /tmp/topology.json --port 3001 \
    --shelley-kes-key /opt/cardano/config/devnet/keys/kes.skey \
    --shelley-vrf-key /opt/cardano/config/devnet/keys/vrf.skey \
    --shelley-operational-certificate /opt/cardano/config/devnet/keys/opcert.cert
