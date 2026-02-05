from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .agents import (
    AgentMemory,
    AgentProfile,
    CDTAdvisor,
    CountryDirectorWriter,
    GovernmentAdvisor,
    ODEReviewer,
    RENReviewer,
)
from .config import SETTINGS
from .events import EVENT_BUS
from .ingestion import build_chunks_for_file
from .models import CandidateResult, ForecastResult, ProjectInputs, ReviewMetric, ReviewResult, RunEvent, RunStatus
from .render import markdown_to_simple_pdf_bytes
from .storage import write_json, append_jsonl, read_json
from .vector_store import LocalTfidfVectorStore


@dataclass(frozen=True)
class KnowledgeSource:
    label: str
    paths: list[Path]
    source: str
    scopes: list[str]
    doc_prefix: str


def _run_dir(run_id: str) -> Path:
    return SETTINGS.runs_dir / run_id


async def _emit(run: RunStatus, type_: str, payload: dict[str, Any]) -> None:
    ev = RunEvent(run_id=run.run_id, type=type_, payload=payload)
    await append_jsonl(_run_dir(run.run_id) / "events.jsonl", ev.model_dump())
    await EVENT_BUS.publish(ev)


async def _log(run: RunStatus, *, node: str, message: str, extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"node": node, "message": message}
    if extra:
        payload.update(extra)
    await _emit(run, "log", payload)


async def _save_run_status(run: RunStatus) -> None:
    await write_json(_run_dir(run.run_id) / "run.json", run.model_dump())


def _load_prompt(agent_id: str, fallback: str) -> str:
    for ext in (".md", ".txt"):
        path = SETTINGS.agent_prompts_dir / f"{agent_id}{ext}"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return fallback


def _agent_profiles() -> dict[str, AgentProfile]:
    defaults = {
        "cd": (
            "You are the IFAD Country Director (orchestrator). Coordinate COSOP drafting, align with IFAD "
            "strategy and SDGs, and synthesize government priorities and CDT inputs into a coherent draft."
        ),
        "cdt_econ": (
            "You are the CDT Regional Economist. Focus on macro context, growth drivers, rural poverty data, "
            "and economic feasibility of the COSOP results chain."
        ),
        "cdt_tech": (
            "You are the CDT Technical Specialist. Focus on technical feasibility, climate and safeguards, "
            "SECAP alignment, and operational realism."
        ),
        "gov_mof": (
            "You represent the Ministry of Finance. Emphasize national development priorities, fiscal space, "
            "policy alignment, and endorsement conditions for IFAD collaboration."
        ),
        "gov_moa": (
            "You represent the Ministry of Agriculture. Emphasize rural development priorities, food systems, "
            "youth and employment, and institutional capacity."
        ),
        "ren": (
            "You are REN. Provide quality and compliance review focused on results chain, safeguards, "
            "policy alignment, and implementation capacity."
        ),
        "ode": (
            "You are ODE. Provide an independent review, focusing on quality, compliance, and evidence use."
        ),
    }

    return {
        "cd": AgentProfile(
            agent_id="cd",
            label="Country Director",
            responsibilities=["IFAD strategy alignment", "Orchestration", "Final COSOP draft"],
            system_prompt=_load_prompt("cd", defaults["cd"]),
            allowed_scopes=("public", "ifad", "government", "technical", "project"),
        ),
        "cdt_econ": AgentProfile(
            agent_id="cdt_econ",
            label="CDT Economist",
            responsibilities=["Macro context", "Economic feasibility", "Results chain realism"],
            system_prompt=_load_prompt("cdt_econ", defaults["cdt_econ"]),
            allowed_scopes=("public", "ifad", "government", "project"),
        ),
        "cdt_tech": AgentProfile(
            agent_id="cdt_tech",
            label="CDT Technical",
            responsibilities=["Technical feasibility", "SECAP/safeguards", "Operational risks"],
            system_prompt=_load_prompt("cdt_tech", defaults["cdt_tech"]),
            allowed_scopes=("public", "ifad", "technical", "project"),
        ),
        "gov_mof": AgentProfile(
            agent_id="gov_mof",
            label="Ministry of Finance",
            responsibilities=["National priorities", "Fiscal constraints", "Endorsement conditions"],
            system_prompt=_load_prompt("gov_mof", defaults["gov_mof"]),
            allowed_scopes=("public", "government", "project"),
        ),
        "gov_moa": AgentProfile(
            agent_id="gov_moa",
            label="Ministry of Agriculture",
            responsibilities=["Agriculture priorities", "Food systems", "Youth employment"],
            system_prompt=_load_prompt("gov_moa", defaults["gov_moa"]),
            allowed_scopes=("public", "government", "project"),
        ),
        "ren": AgentProfile(
            agent_id="ren",
            label="REN Reviewer",
            responsibilities=["Quality control", "Compliance", "Results chain"],
            system_prompt=_load_prompt("ren", defaults["ren"]),
            allowed_scopes=("public", "ifad", "compliance", "project"),
        ),
        "ode": AgentProfile(
            agent_id="ode",
            label="ODE Reviewer",
            responsibilities=["Independent review", "Evidence quality", "Risk mitigation"],
            system_prompt=_load_prompt("ode", defaults["ode"]),
            allowed_scopes=("public", "ifad", "compliance", "project"),
        ),
    }


