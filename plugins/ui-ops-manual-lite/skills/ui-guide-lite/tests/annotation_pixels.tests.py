"""Regression tests for parent-bound annotation pixel verification."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import annotation_pixels  # noqa: E402
import validate_screenshot_manifest as validator  # noqa: E402


class AnnotationPixelsTests(unittest.TestCase):
    def workspace(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    @staticmethod
    def manifest(*, cursor: bool = True) -> dict:
        item = {
            "id": "1",
            "controlName": "Save",
            "caption": "紅框 1：Save",
            "bbox": {"x": 70, "y": 60, "width": 100, "height": 42},
            "status": "verified",
        }
        if cursor:
            item["cursor"] = {"x": 35, "y": 35}
        return {"originalImageSize": {"width": 240, "height": 160}, "annotations": [item]}

    @staticmethod
    def render(parent: Path, output: Path, manifest: dict) -> None:
        with Image.open(parent) as image:
            rendered, _ = annotation_pixels.render_annotation_layer(image, manifest)
        rendered.save(output, format="PNG")

    def test_valid_red_frame_badge_and_cursor_pass(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "annotated.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest()
            self.render(parent, output, manifest)

            result = annotation_pixels.verify_annotation_output(output, parent, manifest)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["semantic_review"], "not_performed")
            self.assertEqual(result["annotations"][0]["status"], "pass")
            self.assertEqual(
                {component["region"] for component in result["annotations"][0]["components"]},
                {"frame", "badge", "cursor"},
            )

    def test_wrong_teal_frame_is_rejected_inside_marker_region(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "teal.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest(cursor=False)
            image = Image.open(parent).convert("RGB")
            ImageDraw.Draw(image).rectangle([70, 60, 170, 102], outline=annotation_pixels.DOCUMENT_TEAL, width=3)
            image.save(output)

            result = annotation_pixels.verify_annotation_output(output, parent, manifest)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_color_missing", result["reason_codes"])
            self.assertIn("annotation_color_teal", result["reason_codes"])

    def test_red_frame_with_teal_badge_is_rejected(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "mixed.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest(cursor=False)
            image = Image.open(parent).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.rectangle([70, 60, 170, 102], outline=annotation_pixels.ANNOTATION_RED, width=3)
            badge = annotation_pixels.badge_box(70, 60, 36, 36, 240, 160, bbox_width=100, bbox_height=42)
            self.assertIsNotNone(badge)
            bx, by, bw, bh = badge
            draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4, fill=annotation_pixels.DOCUMENT_TEAL)
            image.save(output)

            result = annotation_pixels.verify_annotation_output(output, parent, manifest)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_color_teal", result["reason_codes"])
            badge_result = next(component for component in result["annotations"][0]["components"] if component["region"] == "badge")
            self.assertEqual(badge_result["status"], "fail")

    def test_partially_red_edge_mostly_wrong_color_is_rejected(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "partial.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest(cursor=False)
            image = Image.open(parent).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.line([70, 60, 170, 60], fill=annotation_pixels.ANNOTATION_RED, width=3)
            draw.line([70, 102, 170, 102], fill=annotation_pixels.DOCUMENT_TEAL, width=3)
            draw.line([70, 60, 70, 102], fill=annotation_pixels.DOCUMENT_TEAL, width=3)
            draw.line([170, 60, 170, 102], fill=annotation_pixels.DOCUMENT_TEAL, width=3)
            image.save(output)

            result = annotation_pixels.verify_annotation_output(output, parent, manifest)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_color_partial", result["reason_codes"])

    def test_unchanged_parent_that_already_contains_red_ui_fails(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "red-ui.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest(cursor=False)
            self.render(parent, parent, manifest)

            result = annotation_pixels.verify_annotation_output(parent, parent, manifest)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_output_unchanged", result["reason_codes"])
            self.assertIn("annotation_marker_unchanged", result["reason_codes"])

    def test_unrelated_red_ui_does_not_substitute_for_marker(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "ui-red.png"
            output = root / "unchanged.png"
            image = Image.new("RGB", (240, 160), "white")
            ImageDraw.Draw(image).rectangle([5, 5, 45, 35], fill=annotation_pixels.ANNOTATION_RED)
            image.save(parent)
            image.save(output)
            manifest = self.manifest(cursor=False)

            result = annotation_pixels.verify_annotation_output(output, parent, manifest)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_output_unchanged", result["reason_codes"])

    def test_stale_manifest_and_provenance_hashes_are_rejected(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "annotated.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest(cursor=False)
            self.render(parent, output, manifest)
            manifest["redactedSha256"] = "0" * 64
            manifest["annotatedSha256"] = "1" * 64
            provenance = {"parentSha256": "2" * 64, "outputSha256": "3" * 64}

            result = annotation_pixels.verify_annotation_output(output, parent, manifest, provenance=provenance)

            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_parent_hash_mismatch", result["reason_codes"])
            self.assertIn("annotation_output_hash_mismatch", result["reason_codes"])
            self.assertIn("annotation_provenance_parent_hash_mismatch", result["reason_codes"])
            self.assertIn("annotation_provenance_output_hash_mismatch", result["reason_codes"])

    def test_scaled_manifest_and_small_antialias_noise_are_supported(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "scaled.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest = self.manifest(cursor=False)
            manifest["originalImageSize"] = {"width": 120, "height": 80}
            manifest["annotations"][0]["bbox"] = {"x": 35, "y": 30, "width": 50, "height": 21}
            with Image.open(parent) as image:
                rendered, _ = annotation_pixels.render_annotation_layer(image, manifest)
            noisy = rendered.convert("RGB")
            pixels = noisy.load()
            for x in range(noisy.width):
                for y in range(noisy.height):
                    r, g, b = pixels[x, y]
                    if (r, g, b) == annotation_pixels.ANNOTATION_RED:
                        pixels[x, y] = (205, 65, 65)
            noisy.save(output)

            result = annotation_pixels.verify_annotation_output(output, parent, manifest)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["annotations"][0]["scale"]["source"], "originalImageSize")

    def test_invalid_bbox_and_non_red_override_fail_closed(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "invalid.png"
            Image.new("RGB", (240, 160), "white").save(parent)
            invalid = self.manifest(cursor=False)
            invalid["annotations"][0]["bbox"]["x"] = 230
            with Image.open(parent) as image:
                image.save(output)
            result = annotation_pixels.verify_annotation_output(output, parent, invalid)
            self.assertEqual(result["status"], "fail")
            self.assertIn("annotation_bbox_invalid", result["reason_codes"])

            override = self.manifest(cursor=False)
            override["annotationColor"] = "#0F5B5B"
            with self.assertRaises(annotation_pixels.AnnotationGeometryError):
                with Image.open(parent) as image:
                    annotation_pixels.render_annotation_layer(image, override)

    def test_full_profile_cli_draw_and_check_are_self_contained(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "annotated.png"
            manifest_path = root / "manifest.json"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest_path.write_text(json.dumps(self.manifest(cursor=False), ensure_ascii=False), encoding="utf-8")
            script = SCRIPT_ROOT / "annotate.py"
            draw = subprocess.run(
                [sys.executable, str(script), "draw", "--image", str(parent), "--annotations", str(manifest_path), "--output", str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(draw.returncode, 0, draw.stderr)
            check = subprocess.run(
                [sys.executable, str(script), "check", "--image", str(parent), "--annotations", str(manifest_path), "--output-image", str(output), "--verify-output"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_cli_provenance_binds_stroke_and_font_and_missing_output_fails(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            parent = root / "redacted.png"
            output = root / "annotated.png"
            provenance = root / "annotated.provenance.json"
            manifest_path = root / "manifest.json"
            Image.new("RGB", (240, 160), "white").save(parent)
            manifest_path.write_text(json.dumps(self.manifest(cursor=False), ensure_ascii=False), encoding="utf-8")
            script = SCRIPT_ROOT / "annotate.py"
            draw = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "draw",
                    "--image",
                    str(parent),
                    "--annotations",
                    str(manifest_path),
                    "--output",
                    str(output),
                    "--stroke",
                    "5",
                    "--font-size",
                    "30",
                    "--provenance-output",
                    str(provenance),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(draw.returncode, 0, draw.stderr)
            provenance_payload = json.loads(provenance.read_text(encoding="utf-8"))
            self.assertEqual(provenance_payload["drawingInputs"]["stroke"], 5)
            self.assertEqual(provenance_payload["drawingInputs"]["font_size"], 30)

            check = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "check",
                    "--image",
                    str(parent),
                    "--annotations",
                    str(manifest_path),
                    "--stroke",
                    "5",
                    "--font-size",
                    "30",
                    "--provenance",
                    str(provenance),
                    "--verify-output",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(check.returncode, 0, check.stderr)

            wrong_inputs = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "check",
                    "--image",
                    str(parent),
                    "--annotations",
                    str(manifest_path),
                    "--stroke",
                    "3",
                    "--font-size",
                    "26",
                    "--provenance",
                    str(provenance),
                    "--verify-output",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertNotEqual(wrong_inputs.returncode, 0)
            self.assertIn("drawing inputs do not match manifest", wrong_inputs.stderr)

            missing = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "check",
                    "--image",
                    str(parent),
                    "--annotations",
                    str(manifest_path),
                    "--output-image",
                    str(root / "missing.png"),
                    "--verify-output",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("annotation_output_missing", missing.stderr)

    def test_manifest_validator_forwards_annotation_provenance_options(self) -> None:
        with self.workspace() as directory:
            root = Path(directory)
            raw = root / "raw.png"
            parent = root / "redacted.png"
            output = root / "annotated.png"
            provenance_path = root / "annotation-provenance.json"
            manifest_path = root / "manifest.json"
            Image.new("RGB", (240, 160), "white").save(raw)
            Image.new("RGB", (240, 160), "white").save(parent)
            parent_copy = Image.open(parent).convert("RGB")
            manifest = self.manifest(cursor=False)
            manifest.update(
                {
                    "schema_version": 1,
                    "sourceImage": "redacted.png",
                    "redactedImage": "redacted.png",
                    "annotatedImage": "annotated.png",
                    "sourceSha256": annotation_pixels.sha256(parent),
                    "captureKind": "detail",
                    "sourceKind": "captured",
                    "captureState": {"id": "annotation-state", "rawSha256": annotation_pixels.sha256(parent)},
                    "reviewStatus": "checked",
                    "redactions": [],
                    "noSensitiveDataReason": "synthetic test image",
                    "protectedAreas": [],
                }
            )
            manifest["annotations"][0]["source"] = "dom"
            rendered, _ = annotation_pixels.render_annotation_layer(parent_copy, manifest, stroke=5, font_size=30)
            rendered.save(output, format="PNG")
            parent_copy.close()
            manifest["redactedSha256"] = annotation_pixels.sha256(parent)
            manifest["annotatedSha256"] = annotation_pixels.sha256(output)
            manifest["annotationProvenance"] = provenance_path.name
            provenance_payload = {
                "parentSha256": annotation_pixels.sha256(parent),
                "outputSha256": annotation_pixels.sha256(output),
                "drawingInputs": annotation_pixels.annotation_input_payload(manifest, stroke=5, font_size=30),
                "drawingInputSha256": annotation_pixels.annotation_input_sha256(manifest, stroke=5, font_size=30),
            }
            provenance_path.write_text(json.dumps(provenance_payload, ensure_ascii=False), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            report = validator.validate_manifest(manifest_path, verify_annotation_output=True)

            self.assertEqual(report["annotation_output"]["status"], "pass")
            self.assertNotIn("does_not_read_image_pixels_or_ocr", report["limitations"])
            self.assertIn(
                "reads_expected_annotation_marker_pixels_only_no_ocr_or_semantic_review",
                report["limitations"],
            )


if __name__ == "__main__":
    unittest.main()
