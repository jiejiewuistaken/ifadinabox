from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from pydantic import ValidationError

from .llm import AzureChatLLM
from .models import CheckboxStatus, ReviewComment, ReviewResult


@dataclass
class AgentProfile:
    agent_id: str
    label: str
    responsibilities: list[str]
    system_prompt: str
    allowed_scopes: tuple[str, ...]


@dataclass
class AgentMemory:
    system: str
    long_term: list[str] = field(default_factory=list)
    public: list[str] = field(default_factory=list)
    short_term: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)  # {role, content}

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def add_long_term(self, content: str) -> None:
        self.long_term.append(content)

    def add_public(self, content: str) -> None:
        self.public.append(content)

    def add_short_term(self, content: str) -> None:
        self.short_term.append(content)

    def add_reflection(self, content: str) -> None:
        self.reflections.append(content)

    def add_plan(self, content: str) -> None:
        self.plans.append(content)

    def _format_items(self, label: str, items: Iterable[str], max_items: int) -> str:
        trimmed = list(items)[-max_items:]
        if not trimmed:
            return f"{label}: (none)"
        lines = "\n".join(f"- {x}" for x in trimmed)
        return f"{label}:\n{lines}"

    def context_block(self, *, max_items: int = 6) -> str:
        blocks = [
            self._format_items("Long-term memory", self.long_term, max_items),
            self._format_items("Public references", self.public, max_items),
            self._format_items("Short-term memory", self.short_term, max_items),
            self._format_items("Recent reflections", self.reflections, max_items),
            self._format_items("Current plans", self.plans, max_items),
        ]
        return "\n\n".join(blocks).strip()

    def snapshot(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "long_term": self.long_term,
            "public": self.public,
            "short_term": self.short_term,
            "reflections": self.reflections,
            "plans": self.plans,
            "messages": self.messages,
        }


@dataclass
class LLMAgent:
    profile: AgentProfile
    memory: AgentMemory

    def _chat(self, prompt: str, *, max_tokens: int) -> str:
        self.memory.add_message("user", prompt)
        llm = AzureChatLLM()
        out = llm.chat(system=self.memory.system, messages=self.memory.messages, max_new_tokens=max_tokens)
        self.memory.add_message("assistant", out)
        return out

    def reflect(self, *, context: str) -> str:
        prompt = (
            "Reflect on the current COSOP/PCN/PDR work.\n"
            "Summarize the core logic, deviations from your role objectives, and risks.\n\n"
            f"{self.memory.context_block()}\n\n"
            f"Context:\n{context}\n"
        )
        out = self._chat(prompt, max_tokens=320)
        self.memory.add_reflection(out)
        return out

    def plan(self, *, goals: str) -> str:
        prompt = (
            "Formulate concrete next steps aligned with your role.\n"
            "Propose revisions, initiate discussions, or reject non-compliant items.\n\n"
            f"{self.memory.context_block()}\n\n"
            f"Goals:\n{goals}\n"
        )
        out = self._chat(prompt, max_tokens=320)
        self.memory.add_plan(out)
        return out

    def act(
        self,
        *,
        task: str,
        evidence: list[dict[str, Any]] | None = None,
        extra_context: str | None = None,
        max_tokens: int = 900,
    ) -> str:
        evidence_lines = []
        for i, ev in enumerate(evidence or [], start=1):
            loc = f"{ev.get('filename','')}"
            if ev.get("page"):
                loc += f" p.{ev['page']}"
            evidence_lines.append(f"[E{i}] ({loc}) {ev.get('text','')[:500].strip()}")
        evidence_block = "\n".join(evidence_lines) if evidence_lines else "(No evidence retrieved.)"

        prompt = (
            f"Task:\n{task}\n\n"
            f"{self.memory.context_block()}\n\n"
            f"Extra context:\n{extra_context or '(none)'}\n\n"
            f"Evidence excerpts:\n{evidence_block}\n"
        )
        return self._chat(prompt, max_tokens=max_tokens)


