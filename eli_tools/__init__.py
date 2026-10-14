"""Minimal eli_tools module to fix imports."""

import os as _os

# Nothing leaves this machine: onnxruntime (used by the speech model's voice detection) otherwise
# queues usage telemetry for Microsoft's collector, and huggingface_hub reports downloads.
_os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
_os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