def _init_memory(profile: AgentProfile, inputs: ProjectInputs) -> AgentMemory:
    mem = AgentMemory(system=profile.system_prompt)
    mem.add_long_term(f"Responsibilities: {', '.join(profile.responsibilities)}")
    mem.add_long_term(f"Authorized knowledge scopes: {', '.join(profile.allowed_scopes)}")
    if inputs.country:
        mem.add_public(f"Country: {inputs.country}")
    if inputs.title:
        mem.add_public(f"Title: {inputs.title}")
    mem.add_public(f"Output type: {inputs.output_type}")
    if inputs.user_notes:
        mem.add_short_term(f"User notes: {inputs.user_notes}")
    return mem


def _template_path(output_type: str) -> Path:
    mapping = {
        "cosop": SETTINGS.internal_assets_dir / "cosop_template.md",
        "pcn": SETTINGS.internal_assets_dir / "pcn_template.md",
        "pdr": SETTINGS.internal_assets_dir / "pdr_template.md",
    }
    path = mapping.get(output_type, mapping["cosop"])
    if not path.exists():
        return mapping["cosop"]
    return path


def _build_kb_sources() -> list[KnowledgeSource]:
    sources: list[KnowledgeSource] = []

    SETTINGS.internal_materials_dir.mkdir(parents=True, exist_ok=True)
    internal_paths = sorted([p for p in SETTINGS.internal_materials_dir.iterdir() if p.is_file()])
    sources.append(
        KnowledgeSource(
            label="internal_materials",
            paths=internal_paths,
            source="internal",
            scopes=["ifad"],
            doc_prefix="internal",
        )
    )

    SETTINGS.agent_kb_dir.mkdir(parents=True, exist_ok=True)
    kb_scopes = {
        "public": ["public", "historical_cosop"],
        "government": ["government"],
        "gov_mof": ["government"],
        "gov_moa": ["government"],
        "cd": ["ifad"],
        "cdt_econ": ["ifad", "technical"],
        "cdt_tech": ["technical"],
        "ren": ["compliance"],
        "ode": ["compliance"],
    }
    for folder, scopes in kb_scopes.items():
        dir_path = SETTINGS.agent_kb_dir / folder
        dir_path.mkdir(parents=True, exist_ok=True)
        paths = sorted([p for p in dir_path.iterdir() if p.is_file()])
        sources.append(
            KnowledgeSource(
                label=f"agent_kb:{folder}",
                paths=paths,
                source="internal",
                scopes=scopes,
                doc_prefix=f"agent_kb:{folder}",
            )
        )

    return sources


def _retrieve_evidence(
    vs: LocalTfidfVectorStore, *, query: str, scopes: Iterable[str], top_k: int = 6
) -> list[dict[str, Any]]:
    hits = vs.search(query, top_k=top_k, scope_filter=set(scopes))
    return [h.chunk for h in hits]


