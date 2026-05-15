# tofui-wan-longform-postprocess — Docker image for the single
# post-processing pod that runs after all 6 worker pods complete.
#
# Pipeline:
#   1. ffmpeg concat all chunks per segment → 6 silent segment videos
#   2. ffmpeg concat 6 segments → 1 silent 360p video
#   3. RIFE interpolation: 16 fps → 30 fps
#   4. RealESRGAN x2 upscale: 368×640 → 736×1280 (~720p)
#   5. Upload upscaled_silent.mp4 back to R2
#   6. Self-terminate
#
# Much smaller than the worker image (~2-3 GB) — no WAN diffusion models,
# no ComfyUI, just RIFE weights + RealESRGAN model + ffmpeg. CPU-friendly
# base for fast cold start.

FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ffmpeg wget curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Model weights — much smaller than the worker:
#   - RIFE: ~50 MB
#   - RealESRGAN_x2.pth: ~64 MB
# Final image footprint dominated by the CUDA base, not the models.
RUN mkdir -p /workspace/models && \
    wget -q -O /workspace/models/RealESRGAN_x2.pth \
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth" && \
    wget -q -O /workspace/models/rife.zip \
        "https://github.com/megvii-research/ECCV2022-RIFE/releases/download/2.x/v4.0.zip" && \
    cd /workspace/models && unzip rife.zip && rm rife.zip

COPY requirements-postprocess.txt /workspace/requirements-postprocess.txt
RUN pip install --no-cache-dir -r /workspace/requirements-postprocess.txt

COPY postprocess.py /workspace/postprocess.py

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/workspace/postprocess.py"]
