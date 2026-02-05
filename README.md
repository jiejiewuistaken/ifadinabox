# IFAD in a box — COSOP Multi-agent Simulation

End-to-end flow:
- **Input page**: upload files + free-text inputs
- **Simulation page**: multi-agent loop (CD, CDT, Government, REN, ODE) with realtime logs + graph
- **Preview page**: PDF carousel (top candidates) + ODE checklist

No database is used. Everything is stored as **files on disk** under `backend/data/`.

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

## UI flow
1. Open `http://localhost:3000`
2. Click **Create Project**
3. Fill in **Country / Title / Notes**
4. Upload **PDF / DOCX / TXT / MD / PPTX** files
5. Click **Start Simulation**
6. Watch **graph + logs** update in realtime
7. Click **Go to Preview** → see the generated **PDF carousel** + **checkbox checklist**, and download

## Inputs and outputs
**Inputs**
- Project inputs: country, title, user notes
- Knowledge bases by agent (see `backend/assets/agent_kb/`)
- Internal IFAD materials (see `backend/assets/internal_materials/`)
- Optional uploads (PDF/DOCX/TXT/MD/PPTX)

**Outputs**
- COSOP/PCN/PDR draft(s) in Markdown
- Top candidate PDFs (default: up to 5)
- ODE and REN review results + evaluation metrics
- Completion phase forecast (on_track/watchlist/at_risk)

**Optional simulation config (via project inputs)**
- `output_type`: `cosop` | `pcn` | `pdr`
- `num_simulations`: number of candidate runs (cap 100)
- `max_rounds`: revision rounds per candidate (cap 6)
- `top_candidates`: number of PDFs to keep (cap 5)

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
- **Agent prompt memory (top candidate)**
  - `backend/data/runs/<run_id>/cd_memory.json`
  - `backend/data/runs/<run_id>/ode_memory.json`
- **Candidate drafts**
  - `backend/data/runs/<run_id>/candidates/<candidate_id>/draft_round_<n>.md`
- **Generated PDFs**
  - `backend/data/outputs/<run_id>/<candidate_id>/<cosop|pcn|pdr>.pdf`

### “Vector database” location (file-based)
The MVP knowledge base is a local TF‑IDF vector store per run:

- `backend/data/vector_store/<run_id>/chunks.jsonl`
- `backend/data/vector_store/<run_id>/vectorizer.joblib`
- `backend/data/vector_store/<run_id>/matrix.joblib`

## Templates (COSOP/PCN/PDR)
Templates used by the writer agent:
- `backend/assets/cosop_template.md`
- `backend/assets/pcn_template.md`
- `backend/assets/pdr_template.md`

## Preloaded internal materials (chunked every run)
Put pre-existing reference materials here (PDF/DOCX/TXT/MD/PPTX):
- `backend/assets/internal_materials/`

Every run ingests these files into the knowledge base **before** ingesting user uploads.

## Agent knowledge bases
Per-agent folders live under:
- `backend/assets/agent_kb/`

Each subfolder maps to a scope (public, government, IFAD internal, technical, compliance).
Add or replace files here for each stakeholder.

Access scopes (default):
- `public`: all agents
- `government`: gov_mof, gov_moa, cd, cdt
- `ifad`: cd, cdt, ren, ode
- `technical`: cdt, cd
- `compliance`: ren, ode
- `project`: all agents (user uploads)

## Agent prompts
System prompts are stored under:
- `backend/assets/agent_prompts/`

Update these prompts to reflect stakeholder responsibilities and expected standpoints.

## Notes / limitations
- Multi-agent coordination is implemented in the backend; UI shows top candidates only.
- The simulation uses Azure OpenAI chat completions; API keys are required.
- Supported uploads: **PDF, DOCX, TXT, MD, PPTX**.

