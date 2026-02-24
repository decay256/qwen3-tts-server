"""Qwen3-TTS engine wrapper — manages model loading and audio generation."""

import base64
import io
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import config

logger = logging.getLogger(__name__)

# Lazy imports — only loaded when engine initializes on GPU machine
Qwen3TTSModel = None


def _import_qwen_tts():
    global Qwen3TTSModel
    if Qwen3TTSModel is None:
        import torch
        from qwen_tts import Qwen3TTSModel as _Model
        Qwen3TTSModel = _Model


class TTSEngine:
    """Manages Qwen3-TTS models and generates audio."""

    def __init__(self):
        self._models: dict = {}
        self._voice_prompts: dict = {}  # cached clone prompts
        self._loaded = False

    def load_models(self):
        """Load enabled models onto GPU/CPU."""
        _import_qwen_tts()
        import torch

        # Determine if we're running on CPU
        is_cpu = config.CUDA_DEVICE == "cpu" or not torch.cuda.is_available()
        
        if is_cpu:
            logger.info("Running in CPU mode - using bfloat16, no flash attention")
            device_map = "cpu"
            dtype = torch.bfloat16
        else:
            logger.info("Running in GPU mode - using bfloat16, flash attention available")
            device_map = config.CUDA_DEVICE
            dtype = torch.bfloat16

        for model_key in config.ENABLED_MODELS:
            hf_id = config.MODEL_HF_IDS.get(model_key)
            if not hf_id:
                logger.warning("Unknown model key: %s", model_key)
                continue
            logger.info("Loading model %s (%s)...", model_key, hf_id)
            t0 = time.time()
            kwargs = dict(
                device_map=device_map,
                dtype=dtype,
            )
            
            # Try flash attention for GPU only, fall back gracefully
            if not is_cpu:
                try:
                    model = Qwen3TTSModel.from_pretrained(
                        hf_id, attn_implementation="flash_attention_2", **kwargs
                    )
                    logger.info("Loaded %s with flash attention", model_key)
                except Exception as e:
                    logger.info("Flash attention unavailable (%s), using default for %s", str(e), model_key)
                    model = Qwen3TTSModel.from_pretrained(hf_id, **kwargs)
            else:
                # CPU mode - skip flash attention entirely
                model = Qwen3TTSModel.from_pretrained(hf_id, **kwargs)

            self._models[model_key] = model
            logger.info("Loaded %s in %.1fs", model_key, time.time() - t0)

        self._loaded = True
        logger.info("All models loaded: %s", list(self._models.keys()))

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_model(self, key: str):
        model = self._models.get(key)
        if model is None:
            raise RuntimeError(f"Model '{key}' not loaded. Loaded: {list(self._models.keys())}")
        return model

    # ── Voice Design ─────────────────────────────────────────────────
    def generate_voice_design(
        self,
        text: str,
        description: str,
        language: str = "Auto",
    ) -> tuple[np.ndarray, int]:
        """Generate speech with a designed voice from text description."""
        model = self.get_model("voice_design")
        wavs, sr = model.generate_voice_design(
            text=text,
            language=language,
            instruct=description,
        )
        return wavs[0], sr

    # ── Custom Voice ─────────────────────────────────────────────────
    def generate_custom_voice(
        self,
        text: str,
        speaker: str = "Ryan",
        instruct: str = "",
        language: str = "Auto",
    ) -> tuple[np.ndarray, int]:
        """Generate speech with a built-in custom voice."""
        model = self.get_model("custom_voice")
        wavs, sr = model.generate_custom_voice(
            text=text,
            language=language,
            speaker=speaker,
            instruct=instruct if instruct else None,
        )
        return wavs[0], sr

    # ── Voice Clone ──────────────────────────────────────────────────
    def generate_voice_clone(
        self,
        text: str,
        ref_audio_b64: str,
        ref_text: str = "",
        language: str = "Auto",
        x_vector_only_mode: bool = False,
    ) -> tuple[np.ndarray, int]:
        """Clone a voice from reference audio and generate new speech.
        
        Args:
            text: Text to synthesize.
            ref_audio_b64: Base64-encoded reference audio.
            ref_text: Transcript of the reference audio (required unless x_vector_only_mode).
            language: Target language.
            x_vector_only_mode: If True, only use speaker embedding (no ref_text needed,
                lower quality). Use when ref_text is unavailable.
        """
        model_key = "base" if "base" in self._models else "base_small"
        model = self.get_model(model_key)

        # Decode base64 audio to temp file
        audio_bytes = base64.b64decode(ref_audio_b64)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            ref_path = f.name

        try:
            wavs, sr = model.generate_voice_clone(
                text=text,
                language=language,
                ref_audio=ref_path,
                ref_text=ref_text,
                x_vector_only_mode=x_vector_only_mode,
            )
            return wavs[0], sr
        finally:
            Path(ref_path).unlink(missing_ok=True)

    # ── Clone with cached prompt ─────────────────────────────────────
    def generate_with_saved_voice(
        self,
        text: str,
        voice_name: str,
        language: str = "Auto",
    ) -> tuple[np.ndarray, int]:
        """Generate using a previously saved/cloned voice."""
        if voice_name not in self._voice_prompts:
            # Try loading from disk
            voice_dir = config.VOICES_DIR / voice_name
            if not voice_dir.exists():
                raise ValueError(f"Voice '{voice_name}' not found")
            self._load_voice_prompt(voice_name, voice_dir)

        model_key = "base" if "base" in self._models else "base_small"
        model = self.get_model(model_key)
        prompt = self._voice_prompts[voice_name]

        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language,
            reference_audio=str(self._voice_prompts[voice_name]),
        )
        return wavs[0], sr

    def save_voice(
        self,
        name: str,
        ref_audio_b64: str,
        ref_text: str = "",
        description: str = "",
    ) -> dict:
        """Save a voice clone reference audio for future reuse."""
        audio_bytes = base64.b64decode(ref_audio_b64)

        # Save to disk
        voice_dir = config.VOICES_DIR / name
        voice_dir.mkdir(parents=True, exist_ok=True)
        ref_wav = voice_dir / "ref.wav"
        ref_wav.write_bytes(audio_bytes)

        # Save metadata
        meta = {"name": name, "ref_text": ref_text, "description": description}
        (voice_dir / "meta.json").write_text(json.dumps(meta))

        # Cache reference audio path
        self._voice_prompts[name] = str(ref_wav)

        return {"name": name, "status": "saved"}

    def _load_voice_prompt(self, name: str, voice_dir: Path):
        """Load a cached voice reference audio path from disk."""
        ref_path = voice_dir / "ref.wav"
        if not ref_path.exists():
            raise FileNotFoundError(f"No ref.wav for voice '{name}'")
        self._voice_prompts[name] = str(ref_path)

    def list_voices(self) -> list[dict]:
        """List all saved voices."""
        voices = []
        if config.VOICES_DIR.exists():
            for d in config.VOICES_DIR.iterdir():
                if d.is_dir() and (d / "ref.wav").exists():
                    meta = {}
                    if (d / "meta.json").exists():
                        meta = json.loads((d / "meta.json").read_text())
                    voices.append({
                        "name": d.name,
                        "description": meta.get("description", ""),
                        "has_ref_text": bool(meta.get("ref_text")),
                    })

        # Add built-in speakers if custom_voice model loaded
        if "custom_voice" in self._models:
            try:
                speakers = self._models["custom_voice"].get_supported_speakers()
                for s in speakers:
                    voices.append({"name": s, "type": "builtin", "description": ""})
            except Exception:
                pass

        return voices

    def get_health(self) -> dict:
        """Return model status and hardware info."""
        info = {
            "loaded_models": list(self._models.keys()),
            "status": "ready" if self._loaded else "loading",
            "device": config.CUDA_DEVICE,
        }
        
        try:
            import torch
            info["torch_version"] = torch.__version__
            
            if config.CUDA_DEVICE == "cpu" or not torch.cuda.is_available():
                # CPU mode
                info["mode"] = "cpu"
                info["cpu_count"] = os.cpu_count()
                try:
                    # Get memory usage (approximate)
                    import psutil
                    memory = psutil.virtual_memory()
                    info["ram_used_gb"] = round((memory.total - memory.available) / 1e9, 2)
                    info["ram_total_gb"] = round(memory.total / 1e9, 2)
                except ImportError:
                    pass
            else:
                # GPU mode
                info["mode"] = "gpu"
                if torch.cuda.is_available():
                    dev = int(config.CUDA_DEVICE.split(":")[-1]) if ":" in config.CUDA_DEVICE else 0
                    info["gpu_name"] = torch.cuda.get_device_name(dev)
                    info["vram_used_gb"] = round(torch.cuda.memory_allocated(dev) / 1e9, 2)
                    info["vram_total_gb"] = round(torch.cuda.get_device_properties(dev).total_mem / 1e9, 2)
                    
                    # Try nvidia-smi for temperature
                    try:
                        result = subprocess.run(
                            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=5
                        )
                        if result.returncode == 0:
                            info["gpu_temp_c"] = int(result.stdout.strip().split("\n")[0])
                    except Exception:
                        pass
                        
        except Exception as e:
            info["hardware_error"] = str(e)

        return info


