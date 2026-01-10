# IFAD in a box — COSOP Multi-agent Simulation (MVP)

Minimal end-to-end MVP:
- **Input page**: upload files + free-text inputs
- **Simulation page**: 2 agents (**Country Director writer** ↔ **ODE reviewer**) with a simple decision loop (up to 2 rounds), realtime logs + graph via WebSocket
- **Preview page**: embedded **PDF preview** + **download** + 5 MVP checkboxes

No database is used in this MVP. Everything is stored as **files on disk** under `backend/data/`.

## Tech stack
- **Frontend**: Next.js (React) + TypeScript + React Flow + WebSocket
- **Backend**: FastAPI (Python) + local file storage + TF‑IDF “vector store” (file-based) + PDF rendering (ReportLab)

## Run locally

### 1) Backend

```bash
pip3 install -r backend/requirements.txt
export API_KEY="YOUR_AZURE_OPENAI_KEY"
export BASE_URL="https://YOUR-RESOURCE.openai.azure.com"
export MODEL="YOUR_DEPLOYMENT_NAME"
# optional:
# export API_VERSION="2024-08-01-preview"
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

You can also copy `backend/.env.example` → `backend/.env` and export variables from it in your shell.

Backend will listen on `http://localhost:8000`.

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend will listen on `http://localhost:3000`.

## MVP flow (UI)
1. Open `http://localhost:3000`
2. Click **Create Project**
3. Fill in **Country / Title / Notes**
4. Upload **PDF / TXT / MD** files
5. Click **Start Simulation**
6. Watch **graph + logs** update in realtime
7. Click **Go to Preview** → see the generated **PDF** + **checkbox checklist**, and download the PDF

## Where files are stored (important)

Everything lives under `backend/data/`:

- **Projects**
  - `backend/data/projects/<project_id>.json`
- **Uploads**
  - `backend/data/uploads/<project_id>/<filename>`
- **Run status**
  - `backend/data/runs/<run_id>/run.json`
- **Event stream (replay)**
  - `backend/data/runs/<run_id>/events.jsonl`
- **Agent prompt memory**
  - `backend/data/runs/<run_id>/cd_memory.json`
  - `backend/data/runs/<run_id>/ode_memory.json`
- **Draft markdown**
  - `backend/data/runs/<run_id>/draft_round_1.md` (and possibly `draft_round_2.md`)
- **Generated PDF**
  - `backend/data/outputs/<run_id>/cosop.pdf`

### “Vector database” location (file-based)
The MVP knowledge base is a local TF‑IDF vector store per run:

- `backend/data/vector_store/<run_id>/chunks.jsonl`
- `backend/data/vector_store/<run_id>/vectorizer.joblib`
- `backend/data/vector_store/<run_id>/matrix.joblib`

## COSOP template
The internal COSOP template used by the writer agent is:
- `backend/assets/cosop_template.md`

## Preloaded internal materials (chunked every run)
Put any pre-existing reference materials here (PDF/TXT/MD/DOCX):
- `backend/assets/internal_materials/`

Every run ingests these files into the knowledge base **before** ingesting user uploads.

## Notes / limitations (by design for MVP)
- Only **two agents** are implemented: **Country Director (writer)** and **ODE (reviewer)**.
- The “multi-agent” structure (memory, decision loop, event stream) is present, but the content generation is **deterministic** (no external LLM API keys required). You can replace the writer/reviewer logic with real LLM calls later.
- Supported uploads: **PDF, TXT, MD**.

