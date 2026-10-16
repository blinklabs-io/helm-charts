#!/bin/sh
set -eu
mkdir -p /ipc
date +%s > /tmp/started
socat UNIX-LISTEN:/ipc/node.socket,fork EXEC:/bin/cat &
exec socat "TCP-LISTEN:$CARDANO_PORT,fork,reuseaddr" EXEC:/bin/cat
