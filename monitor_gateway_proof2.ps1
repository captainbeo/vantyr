$cmd = @'
set -eu
rm -f /tmp/mvp-proof-monitor2.log
cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp
export MVP_GATEWAY_NETWORK_SUBNET=10.255.247.0/24
export MVP_DEBUG_GATEWAY_ERRORS=1
bash deploy/mvp/verify-gateway.sh up > /tmp/mvp-proof-monitor2.log 2>&1 &
p=$!
while kill -0 $p 2>/dev/null; do
  names=$(docker ps --filter name=commercial-mvp-gateway-proof --format '{{.Names}}' | grep gateway-1 || true)
  if [ -n "$names" ]; then
    echo "=== $names ==="
    docker logs "$names" 2>&1 | tail -120
  fi
  sleep 5
done
cat /tmp/mvp-proof-monitor2.log
'@
wsl.exe bash -lc $cmd
exit $LASTEXITCODE