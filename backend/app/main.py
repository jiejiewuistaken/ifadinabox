from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

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


@app.on_event("startup")
async def _startup() -> None:
    # Optional convenience: load env vars from backend/.env if present.
    # (We do not load .env.example; copy it to .env.)
    backend_dir = Path(__file__).resolve().parents[1]
    dotenv_path = backend_dir / ".env"
    if dotenv_path.exists():
        # override=True so a previously-exported empty API_KEY doesn't “win”.
        load_dotenv(dotenv_path=dotenv_path, override=True)
        # minimal sanity log (does not print secrets)
        api_key_present = bool((os.getenv("API_KEY") or os.getenv("api_key") or "").strip())
        base_url_present = bool((os.getenv("BASE_URL") or os.getenv("base_url") or "").strip())
        model_present = bool((os.getenv("MODEL") or os.getenv("model") or "").strip())
        print(
            f"[startup] loaded {dotenv_path} "
            f"(API_KEY={'yes' if api_key_present else 'no'}, "
            f"BASE_URL={'yes' if base_url_present else 'no'}, "
            f"MODEL={'yes' if model_present else 'no'})"
        )

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

