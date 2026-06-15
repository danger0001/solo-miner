#!/usr/bin/env python3
"""
miner.py — CSD Solo GPU Miner
Compute Substrate mainnet miner that uses GPU-accelerated hash computation
to submit proposals and attestations to the CSD network.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
import yaml

from gpu_worker import GPUWorker

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("csd-miner")

# ── Constants ─────────────────────────────────────────────────────────────────

MAINNET_BOOTNODES = [
    "/ip4/151.240.121.186/tcp/17999",
    "/ip4/151.240.121.220/tcp/17999",
    "/ip4/151.240.121.187/tcp/17999",
    "/ip4/158.69.116.36/tcp/17999",
    "/ip4/145.239.0.111/tcp/17999",
    "/ip4/151.240.121.189/tcp/17999",
]


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg


def build_rpc_url(cfg: dict) -> str:
    host = cfg["node"]["rpc_host"].replace("0.0.0.0", "127.0.0.1")
    port = cfg["node"]["rpc_port"]
    return f"http://{host}:{port}"


# ── Node management ───────────────────────────────────────────────────────────

class CSDNode:
    """Manages the csd node subprocess."""

    def __init__(self, cfg: dict, bootnodes: list[str]):
        self.cfg = cfg
        self.bootnodes = bootnodes
        self.process: Optional[subprocess.Popen] = None

    def _build_cmd(self) -> list[str]:
        n = self.cfg["node"]
        cmd = [
            "./csd", "node",
            "--datadir", n["datadir"],
            "--rpc", f"{n['rpc_host']}:{n['rpc_port']}",
            "--genesis", n["genesis"],
            "--p2p-listen", f"/ip4/{n['p2p_host']}/tcp/{n['p2p_port']}",
        ]
        for bn in self.bootnodes:
            cmd += ["--bootnodes", bn]
        return cmd

    def start(self):
        cmd = self._build_cmd()
        bn_display = ", ".join(self.bootnodes[:3])
        if len(self.bootnodes) > 3:
            bn_display += f" (+{len(self.bootnodes) - 3} more)"
        log.info("Starting csd node...")
        log.info("  Bootstrap nodes: %s", bn_display)
        log.info("  RPC: %s:%s", self.cfg["node"]["rpc_host"], self.cfg["node"]["rpc_port"])
        log.info("  P2P: /ip4/%s/tcp/%s", self.cfg["node"]["p2p_host"], self.cfg["node"]["p2p_port"])

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        log.info("csd node started (PID %d)", self.process.pid)

    def stop(self):
        if self.process and self.process.poll() is None:
            log.info("Stopping csd node (PID %d)...", self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    async def drain_logs(self):
        """Stream node stdout to logger in background."""
        if not self.process:
            return
        loop = asyncio.get_event_loop()
        while self.is_running():
            line = await loop.run_in_executor(None, self.process.stdout.readline)
            if line:
                log.debug("[node] %s", line.rstrip())
            else:
                await asyncio.sleep(0.1)


# ── RPC client ────────────────────────────────────────────────────────────────

class CSDClient:
    """Thin async HTTP client for the csd node RPC."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        return self

    async def __aexit__(self, *_):
        if self._session:
            await self._session.close()

    async def _get(self, path: str) -> dict:
        async with self._session.get(f"{self.base_url}{path}") as r:
            r.raise_for_status()
            return await r.json()

    async def _post(self, path: str, data: dict) -> dict:
        async with self._session.post(
            f"{self.base_url}{path}",
            json=data,
            headers={"Content-Type": "application/json"},
        ) as r:
            r.raise_for_status()
            return await r.json()

    async def get_status(self) -> dict:
        return await self._get("/status")

    async def get_epoch(self) -> int:
        status = await self.get_status()
        return status.get("epoch", 0)

    async def get_peers(self) -> list:
        result = await self._get("/peers")
        return result.get("peers", [])

    async def submit_proposal(self, domain: str, nonce: int, hash_hex: str, payload: str) -> dict:
        return await self._post("/proposal", {
            "domain": domain,
            "nonce": nonce,
            "hash": hash_hex,
            "payload": payload,
        })

    async def submit_attestation(self, proposal_id: str, score: float, confidence: float) -> dict:
        return await self._post("/attest", {
            "proposal_id": proposal_id,
            "score": score,
            "confidence": confidence,
        })

    async def get_proposals(self, domain: str, epoch: int) -> list:
        result = await self._get(f"/proposals/{domain}/{epoch}")
        return result.get("proposals", [])

    async def wait_for_node(self, retries: int = 30, delay: float = 2.0):
        """Block until the node RPC is responsive."""
        log.info("Waiting for node RPC to become available...")
        for attempt in range(retries):
            try:
                await self.get_status()
                log.info("Node RPC is ready.")
                return
            except Exception:
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
        raise RuntimeError("Node RPC did not become available in time.")