def _score_similarity(
    vs: LocalTfidfVectorStore, *, draft_md: str, scopes: Iterable[str], invert: bool = False
) -> tuple[float, str, list[dict[str, Any]]]:
    hits = vs.search(draft_md[:2000], top_k=3, scope_filter=set(scopes))
    if not hits:
        score = 5.0 if invert else 0.0
        rationale = f"No evidence retrieved for scopes: {', '.join(scopes)}."
        return score, rationale, []
    max_sim = max(h.score for h in hits)
    score = (1.0 - max_sim) * 5.0 if invert else max_sim * 5.0
    score = max(0.0, min(5.0, score))
    rationale = f"Top cosine similarity={max_sim:.2f} for scopes: {', '.join(scopes)}."
    evidence = [h.chunk for h in hits[:2]]
    return score, rationale, evidence


def _build_metrics(vs: LocalTfidfVectorStore, *, draft_md: str, ode_review: ReviewResult) -> list[ReviewMetric]:
    metrics: list[ReviewMetric] = []

    score, rationale, evidence = _score_similarity(vs, draft_md=draft_md, scopes=["ifad"])
    metrics.append(
        ReviewMetric(
            id="strategic_consistency",
            label="Strategic consistency",
            score=score,
            rationale=rationale,
            evidence=evidence,
        )
    )

    score, rationale, evidence = _score_similarity(vs, draft_md=draft_md, scopes=["government"])
    metrics.append(
        ReviewMetric(
            id="country_priority_match",
            label="Country priority match",
            score=score,
            rationale=rationale,
            evidence=evidence,
        )
    )

    score, rationale, evidence = _score_similarity(vs, draft_md=draft_md, scopes=["technical"])
    metrics.append(
        ReviewMetric(
            id="technical_feasibility",
            label="Technical feasibility",
            score=score,
            rationale=rationale,
            evidence=evidence,
        )
    )

    blockers = [c for c in ode_review.comments if c.severity == "blocker"]
    if ode_review.passed:
        score = 4.5
        rationale = "ODE review passed; no blocker issues."
    elif blockers:
        score = 1.5
        rationale = f"ODE review flagged blockers ({len(blockers)})."
    else:
        score = 2.5
        rationale = "ODE review identified gaps but no blockers."
    metrics.append(
        ReviewMetric(
            id="compliance_risk",
            label="Compliance, risk, and results chain",
            score=score,
            rationale=rationale,
            evidence=[],
        )
    )

    score, rationale, evidence = _score_similarity(
        vs, draft_md=draft_md, scopes=["public", "historical_cosop"], invert=True
    )
    metrics.append(
        ReviewMetric(
            id="innovation",
            label="Innovation (distance from prior COSOPs)",
            score=score,
            rationale=rationale,
            evidence=evidence,
        )
    )

    return metrics


def _overall_score(metrics: list[ReviewMetric]) -> float:
    if not metrics:
        return 0.0
    return sum(m.score for m in metrics) / len(metrics)


def _build_forecast(*, score: float, passed: bool, blockers: int) -> ForecastResult:
    if passed and score >= 4.0:
        phase = "on_track"
        confidence = min(0.9, 0.6 + score / 10.0)
    elif passed:
        phase = "watchlist"
        confidence = min(0.75, 0.5 + score / 10.0)
    else:
        phase = "at_risk"
        confidence = max(0.35, 0.3 + score / 10.0)

    rationale = (
        f"Overall score {score:.2f}. "
        f"Passed={passed}. "
        f"Blockers={blockers}. "
        "Higher scores imply stronger alignment and feasibility."
    )
    return ForecastResult(phase=phase, confidence=confidence, rationale=rationale)


def _format_revision_notes(reviews: Iterable[ReviewResult]) -> str:
    notes: list[str] = []
    for review in reviews:
        for c in review.comments:
            notes.append(f"- [{c.severity}] {c.section}: {c.comment} Suggestion: {c.suggestion or ''}".strip())
    return "\n".join(notes)


async def init_run(*, project_id: str) -> str:
    run_id = str(uuid4())
    run = RunStatus(run_id=run_id, project_id=project_id, status="queued", round=0, max_rounds=2)
    _run_dir(run_id).mkdir(parents=True, exist_ok=True)
    await _save_run_status(run)
    return run_id


