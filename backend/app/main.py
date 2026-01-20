from __future__ import annotations

import asyncio
import io
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pytesseract import image_to_data, Output, TesseractNotFoundError

from .config import SETTINGS
from .events import EVENT_BUS
from .models import ProjectCreateResponse, ProjectInputs, RunCreateResponse
from .storage import read_json, write_json
from .simulation import init_run, run_simulation


app = FastAPI(title="IFAD in a box (MVP)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(SETTINGS.cors_allow_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _project_path(project_id: str) -> Path:
    return SETTINGS.projects_dir / f"{project_id}.json"


def _ocr_lines(data: dict) -> list[dict]:
    lines: dict[tuple[int, int, int], dict] = {}
    count = len(data.get("text", []))
    for i in range(count):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = 0
        if conf < 0:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        left = int(data["left"][i])
        top = int(data["top"][i])
        width = int(data["width"][i])
        height = int(data["height"][i])
        entry = lines.get(key)
        if entry is None:
            entry = {
                "min_x": left,
                "min_y": top,
                "max_x": left + width,
                "max_y": top + height,
                "words": [],
            }
            lines[key] = entry
        else:
            entry["min_x"] = min(entry["min_x"], left)
            entry["min_y"] = min(entry["min_y"], top)
            entry["max_x"] = max(entry["max_x"], left + width)
            entry["max_y"] = max(entry["max_y"], top + height)
        entry["words"].append(text)
    results = []
    for entry in sorted(lines.values(), key=lambda item: (item["min_y"], item["min_x"])):
        text = " ".join(entry["words"]).strip()
        if not text:
            continue
        results.append(
            {
                "id": str(uuid4()),
                "text": text,
                "box": {
                    "x": entry["min_x"],
                    "y": entry["min_y"],
                    "w": entry["max_x"] - entry["min_x"],
                    "h": entry["max_y"] - entry["min_y"],
                },
            }
        )
    return results


@app.on_event("startup")
async def _startup() -> None:
    SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.projects_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.uploads_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.runs_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.vector_store_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.outputs_dir.mkdir(parents=True, exist_ok=True)


@app.post("/api/projects", response_model=ProjectCreateResponse)
async def create_project() -> ProjectCreateResponse:
    project_id = str(uuid4())
    await write_json(
        _project_path(project_id),
        {"project_id": project_id, "inputs": {}, "uploads": []},
    )
    return ProjectCreateResponse(project_id=project_id)


@app.post("/api/projects/{project_id}/inputs")
async def set_project_inputs(project_id: str, inputs: ProjectInputs) -> dict:
    path = _project_path(project_id)
    project = await read_json(path)
    project["inputs"] = inputs.model_dump()
    await write_json(path, project)
    return {"ok": True}


@app.post("/api/projects/{project_id}/upload")
async def upload_files(project_id: str, files: list[UploadFile] = File(...)) -> dict:
    path = _project_path(project_id)
    project = await read_json(path)

    proj_dir = SETTINGS.uploads_dir / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for f in files:
        dest = proj_dir / f.filename
        content = await f.read()
        dest.write_bytes(content)
        saved.append(str(dest))

    project.setdefault("uploads", [])
    project["uploads"].extend(saved)
    await write_json(path, project)
    return {"ok": True, "saved": saved}


@app.post("/api/ocr")
async def ocr_image(file: UploadFile = File(...)) -> dict:
    if file.content_type and file.content_type not in ("image/png", "image/jpeg"):
        raise HTTPException(status_code=400, detail="Only PNG and JPEG images are supported")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Invalid image") from exc
    try:
        data = image_to_data(image, output_type=Output.DICT)
    except TesseractNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="Tesseract OCR not installed. Install tesseract-ocr to enable OCR.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OCR failed: {exc}") from exc
    boxes = _ocr_lines(data)
    full_text = "\n".join(box["text"] for box in boxes)
    return {"width": image.width, "height": image.height, "text": full_text, "boxes": boxes}


@app.post("/api/projects/{project_id}/runs", response_model=RunCreateResponse)
async def start_run(project_id: str) -> RunCreateResponse:
    project = await read_json(_project_path(project_id))
    run_id = await init_run(project_id=project_id)

    async def _runner() -> None:
        await run_simulation(run_id=run_id, project=project)

    asyncio.create_task(_runner())
    return RunCreateResponse(run_id=run_id)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run_path = SETTINGS.runs_dir / run_id / "run.json"
    if not run_path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return await read_json(run_path)


@app.get("/api/runs/{run_id}/pdf")
async def get_run_pdf(run_id: str, disposition: str = "inline") -> FileResponse:
    run_path = SETTINGS.runs_dir / run_id / "run.json"
    if not run_path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    run = await read_json(run_path)
    pdf_path = run.get("artifacts", {}).get("pdf")
    if not pdf_path:
        raise HTTPException(status_code=409, detail="PDF not ready")
    # IMPORTANT: for iframe preview we need inline disposition; for downloads use attachment.
    if disposition not in ("inline", "attachment"):
        raise HTTPException(status_code=400, detail="disposition must be inline|attachment")
    headers = {"Content-Disposition": f'{disposition}; filename="cosop.pdf"'}
    return FileResponse(pdf_path, media_type="application/pdf", headers=headers)


@app.websocket("/ws/runs/{run_id}")
async def ws_run_events(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    q = EVENT_BUS.subscribe(run_id)
    try:
        while True:
            ev = await q.get()
            await websocket.send_json(ev.model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        EVENT_BUS.unsubscribe(run_id, q)

