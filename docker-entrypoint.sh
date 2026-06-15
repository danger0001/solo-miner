#!/usr/bin/env bash
# docker-entrypoint.sh — Generates config.yaml from env vars and starts miner
set -euo pipefail

WALLET="${MINER_WALLET:-}"
GPU="${GPU_DEVICE:-0}"
RPC="${RPC_PORT:-8789}"
P2P="${P2P_PORT:-18007}"
BN="${BOOTNODES:-all}"

if [[ -z "$WALLET" ]]; then
    echo "[ERROR] MINER_WALLET environment variable is required" >&2
    exit 1
fi

# Write config.yaml from environment
cat > /app/config.yaml <<EOF
miner:
  wallet_address: "${WALLET}"
  domain: "${DOMAIN:-compute}"
  worker_name: "${WORKER_NAME:-docker-worker}"

node:
  datadir: "/app/cs.db"
  rpc_host: "0.0.0.0"
  rpc_port: ${RPC}
  p2p_host: "0.0.0.0"
  p2p_port: ${P2P}
  genesis: "/app/genesis.bin"

gpu:
  device_id: ${GPU}
  threads_per_block: 256
  max_blocks: 4096
  batch_size: 65536

mining:
  proposal_interval: 12
  attestation_interval: 6
  max_retries: 5
  difficulty_target: "0x00000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"

bootnodes:
  - "/ip4/151.240.121.186/tcp/17999"
  - "/ip4/151.240.121.220/tcp/17999"
  - "/ip4/151.240.121.187/tcp/17999"
  - "/ip4/158.69.116.36/tcp/17999"
  - "/ip4/145.239.0.111/tcp/17999"
  - "/ip4/151.240.121.189/tcp/17999"
EOF

echo "[entrypoint] Starting CSD Solo GPU Miner..."
echo "[entrypoint] Wallet : $WALLET"
echo "[entrypoint] GPU    : $GPU"
echo "[entrypoint] RPC    : $RPC  |  P2P : $P2P"
echo "[entrypoint] Bootnodes: $BN"

exec python3 /app/miner.py --config /app/config.yaml --bootnodes "${BN}"
