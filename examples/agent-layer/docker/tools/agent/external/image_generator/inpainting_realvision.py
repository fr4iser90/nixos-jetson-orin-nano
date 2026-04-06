from __future__ import annotations
from typing import Any, Callable
import json
import os
import uuid
import time
import httpx
import base64

# --- METADATA ---
__version__ = "1.0.0"
TOOL_ID = "inpainting_realvision"
TOOL_LABEL = "Inpainting RealVision"
TOOL_DESCRIPTION = "Bearbeitet Bilder via Inpainting (Bild + Maske) mit RealVision über ComfyUI."
TOOL_DOMAIN = "image_editor"

WORKFLOW_PATH = "/app/workflows/external/image_generator/inpainting_realvision.json"
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://localhost:8188")
COMFYUI_CLIENT_ID = str(uuid.uuid4())


def _load_workflow() -> dict:
    with open(WORKFLOW_PATH, "r") as f:
        return json.load(f)


def _queue_inpainting(workflow: dict, image_b64: str, mask_b64: str, prompt: str) -> str:
    import copy
    workflow = copy.deepcopy(workflow)

    # Workflow Nodes setzen
    for node_id, node in workflow.items():
        if node.get("class_type") == "LoadImage":
            if node.get("inputs", {}).get("image", "").startswith("mask"):
                node["inputs"]["image"] = mask_b64
            else:
                node["inputs"]["image"] = image_b64
        elif node.get("class_type") == "CLIPTextEncode":
            node["inputs"]["text"] = prompt

    payload = {"prompt": workflow, "client_id": COMFYUI_CLIENT_ID}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{COMFYUI_URL}/prompt", json=payload)
        r.raise_for_status()
        return r.json()["prompt_id"]


def _get_image_result(prompt_id: str, timeout_seconds: int = 60) -> list[str]:
    with httpx.Client(timeout=10.0) as client:
        for _ in range(timeout_seconds // 2):
            r = client.get(f"{COMFYUI_URL}/history/{prompt_id}")
            r.raise_for_status()
            history = r.json()
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                images = []
                for node_id, node_output in outputs.items():
                    if "images" in node_output:
                        for img in node_output["images"]:
                            img_url = f"{COMFYUI_URL}/view?filename={img['filename']}&subfolder={img.get('subfolder', '')}&type=output"
                            images.append(img_url)
                return images
            time.sleep(2)
    return []


def inpainting_realvision(arguments: dict[str, Any]) -> str:
    prompt = arguments.get("prompt", "").strip()
    image_b64 = arguments.get("image_base64", "")
    mask_b64 = arguments.get("mask_base64", "")

    if not prompt or not image_b64 or not mask_b64:
        return json.dumps({"ok": False, "error": "prompt, image_base64 or mask_base64 missing"}, ensure_ascii=False)

    try:
        workflow = _load_workflow()
        prompt_id = _queue_inpainting(workflow, image_b64, mask_b64, prompt)
        images = _get_image_result(prompt_id)

        if not images:
            return json.dumps({"ok": False, "error": "No image generated or timeout", "prompt_id": prompt_id}, ensure_ascii=False)

        return json.dumps({"ok": True, "prompt": prompt, "edited_image": images[0], "prompt_id": prompt_id}, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# --- HANDLERS ---
HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "inpainting_realvision": inpainting_realvision,
}


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "inpainting_realvision",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text für die bearbeitete Fläche"},
                    "image_path": {"type": "string", "description": "Pfad zum Originalbild"},
                    "mask_path": {"type": "string", "description": "Pfad zur Maske (weiß = zu bearbeitende Fläche)"}
                },
                "required": ["prompt", "image_path", "mask_path"]
            }
        }
    }
]