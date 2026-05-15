# tofui-wan-longform-postprocess

Docker image for the single post-processing pod that runs after all 6
worker pods complete a long-form job.

Pipeline:

1. Download all chunks per segment from R2 → ffmpeg concat → silent
   segment video (×6).
2. ffmpeg concat 6 segments → 1 silent 360p video.
3. RIFE interpolation: 16 fps → 30 fps.
4. RealESRGAN x2 upscale: 368×640 → 736×1280 (~720p).
5. Upload `longform/<jobId>/upscaled_silent.mp4` back to R2.
6. Self-terminate after acked completion heartbeat.

Final image ~2-3 GB (vs. ~38 GB for the worker — no diffusion models).
Same self-terminate discipline as the worker: success branch only,
never in a finally block.

## Release procedure

Same shape as the worker repo (see `tofui-wan-longform-worker/README.md`).
Initial v1.0.0 push is manual; subsequent builds via GHA on tag push.

## Runtime env vars

Same R2/heartbeat env contract as the worker, plus:

| Var | Purpose |
|---|---|
| `NUM_SEGMENTS` | Defaults to 6. Matches the worker pod fanout |

## Status

Day 2 of the tofui long-form rollout — Dockerfile + skeleton are in place.
RIFE + RealESRGAN invocations are stubbed; real implementation lands
Day 18 (Phase 4).
