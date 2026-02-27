"""Minimal RunPod debug handler — just echoes input back."""
import runpod
import torch
import os

def handler(event):
    inp = event.get("input", {})
    return {
        "echo": inp,
        "gpu_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "cuda_version": torch.version.cuda,
        "disk_free_gb": round(os.statvfs("/").f_bavail * os.statvfs("/").f_frsize / 1e9, 1),
    }

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
