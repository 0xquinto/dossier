"""Tests for board_aggregator.docx_utils (T4-3: read a Word CV)."""

import builtins

import pytest

from board_aggregator.docx_utils import docx_to_text

docx = pytest.importorskip("docx")  # python-docx, installed via .[dev]


def _make_docx(path, paragraphs, table_rows=None):
    """Write a minimal .docx with the given paragraphs (+ optional table)."""
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r, row in enumerate(table_rows):
            for c, val in enumerate(row):
                table.cell(r, c).text = val
    document.save(str(path))
    return path


def test_extracts_paragraph_text(tmp_path):
    path = _make_docx(
        tmp_path / "cv.docx",
        ["Jane Doe", "", "Senior Counsel", "Sustainability strategy"],
    )
    text = docx_to_text(path)
    assert "Jane Doe" in text
    assert "Senior Counsel" in text
    assert "Sustainability strategy" in text
    # Empty paragraphs are dropped — no blank lines between entries.
    assert "\n\n" not in text


def test_extracts_table_cells(tmp_path):
    path = _make_docx(
        tmp_path / "cv.docx",
        ["Skills"],
        table_rows=[["Python", "Advanced"], ["Contracts", "Expert"]],
    )
    text = docx_to_text(path)
    assert "Python\tAdvanced" in text
    assert "Contracts\tExpert" in text


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        docx_to_text(tmp_path / "nope.docx")


def test_unsupported_format_raises(tmp_path):
    bad = tmp_path / "cv.pdf"
    bad.write_text("not a docx")
    with pytest.raises(ValueError) as exc:
        docx_to_text(bad)
    assert ".docx" in str(exc.value)


def test_corrupt_docx_raises_value_error(tmp_path):
    bad = tmp_path / "cv.docx"
    bad.write_text("this is not a real word document")
    with pytest.raises(ValueError):
        docx_to_text(bad)


def test_missing_python_docx_raises_runtime_error(tmp_path, monkeypatch):
    """If python-docx isn't installed, give an actionable message, not ImportError."""
    real_path = _make_docx(tmp_path / "cv.docx", ["Hi"])
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "docx":
            raise ImportError("No module named 'docx'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        docx_to_text(real_path)
    assert "python-docx" in str(exc.value)