# ── Stats tracker ─────────────────────────────────────────────────────────────

class MinerStats:
    def __init__(self):
        self.start_time = time.time()
        self.proposals_submitted = 0
        self.proposals_accepted = 0
        self.attestations_submitted = 0
        self.last_epoch = 0
        self.last_reward_epoch = 0
        self.gpu_hashrate_mhs = 0.0
        self.peers_connected = 0

    def uptime(self) -> int:
        return int(time.time() - self.start_time)

    def to_dict(self) -> dict:
        return {
            "uptime_seconds": self.uptime(),
            "proposals_submitted": self.proposals_submitted,
            "proposals_accepted": self.proposals_accepted,
            "attestations_submitted": self.attestations_submitted,
            "gpu_hashrate_mhs": round(self.gpu_hashrate_mhs, 2),
            "peers_connected": self.peers_connected,
            "current_epoch": self.last_epoch,
            "last_reward_epoch": self.last_reward_epoch,
        }

    def log_summary(self):
        log.info(
            "Stats | epoch=%d  proposals=%d/%d  attestations=%d  hashrate=%.1f MH/s  peers=%d  uptime=%ds",
            self.last_epoch,
            self.proposals_accepted,
            self.proposals_submitted,
            self.attestations_submitted,
            self.gpu_hashrate_mhs,
            self.peers_connected,
            self.uptime(),
        )


# ── Stats HTTP server ─────────────────────────────────────────────────────────

async def stats_server(stats: MinerStats, host: str = "127.0.0.1", port: int = 9090):
    """Serve a simple JSON stats endpoint at /stats."""
    from aiohttp import web

    async def handle(request):
        return web.json_response(stats.to_dict())

    app = web.Application()
    app.router.add_get("/stats", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Stats endpoint: http://%s:%d/stats", host, port)


# ── Mining loop ───────────────────────────────────────────────────────────────

async def proposal_loop(client: CSDClient, gpu: GPUWorker, cfg: dict, stats: MinerStats):
    """Continuously generate GPU-accelerated proposals and submit them."""
    domain = cfg["mining"]["domain"]
    interval = cfg["mining"]["proposal_interval"]
    difficulty = cfg["mining"]["difficulty_target"]
    wallet = cfg["miner"]["wallet_address"]
    worker = cfg["miner"]["worker_name"]

    log.info("Starting proposal loop | domain=%s  interval=%ds", domain, interval)

    while True:
        try:
            epoch = await client.get_epoch()
            stats.last_epoch = epoch

            # GPU: compute best nonce + hash for this epoch
            t0 = time.perf_counter()
            nonce, hash_hex = await asyncio.get_event_loop().run_in_executor(
                None,
                gpu.find_nonce,
                epoch,
                difficulty,
            )
            elapsed = time.perf_counter() - t0
            stats.gpu_hashrate_mhs = (gpu.batch_size / elapsed) / 1e6

            payload = json.dumps({
                "wallet": wallet,
                "worker": worker,
                "epoch": epoch,
                "ts": int(time.time()),
            })

            result = await client.submit_proposal(domain, nonce, hash_hex, payload)
            stats.proposals_submitted += 1

            if result.get("accepted"):
                stats.proposals_accepted += 1
                log.info(
                    "Proposal ACCEPTED | epoch=%d  nonce=%d  hash=%s...  hashrate=%.1f MH/s",
                    epoch, nonce, hash_hex[:16], stats.gpu_hashrate_mhs,
                )
            else:
                reason = result.get("reason", "unknown")
                log.warning("Proposal rejected | epoch=%d  reason=%s", epoch, reason)

        except aiohttp.ClientError as exc:
            log.warning("RPC error in proposal loop: %s", exc)
        except Exception as exc:
            log.error("Unexpected error in proposal loop: %s", exc, exc_info=True)

        await asyncio.sleep(interval)


async def attestation_loop(client: CSDClient, gpu: GPUWorker, cfg: dict, stats: MinerStats):
    """Fetch pending proposals and attest to the best ones using GPU scoring."""
    domain = cfg["mining"]["domain"]
    interval = cfg["mining"]["attestation_interval"]

    log.info("Starting attestation loop | domain=%s  interval=%ds", domain, interval)

    while True:
        try:
            epoch = await client.get_epoch()
            proposals = await client.get_proposals(domain, epoch)

            if proposals:
                # GPU: score all proposals in parallel
                scored = await asyncio.get_event_loop().run_in_executor(
                    None,
                    gpu.score_proposals,
                    proposals,
                )
                # Attest to the top-ranked proposal
                best = max(scored, key=lambda x: x["score"])
                result = await client.submit_attestation(
                    best["id"], best["score"], best["confidence"]
                )
                stats.attestations_submitted += 1
                log.debug(
                    "Attested | proposal=%s  score=%.4f  confidence=%.4f",
                    best["id"][:12], best["score"], best["confidence"],
                )

        except aiohttp.ClientError as exc:
            log.warning("RPC error in attestation loop: %s", exc)
        except Exception as exc:
            log.error("Unexpected error in attestation loop: %s", exc, exc_info=True)

        await asyncio.sleep(interval)


async def peer_monitor(client: CSDClient, stats: MinerStats):
    """Periodically update peer count."""
    while True:
        try:
            peers = await client.get_peers()
            stats.peers_connected = len(peers)
            if stats.peers_connected == 0:
                log.warning("No peers connected — check bootstrap nodes or network")
        except Exception:
            pass
        await asyncio.sleep(30)


async def stats_reporter(stats: MinerStats):
    """Print periodic summary."""
    while True:
        await asyncio.sleep(60)
        stats.log_summary()


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="CSD Solo GPU Miner")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--bootnodes",
        default=None,
        help='Comma-separated bootnode multiaddrs, or "all" for all mainnet nodes',
    )
    parser.add_argument("--no-node", action="store_true", help="Skip launching csd node (use existing)")
    parser.add_argument("--gpu", type=int, default=None, help="Override GPU device index")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def resolve_bootnodes(args_bootnodes: Optional[str], cfg_bootnodes: list[str]) -> list[str]:
    if args_bootnodes is None:
        return cfg_bootnodes or MAINNET_BOOTNODES
    if args_bootnodes.strip().lower() == "all":
        return MAINNET_BOOTNODES
    return [bn.strip() for bn in args_bootnodes.split(",") if bn.strip()]


