$env:MVP_GATEWAY_NETWORK_SUBNET = '10.255.247.0/24'
wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp; export MVP_GATEWAY_NETWORK_SUBNET=10.255.247.0/24; bash deploy/mvp/verify-gateway.sh up"
exit $LASTEXITCODE