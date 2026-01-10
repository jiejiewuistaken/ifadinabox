from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agents import AgentMemory, CountryDirectorWriter, ODEReviewer
from .config import SETTINGS
from .events import EVENT_BUS
from .ingestion import build_chunks_for_file
from .models import RunEvent, RunStatus
from .render import markdown_to_simple_pdf_bytes
from .storage import write_json, append_jsonl, read_json
from .vector_store import LocalTfidfVectorStore


def _run_dir(run_id: str) -> Path:
    return SETTINGS.runs_dir / run_id


async def _emit(run: RunStatus, type_: str, payload: dict[str, Any]) -> None:
    ev = RunEvent(run_id=run.run_id, type=type_, payload=payload)
    # persist for replay
    await append_jsonl(_run_dir(run.run_id) / "events.jsonl", ev.model_dump())
    await EVENT_BUS.publish(ev)


async def _log(run: RunStatus, *, node: str, message: str, extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"node": node, "message": message}
    if extra:
        payload.update(extra)
    await _emit(run, "log", payload)


async def _save_run_status(run: RunStatus) -> None:
    await write_json(_run_dir(run.run_id) / "run.json", run.model_dump())


async def init_run(*, project_id: str) -> str:
    run_id = str(uuid4())
    run = RunStatus(run_id=run_id, project_id=project_id, status="queued", round=0, max_rounds=2)
    _run_dir(run_id).mkdir(parents=True, exist_ok=True)
    await _save_run_status(run)
    return run_id


