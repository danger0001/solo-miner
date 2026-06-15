"""
gpu_worker.py — CSD 单机 GPU 矿工 · CUDA 加速计算模块

提供两个核心功能：
  1. 搜索随机数()  — 并行搜索满足难度目标的 SHA-256(轮次||随机数) 哈希
  2. 评分提案()    — 批量评估提案并返回置信度分数

无 GPU 时自动退回 CPU（hashlib）模式。
"""

import hashlib
import logging
import struct
import time
from typing import Optional

日志 = logging.getLogger("csd-矿工.gpu")

# ── CUDA 库导入 ────────────────────────────────────────────────────────────────

try:
    import cupy as cp
    import numpy as np
    CUDA可用 = True
    CUPY可用 = True
    日志.info("已加载 CuPy — GPU 挖矿已启用")
except ImportError:
    try:
        import pycuda.autoinit  # noqa: F401
        import pycuda.driver as cuda
        from pycuda.compiler import SourceModule
        import numpy as np
        CUDA可用 = True
        CUPY可用 = False
        日志.info("已加载 PyCUDA — GPU 挖矿已启用（pycuda 后端）")
    except ImportError:
        import numpy as np
        CUDA可用 = False
        CUPY可用 = False
        日志.warning("未找到 CUDA 支持库，切换至 CPU 挖矿模式（速度较慢）")


# ── CUDA 内核源码 ─────────────────────────────────────────────────────────────
# 每个 CUDA 线程计算 SHA-256(轮次字节 || 随机数字节)，
# 并与难度目标比较。第一个找到合法随机数的线程将结果写入输出缓冲区。

CUDA内核 = r"""
#include <stdint.h>
#include <string.h>

__device__ __constant__ uint32_t K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,
    0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
    0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
    0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,
    0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
    0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,
    0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,
    0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};

#define ROTR(x,n) (((x)>>(n))|((x)<<(32-(n))))
#define CH(x,y,z) (((x)&(y))^(~(x)&(z)))
#define MAJ(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))
#define EP0(x) (ROTR(x,2)^ROTR(x,13)^ROTR(x,22))
#define EP1(x) (ROTR(x,6)^ROTR(x,11)^ROTR(x,25))
#define SIG0(x) (ROTR(x,7)^ROTR(x,18)^((x)>>3))
#define SIG1(x) (ROTR(x,17)^ROTR(x,19)^((x)>>10))

__device__ void sha256(const uint8_t* data, uint32_t len, uint8_t* digest) {
    uint32_t h[8] = {
        0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
        0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19,
    };
    uint8_t block[64];
    memset(block,0,64);
    for(uint32_t i=0;i<len&&i<64;i++) block[i]=data[i];
    block[len]=0x80;
    uint64_t bits=(uint64_t)len*8;
    for(int i=0;i<8;i++) block[63-i]=(uint8_t)(bits>>(i*8));
    uint32_t w[64];
    for(int i=0;i<16;i++)
        w[i]=((uint32_t)block[i*4]<<24)|((uint32_t)block[i*4+1]<<16)|
             ((uint32_t)block[i*4+2]<<8)|((uint32_t)block[i*4+3]);
    for(int i=16;i<64;i++)
        w[i]=SIG1(w[i-2])+w[i-7]+SIG0(w[i-15])+w[i-16];
    uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
    for(int i=0;i<64;i++){
        uint32_t t1=hh+EP1(e)+CH(e,f,g)+K[i]+w[i];
        uint32_t t2=EP0(a)+MAJ(a,b,c);
        hh=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;
    h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
    for(int i=0;i<8;i++){
        digest[i*4]=(h[i]>>24)&0xff;
        digest[i*4+1]=(h[i]>>16)&0xff;
        digest[i*4+2]=(h[i]>>8)&0xff;
        digest[i*4+3]=h[i]&0xff;
    }
}

__global__ void 搜索随机数内核(
    const uint8_t* 轮次字节,
    uint64_t       起始随机数,
    uint32_t       批量大小,
    const uint8_t* 难度目标,
    int64_t*       找到的随机数,
    uint8_t*       找到的哈希
) {
    uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
    if(tid >= 批量大小) return;
    uint64_t 随机数 = 起始随机数 + tid;

    // 输入：轮次(8字节) || 随机数(8字节) = 16字节
    uint8_t 输入[16];
    for(int i=0;i<8;i++) 输入[i]=轮次字节[i];
    for(int i=0;i<8;i++) 输入[8+i]=(uint8_t)((随机数>>(56-i*8))&0xff);

    uint8_t 摘要[32];
    sha256(输入, 16, 摘要);

    for(int i=0;i<32;i++){
        if(摘要[i] < 难度目标[i]){
            if(atomicCAS((unsigned long long*)找到的随机数,
                         (unsigned long long)(-1LL),
                         (unsigned long long)随机数) == (unsigned long long)(-1LL)){
                for(int j=0;j<32;j++) 找到的哈希[j]=摘要[j];
            }
            return;
        }
        if(摘要[i] > 难度目标[i]) return;
    }
}
"""


# ── GPU工作器类 ───────────────────────────────────────────────────────────────

