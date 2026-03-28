import base64
import io
import os
import time
import uuid

import httpx
import torch
from diffusers import ControlNetModel, StableDiffusionControlNetPipeline
from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Security, UploadFile, status
from fastapi.security import APIKeyHeader
from PIL import Image

app = FastAPI(title="worker-diffusion", version="1.0.0")

device = "cuda" if torch.cuda.is_available() else "cpu"
_dtype = torch.float16 if device == "cuda" else torch.float32

controlnet = ControlNetModel.from_pretrained(
    "lllyasviel/sd-controlnet-lineart",
    torch_dtype=_dtype,
)

pipe = StableDiffusionControlNetPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    controlnet=controlnet,
    torch_dtype=_dtype,
).to(device)

if device == "cuda":
    try:
        pipe.enable_xformers_memory_efficient_attention()
    except Exception:
        pass

# 1ª tentativa + até 3 retries após falha (HTTP não-2xx ou erro de rede)
CALLBACK_RETRY_DELAY_SEC = 60
CALLBACK_MAX_RETRIES = 3

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(x_api_key: str | None = Security(_api_key_header)) -> None:
    expected = os.environ.get("WORKER_DIFFUSION_API_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WORKER_DIFFUSION_API_KEY não configurada no servidor",
        )
    provided = (x_api_key or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key inválida ou em falta",
        )


def post_callback_with_retries(callback_url: str, payload: dict) -> None:
    total_attempts = 1 + CALLBACK_MAX_RETRIES
    last_error: Exception | None = None
    for i in range(total_attempts):
        try:
            r = httpx.post(callback_url, json=payload, timeout=120.0)
            r.raise_for_status()
            return
        except Exception as e:
            last_error = e
            print(
                f"Callback falhou (tentativa {i + 1}/{total_attempts}):",
                e,
            )
            if i < total_attempts - 1:
                time.sleep(CALLBACK_RETRY_DELAY_SEC)
    print("Callback esgotou todas as tentativas:", last_error)


def safe_filename(name: str | None) -> str:
    base = (name or "").strip() or f"{uuid.uuid4().hex}.png"
    base = os.path.basename(base)
    if base in (".", "..", ""):
        base = f"{uuid.uuid4().hex}.png"
    if "." not in base:
        base = f"{base}.png"
    return base


def process_and_callback(
    file_bytes: bytes,
    prompt: str,
    callback_url: str,
    filename: str,
) -> None:
    lineart = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    result = pipe(
        prompt=prompt,
        image=lineart,
        num_inference_steps=20,
    ).images[0]

    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    payload = {"filename": filename, "image_base64": img_base64}
    post_callback_with_retries(callback_url, payload)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": device,
        "cuda_available": torch.cuda.is_available(),
    }


@app.post("/colorize_async")
async def colorize_async(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    prompt: str = Form(...),
    callback_url: str = Form(...),
    _auth: None = Depends(verify_api_key),
):
    file_bytes = await file.read()
    filename = safe_filename(file.filename)
    background_tasks.add_task(
        process_and_callback,
        file_bytes,
        prompt,
        callback_url,
        filename,
    )
    return {"status": "processing", "filename": filename}
