#!/usr/bin/env bash
set -eu
rm -rf /tmp/gateway-debug-mvp
cp -R /mnt/c/Users/z/Documents/worktrees/commercial-mvp/deploy/mvp /tmp/gateway-debug-mvp
sed -i '20c\	if false; then' /tmp/gateway-debug-mvp/verify-gateway.sh
export MVP_GATEWAY_NETWORK_SUBNET=10.255.247.0/24
export MVP_DEBUG_GATEWAY_ERRORS=1
bash /tmp/gateway-debug-mvp/verify-gateway.sh up