class GPU工作器:
    def __init__(
        self,
        设备编号: int = 0,
        每块线程数: int = 256,
        最大块数: int = 4096,
        批量大小: int = 65536,
    ):
        self.设备编号 = 设备编号
        self.每块线程数 = 每块线程数
        self.最大块数 = 最大块数
        self.批量大小 = 批量大小
        self._使用cupy = False
        self._内核函数 = None

    def 初始化(self):
        """检测显卡，打印设备信息，编译 CUDA 内核。"""
        global CUDA可用

        if not CUDA可用:
            日志.warning("无 GPU，使用 CPU 挖矿模式（速度较慢）")
            return

        try:
            import cupy as cp
            cp.cuda.Device(self.设备编号).use()
            属性 = cp.cuda.runtime.getDeviceProperties(self.设备编号)
            名称 = 属性["name"].decode()
            显存MB = 属性["totalGlobalMem"] // (1024 * 1024)
            SM主版本 = 属性["major"]
            SM次版本 = 属性["minor"]
            多处理器数 = 属性["multiProcessorCount"]
            每SM核心数 = {(8,6):128,(8,0):64,(7,5):64,(7,0):64}.get(
                (SM主版本, SM次版本), 128
            )
            总核心数 = 多处理器数 * 每SM核心数

            日志.info("GPU | 检测到 CUDA 显卡：")
            日志.info(
                "GPU |   [%d] %s  |  显存: %d MB  |  算力: %d.%d  |  CUDA核心: ~%d",
                self.设备编号, 名称, 显存MB, SM主版本, SM次版本, 总核心数,
            )
            日志.info("GPU | 使用设备 %d", self.设备编号)

            self._内核函数 = cp.RawKernel(CUDA内核, "搜索随机数内核")
            self._使用cupy = True

        except Exception as 异常:
            日志.warning("CuPy 初始化失败（%s），切换至 CPU 模式", 异常)
            CUDA可用 = False

    def _难度字节(self, 难度十六进制: str) -> bytes:
        h = 难度十六进制.replace("0x", "").replace("0X", "")
        return bytes.fromhex(h.zfill(64))

    # ── 搜索随机数 ─────────────────────────────────────────────────────────────

    def 搜索随机数(self, 轮次: int, 难度十六进制: str) -> tuple[int, str]:
        """
        搜索满足 SHA-256(轮次 || 随机数) < 难度目标 的随机数。
        返回 (随机数, 哈希十六进制字符串)。
        """
        if self._使用cupy:
            return self._GPU搜索(轮次, 难度十六进制)
        return self._CPU搜索(轮次, 难度十六进制)

    def _GPU搜索(self, 轮次: int, 难度十六进制: str) -> tuple[int, str]:
        import cupy as cp

        难度 = self._难度字节(难度十六进制)
        轮次字节 = struct.pack(">q", 轮次)

        d_轮次  = cp.array(list(轮次字节), dtype=cp.uint8)
        d_难度  = cp.array(list(难度),     dtype=cp.uint8)

        起始随机数 = 0
        while True:
            d_找到随机数 = cp.array([-1], dtype=cp.int64)
            d_找到哈希   = cp.zeros(32,   dtype=cp.uint8)

            块数 = min(self.最大块数, (self.批量大小 + self.每块线程数 - 1) // self.每块线程数)
            self._内核函数(
                (块数,), (self.每块线程数,),
                (d_轮次, cp.uint64(起始随机数), cp.uint32(self.批量大小),
                 d_难度, d_找到随机数, d_找到哈希),
            )
            cp.cuda.Stream.null.synchronize()

            找到 = int(d_找到随机数[0])
            if 找到 != -1:
                哈希 = "".join(f"{b:02x}" for b in d_找到哈希.tolist())
                return 找到, 哈希

            起始随机数 += self.批量大小

    def _CPU搜索(self, 轮次: int, 难度十六进制: str) -> tuple[int, str]:
        难度 = bytes.fromhex(难度十六进制.replace("0x", "").zfill(64))
        轮次字节 = struct.pack(">q", 轮次)
        随机数 = 0
        while True:
            随机数字节 = struct.pack(">q", 随机数)
            h = hashlib.sha256(轮次字节 + 随机数字节).digest()
            if h < 难度:
                return 随机数, h.hex()
            随机数 += 1

    # ── 评分提案 ───────────────────────────────────────────────────────────────

    def 评分提案(self, 提案列表: list[dict]) -> list[dict]:
        """
        批量评估提案，返回带 score 和 confidence 字段的列表。
        """
        if not 提案列表:
            return []
        if self._使用cupy:
            return self._GPU评分(提案列表)
        return self._CPU评分(提案列表)

    def _GPU评分(self, 提案列表: list[dict]) -> list[dict]:
        import cupy as cp

        IDs   = [p.get("id", "") for p in 提案列表]
        哈希列表 = [p.get("hash", "0" * 64) for p in 提案列表]

        数值 = cp.array(
            [int(h[:16], 16) if len(h) >= 16 else 0 for h in 哈希列表],
            dtype=cp.float64,
        )
        最大值 = float(数值.max()) or 1.0
        分数列表 = (1.0 - 数值 / 最大值).tolist()

        结果 = []
        for i, p in enumerate(提案列表):
            结果.append({
                "id": IDs[i],
                "score": round(分数列表[i], 6),
                "confidence": round(min(分数列表[i] + 0.05, 1.0), 6),
            })
        return 结果

    def _CPU评分(self, 提案列表: list[dict]) -> list[dict]:
        结果 = []
        for p in 提案列表:
            h = p.get("hash", "0" * 64)
            数值 = int(h[:16], 16) if len(h) >= 16 else 0
            分数 = 1.0 - (数值 / (2 ** 64))
            结果.append({
                "id": p.get("id", ""),
                "score": round(分数, 6),
                "confidence": round(min(分数 + 0.05, 1.0), 6),
            })
        return 结果

    # ── 关闭 ──────────────────────────────────────────────────────────────────

    def 关闭(self):
        if self._使用cupy:
            try:
                import cupy as cp
                cp.cuda.Device(self.设备编号).synchronize()
                日志.info("显卡设备 %d 已释放", self.设备编号)
            except Exception:
                pass
