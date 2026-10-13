"""Focused acceptance-r3 regression tests for the full profile."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import test_audit_delivery as fixtures
from test_audit_delivery import _sha256, _table, _write_docx


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import acceptance  # noqa: E402
import annotation_pixels  # noqa: E402
import audit_delivery  # noqa: E402


class AcceptanceR3Tests(unittest.TestCase):
    setUp = fixtures.AuditDeliveryTests.setUp
    tearDown = fixtures.AuditDeliveryTests.tearDown

    def _review_fixture(self):
        docx = _write_docx(self.root, "manual.docx", _table([1000], [[(1, 1000)]]))
        page = self.root / "page.png"
        page.write_bytes(b"page")
        support = self.root / "requirements.md"
        support.write_bytes(b"requirements")
        reviewed = [
            {"kind": "page", "path": page.name, "sha256": _sha256(page)},
            {"kind": "support", "path": support.name, "sha256": _sha256(support)},
        ]
        review = {
            "schema_version": 1,
            "artifact": {"sha256": _sha256(docx)},
            "builder": {"id": "builder"},
            "reviewer": {"id": "reviewer"},
            "reviewed_files": reviewed,
            "checks": {
                "requirements": {"status": "pass", "reason": "checked", "evidence": [support.name]},
                "redaction": {"status": "na", "reason": "no screenshots", "evidence": []},
                "visual": {"status": "pass", "reason": "checked", "evidence": [page.name]},
                "operation": {"status": "pass", "reason": "checked", "evidence": [page.name]},
            },
            "overall": "pass",
        }
        return docx, page, support, review

    def test_require_acceptance_blocks_missing_required_item(self) -> None:
        docx, _page, _support, review = self._review_fixture()
        review["acceptance"] = {
            "schema_version": 1,
            "items": [{
                "id": "layout",
                "applicable": True,
                "status": "pass",
                "reason": "checked",
                "evidence": ["page.png"],
                "actual_artifacts": [{"path": "page.png", "sha256": _sha256(self.root / "page.png"), "scope": "final page"}],
            }],
        }
        catalog = self.root / "acceptance-catalog.json"
        catalog.write_text(json.dumps({"schema_version": 1, "items": [
            {"id": "layout", "applicable": True},
            {"id": "annotation", "applicable": True},
        ]}), encoding="utf-8")
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")

        report = audit_delivery.audit_docx(
            docx,
            review_path,
            acceptance_catalog_path=catalog,
            require_acceptance=True,
        )

        self.assertEqual(report["independent_review"]["status"], "blocked")
        self.assertIn("acceptance_item_missing", report["independent_review"]["reason_codes"])

    def test_acceptance_invalid_evidence_and_stale_actual_hash_cannot_pass(self) -> None:
        docx, page, _support, review = self._review_fixture()
        review["acceptance"] = {
            "schema_version": 1,
            "items": [{
                "id": "layout",
                "applicable": True,
                "status": "pass",
                "reason": "checked",
                "evidence": ["missing.png"],
                "actual_artifacts": [{"path": page.name, "sha256": "0" * 64, "scope": "final page"}],
            }],
        }
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        report = audit_delivery.audit_docx(docx, review_path, require_acceptance=True)

        self.assertEqual(report["independent_review"]["status"], "blocked")
        codes = set(report["independent_review"]["reason_codes"])
        self.assertIn("acceptance_evidence_reference_missing", codes)
        self.assertIn("acceptance_actual_artifact_hash_mismatch", codes)

    def test_require_acceptance_without_catalog_is_blocked(self) -> None:
        docx, page, _support, review = self._review_fixture()
        review["acceptance"] = {
            "schema_version": 1,
            "items": [{
                "id": "layout",
                "applicable": True,
                "status": "pass",
                "reason": "checked",
                "evidence": [page.name],
                "actual_artifacts": [{"path": page.name, "sha256": _sha256(page), "scope": "final page"}],
            }],
        }
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")

        result = acceptance.validate_acceptance(
            review,
            review_path,
            {page.name, "requirements.md"},
            docx,
            require=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("acceptance_catalog_missing", result["reason_codes"])

    def test_catalog_requires_conditional_na_and_binds_actual_artifacts(self) -> None:
        docx, page, _support, review = self._review_fixture()
        review["acceptance"] = {
            "schema_version": 1,
            "items": [
                {
                    "id": "layout",
                    "applicable": True,
                    "status": "pass",
                    "reason": "checked",
                    "evidence": [page.name],
                    "actual_artifacts": [{"path": docx.name, "sha256": _sha256(docx), "scope": "final DOCX"}],
                },
                {
                    "id": "images",
                    "applicable": False,
                    "status": "na",
                    "reason": "this delivery has no captured images",
                    "evidence": [],
                    "actual_artifacts": [],
                },
            ],
        }
        catalog = self.root / "acceptance-catalog.json"
        catalog.write_text(json.dumps({"schema_version": 1, "items": [
            {"id": "layout", "applicable": True, "required": True},
            {"id": "images", "applicable": True, "applicability": "conditional", "required": True},
        ]}), encoding="utf-8")
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")

        result = acceptance.validate_acceptance(
            review,
            review_path,
            {page.name, "requirements.md"},
            docx,
            require=True,
            catalog_path=catalog,
        )

        self.assertEqual(result["status"], "pass")

        unrelated = self.root / "unrelated.png"
        unrelated.write_bytes(b"unrelated")
        review["acceptance"]["items"][0]["actual_artifacts"] = [{
            "path": unrelated.name,
            "sha256": _sha256(unrelated),
            "scope": "unbound file",
        }]
        result = acceptance.validate_acceptance(
            review,
            review_path,
            {page.name, "requirements.md"},
            docx,
            require=True,
            catalog_path=catalog,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("acceptance_actual_artifact_unbound", result["reason_codes"])

    def test_catalog_fixed_applicability_rejects_all_na_override(self) -> None:
        docx, page, _support, review = self._review_fixture()
        review["acceptance"] = {
            "schema_version": 1,
            "items": [{
                "id": "layout",
                "applicable": False,
                "status": "na",
                "reason": "claimed no layout",
                "evidence": [],
                "actual_artifacts": [],
            }],
        }
        catalog = self.root / "acceptance-catalog.json"
        catalog.write_text(json.dumps({"schema_version": 1, "items": [{"id": "layout", "applicable": True, "applicability": "always"}]}), encoding="utf-8")
        result = acceptance.validate_acceptance(
            review,
            self.root / "review.json",
            {page.name, "requirements.md"},
            docx,
            require=True,
            catalog_path=catalog,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("acceptance_item_applicability_mismatch", result["reason_codes"])

    def test_docx_candidate_warning_is_non_blocking_and_preserves_literal(self) -> None:
        table = _table(
            [1000, 1000, 1000],
            [[(1, 1000), (1, 1000), (1, 1000)]],
            first_row_texts=["QA 狀態：Item ID", "儲存", "儲存"],
        )
        docx = _write_docx(self.root, "literal.docx", table)
        report = audit_delivery.audit_docx(docx)

        self.assertEqual(report["mechanical_status"], "pass")
        self.assertTrue(report["candidate_warnings"])
        self.assertNotEqual(report["candidate_warnings_status"], "fail")
        self.assertEqual(report["candidate_warnings_semantic_review"], "not_performed")
        candidates = {warning["code"]: warning for warning in report["candidate_warnings"]}
        self.assertIn(1, candidates["qa_state_candidate"]["paragraphs"])
        self.assertIn(1, candidates["internal_identifier_candidate"]["paragraphs"])
        self.assertEqual(candidates["repeated_operation_candidate"]["paragraphs"], [2, 3])

    def test_known_snake_case_internal_codes_are_advisory_candidates(self) -> None:
        table = _table(
            [1000, 1000],
            [[(1, 1000), (1, 1000)]],
            first_row_texts=["畫面顯示 between_nomin 字樣", "畫面顯示 between_nomax 字樣"],
        )
        docx = _write_docx(self.root, "internal-code-literal.docx", table)
        report = audit_delivery.audit_docx(docx)

        self.assertEqual(report["mechanical_status"], "pass")
        candidates = {warning["code"]: warning for warning in report["candidate_warnings"]}
        self.assertEqual(candidates["internal_identifier_candidate"]["paragraphs"], [1, 2])
        self.assertEqual(report["candidate_warnings_semantic_review"], "not_performed")
        self.assertNotIn("between_nomin", json.dumps(report, ensure_ascii=False))
        self.assertNotIn("between_nomax", json.dumps(report, ensure_ascii=False))

    def test_pending_acceptance_item_cannot_produce_pass(self) -> None:
        docx, page, _support, review = self._review_fixture()
        review["acceptance"] = {
            "schema_version": 1,
            "items": [{
                "id": "layout",
                "applicable": True,
                "status": "pending",
                "reason": "awaiting visual review",
                "evidence": [],
                "actual_artifacts": [],
            }],
        }
        catalog = self.root / "acceptance-catalog.json"
        catalog.write_text(json.dumps({"schema_version": 1, "items": [{"id": "layout", "applicable": True}]}), encoding="utf-8")
        result = acceptance.validate_acceptance(
            review,
            self.root / "review.json",
            {page.name, "requirements.md"},
            docx,
            require=True,
            catalog_path=catalog,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("acceptance_item_incomplete", result["reason_codes"])

    def test_wrong_teal_frame_fails_only_inside_declared_annotation_region(self) -> None:
        redacted = self.root / "redacted.png"
        teal = self.root / "annotated-teal.png"
        Image.new("RGB", (160, 100), "white").save(redacted)
        image = Image.open(redacted).convert("RGB")
        ImageDraw.Draw(image).rectangle([30, 30, 90, 70], outline=(15, 91, 91), width=3)
        image.save(teal)
        manifest = {"annotations": [{"id": "1", "bbox": {"x": 30, "y": 30, "width": 60, "height": 40}}]}

        result = annotation_pixels.verify_annotation_output(teal, redacted, manifest)

        self.assertEqual(result["status"], "fail")
        self.assertIn("annotation_color_missing", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