async def run_simulation(*, run_id: str, project: dict[str, Any]) -> None:
    """
    MVP end-to-end run:
      ingest -> write -> review (maybe revise once) -> render PDF -> done
    """
    run = RunStatus.model_validate(await read_json(_run_dir(run_id) / "run.json"))

    try:
        # Graph is static for MVP: CD <-> ODE
        await _emit(
            run,
            "graph_update",
            {
                "nodes": [
                    {"id": "cd", "label": "Country Director", "status": "idle"},
                    {"id": "ode", "label": "ODE Reviewer", "status": "idle"},
                ],
                "edges": [{"id": "cd-ode", "source": "cd", "target": "ode", "label": "review"}],
            },
        )

        # 1) Ingest
        run.status = "ingesting"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status})
        await _log(run, node="ingest", message="Starting ingestion: internal materials + user uploads → chunk → local vector store")

        # Create per-run vector store folder (file-based “db”)
        vs_dir = SETTINGS.vector_store_dir / run_id
        vs = LocalTfidfVectorStore(vs_dir)
        vs.reset()
        await _log(run, node="ingest", message="Vector store reset", extra={"vector_store_dir": str(vs_dir)})

        # Internal materials (any files in assets/internal_materials) go into KB as internal source
        SETTINGS.internal_materials_dir.mkdir(parents=True, exist_ok=True)
        internal_paths = sorted([p for p in SETTINGS.internal_materials_dir.iterdir() if p.is_file()])
        await _log(run, node="ingest", message="Found internal materials", extra={"count": len(internal_paths)})
        internal_total = 0
        for p in internal_paths:
            try:
                chunks = build_chunks_for_file(p, source="internal", doc_id=f"internal:{p.name}")
                vs.add_chunks(chunks)
                internal_total += len(chunks)
                await _log(run, node="ingest", message="Chunked internal file", extra={"file": p.name, "chunks": len(chunks)})
            except Exception as e:
                await _log(run, node="ingest", message="Skipped internal file (unsupported or failed parse)", extra={"file": p.name, "error": str(e)})

        # Writer uses a markdown skeleton template (kept in assets); also chunk it as internal knowledge.
        template_path = SETTINGS.internal_assets_dir / "cosop_template.md"
        tpl_chunks = build_chunks_for_file(template_path, source="internal", doc_id="internal:cosop_template_md")
        vs.add_chunks(tpl_chunks)
        internal_total += len(tpl_chunks)
        await _log(run, node="ingest", message="Added COSOP markdown skeleton template to KB", extra={"chunks": len(tpl_chunks)})

        # User uploads
        upload_paths = project.get("uploads", [])
        await _log(run, node="ingest", message="Found user uploads", extra={"count": len(upload_paths)})
        user_total = 0
        for p in upload_paths:
            path = Path(p)
            if not path.exists():
                await _log(run, node="ingest", message="Upload path missing (skipped)", extra={"path": str(path)})
                continue
            try:
                chunks = build_chunks_for_file(path, source="user")
                vs.add_chunks(chunks)
                user_total += len(chunks)
                await _log(run, node="ingest", message="Chunked user file", extra={"file": path.name, "chunks": len(chunks)})
            except Exception as e:
                await _log(run, node="ingest", message="Skipped user file (unsupported or failed parse)", extra={"file": path.name, "error": str(e)})

        vs.build()
        await _log(
            run,
            node="ingest",
            message="Vector store build complete",
            extra={"vector_store_dir": str(vs_dir), "internal_chunks": internal_total, "user_chunks": user_total},
        )

        # 2) Write + 3) Review loop
        cd_memory = AgentMemory(
                system=(
                    "You are the IFAD Country Director. You are responsible for coordinating COSOP drafting "
                    "using the provided COSOP template and evidence. Produce a coherent, structured draft."
                )
            )
        ode_memory = AgentMemory(
                system=(
                    "You are an independent ODE reviewer. You must assess draft quality and basic compliance, "
                    "and return structured comments and checkbox assessments."
                )
            )
        writer = CountryDirectorWriter(memory=cd_memory)
        reviewer = ODEReviewer(memory=ode_memory)

        template_md = template_path.read_text(encoding="utf-8")
        revision_notes: str | None = None

        for r in range(1, run.max_rounds + 1):
            run.round = r
            await _emit(run, "round_update", {"round": r})
            await _log(run, node="orchestrator", message="Entering round", extra={"round": r})

            # Writer
            run.status = "writing"
            await _save_run_status(run)
            await _emit(run, "run_status", {"status": run.status, "round": r})
            await _emit(run, "graph_update", {"node_status": {"cd": "writing", "ode": "idle"}})
            await _log(run, node="cd_writer", message="Drafting COSOP (LLM)", extra={"round": r})

            query = "country context objectives implementation risks safeguards inclusion"
            await _log(run, node="kb_retrieval", message="Retrieving evidence from vector store", extra={"query": query, "top_k": 6})
            evidence_hits = vs.search(query, top_k=6)
            evidence = [h.chunk for h in evidence_hits]
            await _log(run, node="kb_retrieval", message="Retrieved evidence", extra={"count": len(evidence)})
            draft_md = writer.write(
                template_md=template_md,
                project_inputs=project.get("inputs", {}),
                evidence=evidence,
                revision_notes=revision_notes,
            )
            await _log(run, node="cd_writer", message="Draft complete", extra={"chars": len(draft_md)})
            draft_path = _run_dir(run_id) / f"draft_round_{r}.md"
            draft_path.write_text(draft_md, encoding="utf-8")
            await _emit(run, "draft_created", {"path": str(draft_path)})

            # Reviewer
            run.status = "reviewing"
            await _save_run_status(run)
            await _emit(run, "run_status", {"status": run.status, "round": r})
            await _emit(run, "graph_update", {"node_status": {"cd": "idle", "ode": "reviewing"}})
            await _log(run, node="ode_reviewer", message="Reviewing draft (LLM, JSON output)", extra={"round": r})

            review = reviewer.review(draft_md=draft_md)
            run.review = review
            await _save_run_status(run)
            await _emit(run, "review_result", review.model_dump())
            await _log(run, node="ode_reviewer", message="Review complete", extra={"passed": review.passed, "comments": len(review.comments)})

            if review.passed or r >= run.max_rounds:
                break

            # Prepare revision notes for next round
            notes = []
            for c in review.comments:
                notes.append(f"- [{c.severity}] {c.section}: {c.comment} Suggestion: {c.suggestion or ''}".strip())
            revision_notes = "\n".join(notes)
            await _log(run, node="orchestrator", message="Reviewer requested revisions; proceeding to next round.")

        # 4) Render PDF
        run.status = "rendering"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "round": run.round})
        await _emit(run, "graph_update", {"node_status": {"cd": "idle", "ode": "idle"}})
        await _log(run, node="render", message="Rendering PDF from latest markdown")

        latest_md_path = _run_dir(run_id) / f"draft_round_{run.round}.md"
        pdf_bytes = markdown_to_simple_pdf_bytes(latest_md_path.read_text(encoding="utf-8"))
        out_dir = SETTINGS.outputs_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / "cosop.pdf"
        pdf_path.write_bytes(pdf_bytes)
        await _log(run, node="render", message="PDF written", extra={"pdf_path": str(pdf_path)})

        run.artifacts["draft_md"] = str(latest_md_path)
        run.artifacts["pdf"] = str(pdf_path)
        run.artifacts["cd_memory"] = str(_run_dir(run_id) / "cd_memory.json")
        run.artifacts["ode_memory"] = str(_run_dir(run_id) / "ode_memory.json")

        await write_json(
            _run_dir(run_id) / "cd_memory.json",
            {"system": cd_memory.system, "messages": cd_memory.messages},
        )
        await write_json(
            _run_dir(run_id) / "ode_memory.json",
            {"system": ode_memory.system, "messages": ode_memory.messages},
        )

        run.status = "completed"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "round": run.round, "artifacts": run.artifacts})
        await _log(run, node="orchestrator", message="Run completed")
        return

    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "error": run.error})
        raise

