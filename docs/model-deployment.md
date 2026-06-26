# IMX500 Model Deployment

## Overview

Maehbot supports:

1. **Sony stock models** on the IMX500 (primary path via `Imx500Detector`)
2. **Custom models** trained from annotated sessions (YOLO export → IMX500 toolchain)

## Training workflow in Maehbot

1. Record a learning drive on the mower via **Training → Anlernfahrt aufnehmen** (Start / Pause / Stopp), or upload a video file
2. Annotate frames (draw bbox, assign class)
3. Export YOLO via API or UI → `/var/lib/maehbot/exports/yolo/session_<id>/`

**Step-by-step Ultralytics training (German):** [ultralytics-training.md](ultralytics-training.md)

Live recording is handled by **core** (camera access). The web UI sends commands via
`/var/lib/maehbot/recording_command.json`; core writes status to `recording_status.json`.

Alternatively copy a video to `/var/lib/maehbot/videos/` and register via upload API.

Export layout:

```
exports/yolo/session_1/
  images/train/
  labels/train/
  classes.txt
```

## YOLO → IMX500 (external steps)

Sony provides tools to deploy neural networks to the IMX500 AI camera.
Typical pipeline (see Sony / Raspberry Pi IMX500 documentation):

1. Train YOLO model externally (e.g. Ultralytics) using exported dataset
2. Convert model to format accepted by Sony IMX500 converter
3. Deploy firmware package to the camera module
4. Point `Imx500Detector` at the deployed model configuration

Until a custom model is deployed, `Imx500Detector` falls back to mock detection
for integration testing.

## CPU fallback

Set in `config/local.yaml`:

```yaml
detection:
  inference_target: pi_cpu
```

Implement `CpuFallbackDetector` with TFLite/ONNX when a Pi-side model is ready.

## Classes

Configured in `config/defaults.yaml`. Map classes to spray behavior via `sprayable` flag.
