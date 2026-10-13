#!/usr/bin/env python3
"""Conservative DOCX text candidate warnings for lite reviewer follow-up."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


# These identifiers are review candidates only.  The two ``between_*``
# operation codes are known internal rule names from production documents;
# they intentionally remain usable as literal UI text after reviewer review.
_INTERNAL = re.compile(r"\b(?:uuid|guid|request[ _-]?id|trace[ _-]?id|session[ _-]?id|internal[ _-]?id|item[ _-]?id|row[ _-]?id|tenant[ _-]?id|between_nomin|between_nomax)\b", re.I)
_QA_STATE = re.compile(r"\b(?:qa|uat|staging|dev|debug|test|draft|pending|blocked|not[ _-]?performed)\b", re.I)
_OPERATION = re.compile(r"(?:儲存|保存|提交|送出|查詢|搜尋|點選|按下|click|save|submit|select|search|open)", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def inspect_docx(path: str | Path) -> dict[str, object]:
    """Return non-blocking warning codes; matched text is intentionally omitted."""

    try:
        with zipfile.ZipFile(Path(path), "r") as package:
            root = ET.fromstring(package.read("word/document.xml"))
        paragraphs: list[tuple[int, str]] = []
        for index, paragraph in enumerate((node for node in root.iter() if _local(node.tag) == "p"), 1):
            text = "".join((node.text or "") for node in paragraph.iter() if _local(node.tag) == "t")
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                paragraphs.append((index, text))
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return {"status": "unavailable", "semantic_review": "not_performed", "warnings": [{"code": "docx_text_unreadable"}]}
    warnings: list[dict[str, object]] = []
    internal_paragraphs = [index for index, text in paragraphs if _INTERNAL.search(text)]
    qa_paragraphs = [index for index, text in paragraphs if _QA_STATE.search(text)]
    if internal_paragraphs:
        warnings.append({"code": "internal_identifier_candidate", "paragraphs": internal_paragraphs, "count": len(internal_paragraphs)})
    if qa_paragraphs:
        warnings.append({"code": "qa_state_candidate", "paragraphs": qa_paragraphs, "count": len(qa_paragraphs)})
    counts: dict[str, list[int]] = {}
    for index, text in paragraphs:
        if _OPERATION.search(text):
            key = text.casefold()
            counts.setdefault(key, []).append(index)
    repeated_paragraphs = [index for indices in counts.values() if len(indices) > 1 for index in indices]
    if repeated_paragraphs:
        warnings.append({"code": "repeated_operation_candidate", "paragraphs": repeated_paragraphs, "occurrences": len(repeated_paragraphs)})
    return {"status": "review_required" if warnings else "clear", "semantic_review": "not_performed", "warnings": warnings, "paragraph_count": len(paragraphs)}
