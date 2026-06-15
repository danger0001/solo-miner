#!/usr/bin/env bash
# start.sh — CSD 单机 GPU 矿工启动脚本
#
# 用法：
#   ./start.sh                              # 自动检测带宽，选择最优节点
#   ./start.sh --引导节点 全部              # 强制使用全部主网节点
#   ./start.sh --跳过带宽检测              # 跳过带宽检测，使用全部节点
#   ./start.sh --带宽阈值 10               # 自定义低带宽阈值（Mbps，默认 5）
#   ./start.sh --显卡 1                    # 使用第二块显卡
#   ./start.sh --仅矿工                    # 不启动 csd 节点（使用已有节点）
#   ./start.sh --调试                      # 输出详细日志
#
set -euo pipefail

log_info() { echo "[信息] $*"; }
log_ok()   { echo "[完成] $*"; }
log_warn() { echo "[警告] $*"; }
log_err()  { echo "[错误] $*" >&2; exit 1; }

MAINNET_NODES=(
    "/ip4/151.240.121.186/tcp/17999"
    "/ip4/151.240.121.220/tcp/17999"
    "/ip4/151.240.121.187/tcp/17999"
    "/ip4/158.69.116.36/tcp/17999"
    "/ip4/145.239.0.111/tcp/17999"
    "/ip4/151.240.121.189/tcp/17999"
)

ARG_BOOTNODES=""
ARG_GPU=""
ARG_NO_NODE=""
ARG_DEBUG=""
ARG_SKIP_BW=""
ARG_BW_THRESHOLD=""
CONFIG_FILE="config.yaml"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --引导节点|--bootnodes)
            ARG_BOOTNODES="$2"; shift 2 ;;
        --显卡|--gpu)
            ARG_GPU="$2"; shift 2 ;;
        --仅矿工|--no-node)
            ARG_NO_NODE="--no-node"; shift ;;
        --调试|--debug)
            ARG_DEBUG="--debug"; shift ;;
        --跳过带宽检测|--skip-bw)
            ARG_SKIP_BW="--skip-bw"; shift ;;
        --带宽阈值|--bw-threshold)
            ARG_BW_THRESHOLD="--bw-threshold $2"; shift 2 ;;
        --配置|--config)
            CONFIG_FILE="$2"; shift 2 ;;
        *)
            EXTRA_ARGS+=("$1"); shift ;;
    esac
done

[[ -f "$CONFIG_FILE" ]] || log_err "配置文件 $CONFIG_FILE 不存在，请先运行安装脚本"
[[ -f "csd" ]]          || log_err "csd 程序不存在，请先运行安装脚本"
[[ -f "genesis.bin" ]]  || log_err "genesis.bin 不存在，请先运行安装脚本"
python3 --version >/dev/null 2>&1 || log_err "未找到 python3"
python3 -c "import aiohttp" 2>/dev/null || log_err "缺少依赖，请运行：pip install -r requirements.txt"

if [[ -z "$ARG_BOOTNODES" ]]; then
    BN_FLAG=""
    log_info "引导节点：使用 config.yaml 中的配置"
elif [[ "${ARG_BOOTNODES,,}" == "全部" ]] || [[ "${ARG_BOOTNODES,,}" == "all" ]]; then
    BN_LIST=$(IFS=","; echo "${MAINNET_NODES[*]}")
    BN_FLAG="--bootnodes ${BN_LIST}"
    log_info "引导节点：全部 ${#MAINNET_NODES[@]} 个主网节点"
else
    BN_FLAG="--bootnodes ${ARG_BOOTNODES}"
    IFS=',' read -ra NODE_ARR <<< "$ARG_BOOTNODES"
    log_info "引导节点：${#NODE_ARR[@]} 个自定义节点"
fi

if command -v nvidia-smi &>/dev/null; then
    GPU_IDX="${ARG_GPU:-0}"
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i "$GPU_IDX" 2>/dev/null || echo "未知")
    log_ok "使用显卡 [$GPU_IDX] $GPU_NAME"
else
    log_warn "未检测到 NVIDIA 显卡，使用 CPU 模式"
fi

[[ -n "$ARG_GPU" ]] && GPU_FLAG="--gpu $ARG_GPU" || GPU_FLAG=""

echo ""
echo "========================================"
echo "   CSD 单机 GPU 矿工  ·  正在启动"
echo "========================================"
echo ""

CMD="python3 miner.py --config ${CONFIG_FILE} ${BN_FLAG} ${GPU_FLAG} ${ARG_NO_NODE} ${ARG_DEBUG} ${ARG_SKIP_BW} ${ARG_BW_THRESHOLD}"
log_info "执行命令：$CMD"
echo ""

exec $CMD "${EXTRA_ARGS[@]}"
