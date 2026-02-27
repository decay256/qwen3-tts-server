"""RunPod serverless handler — wraps the standalone TTS server for queue-based endpoints.

Maps RunPod's handler(event) interface to our FastAPI endpoints.
The handler receives a JSON event with an 'input' field containing:
  - endpoint: str (e.g., "/api/v1/voices/design")
  - method: str (default "POST")
  - body: dict (request body)

Returns the same JSON the FastAPI endpoint would return.
"""

import asyncio
import base64
import gc
import logging
import os
import sys
import time
import traceback

import runpod

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Global state ────────────────────────────────────────────────────
engine = None
prompt_store = None
start_time = None
init_error = None


def init():
    """Load models once at worker startup."""
    global engine, prompt_store, start_time, init_error
    start_time = time.time()

    try:
        # Add server directory to path if needed
        server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
            logger.info("Added %s to sys.path", server_dir)

        logger.info("Python: %s", sys.version)
        logger.info("CWD: %s", os.getcwd())
        logger.info("Contents: %s", os.listdir("."))

        import torch
        logger.info("Torch: %s, CUDA: %s, GPU: %s",
                     torch.__version__, torch.cuda.is_available(),
                     torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")

        from server.tts_engine import TTSEngine
        from server.prompt_store import PromptStore

        engine = TTSEngine()
        logger.info("Loading TTS models...")
        engine.load_models()
        logger.info("Models loaded: %s", engine.get_loaded_models())

        prompts_dir = os.environ.get("PROMPTS_DIR", "./voice-prompts")
        prompt_store = PromptStore(prompts_dir)
        logger.info("Prompt store: %d prompts", len(prompt_store.list_prompts()))
        logger.info("Init complete in %.1fs", time.time() - start_time)

    except Exception as e:
        init_error = traceback.format_exc()
        logger.error("INIT FAILED: %s", init_error)


def _audio_to_base64(audio_data: bytes) -> str:
    return base64.b64encode(audio_data).decode("utf-8")


# ── Endpoint handlers ──────────────────────────────────────────────

def handle_status():
    import torch
    return {
        "status": "running",
        "tunnel_connected": True,
        "models_loaded": engine.get_loaded_models() if engine else [],
        "prompts_count": len(prompt_store.list_prompts()) if prompt_store else 0,
        "uptime_s": round(time.time() - start_time, 1) if start_time else 0,
        "gpu_available": torch.cuda.is_available(),
    }


def handle_design(body):
    text = body["text"]
    instruct = body["instruct"]
    language = body.get("language", "English")
    audio_data, duration = engine.synthesize_voice_design(text, instruct, language)
    gc.collect()
    return {"audio": _audio_to_base64(audio_data), "duration_s": round(duration, 2), "format": "wav"}


def handle_batch_design(body):
    items = body["items"]
    create_prompts = body.get("create_prompts", False)
    results = []
    for item in items:
        try:
            audio_data, duration = engine.synthesize_voice_design(
                item["text"], item["instruct"], item.get("language", "English")
            )
            result = {
                "name": item["name"],
                "status": "ok",
                "audio": _audio_to_base64(audio_data),
                "duration_s": round(duration, 2),
            }
            if create_prompts:
                metadata = {k: item.get(k) for k in
                            ["character", "emotion", "intensity", "description", "instruct", "base_description"]}
                metadata["tags"] = item.get("tags", [])
                prompt_result = engine.create_clone_prompt(audio_data, item["name"], item["text"], metadata=metadata)
                if prompt_result:
                    prompt_store.save_prompt(item["name"], prompt_result,
                                            tags=metadata.get("tags", []), ref_text=item["text"],
                                            metadata=metadata)
                    result["prompt_created"] = True
            results.append(result)
            gc.collect()
        except Exception as e:
            results.append({"name": item["name"], "status": "error", "error": str(e)})
    return {"results": results, "total": len(results)}


def handle_cast(body):
    from server.emotion_presets import build_casting_batch, BatchDesignItem
    items = body.get("entries") or build_casting_batch(
        body["character"], body["description"],
        emotions=body.get("emotions"), intensities=body.get("intensities"), modes=body.get("modes"),
    )
    return handle_batch_design({"items": items, "create_prompts": True})


def handle_clone_prompt_create(body):
    audio_bytes = base64.b64decode(body["audio"])
    metadata = {k: body.get(k) for k in
                ["character", "emotion", "intensity", "description", "instruct", "base_description"]}
    prompt_data = engine.create_clone_prompt(audio_bytes, body["name"], body.get("ref_text"), metadata=metadata)
    if prompt_data:
        prompt_store.save_prompt(body["name"], prompt_data,
                                tags=body.get("tags", []), ref_text=body.get("ref_text", ""),
                                metadata=metadata)
    return {"status": "created", "name": body["name"]}


def handle_synthesize_with_prompt(body):
    prompt_name = body["voice_prompt"]
    prompt_data = prompt_store.load_prompt(prompt_name)
    if not prompt_data:
        return {"error": f"Prompt '{prompt_name}' not found"}
    audio_data, duration = engine.synthesize_with_clone_prompt(
        prompt_data, body["text"], body.get("language", "Auto")
    )
    gc.collect()
    return {"audio": _audio_to_base64(audio_data), "duration_s": round(duration, 2), "format": "wav"}


def handle_list_prompts(body):
    tags = body.get("tags")
    return {"prompts": prompt_store.list_prompts(tags=tags)}


def handle_search_prompts(body):
    return {"prompts": prompt_store.search_prompts(
        character=body.get("character"), emotion=body.get("emotion"),
        intensity=body.get("intensity"), tags=body.get("tags"),
    )}


def handle_list_characters(body):
    return {"characters": prompt_store.list_characters()}


def handle_delete_prompt(body):
    prompt_store.delete_prompt(body["name"])
    return {"status": "deleted", "name": body["name"]}


def handle_emotions(body):
    from server.emotion_presets import EMOTION_PRESETS, MODE_PRESETS, EMOTION_ORDER, MODE_ORDER
    emotions = {name: {
        "instruct_medium": p.instruct_medium, "instruct_intense": p.instruct_intense,
        "ref_text_medium": p.ref_text_medium, "ref_text_intense": p.ref_text_intense,
    } for name, p in EMOTION_PRESETS.items()}
    modes = {name: {"instruct": p.instruct, "ref_text": p.ref_text} for name, p in MODE_PRESETS.items()}
    return {"emotions": emotions, "modes": modes, "emotion_order": EMOTION_ORDER, "mode_order": MODE_ORDER}


# ── Route dispatch ──────────────────────────────────────────────────

ROUTES = {
    "/api/v1/status": ("GET", handle_status),
    "/api/v1/voices/design": ("POST", handle_design),
    "/api/v1/voices/design/batch": ("POST", handle_batch_design),
    "/api/v1/voices/cast": ("POST", handle_cast),
    "/api/v1/voices/clone-prompt": ("POST", handle_clone_prompt_create),
    "/api/v1/tts/clone-prompt": ("POST", handle_synthesize_with_prompt),
    "/api/v1/voices/prompts": ("GET", handle_list_prompts),
    "/api/v1/voices/prompts/search": ("GET", handle_search_prompts),
    "/api/v1/voices/characters": ("GET", handle_list_characters),
    "/api/v1/voices/prompts/delete": ("POST", handle_delete_prompt),
    "/api/v1/voices/emotions": ("GET", handle_emotions),
}


def handler(event):
    """RunPod handler — dispatches to the appropriate endpoint.

    Input format:
        {"endpoint": "/api/v1/voices/design", "body": {"text": "...", "instruct": "..."}}
    """
    inp = event.get("input", {})
    endpoint = inp.get("endpoint", "/api/v1/status")
    body = inp.get("body", {})

    # API key check
    api_key = os.environ.get("API_KEY", "")
    req_key = inp.get("api_key", "")
    if api_key and req_key != api_key:
        return {"error": "Invalid API key"}

    # Report init failure
    if init_error:
        return {"error": f"Server init failed: {init_error}"}

    route = ROUTES.get(endpoint)
    if not route:
        return {"error": f"Unknown endpoint: {endpoint}"}

    _, handler_fn = route
    try:
        if endpoint == "/api/v1/status":
            return handler_fn()
        return handler_fn(body)
    except Exception as e:
        logger.exception("Handler error for %s", endpoint)
        return {"error": str(e)}


# ── Startup ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    init()
    runpod.serverless.start({"handler": handler})