def wav_to_format(wav: np.ndarray, sr: int, fmt: str = "mp3") -> bytes:
    """Convert numpy waveform to output format bytes."""
    if fmt == "wav":
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV")
        return buf.getvalue()

    # For mp3/ogg, write wav then convert with ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
        sf.write(wf.name, wav, sr)
        wav_path = wf.name

    out_path = wav_path.replace(".wav", f".{fmt}")
    try:
        # Try libmp3lame first, fallback to built-in mp3 encoder
        codec = {"mp3": "libmp3lame", "ogg": "libvorbis"}.get(fmt, fmt)
        cmd = ["ffmpeg", "-y", "-i", wav_path, "-c:a", codec, "-q:a", "2", out_path]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        except subprocess.CalledProcessError as e:
            if fmt == "mp3":
                # Fallback: try built-in Windows MP3 encoder
                codec = "mp3"
                cmd = ["ffmpeg", "-y", "-i", wav_path, "-c:a", codec, "-q:a", "2", out_path]
                subprocess.run(cmd, capture_output=True, check=True, timeout=30)
            else:
                raise e
        return Path(out_path).read_bytes()
    finally:
        Path(wav_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


# Text chunking for long inputs
def chunk_text(text: str, max_chars: int = 500) -> list[str]:
    """Split text into chunks at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""
    # Split on sentence-ending punctuation
    import re
    sentences = re.split(r'(?<=[.!?。！？])\s+', text)

    for sentence in sentences:
        if len(current) + len(sentence) > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]