@dataclass
class CountryDirectorWriter(LLMAgent):
    """
    Writer agent: produces a COSOP/PCN/PDR draft from template + evidence + stakeholder guidance.
    """

    def draft(
        self,
        *,
        template_md: str,
        project_inputs: dict[str, Any],
        evidence: list[dict[str, Any]],
        revision_notes: str | None = None,
        guidance_notes: str | None = None,
        output_type: str = "cosop",
    ) -> str:
        country = project_inputs.get("country") or "Unknown country"
        title = project_inputs.get("title") or f"Untitled {output_type.upper()}"
        user_notes = (project_inputs.get("user_notes") or "").strip()
        doc_label = output_type.upper()

        evidence_lines = []
        for i, ev in enumerate(evidence, start=1):
            loc = f"{ev.get('filename','')}"
            if ev.get("page"):
                loc += f" p.{ev['page']}"
            evidence_lines.append(f"[E{i}] ({loc}) {ev.get('text','')[:700].strip()}")
        evidence_annex = "\n\n".join(evidence_lines) if evidence_lines else "(No evidence retrieved.)"

        prompt = (
            f"You must draft a {doc_label} in Markdown.\n"
            "Follow the template headings exactly. Keep it coherent and professional.\n"
            "Use inclusive, non-discriminatory language.\n"
            "Use the evidence excerpts in the annex; you may quote them and reference [E1], [E2], ... where relevant.\n\n"
            f"Country: {country}\n"
            f"Title: {title}\n\n"
            f"User notes:\n{user_notes}\n\n"
            f"Guidance from other stakeholders:\n{guidance_notes or '(none)'}\n\n"
            f"Revision notes (if any):\n{revision_notes or ''}\n\n"
            "Template:\n"
            f"{template_md}\n\n"
            "Evidence excerpts:\n"
            f"{evidence_annex}\n"
        )

        return self._chat(prompt, max_tokens=1800)


