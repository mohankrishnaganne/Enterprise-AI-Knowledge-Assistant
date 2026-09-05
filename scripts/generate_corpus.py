"""Write the synthetic ACME Corp corpus to ``data/raw/``.

The corpus is generated rather than committed as prose so it stays reproducible and so
the two PDF documents can be rebuilt on any machine. Run with::

    python scripts/generate_corpus.py

Two business documents are additionally rendered to PDF (and their markdown source
removed) so the PDF ingestion path is exercised by the real pipeline rather than assumed
to work.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow `python scripts/generate_corpus.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.corpus import business, operational, technical  # noqa: E402
from src.config import RAW_DATA_DIR  # noqa: E402
from src.logging_conf import get_logger  # noqa: E402

log = get_logger(__name__)

# category -> {filename: markdown body}
CORPUS: dict[str, dict[str, str]] = {
    "technical": technical.DOCUMENTS,
    "operational": operational.DOCUMENTS,
    "business": business.DOCUMENTS,
}


def _render_pdf(markdown_text: str, destination: Path) -> None:
    """Render a markdown document to a simple, text-extractable PDF.

    Deliberately plain: the point is to produce a real PDF that ``pypdf`` can extract
    text from, preserving heading structure so the metadata extractor still finds
    sections. Tables are emitted as preformatted lines rather than drawn, because the
    goal is faithful text extraction, not typography.
    """
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    mono = ParagraphStyle(
        "Mono",
        parent=styles["BodyText"],
        fontName="Courier",
        fontSize=8.5,
        leading=11,
        alignment=TA_LEFT,
    )

    doc = SimpleDocTemplate(
        str(destination),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=destination.stem,
    )

    flowables: list = []
    for block in markdown_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue

        if block.startswith("# "):
            flowables.append(Paragraph(_escape(block[2:]), styles["Title"]))
        elif block.startswith("## "):
            flowables.append(Spacer(1, 8))
            flowables.append(Paragraph(_escape(block[3:]), styles["Heading2"]))
        elif block.startswith("### "):
            flowables.append(Paragraph(_escape(block[4:]), styles["Heading3"]))
        elif block.lstrip().startswith("|"):
            # Markdown table: keep it monospaced so the row structure survives extraction.
            for line in block.splitlines():
                flowables.append(Paragraph(_escape(line.strip()), mono))
        else:
            flowables.append(Paragraph(_escape(block.replace("\n", " ")), styles["BodyText"]))
        flowables.append(Spacer(1, 5))

    doc.build(flowables)


def _escape(text: str) -> str:
    """Escape XML-significant characters and convert **bold** for ReportLab markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def generate(output_dir: Path = RAW_DATA_DIR, *, pdf: bool = True) -> dict[str, int]:
    """Write the corpus. Returns a per-category count of files written."""
    counts: dict[str, int] = {}

    for category, documents in CORPUS.items():
        category_dir = output_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)

        # Clear previously generated files so a rename in the source does not leave
        # an orphan behind that would silently keep being ingested.
        for stale in [*category_dir.glob("*.md"), *category_dir.glob("*.pdf")]:
            stale.unlink()

        as_pdf = set(business.PDF_DOCUMENTS) if category == "business" and pdf else set()

        for filename, body in documents.items():
            if filename in as_pdf:
                target = category_dir / f"{Path(filename).stem}.pdf"
                _render_pdf(body, target)
            else:
                target = category_dir / filename
                target.write_text(body, encoding="utf-8")
            log.debug("wrote_document", path=str(target.relative_to(output_dir.parent.parent)))

        counts[category] = len(documents)

    return counts


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate the synthetic ACME Corp corpus.")
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Write every document as markdown (skips the reportlab dependency).",
    )
    args = parser.parse_args()

    counts = generate(pdf=not args.no_pdf)

    total_chars = sum(len(body) for docs in CORPUS.values() for body in docs.values())
    log.info(
        "corpus_generated",
        destination=str(RAW_DATA_DIR),
        total_documents=sum(counts.values()),
        total_characters=total_chars,
        **counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
