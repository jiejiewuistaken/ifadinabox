from __future__ import annotations

from io import BytesIO
from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas


def _wrap_lines(text: str, *, font_name: str, font_size: int, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        candidate = (" ".join(cur + [w])).strip()
        if stringWidth(candidate, font_name, font_size) <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def markdown_to_simple_pdf_bytes(md: str) -> bytes:
    """
    Minimal Markdown -> PDF renderer for MVP:
    - '# ' and '## ' headings
    - bullet lines
    - everything else as wrapped paragraphs
    """
    buf = BytesIO()
    c = Canvas(buf, pagesize=A4)
    width, height = A4

    x_margin = 2 * cm
    y = height - 2 * cm
    max_width = width - 2 * cm * 2

    def new_page() -> None:
        nonlocal y
        c.showPage()
        y = height - 2 * cm

    def draw_lines(lines: Iterable[str], *, font: str, size: int, leading: int) -> None:
        nonlocal y
        c.setFont(font, size)
        for line in lines:
            if y < 2 * cm:
                new_page()
                c.setFont(font, size)
            c.drawString(x_margin, y, line)
            y -= leading

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            y -= 8
            continue
        if line.startswith("# "):
            y -= 6
            draw_lines([line[2:].strip()], font="Helvetica-Bold", size=18, leading=22)
            y -= 6
            continue
        if line.startswith("## "):
            y -= 4
            draw_lines([line[3:].strip()], font="Helvetica-Bold", size=14, leading=18)
            y -= 2
            continue
        if line.startswith("### "):
            draw_lines([line[4:].strip()], font="Helvetica-Bold", size=12, leading=16)
            continue
        if line.lstrip().startswith("- "):
            content = line.lstrip()[2:].strip()
            wrapped = _wrap_lines(f"• {content}", font_name="Helvetica", font_size=10, max_width=max_width)
            draw_lines(wrapped, font="Helvetica", size=10, leading=14)
            continue
        wrapped = _wrap_lines(line.strip(), font_name="Helvetica", font_size=10, max_width=max_width)
        draw_lines(wrapped, font="Helvetica", size=10, leading=14)

    c.save()
    return buf.getvalue()