@dataclass
class GovernmentAdvisor(LLMAgent):
    def propose_priorities(
        self, *, project_inputs: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> str:
        country = project_inputs.get("country") or "the country"
        task = (
            f"Provide the government's priorities, constraints, and red lines for {country}.\n"
            "Return concise bullet points grouped by: priorities, constraints, endorsement conditions."
        )
        return self.act(task=task, evidence=evidence, max_tokens=700)


@dataclass
class CDTAdvisor(LLMAgent):
    def provide_technical_feedback(
        self, *, concept: str, evidence: list[dict[str, Any]], focus: str
    ) -> str:
        task = (
            f"Review the concept and provide technical feedback ({focus}).\n"
            "Return: key risks, feasibility concerns, and suggested revisions in bullets."
        )
        return self.act(task=task, evidence=evidence, extra_context=concept, max_tokens=700)


@dataclass
class RENReviewer:
    """
    Quality and compliance reviewer.
    """

    memory: AgentMemory

    def review(self, *, draft_md: str) -> ReviewResult:
        schema_hint = {
            "passed": True,
            "comments": [
                {"severity": "major", "section": "Overall", "comment": "...", "suggestion": "..."},
            ],
            "checkboxes": [
                {
                    "id": "policy_alignment",
                    "label": "Aligned with IFAD policy and COSOP mandate",
                    "status": "true",
                    "rationale": "...",
                    "evidence": [],
                }
            ],
        }

        prompt = (
            "You are REN. Review the COSOP draft for quality, compliance, and results orientation.\n"
            "Return ONLY valid JSON matching this schema shape (no markdown fences):\n"
            f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
            "Checkbox IDs to use:\n"
            "- policy_alignment\n"
            "- results_chain\n"
            "- implementation_capacity\n"
            "- risk_mitigation\n"
            "- compliance_quality\n\n"
            "Draft:\n"
            f"{draft_md}\n"
        )
        self.memory.add_message("user", prompt)
        llm = AzureChatLLM()
        out = llm.chat(system=self.memory.system, messages=self.memory.messages, max_new_tokens=900)
        self.memory.add_message("assistant", out)

        try:
            data = json.loads(out)
            return ReviewResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return self._heuristic_review(draft_md=draft_md)

    def _heuristic_review(self, *, draft_md: str) -> ReviewResult:
        self.memory.add_message("user", "Fallback heuristic REN review (JSON parse failed).")

        comments: list[ReviewComment] = []
        has_results = "theory of change" in draft_md.lower() or "results" in draft_md.lower()
        has_impl = "implementation arrangements" in draft_md.lower()
        has_risks = "risk" in draft_md.lower() or "mitigation" in draft_md.lower()
        has_policy = "ifad" in draft_md.lower() or "strategic" in draft_md.lower()
        has_compliance = "safeguard" in draft_md.lower() or "compliance" in draft_md.lower()

        if not has_results:
            comments.append(
                ReviewComment(
                    severity="major",
                    section="Results",
                    comment="Results chain or theory of change is unclear.",
                    suggestion="Clarify the results chain and outcomes in the strategic objectives section.",
                )
            )
        if not has_impl:
            comments.append(
                ReviewComment(
                    severity="major",
                    section="Implementation",
                    comment="Implementation capacity is not explicit.",
                    suggestion="Detail implementation arrangements and partner capacities.",
                )
            )
        if not has_risks:
            comments.append(
                ReviewComment(
                    severity="major",
                    section="Risk",
                    comment="Risks and mitigation are not sufficiently covered.",
                    suggestion="Strengthen the risks and mitigation section with concrete actions.",
                )
            )

        checkboxes = [
            CheckboxStatus(
                id="policy_alignment",
                label="Aligned with IFAD policy and COSOP mandate",
                status="true" if has_policy else "partial",
                rationale="Detected IFAD/strategic alignment language." if has_policy else "Limited policy alignment cues found.",
                evidence=[],
            ),
            CheckboxStatus(
                id="results_chain",
                label="Results chain / theory of change is clear",
                status="true" if has_results else "false",
                rationale="Results chain language detected." if has_results else "Missing results chain language.",
                evidence=[],
            ),
            CheckboxStatus(
                id="implementation_capacity",
                label="Implementation capacity is addressed",
                status="true" if has_impl else "false",
                rationale="Implementation arrangements section found." if has_impl else "Implementation details missing.",
                evidence=[],
            ),
            CheckboxStatus(
                id="risk_mitigation",
                label="Risk mitigation measures are included",
                status="true" if has_risks else "false",
                rationale="Risk/mitigation language detected." if has_risks else "No explicit risk mitigation.",
                evidence=[],
            ),
            CheckboxStatus(
                id="compliance_quality",
                label="Compliance and quality safeguards are addressed",
                status="true" if has_compliance else "partial",
                rationale="Safeguards/compliance language detected." if has_compliance else "No clear compliance statements.",
                evidence=[],
            ),
        ]

        passed = all(cb.status in ("true", "partial") for cb in checkboxes) and not any(
            c.severity == "blocker" for c in comments
        )
        return ReviewResult(passed=passed, comments=comments, checkboxes=checkboxes)


@dataclass
class ODEReviewer:
    """
    ODE reviewer: deterministic checks + comments + 5 checkboxes.
    """

    memory: AgentMemory

    def review(self, *, draft_md: str) -> ReviewResult:
        schema_hint = {
            "passed": True,
            "comments": [
                {"severity": "major", "section": "Overall", "comment": "...", "suggestion": "..."},
            ],
            "checkboxes": [
                {
                    "id": "word_count",
                    "label": "Word count meets MVP threshold (>= 800 words)",
                    "status": "true",
                    "rationale": "...",
                    "evidence": [],
                }
            ],
        }

        prompt = (
            "You are ODE. Review the COSOP draft.\n"
            "Return ONLY valid JSON matching this schema shape (no markdown fences):\n"
            f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
            "Checkbox requirements (use exactly these IDs):\n"
            "- word_count: >= 800 words\n"
            "- structure: includes core sections (context, objectives/ToC, implementation, risks)\n"
            "- inclusion: inclusive / non-discriminatory language\n"
            "- safeguards: mentions safeguards/inclusion risk mitigation\n"
            "- evidence: includes evidence excerpts/citations\n\n"
            "Draft:\n"
            f"{draft_md}\n"
        )
        self.memory.add_message("user", prompt)
        llm = AzureChatLLM()
        out = llm.chat(system=self.memory.system, messages=self.memory.messages, max_new_tokens=900)
        self.memory.add_message("assistant", out)

        try:
            data = json.loads(out)
            return ReviewResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return self._heuristic_review(draft_md=draft_md)

    def _heuristic_review(self, *, draft_md: str) -> ReviewResult:
        self.memory.add_message("user", "Fallback heuristic review (JSON parse failed).")

        # Basic metrics
        text_only = re.sub(r"`[^`]*`", "", draft_md)
        words = re.findall(r"\b\w+\b", text_only)
        word_count = len(words)

        draft_lower = draft_md.lower()
        required_sections = {
            "Country context": ["country context"],
            "Strategic objectives / theory of change": ["strategic objectives", "theory of change"],
            "Implementation arrangements": ["implementation arrangements", "implementation"],
            "Risks and mitigation": ["risks", "mitigation"],
        }
        missing = [
            section
            for section, terms in required_sections.items()
            if not any(term in draft_lower for term in terms)
        ]

        discriminatory_terms = [
            r"\b(inferior|superior)\b",
            r"\b(race-based|racially inferior)\b",
        ]
        found_discriminatory = any(re.search(p, draft_md, flags=re.IGNORECASE) for p in discriminatory_terms)

        has_evidence = "annex: evidence excerpts" in draft_lower and "[e1]" in draft_lower

        comments: list[ReviewComment] = []
        if word_count < 800:
            comments.append(
                ReviewComment(
                    severity="major",
                    section="Overall",
                    comment=f"Draft is likely under-developed (word_count={word_count}).",
                    suggestion="Expand country context, lessons learned, and implementation arrangements with more evidence.",
                )
            )
        if missing:
            comments.append(
                ReviewComment(
                    severity="blocker",
                    section="Structure",
                    comment=f"Missing required sections: {', '.join(missing)}",
                    suggestion="Add the missing sections using COSOP template headings.",
                )
            )
        if found_discriminatory:
            comments.append(
                ReviewComment(
                    severity="blocker",
                    section="Compliance",
                    comment="Potential discriminatory or inappropriate language detected.",
                    suggestion="Rewrite to ensure inclusive, non-discriminatory language consistent with IFAD values.",
                )
            )
        if not has_evidence:
            comments.append(
                ReviewComment(
                    severity="major",
                    section="Evidence",
                    comment="No evidence excerpts/citations detected in the annex.",
                    suggestion="Include excerpts from uploaded materials and internal template references.",
                )
            )

        # 5 checkboxes
        checkboxes = [
            CheckboxStatus(
                id="word_count",
                label="Word count meets MVP threshold (>= 800 words)",
                status="true" if word_count >= 800 else "false",
                rationale=f"Detected approximately {word_count} words.",
                evidence=[],
            ),
            CheckboxStatus(
                id="structure",
                label="Includes core COSOP sections (context, objectives/ToC, implementation, risks)",
                status="true" if not missing else "false",
                rationale="All required headings present." if not missing else f"Missing: {', '.join(missing)}",
                evidence=[],
            ),
            CheckboxStatus(
                id="inclusion",
                label="Inclusive / non-discriminatory language (basic heuristic)",
                status="true" if not found_discriminatory else "false",
                rationale="No flagged discriminatory terms found." if not found_discriminatory else "Flagged terms matched heuristic patterns.",
                evidence=[],
            ),
            CheckboxStatus(
                id="safeguards",
                label="Mentions safeguards/inclusion risk mitigation (SECAP-relevant)",
                status="true" if "safeguards" in draft_md.lower() else "partial",
                rationale="Detected safeguards language in risks/mitigation section."
                if "safeguards" in draft_md.lower()
                else "No explicit safeguards keyword found; may need strengthening.",
                evidence=[],
            ),
            CheckboxStatus(
                id="evidence",
                label="Provides evidence excerpts/citations from inputs (RAG annex)",
                status="true" if has_evidence else "false",
                rationale="Evidence annex includes at least one excerpt." if has_evidence else "No evidence excerpts detected.",
                evidence=[],
            ),
        ]

        passed = all(cb.status in ("true", "partial") for cb in checkboxes) and not any(
            c.severity == "blocker" for c in comments
        )

        result = ReviewResult(passed=passed, comments=comments, checkboxes=checkboxes)
        self.memory.add_message("assistant", f"Review complete. passed={passed}")
        return result

