from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import json
from pydantic import ValidationError

from .llm import AzureChatLLM
from .models import CheckboxStatus, ReviewComment, ReviewResult


@dataclass
class AgentMemory:
    system: str
    messages: list[dict[str, str]] = field(default_factory=list)  # {role, content}

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})


@dataclass
class CountryDirectorWriter:
    """
    MVP writer agent: produces a COSOP draft from template + retrieved evidence + user notes.
    This is deterministic (no external LLM keys required) but keeps a prompt/memory structure
    so you can swap in a real LLM later.
    """

    memory: AgentMemory

    def write(
        self,
        *,
        template_md: str,
        project_inputs: dict[str, Any],
        evidence: list[dict[str, Any]],
        revision_notes: str | None = None,
    ) -> str:
        country = project_inputs.get("country") or "Unknown country"
        title = project_inputs.get("title") or "Untitled COSOP"
        user_notes = (project_inputs.get("user_notes") or "").strip()

        evidence_lines = []
        for i, ev in enumerate(evidence, start=1):
            loc = f"{ev.get('filename','')}"
            if ev.get("page"):
                loc += f" p.{ev['page']}"
            evidence_lines.append(f"[E{i}] ({loc}) {ev.get('text','')[:700].strip()}")
        evidence_annex = "\n\n".join(evidence_lines) if evidence_lines else "(No evidence retrieved.)"

        prompt = (
            "You must draft a COSOP in **Markdown**.\n"
            "Follow the template headings exactly. Keep it coherent and professional.\n"
            "Use inclusive, non-discriminatory language.\n"
            "Use the evidence excerpts in the annex; you may quote them and reference [E1], [E2], ... where relevant.\n\n"
            f"Country: {country}\n"
            f"Title: {title}\n\n"
            f"User notes:\n{user_notes}\n\n"
            f"Revision notes (if any):\n{revision_notes or ''}\n\n"
            "Template:\n"
            f"{template_md}\n\n"
            "Evidence excerpts:\n"
            f"{evidence_annex}\n"
        )

        self.memory.add("user", prompt)
        llm = AzureChatLLM()
        out = llm.chat(system=self.memory.system, messages=self.memory.messages, max_new_tokens=1800)
        self.memory.add("assistant", out)

        # Ensure we return markdown; if model returns extra leading text, just return as-is for MVP.
        return out

@dataclass
class ODEReviewer:
    """
    MVP reviewer: deterministic checks + comments + 5 checkboxes.
    """

    memory: AgentMemory

    def review(self, *, draft_md: str) -> ReviewResult:
        schema_hint = {
            "passed": True,
            "comments": [
                {"severity": "major", "section": "Overall", "comment": "…", "suggestion": "…"},
            ],
            "checkboxes": [
                {
                    "id": "word_count",
                    "label": "Word count meets MVP threshold (>= 800 words)",
                    "status": "true",
                    "rationale": "…",
                    "evidence": [],
                }
            ],
        }

        prompt = (
            "You are ODE. Review the COSOP draft.\n"
            "Return ONLY valid JSON matching this schema shape (no markdown fences):\n"
            f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
            "MVP checkbox requirements (use exactly these IDs):\n"
            "- word_count: >= 800 words\n"
            "- structure: includes core sections (context, objectives/ToC, implementation, risks)\n"
            "- inclusion: inclusive / non-discriminatory language\n"
            "- safeguards: mentions safeguards/inclusion risk mitigation\n"
            "- evidence: includes evidence excerpts/citations\n\n"
            "Draft:\n"
            f"{draft_md}\n"
        )
        self.memory.add("user", prompt)
        llm = AzureChatLLM()
        out = llm.chat(system=self.memory.system, messages=self.memory.messages, max_new_tokens=900)
        self.memory.add("assistant", out)

        try:
            data = json.loads(out)
            return ReviewResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            # Fallback to previous deterministic heuristic if JSON parsing fails
            return self._heuristic_review(draft_md=draft_md)

    def _heuristic_review(self, *, draft_md: str) -> ReviewResult:
        self.memory.add("user", "Fallback heuristic review (JSON parse failed).")

        # Basic metrics
        text_only = re.sub(r"`[^`]*`", "", draft_md)
        words = re.findall(r"\b\w+\b", text_only)
        word_count = len(words)

        required_headings = [
            "## 1. Country context",
            "## 3. Strategic objectives and theory of change",
            "## 4. Implementation arrangements",
            "## 5. Risks and mitigation",
        ]
        missing = [h for h in required_headings if h not in draft_md]

        discriminatory_terms = [
            r"\b(inferior|superior)\b",
            r"\b(race-based|racially inferior)\b",
        ]
        found_discriminatory = any(re.search(p, draft_md, flags=re.IGNORECASE) for p in discriminatory_terms)

        has_evidence = "## 6. Annex: Evidence excerpts" in draft_md and "[E1]" in draft_md

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

        # 5 MVP checkboxes
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
                status="true" if "Safeguards" in draft_md or "safeguards" in draft_md else "partial",
                rationale="Detected safeguards language in risks/mitigation section."
                if ("Safeguards" in draft_md or "safeguards" in draft_md)
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
        self.memory.add("assistant", f"Review complete. passed={passed}")
        return result

