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
        await _emit(run, "log", {"message": "Ingesting uploads and building local vector store..."})

        # Create per-run vector store folder (file-based “db”)
        vs_dir = SETTINGS.vector_store_dir / run_id
        vs = LocalTfidfVectorStore(vs_dir)
        vs.reset()

        # Internal template goes into KB as internal source
        template_path = SETTINGS.internal_assets_dir / "cosop_template.md"
        internal_chunks = build_chunks_for_file(template_path, source="internal", doc_id="internal:cosop_template")
        vs.add_chunks(internal_chunks)

        # User uploads
        upload_paths = project.get("uploads", [])
        for p in upload_paths:
            path = Path(p)
            if not path.exists():
                continue
            chunks = build_chunks_for_file(path, source="user")
            vs.add_chunks(chunks)

        vs.build()
        await _emit(run, "log", {"message": f"Vector store built at {vs_dir}."})

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

            # Writer
            run.status = "writing"
            await _save_run_status(run)
            await _emit(run, "run_status", {"status": run.status, "round": r})
            await _emit(run, "graph_update", {"node_status": {"cd": "writing", "ode": "idle"}})
            await _emit(run, "log", {"message": f"Round {r}: Country Director drafting COSOP..."})

            evidence_hits = vs.search("country context objectives implementation risks safeguards", top_k=6)
            evidence = [h.chunk for h in evidence_hits]
            draft_md = writer.write(
                template_md=template_md,
                project_inputs=project.get("inputs", {}),
                evidence=evidence,
                revision_notes=revision_notes,
            )
            draft_path = _run_dir(run_id) / f"draft_round_{r}.md"
            draft_path.write_text(draft_md, encoding="utf-8")
            await _emit(run, "draft_created", {"path": str(draft_path)})

            # Reviewer
            run.status = "reviewing"
            await _save_run_status(run)
            await _emit(run, "run_status", {"status": run.status, "round": r})
            await _emit(run, "graph_update", {"node_status": {"cd": "idle", "ode": "reviewing"}})
            await _emit(run, "log", {"message": f"Round {r}: ODE reviewing draft..."})

            review = reviewer.review(draft_md=draft_md)
            run.review = review
            await _save_run_status(run)
            await _emit(run, "review_result", review.model_dump())

            if review.passed or r >= run.max_rounds:
                break

            # Prepare revision notes for next round
            notes = []
            for c in review.comments:
                notes.append(f"- [{c.severity}] {c.section}: {c.comment} Suggestion: {c.suggestion or ''}".strip())
            revision_notes = "\n".join(notes)
            await _emit(run, "log", {"message": "Reviewer requested revisions; proceeding to next round."})

        # 4) Render PDF
        run.status = "rendering"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "round": run.round})
        await _emit(run, "graph_update", {"node_status": {"cd": "idle", "ode": "idle"}})
        await _emit(run, "log", {"message": "Rendering PDF from latest markdown..."})

        latest_md_path = _run_dir(run_id) / f"draft_round_{run.round}.md"
        pdf_bytes = markdown_to_simple_pdf_bytes(latest_md_path.read_text(encoding="utf-8"))
        out_dir = SETTINGS.outputs_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / "cosop.pdf"
        pdf_path.write_bytes(pdf_bytes)

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
        await _emit(run, "log", {"message": "Run completed."})
        return

    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "error": run.error})
        raise