async def _run_candidate(
    *,
    run: RunStatus,
    run_id: str,
    candidate_id: str,
    vs: LocalTfidfVectorStore,
    profiles: dict[str, AgentProfile],
    inputs: ProjectInputs,
    template_md: str,
    enable_reflection: bool,
    enable_planning: bool,
) -> CandidateResult:
    candidate_dir = _run_dir(run_id) / "candidates" / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)

    mem_cd = _init_memory(profiles["cd"], inputs)
    mem_cdt_econ = _init_memory(profiles["cdt_econ"], inputs)
    mem_cdt_tech = _init_memory(profiles["cdt_tech"], inputs)
    mem_gov_mof = _init_memory(profiles["gov_mof"], inputs)
    mem_gov_moa = _init_memory(profiles["gov_moa"], inputs)
    mem_ren = _init_memory(profiles["ren"], inputs)
    mem_ode = _init_memory(profiles["ode"], inputs)

    cd_writer = CountryDirectorWriter(profile=profiles["cd"], memory=mem_cd)
    cdt_econ = CDTAdvisor(profile=profiles["cdt_econ"], memory=mem_cdt_econ)
    cdt_tech = CDTAdvisor(profile=profiles["cdt_tech"], memory=mem_cdt_tech)
    gov_mof = GovernmentAdvisor(profile=profiles["gov_mof"], memory=mem_gov_mof)
    gov_moa = GovernmentAdvisor(profile=profiles["gov_moa"], memory=mem_gov_moa)
    ren = RENReviewer(memory=mem_ren)
    ode = ODEReviewer(memory=mem_ode)

    revision_notes: str | None = None
    gov_notes: str | None = None
    cdt_notes: str | None = None
    concept_notes: str | None = None

    for r in range(1, run.max_rounds + 1):
        run.round = r
        await _emit(run, "round_update", {"round": r, "candidate_id": candidate_id})
        await _log(run, node="orchestrator", message="Entering round", extra={"round": r, "candidate_id": candidate_id})

        if not gov_notes:
            await _emit(
                run,
                "graph_update",
                {"node_status": {"gov_mof": "consulting", "gov_moa": "consulting", "cd": "planning"}},
            )
            gov_evidence = _retrieve_evidence(
                vs,
                query="country priorities policy strategy constraints",
                scopes=profiles["gov_mof"].allowed_scopes,
            )
            if enable_reflection:
                gov_mof.reflect(context="Prepare government priorities for COSOP endorsement.")
                gov_moa.reflect(context="Prepare agriculture priorities and rural development constraints.")
            if enable_planning:
                gov_mof.plan(goals="Provide priorities, constraints, and endorsement conditions.")
                gov_moa.plan(goals="Provide agriculture priorities and red lines.")
            mof_notes = gov_mof.propose_priorities(project_inputs=inputs.model_dump(), evidence=gov_evidence)
            moa_notes = gov_moa.propose_priorities(project_inputs=inputs.model_dump(), evidence=gov_evidence)
            gov_notes = "\n\n".join(["[MoF]\n" + mof_notes, "[MoA]\n" + moa_notes])
            mem_cd.add_short_term(f"Government priorities:\n{gov_notes}")
            await _emit(run, "graph_update", {"node_status": {"gov_mof": "idle", "gov_moa": "idle"}})

        cd_evidence = _retrieve_evidence(
            vs,
            query="cosop strategy objectives implementation risks safeguards inclusion",
            scopes=profiles["cd"].allowed_scopes,
        )
        if enable_reflection:
            cd_writer.reflect(context=gov_notes or "Government inputs not provided.")
        if enable_planning:
            cd_writer.plan(goals="Draft a coherent COSOP concept aligned with IFAD strategy and government priorities.")
        concept_notes = cd_writer.act(
            task="Draft a short COSOP concept note (objectives, target groups, and strategic focus).",
            evidence=cd_evidence,
            extra_context=gov_notes,
            max_tokens=700,
        )
        mem_cd.add_short_term(f"Concept note:\n{concept_notes}")

        if not cdt_notes:
            await _emit(run, "graph_update", {"node_status": {"cdt_econ": "reviewing", "cdt_tech": "reviewing"}})
            econ_evidence = _retrieve_evidence(
                vs,
                query="macro economic context poverty trends fiscal space",
                scopes=profiles["cdt_econ"].allowed_scopes,
            )
            tech_evidence = _retrieve_evidence(
                vs,
                query="technical feasibility safeguards climate secap",
                scopes=profiles["cdt_tech"].allowed_scopes,
            )
            if enable_reflection:
                cdt_econ.reflect(context=concept_notes or "")
                cdt_tech.reflect(context=concept_notes or "")
            if enable_planning:
                cdt_econ.plan(goals="Provide economic feasibility feedback and data gaps.")
                cdt_tech.plan(goals="Provide technical feasibility and safeguards feedback.")
            econ_notes = cdt_econ.provide_technical_feedback(
                concept=concept_notes or "", evidence=econ_evidence, focus="macroeconomics"
            )
            tech_notes = cdt_tech.provide_technical_feedback(
                concept=concept_notes or "", evidence=tech_evidence, focus="technical feasibility"
            )
            cdt_notes = "\n\n".join(["[CDT Economist]\n" + econ_notes, "[CDT Technical]\n" + tech_notes])
            mem_cd.add_short_term(f"CDT feedback:\n{cdt_notes}")
            await _emit(run, "graph_update", {"node_status": {"cdt_econ": "idle", "cdt_tech": "idle"}})

        # Writer
        run.status = "writing"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "round": r, "candidate_id": candidate_id})
        await _emit(run, "graph_update", {"node_status": {"cd": "writing"}})
        await _log(run, node="cd_writer", message="Drafting COSOP (LLM)", extra={"round": r, "candidate_id": candidate_id})

        guidance_notes = "\n\n".join([x for x in [gov_notes, concept_notes, cdt_notes] if x])
        draft_md = cd_writer.draft(
            template_md=template_md,
            project_inputs=inputs.model_dump(),
            evidence=cd_evidence,
            revision_notes=revision_notes,
            guidance_notes=guidance_notes,
            output_type=inputs.output_type,
        )
        await _log(run, node="cd_writer", message="Draft complete", extra={"chars": len(draft_md), "candidate_id": candidate_id})
        draft_path = candidate_dir / f"draft_round_{r}.md"
        draft_path.write_text(draft_md, encoding="utf-8")
        await _emit(run, "draft_created", {"path": str(draft_path), "candidate_id": candidate_id})

        # Review
        run.status = "reviewing"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "round": r, "candidate_id": candidate_id})
        await _emit(run, "graph_update", {"node_status": {"cd": "idle", "ren": "reviewing", "ode": "reviewing"}})
        await _log(run, node="review", message="REN and ODE reviewing draft", extra={"round": r, "candidate_id": candidate_id})

        ren_review = ren.review(draft_md=draft_md)
        ode_review = ode.review(draft_md=draft_md)
        metrics = _build_metrics(vs, draft_md=draft_md, ode_review=ode_review)
        review_with_metrics = ode_review.model_copy(update={"metrics": metrics})
        overall = _overall_score(metrics)
        blockers = len([c for c in ode_review.comments if c.severity == "blocker"])
        passed = ren_review.passed and ode_review.passed and overall >= 3.0
        forecast = _build_forecast(score=overall, passed=passed, blockers=blockers)

        await _emit(
            run,
            "review_result",
            {"candidate_id": candidate_id, "ode_review": review_with_metrics.model_dump(), "ren_review": ren_review.model_dump()},
        )

        if passed or r >= run.max_rounds:
            # Save agent memories for this candidate
            memory_dir = candidate_dir / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            await write_json(memory_dir / "cd.json", mem_cd.snapshot())
            await write_json(memory_dir / "ode.json", mem_ode.snapshot())
            await write_json(memory_dir / "ren.json", mem_ren.snapshot())
            await write_json(memory_dir / "gov_mof.json", mem_gov_mof.snapshot())
            await write_json(memory_dir / "gov_moa.json", mem_gov_moa.snapshot())
            await write_json(memory_dir / "cdt_econ.json", mem_cdt_econ.snapshot())
            await write_json(memory_dir / "cdt_tech.json", mem_cdt_tech.snapshot())

            return CandidateResult(
                candidate_id=candidate_id,
                score=overall,
                passed=passed,
                round=r,
                draft_path=str(draft_path),
                review=review_with_metrics,
                ren_review=ren_review,
                ode_review=ode_review,
                forecast=forecast,
            )

        revision_notes = _format_revision_notes([ren_review, ode_review])
        await _log(
            run,
            node="orchestrator",
            message="Reviewers requested revisions; proceeding to next round.",
            extra={"candidate_id": candidate_id},
        )

    # Should not reach, but fallback
    return CandidateResult(
        candidate_id=candidate_id,
        score=0.0,
        passed=False,
        round=run.max_rounds,
        draft_path=str(candidate_dir / f"draft_round_{run.max_rounds}.md"),
        review=ReviewResult(passed=False, comments=[], checkboxes=[]),
    )


