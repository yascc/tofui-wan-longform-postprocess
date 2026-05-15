"""postprocess.py — concat + upscale + interpolate the worker output.

Runs in a single pod spawned by tofui after all 6 worker pods report
'completed'. Pipeline:

  1. Download all chunks per segment from R2 → ffmpeg concat → silent
     segment video (×6)
  2. ffmpeg concat 6 segments → 1 silent 360p video
  3. RIFE interpolation: 16 fps → 30 fps
  4. RealESRGAN x2 upscale: 368×640 → 736×1280 (~720p)
  5. Upload longform/<jobId>/upscaled_silent.mp4 back to R2
  6. Heartbeat completion (acked) → self-terminate

Same self-terminate discipline as the worker: success branch only, never
in a finally block. See ../tofui-wan-longform-worker/worker.py for the
rationale and pattern.

Day-2 scope: SKELETON. The actual RIFE + RealESRGAN invocations are stubs.
Day 18 (Phase 4) fills them in.
"""

import os
import sys
import time
import subprocess
import traceback
from pathlib import Path

import boto3
import requests


def _require_env(name):
    v = os.environ.get(name)
    if not v:
        print(f"[postprocess] FATAL: env var {name} is required", flush=True)
        sys.exit(2)
    return v


JOB_ID         = _require_env('JOB_ID')
R2_BUCKET      = _require_env('R2_BUCKET')
R2_ACCESS_KEY  = _require_env('R2_ACCESS_KEY_ID')
R2_SECRET      = _require_env('R2_SECRET_ACCESS_KEY')
R2_ENDPOINT    = _require_env('R2_ENDPOINT')
HEARTBEAT_URL  = _require_env('TOFUI_HEARTBEAT_WEBHOOK_URL')
WORKER_SECRET  = _require_env('TOFUI_HEARTBEAT_SECRET')
RUNPOD_POD_ID  = _require_env('RUNPOD_POD_ID')
RUNPOD_API_KEY = _require_env('RUNPOD_API_KEY')

NUM_SEGMENTS = int(os.environ.get('NUM_SEGMENTS', '6'))

s3 = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET,
    region_name='auto',
)


# ─── heartbeats (same shape as worker) ───────────────────────────────────────

def _hb_body(stage, status, error=None):
    body = {
        'jobId':    JOB_ID,
        'podId':    RUNPOD_POD_ID,
        'role':     'postprocess',
        'stage':    stage,       # 'concat' | 'rife' | 'upscale' | 'upload' | 'done'
        'status':   status,      # 'running' | 'error' | 'completed'
    }
    if error is not None:
        body['errorMessage'] = error
    return body


def heartbeat(stage, status='running', error=None):
    try:
        requests.post(
            HEARTBEAT_URL,
            json=_hb_body(stage, status, error),
            headers={'X-Tofui-Worker-Secret': WORKER_SECRET},
            timeout=10,
        )
    except Exception as e:
        print(f"[heartbeat] failed: {e}", flush=True)


def heartbeat_with_ack(stage, status, max_retries=5):
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                HEARTBEAT_URL,
                json=_hb_body(stage, status),
                headers={'X-Tofui-Worker-Secret': WORKER_SECRET},
                timeout=10,
            )
            if resp.status_code == 200:
                try:
                    if resp.json().get('ok') is True:
                        return True
                except ValueError:
                    pass
            print(f"[heartbeat-ack] attempt {attempt + 1}: status={resp.status_code}", flush=True)
        except Exception as e:
            print(f"[heartbeat-ack] attempt {attempt + 1}: {e}", flush=True)
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    return False


def self_terminate():
    try:
        requests.delete(
            f'https://rest.runpod.io/v1/pods/{RUNPOD_POD_ID}',
            headers={'Authorization': f'Bearer {RUNPOD_API_KEY}'},
            timeout=10,
        )
        print("[self-terminate] sent DELETE to RunPod", flush=True)
    except Exception as e:
        print(f"[self-terminate] failed (orchestrator Layer 1 will catch): {e}", flush=True)


# ─── pipeline stages (Day 18 fill-in) ─────────────────────────────────────────

def download_and_concat_segments(work_dir):
    """For each segment p0..p5, list chunks in R2, download in order, ffmpeg
    concat → segment_<N>_silent.mp4 in work_dir. Day 18 TODO."""
    raise NotImplementedError("download_and_concat_segments — Day 18")


def concat_all_segments(work_dir):
    """ffmpeg concat segment_0..5 → full_silent.mp4. Day 18 TODO."""
    raise NotImplementedError("concat_all_segments — Day 18")


def rife_interpolate(in_path, out_path):
    """16 fps → 30 fps via RIFE. Uses /workspace/models/rife v4.0. Day 18 TODO."""
    raise NotImplementedError("rife_interpolate — Day 18")


def realesrgan_upscale(in_path, out_path):
    """2x upscale via RealESRGAN. 368×640 → 736×1280. Day 18 TODO."""
    raise NotImplementedError("realesrgan_upscale — Day 18")


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"[postprocess] Starting — job={JOB_ID} segments={NUM_SEGMENTS}", flush=True)

    work_dir = Path('/tmp/postprocess')
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        heartbeat('concat')
        download_and_concat_segments(str(work_dir))
        concat_all_segments(str(work_dir))

        heartbeat('rife')
        rife_interpolate(str(work_dir / 'full_silent.mp4'), str(work_dir / 'full_rife.mp4'))

        heartbeat('upscale')
        realesrgan_upscale(str(work_dir / 'full_rife.mp4'), str(work_dir / 'upscaled_silent.mp4'))

        heartbeat('upload')
        out_key = f"longform/{JOB_ID}/upscaled_silent.mp4"
        s3.upload_file(str(work_dir / 'upscaled_silent.mp4'), R2_BUCKET, out_key)

        print("[postprocess] All stages done; awaiting completion ack", flush=True)
        if not heartbeat_with_ack('done', 'completed'):
            print("[postprocess] Completion not acked; exiting WITHOUT self-terminate", flush=True)
            sys.exit(1)

        print("[postprocess] Completion acknowledged; self-terminating", flush=True)
        self_terminate()
        sys.exit(0)

    except Exception as e:
        err = ''.join(traceback.format_exception(type(e), e, e.__traceback__))[-2000:]
        try:
            heartbeat('error', 'error', error=err)
        except Exception:
            pass
        print(f"[postprocess] Error path; exiting WITHOUT self-terminate. tail={err[-200:]}", flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
