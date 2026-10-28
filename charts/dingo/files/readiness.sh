#!/bin/sh
set -eu

health_port=$1
request_timeout=$2
blockfrost_port=$3
blockfrost_scheme=$4
shift 4

timeout "$request_timeout" wget --no-proxy --quiet --tries=1 --timeout="$request_timeout" --output-document=/dev/null \
  "http://127.0.0.1:$health_port/readyz"

for port do
  timeout "$request_timeout" /bin/bash -ec \
    'exec 3<>/dev/tcp/127.0.0.1/"$1"' readiness "$port"
done

if [ "$blockfrost_port" -gt 0 ]; then
  # The loopback connection uses the pod's certificate, whose SAN is its public hostname.
  timeout "$request_timeout" wget --no-proxy --quiet --tries=1 --timeout="$request_timeout" --no-check-certificate \
    --output-document=/dev/null \
    "$blockfrost_scheme://127.0.0.1:$blockfrost_port/blocks/latest"
fi
