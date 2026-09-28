#!/usr/bin/env bash
# 视觉/OCR 环境一键安装固化 (2026-09-24 晚定型)
# 覆盖: plan-a venv 全部 pip 依赖 + torch/torchvision cu124 本地 wheel + Qwen2.5-VL-7B 模型
# 用法: Git Bash 里  bash scripts/plan-a/setup_vision.sh
# 全程幂等, 已装好的会跳过/校验后跳过
set -euo pipefail
cd "$(dirname "$0")"   # scripts/plan-a

PY=/c/Users/admin/anaconda3/python.exe
VENV_PY=venv/Scripts/python.exe
MODEL_DIR=downloads/models/Qwen2.5-VL-7B-Instruct
TSINGHUA="https://pypi.tuna.tsinghua.edu.cn/simple"

# ---- 0) venv ----
if [ ! -x "$VENV_PY" ]; then
  echo "[0] create venv"
  "$PY" -m venv venv
fi
# 注意: venv 内 pip.exe 等 console script 可能因路径内嵌损坏, 一律用 python -m pip

# ---- 1) 基础 pip 依赖(清华源) ----
echo "[1] pip deps"
"$VENV_PY" -m pip install -q -i "$TSINGHUA" \
  faster-whisper rapidocr-onnxruntime transformers modelscope accelerate \
  qwen-vl-utils opencv-python pillow jieba pypinyin numpy

# ---- 2) torch/torchvision cu124 本地 wheel ----
# 坑1: download.pytorch.org 按 IP 限速 ~0.2-2MB/s, 2.5GB 要 ~20-50min, 耐心等
# 坑2: 文件名必须保持官方原名(cp313-cp313 两段), 手敲少一段会被 pip 拒:
#      Invalid wheel filename (wrong number of parts) — 下完用 parse_wheel_filename 校验
# 坑3: 从清华源直接装 torchvision 会连带 torch+cpu 覆盖 cu 版, 必须本地 wheel + --no-deps
TORCH_WHL=downloads/torch-2.6.0+cu124-cp313-cp313-win_amd64.whl
TV_WHL=downloads/torchvision-0.21.0+cu124-cp313-cp313-win_amd64.whl
TORCH_URL=https://download.pytorch.org/whl/cu124/torch-2.6.0%2Bcu124-cp313-cp313-win_amd64.whl
TV_URL=https://download.pytorch.org/whl/cu124/torchvision-0.21.0%2Bcu124-cp313-cp313-win_amd64.whl

check_wheel() {  # $1=path  校验文件名能被 pip 接受
  "$VENV_PY" - "$1" <<'EOF'
import sys
from pip._vendor.packaging.utils import parse_wheel_filename
import os
parse_wheel_filename(os.path.basename(sys.argv[1]))
EOF
}

mkdir -p downloads
for pair in "$TORCH_WHL|$TORCH_URL" "$TV_WHL|$TV_URL"; do
  whl="${pair%%|*}"; url="${pair##*|}"
  if [ -f "$whl" ] && check_wheel "$whl" 2>/dev/null; then
    echo "[2] exists: $whl"
  else
    echo "[2] download: $url  (限速, 可能几十分钟)"
    curl -fL --retry 3 -C - -o "$whl" "$url"
    check_wheel "$whl"
  fi
done
"$VENV_PY" -m pip install -q --no-deps --force-reinstall "$TORCH_WHL" "$TV_WHL"

# ---- 3) CUDA 自检 ----
echo "[3] cuda check"
"$VENV_PY" -c "import torch, torchvision; assert torch.cuda.is_available(), 'CUDA 不可用'; print('torch', torch.__version__, 'cuda OK | tv', torchvision.__version__)"

# ---- 4) Qwen2.5-VL-7B 模型(modelscope CDN ~85MB/s, 远快于 HF) ----
if [ -f "$MODEL_DIR/model.safetensors.index.json" ]; then
  echo "[4] model exists: $MODEL_DIR"
else
  echo "[4] download Qwen2.5-VL-7B-Instruct (~16GB, modelscope)"
  "$VENV_PY" -c "from modelscope import snapshot_download; snapshot_download('Qwen/Qwen2.5-VL-7B-Instruct', local_dir=r'downloads/models/Qwen2.5-VL-7B-Instruct')"
fi

# ---- 5) 冒烟测试 ----
echo "[5] smoke test"
"$VENV_PY" -c "
from rapidocr_onnxruntime import RapidOCR; RapidOCR()
from transformers import Qwen2_5_VLForConditionalGeneration
import faster_whisper, cv2
print('smoke OK: rapidocr + transformers(Qwen2.5-VL) + faster-whisper + cv2')
"

echo "== setup_vision 完成 =="
echo " whisper 模型: 首次转写自动下载, 慢则 export HF_ENDPOINT=https://hf-mirror.com"
echo " ffmpeg: 依赖 WinGet Links 里的 ffmpeg/ffprobe(抽帧用), 不在本脚本范围"