async def run_simulation(*, run_id: str, project: dict[str, Any]) -> None:
    run = RunStatus.model_validate(await read_json(_run_dir(run_id) / "run.json"))

    try:
        profiles = _agent_profiles()
        for p in profiles.values():
            await _log(
                run,
                node="prompt",
                message="Loaded agent prompt for review",
                extra={"agent_id": p.agent_id, "label": p.label},
            )
        await _emit(
            run,
            "graph_update",
            {
                "nodes": [
                    {"id": "cd", "label": profiles["cd"].label, "status": "idle"},
                    {"id": "cdt_econ", "label": profiles["cdt_econ"].label, "status": "idle"},
                    {"id": "cdt_tech", "label": profiles["cdt_tech"].label, "status": "idle"},
                    {"id": "gov_mof", "label": profiles["gov_mof"].label, "status": "idle"},
                    {"id": "gov_moa", "label": profiles["gov_moa"].label, "status": "idle"},
                    {"id": "ren", "label": profiles["ren"].label, "status": "idle"},
                    {"id": "ode", "label": profiles["ode"].label, "status": "idle"},
                ],
                "edges": [
                    {"id": "gov-cd", "source": "gov_mof", "target": "cd", "label": "priorities"},
                    {"id": "gov2-cd", "source": "gov_moa", "target": "cd", "label": "priorities"},
                    {"id": "cdt-cd", "source": "cdt_econ", "target": "cd", "label": "technical review"},
                    {"id": "cdt2-cd", "source": "cdt_tech", "target": "cd", "label": "technical review"},
                    {"id": "ren-cd", "source": "ren", "target": "cd", "label": "quality review"},
                    {"id": "ode-cd", "source": "ode", "target": "cd", "label": "evaluation"},
                ],
            },
        )

        inputs = ProjectInputs.model_validate(project.get("inputs", {}))
        num_simulations = max(1, min(int(inputs.num_simulations), 100))
        max_rounds = max(1, min(int(inputs.max_rounds), 6))
        top_candidates = max(1, min(int(inputs.top_candidates), num_simulations, 5))
        run.max_rounds = max_rounds
        await _save_run_status(run)
        await _log(
            run,
            node="orchestrator",
            message="Simulation config",
            extra={
                "output_type": inputs.output_type,
                "num_simulations": num_simulations,
                "max_rounds": max_rounds,
                "top_candidates": top_candidates,
            },
        )
        run.artifacts["output_type"] = inputs.output_type
        run.artifacts["num_simulations"] = num_simulations
        run.artifacts["max_rounds"] = max_rounds
        run.artifacts["top_candidates"] = top_candidates
        await _save_run_status(run)

        # 1) Ingest
        run.status = "ingesting"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status})
        await _log(
            run,
            node="ingest",
            message="Starting ingestion: internal materials + agent KB + user uploads -> chunk -> local vector store",
        )

        vs_dir = SETTINGS.vector_store_dir / run_id
        vs = LocalTfidfVectorStore(vs_dir)
        vs.reset()
        await _log(run, node="ingest", message="Vector store reset", extra={"vector_store_dir": str(vs_dir)})

        internal_total = 0
        for source in _build_kb_sources():
            await _log(run, node="ingest", message="Found KB source", extra={"label": source.label, "count": len(source.paths)})
            for p in source.paths:
                try:
                    chunks = build_chunks_for_file(
                        p,
                        source=source.source,
                        doc_id=f"{source.doc_prefix}:{p.name}",
                        meta={"scopes": source.scopes},
                    )
                    vs.add_chunks(chunks)
                    internal_total += len(chunks)
                    await _log(run, node="ingest", message="Chunked KB file", extra={"file": p.name, "chunks": len(chunks)})
                except Exception as e:
                    await _log(run, node="ingest", message="Skipped KB file (unsupported or failed parse)", extra={"file": p.name, "error": str(e)})

        template_path = _template_path(inputs.output_type)
        if template_path.exists():
            tpl_chunks = build_chunks_for_file(
                template_path,
                source="internal",
                doc_id=f"internal:{template_path.name}",
                meta={"scopes": ["ifad"]},
            )
            vs.add_chunks(tpl_chunks)
            internal_total += len(tpl_chunks)
            await _log(run, node="ingest", message="Added template to KB", extra={"template": template_path.name})

        upload_paths = project.get("uploads", [])
        await _log(run, node="ingest", message="Found user uploads", extra={"count": len(upload_paths)})
        user_total = 0
        for p in upload_paths:
            path = Path(p)
            if not path.exists():
                await _log(run, node="ingest", message="Upload path missing (skipped)", extra={"path": str(path)})
                continue
            try:
                chunks = build_chunks_for_file(path, source="user", meta={"scopes": ["project"]})
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

        template_md = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

        # 2) Multi-simulation loop
        candidates: list[CandidateResult] = []
        enable_reflection = True
        enable_planning = True
        for idx in range(num_simulations):
            candidate_id = f"cand_{idx + 1:03d}"
            await _log(run, node="orchestrator", message="Starting candidate simulation", extra={"candidate_id": candidate_id})
            result = await _run_candidate(
                run=run,
                run_id=run_id,
                candidate_id=candidate_id,
                vs=vs,
                profiles=profiles,
                inputs=inputs,
                template_md=template_md,
                enable_reflection=enable_reflection,
                enable_planning=enable_planning,
            )
            candidates.append(result)
            run.candidates = candidates
            await _save_run_status(run)

        # Rank candidates
        ranked = sorted(candidates, key=lambda c: (c.passed, c.score), reverse=True)
        selected = ranked[:top_candidates]
        run.selected_candidates = [c.candidate_id for c in selected]

        # 3) Render PDFs for selected candidates
        run.status = "rendering"
        await _save_run_status(run)
        await _emit(run, "run_status", {"status": run.status, "round": run.round})
        await _emit(run, "graph_update", {"node_status": {"cd": "idle", "ren": "idle", "ode": "idle"}})

        out_dir = SETTINGS.outputs_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        candidate_pdfs: dict[str, str] = {}
        for cand in selected:
            pdf_bytes = markdown_to_simple_pdf_bytes(Path(cand.draft_path).read_text(encoding="utf-8"))
            cand_dir = out_dir / cand.candidate_id
            cand_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = cand_dir / f"{inputs.output_type}.pdf"
            pdf_path.write_bytes(pdf_bytes)
            candidate_pdfs[cand.candidate_id] = str(pdf_path)
            cand.pdf_path = str(pdf_path)
            await _log(run, node="render", message="PDF written", extra={"candidate_id": cand.candidate_id, "pdf_path": str(pdf_path)})

        run.artifacts["candidate_pdfs"] = candidate_pdfs

        top = selected[0] if selected else None
        if top:
            run.review = top.review
            run.forecast = top.forecast
            run.artifacts["draft_md"] = top.draft_path
            run.artifacts["pdf"] = top.pdf_path or ""
            run.artifacts["top_candidate_id"] = top.candidate_id

            # Copy top candidate memory to root for backward compatibility
            mem_dir = _run_dir(run_id) / "candidates" / top.candidate_id / "memory"
            if mem_dir.exists():
                cd_mem_path = mem_dir / "cd.json"
                ode_mem_path = mem_dir / "ode.json"
                if cd_mem_path.exists():
                    await write_json(_run_dir(run_id) / "cd_memory.json", await read_json(cd_mem_path))
                    run.artifacts["cd_memory"] = str(_run_dir(run_id) / "cd_memory.json")
                if ode_mem_path.exists():
                    await write_json(_run_dir(run_id) / "ode_memory.json", await read_json(ode_mem_path))
                    run.artifacts["ode_memory"] = str(_run_dir(run_id) / "ode_memory.json")

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

