#!/usr/bin/env python3
"""Validate the opt-in, hash-bound acceptance catalog for delivery reviews.

This module validates evidence references and bytes only.  It never decides
whether a UI control is semantically correct; that remains reviewer work.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_STATUSES = {"pass", "fail", "blocked", "pending", "na", "not_applicable"}


def _normal_path(value: Any) -> str:
    return value.strip().replace("\\", "/") if isinstance(value, str) else ""


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value.strip()))


def _resolve(base_dir: Path, value: Any) -> Path | None:
    if isinstance(value, Path):
        candidate = value.expanduser()
    elif isinstance(value, str) and value.strip():
        candidate = Path(value).expanduser()
    else:
        return None
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        return candidate.resolve()
    except OSError:
        return None


def _load_catalog(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "acceptance_catalog_invalid"
    if isinstance(value, Mapping) and isinstance(value.get("acceptance"), Mapping):
        value = value["acceptance"]
    if not isinstance(value, Mapping):
        return None, "acceptance_catalog_invalid"
    return value, None


def _item_summary(item: Mapping[str, Any], artifact_results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": str(item.get("id", "")),
        "applicable": item.get("applicable"),
        "status": str(item.get("status", "")).strip().casefold(),
        "reason_provided": isinstance(item.get("reason"), str) and bool(item.get("reason", "").strip()),
        "evidence_count": len(item.get("evidence", [])) if isinstance(item.get("evidence"), list) else 0,
        "actual_artifacts": artifact_results,
    }
    return summary


def validate_acceptance(
    review: Any,
    review_path: str | Path,
    reviewed_paths: set[str],
    docx_path: str | Path | None = None,
    *,
    require: bool = False,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a review acceptance object and optional item catalog.

    ``reviewed_paths`` must contain the exact normalized
    ``reviewed_files[].path`` values.  The result intentionally contains only
    structural counts, paths' basenames, scopes and hashes/statuses.
    """

    base_dir = Path(review_path).expanduser().resolve().parent
    result: dict[str, Any] = {
        "status": "not_applicable",
        "schema_version": SCHEMA_VERSION,
        "semantic_review": "not_performed",
        "items": [],
    }
    reasons: list[str] = []
    catalog: Mapping[str, Any] | None = None
    # The strengthened gate is deliberately explicit.  A caller that opts in
    # to required acceptance must also select the catalog whose IDs define the
    # complete review surface; otherwise an arbitrary self-authored list could
    # satisfy the gate.
    if require and catalog_path is None:
        reasons.append("acceptance_catalog_missing")
    if catalog_path is not None:
        catalog, catalog_error = _load_catalog(Path(catalog_path).expanduser().resolve())
        if catalog_error:
            reasons.append(catalog_error)
    raw_acceptance = review.get("acceptance") if isinstance(review, Mapping) else None
    if raw_acceptance is None and isinstance(review, Mapping):
        raw_acceptance = review.get("acceptance_items")
    if raw_acceptance is None and catalog_path is not None:
        reasons.append("acceptance_missing")
        result["status"] = "blocked"
        result["reason_codes"] = sorted(set(reasons))
        return result
    if raw_acceptance is None:
        if require:
            reasons.append("acceptance_missing")
            result["status"] = "blocked"
            result["reason_codes"] = sorted(set(reasons))
        return result
    if isinstance(raw_acceptance, list):
        raw_acceptance = {"schema_version": SCHEMA_VERSION, "items": raw_acceptance}
    if not isinstance(raw_acceptance, Mapping):
        reasons.append("acceptance_invalid")
        result["status"] = "blocked"
        result["reason_codes"] = sorted(set(reasons))
        return result
    schema = raw_acceptance.get("schema_version")
    if schema != SCHEMA_VERSION or isinstance(schema, bool):
        reasons.append("acceptance_schema_invalid")
    raw_items = raw_acceptance.get("items")
    if not isinstance(raw_items, list):
        reasons.append("acceptance_items_invalid")
        raw_items = []

    catalog_items = catalog.get("items") if isinstance(catalog, Mapping) else None
    if catalog is not None:
        catalog_schema = catalog.get("schema_version")
        if catalog_schema != SCHEMA_VERSION or isinstance(catalog_schema, bool):
            reasons.append("acceptance_catalog_schema_invalid")
        if not isinstance(catalog_items, list) or not catalog_items:
            reasons.append("acceptance_catalog_items_invalid")
            catalog_items = []

    # Keep both declarations: ``required`` controls whether the catalog row
    # must be present; ``applicability`` controls whether its outcome can pass
    # as an explicit NA.  Older catalogs omit the mode and retain fixed
    # boolean applicability.
    catalog_map: dict[str, tuple[str, bool, bool]] = {}
    for index, catalog_item in enumerate(catalog_items or []):
        if not isinstance(catalog_item, Mapping) or not isinstance(catalog_item.get("id"), str) or not catalog_item["id"].strip():
            reasons.append("acceptance_catalog_item_invalid")
            continue
        identifier = catalog_item["id"].strip()
        applicable = catalog_item.get("applicable", True)
        if not isinstance(applicable, bool):
            reasons.append("acceptance_catalog_applicability_invalid")
            continue
        mode = catalog_item.get("applicability")
        if mode is None:
            mode = "always"
        if not isinstance(mode, str) or mode.strip().casefold() not in {"always", "conditional"}:
            reasons.append("acceptance_catalog_applicability_mode_invalid")
            continue
        mode = mode.strip().casefold()
        if mode == "always" and not applicable:
            reasons.append("acceptance_catalog_applicability_invalid")
            applicable = True
        required = catalog_item.get("required", True)
        if not isinstance(required, bool):
            reasons.append("acceptance_catalog_required_invalid")
            continue
        if identifier in catalog_map:
            reasons.append("acceptance_catalog_duplicate_id")
        catalog_map[identifier] = (mode, applicable, required)

    seen: set[str] = set()
    seen_statuses: list[str] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            reasons.append("acceptance_item_invalid")
            continue
        identifier = raw_item.get("id")
        identifier = identifier.strip() if isinstance(identifier, str) else ""
        if not identifier:
            reasons.append("acceptance_item_id_missing")
            continue
        if identifier in seen:
            reasons.append("acceptance_item_duplicate_id")
        seen.add(identifier)
        applicable = raw_item.get("applicable")
        if not isinstance(applicable, bool):
            reasons.append("acceptance_item_applicability_invalid")
            applicable = True
        if catalog_map:
            if identifier not in catalog_map:
                reasons.append("acceptance_item_unknown")
            elif catalog_map[identifier][0] == "always" and applicable is not True:
                reasons.append("acceptance_item_applicability_mismatch")
        status = raw_item.get("status")
        status = status.strip().casefold() if isinstance(status, str) else ""
        seen_statuses.append(status)
        if status not in _STATUSES:
            reasons.append("acceptance_item_status_invalid")
        reason = raw_item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            reasons.append("acceptance_item_reason_missing")

        evidence = raw_item.get("evidence")
        evidence_values = evidence if isinstance(evidence, list) else []
        if not isinstance(evidence, list):
            reasons.append("acceptance_evidence_invalid")
        for evidence_value in evidence_values:
            reference = _normal_path(evidence_value)
            if not reference:
                reasons.append("acceptance_evidence_invalid")
            elif reference not in reviewed_paths:
                reasons.append("acceptance_evidence_reference_missing")
        if applicable and status == "pass" and not evidence_values:
            reasons.append("acceptance_evidence_missing")

        raw_artifacts = raw_item.get("actual_artifacts", raw_item.get("actualArtifacts"))
        if "actual_artifacts" not in raw_item and "actualArtifacts" not in raw_item:
            reasons.append("acceptance_actual_artifacts_invalid")
        artifact_values = raw_artifacts if isinstance(raw_artifacts, list) else []
        if raw_artifacts is not None and not isinstance(raw_artifacts, list):
            reasons.append("acceptance_actual_artifacts_invalid")
        if applicable and status == "pass" and not artifact_values:
            reasons.append("acceptance_actual_artifacts_missing")
        artifact_results: list[dict[str, Any]] = []
        artifact_paths: set[str] = set()
        for artifact in artifact_values:
            if not isinstance(artifact, Mapping):
                reasons.append("acceptance_actual_artifact_invalid")
                continue
            path_value = artifact.get("path")
            scope = artifact.get("scope")
            path = _resolve(base_dir, path_value)
            path_key = _normal_path(path_value)
            artifact_status = "pass"
            final_docx = _resolve(base_dir, docx_path) if docx_path is not None else None
            reviewed_keys = {_normal_path(reviewed) for reviewed in reviewed_paths}
            if path_key not in reviewed_keys and path != final_docx:
                reasons.append("acceptance_actual_artifact_unbound")
                artifact_status = "blocked"
            if path_key in artifact_paths:
                reasons.append("acceptance_actual_artifact_duplicate")
                artifact_status = "blocked"
            artifact_paths.add(path_key)
            if path is None or not path.is_file():
                reasons.append("acceptance_actual_artifact_missing")
                artifact_status = "blocked"
            declared_hash = artifact.get("sha256")
            if not _valid_hash(declared_hash):
                reasons.append("acceptance_actual_artifact_hash_invalid")
                artifact_status = "blocked"
            elif path is not None and path.is_file() and _sha256(path) != str(declared_hash).strip().lower():
                reasons.append("acceptance_actual_artifact_hash_mismatch")
                artifact_status = "blocked"
            if not isinstance(scope, str) or not scope.strip():
                reasons.append("acceptance_actual_artifact_scope_missing")
                scope = ""
                artifact_status = "blocked"
            artifact_results.append({
                "path": Path(path_value).name if isinstance(path_value, str) else "",
                "scope": scope,
                "status": artifact_status,
            })

        result["items"].append(_item_summary({**raw_item, "id": identifier, "status": status, "applicable": applicable}, artifact_results))

    if catalog_map:
        # Every catalog row must be represented.  Non-applicable rows still
        # need an explicit NA acknowledgement so the applicability decision is
        # reviewable and cannot disappear through omission.
        for identifier, (_mode, _applicable, required) in catalog_map.items():
            if required and identifier not in seen:
                reasons.append("acceptance_item_missing")

    if not raw_items:
        reasons.append("acceptance_items_empty")
    # Status is evaluated per catalog applicability.  An NA row is complete
    # when it has a reason, while pending/blocked/fail applicable work cannot
    # produce an overall pass.
    for item in result["items"]:
        status = item.get("status")
        if item.get("applicable") is False:
            if status not in {"na", "not_applicable"}:
                reasons.append("acceptance_not_applicable_status_invalid")
        elif status == "fail":
            reasons.append("acceptance_item_failed")
        elif status != "pass":
            reasons.append("acceptance_item_incomplete")
    if any(status == "fail" for status in seen_statuses):
        result["status"] = "fail"
    elif reasons:
        result["status"] = "blocked"
    else:
        result["status"] = "pass"
    if reasons:
        result["reason_codes"] = sorted(set(reasons))
    return result