async def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load config
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        log.error("Config file not found: %s  (run ./setup.sh first)", cfg_path)
        sys.exit(1)
    cfg = load_config(str(cfg_path))

    # Apply CLI overrides
    if args.gpu is not None:
        cfg["gpu"]["device_id"] = args.gpu

    bootnodes = resolve_bootnodes(args.bootnodes, cfg.get("bootnodes", []))
    log.info("Bootstrap nodes (%d):", len(bootnodes))
    for bn in bootnodes:
        log.info("  %s", bn)

    # Validate wallet
    wallet = cfg["miner"].get("wallet_address", "")
    if not wallet or wallet == "YOUR_WALLET_ADDRESS_HERE":
        log.error("wallet_address is not set in config.yaml")
        sys.exit(1)

    stats = MinerStats()

    # Start csd node subprocess
    node = CSDNode(cfg, bootnodes)
    if not args.no_node:
        node.start()

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        log.info("Shutdown signal received...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Initialize GPU worker
    gpu = GPUWorker(
        device_id=cfg["gpu"]["device_id"],
        threads_per_block=cfg["gpu"]["threads_per_block"],
        max_blocks=cfg["gpu"]["max_blocks"],
        batch_size=cfg["gpu"]["batch_size"],
    )
    gpu.initialize()

    rpc_url = build_rpc_url(cfg)

    async with CSDClient(rpc_url) as client:
        await client.wait_for_node(retries=40, delay=3.0)

        tasks = [
            asyncio.create_task(proposal_loop(client, gpu, cfg, stats)),
            asyncio.create_task(attestation_loop(client, gpu, cfg, stats)),
            asyncio.create_task(peer_monitor(client, stats)),
            asyncio.create_task(stats_reporter(stats)),
            asyncio.create_task(stats_server(stats)),
        ]
        if not args.no_node:
            tasks.append(asyncio.create_task(node.drain_logs()))

        log.info("=" * 60)
        log.info("  CSD Solo GPU Miner running")
        log.info("  Wallet : %s", wallet)
        log.info("  Domain : %s", cfg["mining"]["domain"])
        log.info("  GPU    : device %d", cfg["gpu"]["device_id"])
        log.info("  Stats  : http://127.0.0.1:9090/stats")
        log.info("=" * 60)

        # Run until shutdown signal or node dies
        await shutdown_event.wait()

        log.info("Shutting down...")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    node.stop()
    gpu.shutdown()
    log.info("Miner stopped. Final stats:")
    stats.log_summary()


if __name__ == "__main__":
    asyncio.run(main())
