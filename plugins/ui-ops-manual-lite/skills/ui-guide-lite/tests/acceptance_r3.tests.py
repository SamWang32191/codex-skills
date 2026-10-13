"""Focused acceptance-r3 regression tests for the lite profile."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import acceptance  # noqa: E402
import annotation_pixels  # noqa: E402
import content_candidates  # noqa: E402


class AcceptanceR3Tests(unittest.TestCase):
    def test_missing_item_and_invalid_evidence_block_formal_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "page.png"
            page.write_bytes(b"page")
            review = {
                "acceptance": {"schema_version": 1, "items": [{
                    "id": "layout",
                    "applicable": True,
                    "status": "pass",
                    "reason": "checked",
                    "evidence": ["missing.png"],
                    "actual_artifacts": [{"path": page.name, "sha256": "0" * 64, "scope": "final page"}],
                }]},
            }
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"schema_version": 1, "items": [
                {"id": "layout", "applicable": True},
                {"id": "annotation", "applicable": True},
            ]}), encoding="utf-8")

            result = acceptance.validate_acceptance(
                review,
                root / "review.json",
                {"page.png"},
                root / "manual.docx",
                require=True,
                catalog_path=catalog,
            )

            self.assertEqual(result["status"], "blocked")
            self.assertIn("acceptance_item_missing", result["reason_codes"])
            self.assertIn("acceptance_evidence_reference_missing", result["reason_codes"])

    def test_required_gate_without_catalog_and_unbound_actual_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "page.png"
            page.write_bytes(b"page")
            review = {"acceptance": {"schema_version": 1, "items": [{
                "id": "layout",
                "applicable": True,
                "status": "pass",
                "reason": "checked",
                "evidence": [page.name],
                "actual_artifacts": [{"path": page.name, "sha256": acceptance._sha256(page), "scope": "final page"}],
            }]}}
            missing_catalog = acceptance.validate_acceptance(review, root / "review.json", {page.name}, root / "manual.docx", require=True)
            self.assertEqual(missing_catalog["status"], "blocked")
            self.assertIn("acceptance_catalog_missing", missing_catalog["reason_codes"])

            unrelated = root / "unrelated.png"
            unrelated.write_bytes(b"unrelated")
            review["acceptance"]["items"][0]["actual_artifacts"][0] = {
                "path": unrelated.name,
                "sha256": acceptance._sha256(unrelated),
                "scope": "unbound file",
            }
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"schema_version": 1, "items": [{"id": "layout", "applicable": True}]}), encoding="utf-8")
            result = acceptance.validate_acceptance(review, root / "review.json", {page.name}, root / "manual.docx", require=True, catalog_path=catalog)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("acceptance_actual_artifact_unbound", result["reason_codes"])

    def test_conditional_na_is_complete_but_catalog_applicability_is_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "page.png"
            page.write_bytes(b"page")
            review = {"acceptance": {"schema_version": 1, "items": [{
                "id": "images",
                "applicable": False,
                "status": "na",
                "reason": "no captured images in this delivery",
                "evidence": [],
                "actual_artifacts": [],
            }]}}
            conditional_catalog = root / "conditional.json"
            conditional_catalog.write_text(json.dumps({"schema_version": 1, "items": [{"id": "images", "applicable": True, "applicability": "conditional", "required": True}]}), encoding="utf-8")
            result = acceptance.validate_acceptance(review, root / "review.json", {page.name}, root / "manual.docx", require=True, catalog_path=conditional_catalog)
            self.assertEqual(result["status"], "pass")

            fixed_catalog = root / "fixed.json"
            fixed_catalog.write_text(json.dumps({"schema_version": 1, "items": [{"id": "images", "applicable": True, "applicability": "always", "required": True}]}), encoding="utf-8")
            result = acceptance.validate_acceptance(review, root / "review.json", {page.name}, root / "manual.docx", require=True, catalog_path=fixed_catalog)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("acceptance_item_applicability_mismatch", result["reason_codes"])

    def test_pending_item_blocks_and_candidate_indices_are_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docx = root / "literal.docx"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                '<w:p><w:r><w:t>QA 狀態：Item ID</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>儲存</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>儲存</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>畫面顯示 between_nomin 字樣</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>畫面顯示 between_nomax 字樣</w:t></w:r></w:p>'
                '</w:body></w:document>'
            ).encode("utf-8")
            with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("word/document.xml", xml)
            candidates = content_candidates.inspect_docx(docx)
            self.assertEqual(candidates["semantic_review"], "not_performed")
            warnings = {item["code"]: item for item in candidates["warnings"]}
            self.assertEqual(warnings["internal_identifier_candidate"]["paragraphs"], [1, 4, 5])
            self.assertEqual(warnings["repeated_operation_candidate"]["paragraphs"], [2, 3])

            page = root / "page.png"
            page.write_bytes(b"page")
            review = {"acceptance": {"schema_version": 1, "items": [{
                "id": "layout",
                "applicable": True,
                "status": "pending",
                "reason": "awaiting review",
                "evidence": [],
                "actual_artifacts": [],
            }]}}
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"schema_version": 1, "items": [{"id": "layout", "applicable": True}]}), encoding="utf-8")
            result = acceptance.validate_acceptance(review, root / "review.json", {page.name}, docx, require=True, catalog_path=catalog)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("acceptance_item_incomplete", result["reason_codes"])

    def test_stale_output_hash_and_teal_frame_fail_region_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            redacted = root / "redacted.png"
            annotated = root / "annotated.png"
            Image.new("RGB", (160, 100), "white").save(redacted)
            image = Image.open(redacted).convert("RGB")
            ImageDraw.Draw(image).rectangle([30, 30, 90, 70], outline=(15, 91, 91), width=3)
            image.save(annotated)
            manifest = {"annotations": [{"id": "1", "bbox": {"x": 30, "y": 30, "width": 60, "height": 40}}]}

            result = annotation_pixels.verify_annotation_output(annotated, redacted, manifest)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_color_missing", result["reason_codes"])
            self.assertNotEqual(result["output_sha256"], "0" * 64)


if __name__ == "__main__":
    unittest.main()
