$cmd = @'
set -eu
rm -rf /tmp/gateway-debug-mvp /tmp/mvp-debug.log
cp -R /mnt/c/Users/z/Documents/worktrees/commercial-mvp/deploy/mvp /tmp/gateway-debug-mvp
sed -i '/cleanup() {/a\\tif [[ \"$MVP_KEEP_GATEWAY_PROOF\" == 1 ]]; then return; fi' /tmp/gateway-debug-mvp/verify-gateway.sh
export MVP_GATEWAY_NETWORK_SUBNET=10.255.247.0/24
export MVP_KEEP_GATEWAY_PROOF=1
export MVP_DEBUG_GATEWAY_ERRORS=1
bash /tmp/gateway-debug-mvp/verify-gateway.sh up
'@
wsl.exe bash -lc $cmd
exit $LASTEXITCODE