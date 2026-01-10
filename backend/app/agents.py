from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import ReviewComment, ReviewResult, CheckboxStatus


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

        self.memory.add(
            "user",
            "Write COSOP draft using template. Inputs:\n"
            f"- country={country}\n- title={title}\n- user_notes={user_notes[:5000]}\n"
            f"- revision_notes={(revision_notes or '')[:3000]}\n",
        )

        evidence_lines = []
        for i, ev in enumerate(evidence, start=1):
            loc = f"{ev.get('filename','')}"
            if ev.get("page"):
                loc += f" p.{ev['page']}"
            evidence_lines.append(f"[E{i}] ({loc}) {ev.get('text','')[:500].strip()}")
        evidence_annex = "\n\n".join(evidence_lines) if evidence_lines else "(No evidence retrieved.)"

        country_context = (
            f"This COSOP draft concerns **{country}**. "
            "It is prepared as an MVP simulation and should be refined with country diagnostics "
            "and stakeholder consultations.\n\n"
            + (f"User-provided notes:\n\n{user_notes}\n" if user_notes else "")
        )

        lessons_learned = (
            "Key lessons learned are synthesized from available documentation provided to the system "
            "(e.g., CCR/CSPE references where available). Where gaps exist, the CDT should commission "
            "background studies and validate findings through consultations.\n"
        )

        strategy_toc = (
            "### Strategic objectives\n"
            "- SO1: Improve inclusive rural livelihoods and incomes.\n"
            "- SO2: Strengthen resilience to climate and market shocks.\n\n"
            "### Theory of change (high level)\n"
            "If investments expand access to services, finance, markets, and climate-smart practices, "
            "then smallholders—especially women and youth—can increase productivity and incomes while "
            "reducing vulnerability.\n"
        )

        implementation_arrangements = (
            "Implementation will be coordinated by the Country Delivery Team (CDT) under the CD’s leadership. "
            "The approach will align with IFAD procedures and emphasize partner coordination, learning, and "
            "adaptive management.\n"
        )

        risks_mitigation = (
            "- **Safeguards / inclusion risk**: Risk of exclusion of vulnerable groups. Mitigation: explicit targeting, "
            "inclusive consultation, grievance redress.\n"
            "- **Climate risk**: Increased climate variability. Mitigation: climate-smart investments, risk screening.\n"
            "- **Institutional risk**: Limited capacity. Mitigation: capacity building and phased implementation.\n"
        )

        draft = template_md
        draft = draft.replace("{{title}}", title)
        draft = draft.replace("{{country_context}}", country_context)
        draft = draft.replace("{{lessons_learned}}", lessons_learned)
        draft = draft.replace("{{strategy_toc}}", strategy_toc)
        draft = draft.replace("{{implementation_arrangements}}", implementation_arrangements)
        draft = draft.replace("{{risks_mitigation}}", risks_mitigation)
        draft = draft.replace("{{evidence_annex}}", evidence_annex)

        if revision_notes:
            draft += "\n\n---\n\n## Revision notes (from reviewer)\n\n" + revision_notes.strip() + "\n"

        self.memory.add("assistant", "Draft produced (markdown).")
        return draft


@dataclass
class ODEReviewer:
    """
    MVP reviewer: deterministic checks + comments + 5 checkboxes.
    """

    memory: AgentMemory

    def review(self, *, draft_md: str) -> ReviewResult:
        self.memory.add("user", "Review the draft for quality and basic compliance. Return structured result.")

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

