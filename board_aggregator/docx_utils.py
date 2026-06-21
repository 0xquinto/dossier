"""Extract plain text from a Word (.docx) CV.

The Read tool can't open binary .docx files, so a new user's Word resume was
unreadable and they had to paste the raw text by hand (T4-3). primer-8 calls
``docx_to_text`` via Bash during onboarding to pull the text itself instead.

Depends on python-docx (shipped via the .[dev] install path). The dependency
is imported lazily so importing this module never crashes the package when
python-docx is absent — the failure surfaces as a clear message only when a
.docx is actually read.
"""

from pathlib import Path


def docx_to_text(file_path: str | Path) -> str:
    """Return the visible text of a .docx file as newline-joined paragraphs.

    Paragraph text and table cell text are included, in document order.
    Empty paragraphs are dropped. Raises:

    - ``FileNotFoundError`` if the path doesn't exist.
    - ``ValueError`` if the path isn't a .docx file or isn't a valid Word doc.
    - ``RuntimeError`` if python-docx isn't installed (install ``.[dev]``).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")
    if path.suffix.lower() != ".docx":
        raise ValueError(
            f"Not a .docx file: {path} (got suffix {path.suffix!r}). "
            "Only Word .docx is supported here."
        )

    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover - exercised via patched import
        raise RuntimeError(
            "python-docx is required to read .docx files. "
            "Install it with: .venv/bin/pip install -e \".[dev]\""
        ) from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ValueError(f"Could not open {path} as a Word document: {exc}") from exc

    lines: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append("\t".join(cells))

    return "\n".join(lines)
