# CSD Solo GPU Miner

A GPU-accelerated solo miner for the [Compute Substrate](https://computesubstrate.org/) network. Uses CUDA to parallelize proposal hash computation, maximizing throughput when submitting proposals and attestations to the CSD mainnet.

---

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Bootstrap Nodes](#bootstrap-nodes)
- [GPU Mining Details](#gpu-mining-details)
- [Docker Deployment](#docker-deployment)
- [Manual Setup](#manual-setup)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

---

## Requirements

### Hardware
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16 GB |
| GPU | NVIDIA GTX 1060 (CUDA 6.1+) | NVIDIA RTX 3080+ |
| Storage | 20 GB SSD | 100 GB NVMe SSD |
| Network | 10 Mbps | 100 Mbps+ |

### Software
- Linux (Ubuntu 20.04+ recommended)
- NVIDIA Driver >= 470
- CUDA Toolkit >= 11.4
- Python >= 3.9
- Docker + NVIDIA Container Toolkit *(optional, for Docker deployment)*

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/csd-solo-miner.git
cd csd-solo-miner

# 2. Run the automated setup (downloads csd binary + genesis file)
chmod +x setup.sh && ./setup.sh

# 3. Start mining with default bootstrap nodes
./start.sh

# 4. Or specify custom bootstrap nodes
./start.sh --bootnodes "/ip4/151.240.121.186/tcp/17999,/ip4/158.69.116.36/tcp/17999"
```

---

## Configuration

Edit `config.yaml` before starting:

```yaml
# Miner identity
miner:
  wallet_address: "YOUR_WALLET_ADDRESS_HERE"
  domain: "compute"           # CSD domain to mine on
  worker_name: "worker-01"

# Node settings
node:
  datadir: "./cs.db"
  rpc_host: "0.0.0.0"
  rpc_port: 8789
  p2p_host: "0.0.0.0"
  p2p_port: 18007
  genesis: "./genesis.bin"

# GPU settings
gpu:
  device_id: 0                # GPU index (0 = first GPU)
  threads_per_block: 256
  max_blocks: 4096
  batch_size: 65536           # Hashes computed per GPU batch

# Mining settings
mining:
  proposal_interval: 12       # Seconds between proposal submissions
  attestation_interval: 6     # Seconds between attestation checks
  max_retries: 5
  difficulty_target: "0x00000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"

# Bootstrap nodes (mainnet defaults included)
bootnodes:
  - "/ip4/151.240.121.186/tcp/17999"
  - "/ip4/151.240.121.220/tcp/17999"
  - "/ip4/151.240.121.187/tcp/17999"
  - "/ip4/158.69.116.36/tcp/17999"
  - "/ip4/145.239.0.111/tcp/17999"
  - "/ip4/151.240.121.189/tcp/17999"
```

---

## Bootstrap Nodes

The following official mainnet bootstrap nodes are pre-configured. Using all of them is recommended for faster peer discovery:

| Node | Address |
|------|---------|
| Bootnode 1 | `/ip4/151.240.121.186/tcp/17999` |
| Bootnode 2 | `/ip4/151.240.121.220/tcp/17999` |
| Bootnode 3 | `/ip4/151.240.121.187/tcp/17999` |
| Bootnode 4 | `/ip4/158.69.116.36/tcp/17999`   |
| Bootnode 5 | `/ip4/145.239.0.111/tcp/17999`   |
| Bootnode 6 | `/ip4/151.240.121.189/tcp/17999` |

To override bootstrap nodes at runtime:

```bash
# Single node
./start.sh --bootnodes "/ip4/151.240.121.186/tcp/17999"

# Multiple nodes (comma-separated)
./start.sh --bootnodes "/ip4/151.240.121.186/tcp/17999,/ip4/158.69.116.36/tcp/17999"

# All mainnet nodes
./start.sh --bootnodes all
```

---

## GPU Mining Details

The miner accelerates proposal generation using CUDA:

1. **Batch Hash Computation** — CUDA kernels compute thousands of candidate nonces in parallel per block, selecting the best candidate that meets the current difficulty target.
2. **Parallel Attestation Scoring** — GPU evaluates multiple proposals simultaneously to find the highest-confidence attestations.
3. **Memory-Mapped Work Queue** — Pinned host memory enables zero-copy data transfer between CPU and GPU for low-latency proposal submission.

### GPU Auto-Detection

On startup the miner prints detected GPUs:

```
[GPU] Detected 1 CUDA device(s):
[GPU]   [0] NVIDIA GeForce RTX 3080  |  VRAM: 10240 MB  |  SM: 8.6  |  Cores: 8704
[GPU] Using device 0
```

### Multi-GPU (Coming Soon)

Multi-GPU support is planned. To manually run multiple instances across GPUs:

```bash
GPU_DEVICE=0 ./start.sh --rpc-port 8789 --p2p-port 18007 &
GPU_DEVICE=1 ./start.sh --rpc-port 8790 --p2p-port 18008 &
```

---

## Docker Deployment

### Prerequisites

Install NVIDIA Container Toolkit:

```bash
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list \
  | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Start with Docker Compose

```bash
# Copy and edit config
cp config.yaml.example config.yaml
nano config.yaml   # Set your wallet address

# Build and start
docker compose up -d

# View logs
docker compose logs -f miner

# Stop
docker compose down
```

### Environment Variables (Docker)

| Variable | Default | Description |
|----------|---------|-------------|
| `MINER_WALLET` | *(required)* | Your CSD wallet address |
| `GPU_DEVICE` | `0` | CUDA device index |
| `BOOTNODES` | *(all mainnet)* | Comma-separated bootnode multiaddrs |
| `RPC_PORT` | `8789` | Node RPC port |
| `P2P_PORT` | `18007` | P2P listen port |

---

## Manual Setup

If you prefer not to use `setup.sh`:

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Download genesis file
curl -O https://computesubstrate.org/downloads/genesis.bin

# 3. Download csd binary (Linux x86_64)
curl -O https://computesubstrate.org/downloads/csd-linux-amd64
chmod +x csd-linux-amd64
mv csd-linux-amd64 csd

# 4. Verify checksum
sha256sum -c checksums.txt

# 5. Start the node manually
./csd node \
  --datadir cs.db \
  --rpc 0.0.0.0:8789 \
  --genesis genesis.bin \
  --p2p-listen /ip4/0.0.0.0/tcp/18007 \
  --bootnodes /ip4/151.240.121.186/tcp/17999 \
  --bootnodes /ip4/151.240.121.220/tcp/17999 \
  --bootnodes /ip4/151.240.121.187/tcp/17999 \
  --bootnodes /ip4/158.69.116.36/tcp/17999 \
  --bootnodes /ip4/145.239.0.111/tcp/17999 \
  --bootnodes /ip4/151.240.121.189/tcp/17999

# 6. In a second terminal, start the GPU miner
python miner.py --config config.yaml
```

---

## Monitoring

The miner exposes a local dashboard at `http://localhost:9090/stats`:

```json
{
  "uptime_seconds": 3600,
  "proposals_submitted": 142,
  "proposals_accepted": 138,
  "attestations_submitted": 891,
  "gpu_hashrate_mhs": 1245.3,
  "gpu_utilization_pct": 94,
  "peers_connected": 12,
  "current_epoch": 8821,
  "last_reward_epoch": 8815
}
```

---

## Troubleshooting

**`CUDA not available` error**
- Verify `nvidia-smi` works and driver is installed.
- Install CUDA Toolkit matching your driver: https://developer.nvidia.com/cuda-downloads
- The miner will fall back to CPU mode automatically if CUDA is unavailable.

**`Connection refused` on RPC**
- Wait 30–60 seconds for the node to initialize and sync.
- Check that ports 8789 (RPC) and 18007 (P2P) are not blocked by a firewall.

**`genesis.bin not found`**
- Run `./setup.sh` again, or manually download:
  `curl -O https://computesubstrate.org/downloads/genesis.bin`

**Node not finding peers**
- Ensure at least one bootnode is reachable: `nc -zv 151.240.121.186 17999`
- Try specifying all bootnodes with `./start.sh --bootnodes all`

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Resources

- [Compute Substrate Website](https://computesubstrate.org/)
- [Original Paper](https://computesubstrate.org/downloads/Compute_Substrate_Original_Paper.pdf)
- [Official GitHub](https://github.com/compute-substrate/compute-substrate)
- [Explorer](https://explorer.computesubstrate.org)
