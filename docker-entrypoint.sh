#!/usr/bin/env bash
# docker-entrypoint.sh — 从环境变量生成 config.yaml 并启动矿工
set -euo pipefail

钱包="${MINER_WALLET:-}"
显卡="${GPU_DEVICE:-0}"
RPC端口="${RPC_PORT:-8789}"
P2P端口="${P2P_PORT:-18007}"
引导节点="${BOOTNODES:-all}"

if [[ -z "$钱包" ]]; then
    echo "[错误] 必须设置环境变量 MINER_WALLET（CSD 钱包地址）" >&2
    exit 1
fi

# 根据环境变量写入配置文件
cat > /app/config.yaml <<EOF
miner:
  wallet_address: "${钱包}"
  domain: "${DOMAIN:-compute}"
  worker_name: "${WORKER_NAME:-docker-worker}"

node:
  datadir: "/app/cs.db"
  rpc_host: "0.0.0.0"
  rpc_port: ${RPC端口}
  p2p_host: "0.0.0.0"
  p2p_port: ${P2P端口}
  genesis: "/app/genesis.bin"

gpu:
  device_id: ${显卡}
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

echo "[启动] CSD 单机 GPU 矿工 - Docker 模式"
echo "[启动] 钱包地址  : $钱包"
echo "[启动] 显卡设备  : $显卡"
echo "[启动] RPC 端口  : $RPC端口 | P2P 端口: $P2P端口"
echo "[启动] 引导节点  : $引导节点"

exec python3 /app/miner.py --config /app/config.yaml --bootnodes "${引导节点}"
