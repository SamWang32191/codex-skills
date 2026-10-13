#!/usr/bin/env python3
"""Parent-bound pixel checks for screenshot annotations.

The annotation layer is deliberately deterministic: frames, badges and
cursors use ``#D64545`` (RGB ``214, 69, 69``).  Verification re-renders that
layer over the supplied redacted parent and compares the expected marker
cores in their manifest regions.  It never accepts a global count of red
pixels, and it never treats a geometry/color result as semantic approval of a
control target.

This module is self-contained so the full profile can run without importing
the lite profile or any Word/LibreOffice runtime.  A non-red color override is
unsupported and fails closed; callers that need a different palette must add
an explicitly reviewed, profile-specific renderer and evidence contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - bundled runtime supplies Pillow
    Image = None  # type: ignore[assignment,misc]
    ImageDraw = None  # type: ignore[assignment,misc]
    ImageFont = None  # type: ignore[assignment,misc]


ANNOTATION_RED = (214, 69, 69)
DOCUMENT_TEAL = (15, 91, 91)
DEFAULT_STROKE = 3
DEFAULT_FONT_SIZE = 26
DEFAULT_TOLERANCE = 42
MIN_RED_RATIO = 0.80


class AnnotationGeometryError(ValueError):
    """Raised when a manifest marker cannot be rendered without clipping."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def sha256(path: str | Path) -> str | None:
    """Return the file digest, or ``None`` when the file cannot be read."""

    return _sha256(Path(path).expanduser().resolve())


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _is_hash(value: Any) -> bool:
    if not isinstance(value, str) or len(value.strip()) != 64:
        return False
    try:
        int(value.strip(), 16)
    except ValueError:
        return False
    return True


def _near(pixel: tuple[int, ...], expected: tuple[int, int, int], tolerance: int) -> bool:
    if len(pixel) < 3:
        return False
    return max(abs(int(pixel[index]) - expected[index]) for index in range(3)) <= tolerance


def _pixel_changed(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    return left[:3] != right[:3]


def _as_rgb(image: Any) -> Any:
    if Image is None:
        raise AnnotationGeometryError("annotation_pixels_unavailable")
    return image.convert("RGB")


def _size_mapping(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    width, height = value.get("width"), value.get("height")
    if not _is_number(width) or not _is_number(height):
        return None
    width_float, height_float = float(width), float(height)
    if width_float <= 0 or height_float <= 0:
        return None
    return width_float, height_float


def _scale_mapping(value: Any) -> tuple[float, float] | None:
    if _is_number(value):
        scale = float(value)
        return (scale, scale) if scale > 0 else None
    if not isinstance(value, Mapping):
        return None
    x, y = value.get("x"), value.get("y")
    if not _is_number(x) or not _is_number(y):
        return None
    x_float, y_float = float(x), float(y)
    if x_float <= 0 or y_float <= 0:
        return None
    return x_float, y_float


def _resolve_scale(manifest: Mapping[str, Any], image_size: tuple[int, int]) -> tuple[float, float, str]:
    """Resolve an explicit annotation scale, with a safe size-derived fallback.

    Bboxes normally already use PNG pixels and therefore have a scale of
    ``1,1``.  A manifest may explicitly provide ``annotationScale`` or
    ``renderScale`` (a number or ``{"x", "y"}``), or a calibrated
    ``coordinateTransform.scale``.  When only ``originalImageSize`` is
    present, derive a scale if every bbox fits that declared source space;
    this supports high-DPI/resize exports without guessing a transform.
    """

    for key in ("annotationScale", "renderScale"):
        if key in manifest:
            value = _scale_mapping(manifest.get(key))
            if value is None:
                raise AnnotationGeometryError("annotation_scale_invalid")
            return value[0], value[1], key
    transform = manifest.get("coordinateTransform")
    if isinstance(transform, Mapping) and "scale" in transform:
        value = _scale_mapping(transform.get("scale"))
        if value is None:
            raise AnnotationGeometryError("annotation_scale_invalid")
        return value[0], value[1], "coordinateTransform.scale"

    declared = _size_mapping(manifest.get("originalImageSize"))
    if declared is not None and (not math.isclose(declared[0], image_size[0]) or not math.isclose(declared[1], image_size[1])):
        annotations = manifest.get("annotations")
        if isinstance(annotations, list):
            fits_source = True
            for item in annotations:
                if not isinstance(item, Mapping):
                    fits_source = False
                    break
                box = item.get("bbox")
                if not isinstance(box, Mapping):
                    fits_source = False
                    break
                values = [box.get(name) for name in ("x", "y", "width", "height")]
                if not all(_is_number(value) for value in values):
                    fits_source = False
                    break
                x, y, width, height = (float(value) for value in values)
                if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > declared[0] + 1e-6 or y + height > declared[1] + 1e-6:
                    fits_source = False
                    break
            if fits_source:
                return image_size[0] / declared[0], image_size[1] / declared[1], "originalImageSize"
    return 1.0, 1.0, "png-pixels"


def _raw_bbox(item: Mapping[str, Any]) -> tuple[float, float, float, float]:
    value = item.get("bbox")
    if not isinstance(value, Mapping):
        raise AnnotationGeometryError("annotation_bbox_invalid")
    values = [value.get(name) for name in ("x", "y", "width", "height")]
    if not all(_is_number(item_value) for item_value in values):
        raise AnnotationGeometryError("annotation_bbox_invalid")
    x, y, width, height = (float(item_value) for item_value in values)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise AnnotationGeometryError("annotation_bbox_invalid")
    return x, y, width, height


def _box(item: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    """Compatibility parser for callers that only need a bounded integer box."""

    try:
        x, y, width, height = _raw_bbox(item)
    except AnnotationGeometryError:
        return None
    rounded = tuple(round(value) for value in (x, y, width, height))
    if rounded[2] <= 0 or rounded[3] <= 0:
        return None
    return rounded  # type: ignore[return-value]


def _stroke_points(
    box: tuple[int, int, int, int], stroke: int, width: int, height: int
) -> list[tuple[int, int]]:
    """Return un-clipped frame core points for legacy sampling callers."""

    x, y, box_width, box_height = box
    if stroke <= 0 or x < 0 or y < 0 or box_width <= 0 or box_height <= 0:
        return []
    if x + box_width >= width or y + box_height >= height:
        return []
    inset = max(0, stroke // 2)
    points: set[tuple[int, int]] = set()
    for offset in range(box_width + 1):
        points.add((x + offset, y + inset))
        points.add((x + offset, y + box_height - inset))
    for offset in range(box_height + 1):
        points.add((x + inset, y + offset))
        points.add((x + box_width - inset, y + offset))
    return sorted(points)


def _scaled_bbox(
    item: Mapping[str, Any],
    image_size: tuple[int, int],
    scale: tuple[float, float],
    manifest: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    raw_x, raw_y, raw_width, raw_height = _raw_bbox(item)
    declared = _size_mapping(manifest.get("originalImageSize"))
    source_width, source_height = declared if declared is not None else image_size
    if raw_x + raw_width > source_width + 1e-6 or raw_y + raw_height > source_height + 1e-6:
        raise AnnotationGeometryError("annotation_bbox_invalid")
    x = raw_x * scale[0]
    y = raw_y * scale[1]
    right = (raw_x + raw_width) * scale[0]
    bottom = (raw_y + raw_height) * scale[1]
    x0, y0, x1, y1 = (round(value) for value in (x, y, right, bottom))
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0 or x1 > image_size[0] or y1 > image_size[1]:
        raise AnnotationGeometryError("annotation_bbox_invalid")
    return x0, y0, x1 - x0, y1 - y0


def _badge_point(spec: Any) -> tuple[float, float] | None:
    if not isinstance(spec, Mapping):
        return None
    candidate = spec.get("position") if isinstance(spec.get("position"), Mapping) else spec
    if not isinstance(candidate, Mapping) or not {"x", "y"} <= set(candidate):
        return None
    values = (candidate.get("x"), candidate.get("y"))
    if not all(_is_number(value) for value in values):
        return None
    return float(values[0]), float(values[1])


def _badge_anchor(spec: Any) -> str | None:
    if not isinstance(spec, Mapping):
        return None
    value = spec.get("anchor", spec.get("placement", spec.get("position")))
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace("_", "-")
    return normalized if normalized in {"top-left", "top-right", "bottom-left", "bottom-right"} else None


def _badge_offset(spec: Any) -> tuple[float, float] | None:
    if not isinstance(spec, Mapping) or spec.get("offset") is None:
        return (0.0, 0.0)
    value = spec.get("offset")
    if not isinstance(value, Mapping) or not {"x", "y"} <= set(value):
        return None
    if not all(_is_number(value.get(key)) for key in ("x", "y")):
        return None
    return float(value["x"]), float(value["y"])


def badge_box(
    bbox_x: int,
    bbox_y: int,
    badge_w: int,
    badge_h: int,
    img_w: int,
    img_h: int,
    *,
    bbox_width: int = 0,
    bbox_height: int = 0,
    badge_spec: Any = None,
) -> tuple[int, int, int, int] | None:
    """Resolve a bounded badge rectangle without silently clipping it."""

    gap = 4
    point = _badge_point(badge_spec)
    offset = _badge_offset(badge_spec)
    if offset is None:
        return None
    if point is not None:
        x0, y0 = point[0] + offset[0], point[1] + offset[1]
        if x0 < 0 or y0 < 0 or x0 + badge_w > img_w or y0 + badge_h > img_h:
            return None
        return round(x0), round(y0), badge_w, badge_h
    if isinstance(badge_spec, Mapping) and ({"x", "y"} <= set(badge_spec) or isinstance(badge_spec.get("position"), Mapping)):
        return None

    anchor = _badge_anchor(badge_spec)
    if anchor is None and badge_spec is not None:
        if not isinstance(badge_spec, Mapping) or any(
            key in badge_spec for key in ("anchor", "placement", "position", "offset")
        ):
            return None
    if anchor == "top-right":
        x0, y0 = bbox_x + bbox_width + gap, bbox_y - gap - badge_h
    elif anchor == "bottom-left":
        x0, y0 = bbox_x - gap - badge_w, bbox_y + bbox_height + gap
    elif anchor == "bottom-right":
        x0, y0 = bbox_x + bbox_width + gap, bbox_y + bbox_height + gap
    else:
        x0, y0 = bbox_x - gap - badge_w, bbox_y - gap - badge_h
    x0 += offset[0]
    y0 += offset[1]
    if anchor is not None and (x0 < 0 or y0 < 0 or x0 + badge_w > img_w or y0 + badge_h > img_h):
        x0, y0 = bbox_x + gap, bbox_y + gap
        if x0 + badge_w > img_w:
            x0 = bbox_x + gap - badge_w
        if y0 + badge_h > img_h:
            y0 = bbox_y + gap - badge_h
    elif anchor is None and badge_spec is None and (x0 < 0 or y0 < 0):
        x0, y0 = bbox_x + gap, bbox_y + gap
        if x0 + badge_w > img_w:
            x0 = bbox_x + gap - badge_w
        if y0 + badge_h > img_h:
            y0 = bbox_y + gap - badge_h
    if x0 < 0 or y0 < 0 or x0 + badge_w > img_w or y0 + badge_h > img_h:
        return None
    return round(x0), round(y0), badge_w, badge_h


def _scaled_cursor(
    item: Mapping[str, Any], image_size: tuple[int, int], scale: tuple[float, float], manifest: Mapping[str, Any]
) -> tuple[int, int] | None:
    value = item.get("cursor")
    if value is None:
        return None
    if not isinstance(value, Mapping) or not all(_is_number(value.get(key)) for key in ("x", "y")):
        raise AnnotationGeometryError("annotation_cursor_invalid")
    declared = _size_mapping(manifest.get("originalImageSize"))
    source_width, source_height = declared if declared is not None else image_size
    x, y = float(value["x"]), float(value["y"])
    if x < 0 or y < 0 or x >= source_width or y >= source_height:
        raise AnnotationGeometryError("annotation_cursor_invalid")
    point = round(x * scale[0]), round(y * scale[1])
    if not (0 <= point[0] < image_size[0] and 0 <= point[1] < image_size[1]):
        raise AnnotationGeometryError("annotation_cursor_invalid")
    return point


def _draw_cursor(draw: Any, cursor: tuple[int, int], target: tuple[int, int, int, int], *, color: tuple[int, int, int], outline: bool) -> None:
    cx, cy = cursor
    x, y, width, height = target
    tx = min(max(cx, x), x + width)
    ty = min(max(cy, y), y + height)
    if (cx, cy) == (tx, ty):
        return
    length = 26
    angle = math.atan2(ty - cy, tx - cx)
    tip = (tx, ty)
    base_x = tx - length * math.cos(angle)
    base_y = ty - length * math.sin(angle)
    normal = math.pi / 2
    wing = 7
    left = (base_x - wing * math.cos(angle + normal), base_y - wing * math.sin(angle + normal))
    right = (base_x - wing * math.cos(angle - normal), base_y - wing * math.sin(angle - normal))
    if outline:
        draw.line([cx, cy, base_x, base_y], fill=(255, 255, 255), width=5)
        draw.polygon([tip, left, right], fill=(255, 255, 255))
    draw.line([cx, cy, base_x, base_y], fill=color, width=3)
    draw.polygon([tip, left, right], fill=color)


def _font_kwargs(font_size: int) -> dict[str, Any]:
    if ImageFont is not None and hasattr(ImageFont, "load_default"):
        try:
            return {"font": ImageFont.truetype("DejaVuSans.ttf", font_size)}
        except (OSError, IOError):
            pass
    return {"font_size": font_size}


def _draw_badge(draw: Any, badge: tuple[int, int, int, int], number: str, font_size: int) -> None:
    bx, by, bw, bh = badge
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4, fill=ANNOTATION_RED)
    kwargs = _font_kwargs(font_size)
    try:
        draw.text((bx + bw / 2, by + bh / 2), number, fill=(255, 255, 255), anchor="mm", **kwargs)
    except TypeError:
        draw.text((bx + 2, by + 2), number, fill=(255, 255, 255), **kwargs)


def _marker_mask(size: tuple[int, int]) -> Any:
    if Image is None:
        raise AnnotationGeometryError("annotation_pixels_unavailable")
    return Image.new("L", size, 0)


def _mask_points(mask: Any) -> set[tuple[int, int]]:
    width, height = mask.size
    pixels = mask.load()
    return {(x, y) for y in range(height) for x in range(width) if pixels[x, y]}


def _marker_geometry(
    item: Mapping[str, Any],
    index: int,
    manifest: Mapping[str, Any],
    image_size: tuple[int, int],
    scale: tuple[float, float],
    stroke: int,
    font_size: int,
) -> dict[str, Any]:
    bbox = _scaled_bbox(item, image_size, scale, manifest)
    border = max(3, math.ceil(font_size * 0.16))
    badge_width = font_size + 2 * border
    badge_height = font_size + 2 * border
    badge = badge_box(
        bbox[0], bbox[1], badge_width, badge_height, image_size[0], image_size[1],
        bbox_width=bbox[2], bbox_height=bbox[3],
        badge_spec=item.get("badgePosition", item.get("badge")),
    )
    if badge is None:
        raise AnnotationGeometryError("annotation_badge_invalid")
    cursor = _scaled_cursor(item, image_size, scale, manifest)
    return {"index": index, "id": str(item.get("id", "")), "bbox": bbox, "badge": badge, "cursor": cursor}


def _color_override_error(manifest: Mapping[str, Any], item: Mapping[str, Any]) -> str | None:
    values: list[Any] = []
    for source in (manifest, item):
        for key in ("annotationColor", "annotation_color", "strokeColor", "badgeColor", "cursorColor"):
            if key in source:
                values.append(source.get(key))
    for value in values:
        if isinstance(value, str):
            normalized = value.strip().lstrip("#").casefold()
            if normalized == "d64545":
                continue
        elif isinstance(value, (list, tuple)) and len(value) == 3 and tuple(value) == ANNOTATION_RED:
            continue
        return "annotation_color_override_unsupported"
    return None


def color_override_errors(manifest: Mapping[str, Any]) -> list[str]:
    """Return fail-closed errors for unsupported non-red palette overrides."""

    errors: list[str] = []
    annotations = manifest.get("annotations") if isinstance(manifest, Mapping) else None
    if not isinstance(annotations, list):
        return errors
    for item in annotations:
        if isinstance(item, Mapping):
            error = _color_override_error(manifest, item)
            if error:
                errors.append(error)
    if not annotations:
        error = _color_override_error(manifest, {})
        if error:
            errors.append(error)
    return sorted(set(errors))


def render_annotation_layer(
    parent: Any,
    manifest: Mapping[str, Any],
    *,
    stroke: int = DEFAULT_STROKE,
    font_size: int = DEFAULT_FONT_SIZE,
) -> tuple[Any, list[dict[str, Any]]]:
    """Render the expected annotation output and marker-core coordinates."""

    if Image is None or ImageDraw is None:
        raise AnnotationGeometryError("annotation_pixels_unavailable")
    if not isinstance(stroke, int) or isinstance(stroke, bool) or stroke <= 0:
        raise AnnotationGeometryError("annotation_stroke_invalid")
    if not isinstance(font_size, int) or isinstance(font_size, bool) or font_size <= 0:
        raise AnnotationGeometryError("annotation_font_size_invalid")
    annotations = manifest.get("annotations") if isinstance(manifest, Mapping) else None
    if not isinstance(annotations, list) or not annotations:
        raise AnnotationGeometryError("annotation_manifest_empty")
    image = _as_rgb(parent).copy()
    image.info.clear()
    size = image.size
    scale_x, scale_y, scale_source = _resolve_scale(manifest, size)
    effective_stroke = max(1, round(stroke * ((scale_x + scale_y) / 2)))
    records: list[dict[str, Any]] = []
    draw = ImageDraw.Draw(image)
    for index, raw_item in enumerate(annotations):
        if not isinstance(raw_item, Mapping):
            raise AnnotationGeometryError("annotation_item_invalid")
        color_error = _color_override_error(manifest, raw_item)
        if color_error:
            raise AnnotationGeometryError(color_error)
        geometry = _marker_geometry(raw_item, index, manifest, size, (scale_x, scale_y), effective_stroke, font_size)
        frame_mask = _marker_mask(size)
        frame_mask_draw = ImageDraw.Draw(frame_mask)
        x, y, width, height = geometry["bbox"]
        draw.rectangle([x, y, x + width, y + height], outline=ANNOTATION_RED, width=effective_stroke)
        frame_mask_draw.rectangle([x, y, x + width, y + height], outline=255, width=effective_stroke)

        cursor = geometry["cursor"]
        cursor_mask = _marker_mask(size)
        cursor_mask_draw = ImageDraw.Draw(cursor_mask)
        if cursor is not None:
            _draw_cursor(draw, cursor, geometry["bbox"], color=ANNOTATION_RED, outline=True)
            _draw_cursor(cursor_mask_draw, cursor, geometry["bbox"], color=255, outline=False)

        badge_mask = _marker_mask(size)
        badge_mask_draw = ImageDraw.Draw(badge_mask)
        bx, by, bw, bh = geometry["badge"]
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4, fill=ANNOTATION_RED)
        badge_mask_draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4, fill=255)
        _draw_badge(draw, geometry["badge"], str(raw_item.get("id", "")), font_size)

        components: dict[str, dict[str, Any]] = {}
        for name, mask in (("frame", frame_mask), ("badge", badge_mask), ("cursor", cursor_mask)):
            all_points = _mask_points(mask)
            expected_red = {point for point in all_points if _near(image.getpixel(point), ANNOTATION_RED, 2)}
            components[name] = {"mask": all_points, "expected_red": expected_red}
        geometry["components"] = components
        geometry["scale"] = {"x": scale_x, "y": scale_y, "source": scale_source}
        records.append(geometry)
    return image, records


def _load_provenance(value: Mapping[str, Any] | str | Path | None) -> tuple[Mapping[str, Any] | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, Mapping):
        return value, None
    try:
        payload = json.loads(Path(value).expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "annotation_provenance_unreadable"
    return (payload, None) if isinstance(payload, Mapping) else (None, "annotation_provenance_invalid")


def _declared_hash(manifest: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[str | None, str | None]:
    for key in keys:
        if key in manifest:
            value = manifest.get(key)
            if not _is_hash(value):
                return None, f"{key}_invalid"
            return str(value).strip().casefold(), None
    return None, None


def annotation_input_payload(
    manifest: Mapping[str, Any], *, stroke: int = DEFAULT_STROKE, font_size: int = DEFAULT_FONT_SIZE
) -> dict[str, Any]:
    """Return the canonical pixel-affecting input payload used by provenance."""

    annotations = manifest.get("annotations", [])
    values: list[dict[str, Any]] = []
    if isinstance(annotations, list):
        for item in annotations:
            if not isinstance(item, Mapping):
                values.append({"invalid": item})
                continue
            box = item.get("bbox")
            value: dict[str, Any] = {
                "id": item.get("id"),
                "bbox": {
                    key: box.get(key) for key in ("x", "y", "width", "height")
                } if isinstance(box, Mapping) else box,
            }
            cursor = item.get("cursor")
            if isinstance(cursor, Mapping):
                value["cursor"] = {key: cursor.get(key) for key in ("x", "y")}
            elif cursor is not None:
                value["cursor"] = cursor
            for key in ("badge", "badgePosition"):
                if key in item:
                    value[key] = item[key]
            values.append(value)
    else:
        values.append({"invalid": annotations})
    return {"schema_version": 1, "stroke": stroke, "font_size": font_size, "annotations": values}


def annotation_input_sha256(
    manifest: Mapping[str, Any], *, stroke: int = DEFAULT_STROKE, font_size: int = DEFAULT_FONT_SIZE
) -> str:
    payload = json.dumps(
        annotation_input_payload(manifest, stroke=stroke, font_size=font_size),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_annotation_output(
    output_path: str | Path,
    parent_path: str | Path,
    manifest: Mapping[str, Any],
    *,
    stroke: int = DEFAULT_STROKE,
    font_size: int = DEFAULT_FONT_SIZE,
    tolerance: int = DEFAULT_TOLERANCE,
    provenance: Mapping[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Verify actual marker pixels against a redacted parent and manifest."""

    output = Path(output_path).expanduser().resolve()
    parent = Path(parent_path).expanduser().resolve()
    output_hash = _sha256(output)
    parent_hash = _sha256(parent)
    result: dict[str, Any] = {
        "status": "blocked",
        "semantic_review": "not_performed",
        "geometry_status": "blocked",
        "color_status": "blocked",
        "output_sha256": output_hash,
        "parent_sha256": parent_hash,
        "annotations": [],
        "reason_codes": [],
    }
    reasons: list[str] = []
    if Image is None:
        reasons.append("annotation_pixels_unavailable")
        result["reason_codes"] = reasons
        return result
    if not output.is_file() or not parent.is_file():
        reasons.append("annotation_output_missing")
        result["reason_codes"] = reasons
        return result
    try:
        with Image.open(output) as output_image, Image.open(parent) as parent_image:
            output_format, parent_format = output_image.format, parent_image.format
            if output_format != "PNG" or parent_format != "PNG":
                reasons.append("annotation_output_not_png")
            actual = output_image.convert("RGB")
            source = parent_image.convert("RGB")
            if actual.size != source.size:
                reasons.append("annotation_output_dimensions_mismatch")

            declared_parent, parent_error = _declared_hash(manifest, ("redactedSha256", "parentSha256"))
            if parent_error:
                reasons.append("annotation_parent_hash_invalid")
            elif declared_parent is not None and parent_hash is not None and declared_parent != parent_hash.casefold():
                reasons.append("annotation_parent_hash_mismatch")
            declared_output, output_error = _declared_hash(manifest, ("annotatedSha256", "outputSha256"))
            if output_error:
                reasons.append("annotation_output_hash_invalid")
            elif declared_output is not None and output_hash is not None and declared_output != output_hash.casefold():
                reasons.append("annotation_output_hash_mismatch")

            provenance_payload, provenance_error = _load_provenance(provenance)
            if provenance_error:
                reasons.append(provenance_error)
            if provenance_payload is not None:
                provenance_parent = provenance_payload.get("parentSha256", provenance_payload.get("redactedSha256"))
                provenance_output = provenance_payload.get("outputSha256", provenance_payload.get("annotatedSha256"))
                if not _is_hash(provenance_parent):
                    reasons.append("annotation_provenance_parent_hash_invalid")
                elif parent_hash is not None and str(provenance_parent).casefold() != parent_hash.casefold():
                    reasons.append("annotation_provenance_parent_hash_mismatch")
                if not _is_hash(provenance_output):
                    reasons.append("annotation_provenance_output_hash_invalid")
                elif output_hash is not None and str(provenance_output).casefold() != output_hash.casefold():
                    reasons.append("annotation_provenance_output_hash_mismatch")
                expected_inputs = annotation_input_payload(manifest, stroke=stroke, font_size=font_size)
                declared_inputs = provenance_payload.get("drawingInputs")
                if declared_inputs is not None and declared_inputs != expected_inputs:
                    reasons.append("annotation_provenance_input_mismatch")
                declared_input_hash = provenance_payload.get(
                    "drawingInputSha256", provenance_payload.get("inputSha256")
                )
                if declared_input_hash is not None:
                    if not _is_hash(declared_input_hash):
                        reasons.append("annotation_provenance_input_hash_invalid")
                    elif str(declared_input_hash).casefold() != annotation_input_sha256(
                        manifest, stroke=stroke, font_size=font_size
                    ).casefold():
                        reasons.append("annotation_provenance_input_hash_mismatch")

            if actual.size == source.size and output_format == "PNG" and parent_format == "PNG":
                try:
                    expected, markers = render_annotation_layer(source, manifest, stroke=stroke, font_size=font_size)
                except AnnotationGeometryError as error:
                    reasons.append(error.code)
                else:
                    result["geometry_status"] = "pass"
                    marker_changed_total = 0
                    for marker in markers:
                        component_results: list[dict[str, Any]] = []
                        marker_expected_points: set[tuple[int, int]] = set()
                        for component_name in ("frame", "badge", "cursor"):
                            component = marker["components"][component_name]
                            expected_points = component["expected_red"]
                            if not expected_points:
                                if component_name == "cursor" and marker.get("cursor") is None:
                                    continue
                                reasons.append("annotation_marker_expected_core_missing")
                                component_results.append({
                                    "region": component_name,
                                    "status": "fail",
                                    "expected_red_pixels": 0,
                                    "red_core_hits": 0,
                                    "red_ratio": 0.0,
                                    "teal_core_hits": 0,
                                    "changed_pixels": 0,
                                })
                                continue
                            marker_expected_points.update(expected_points)
                            red_hits = 0
                            teal_hits = 0
                            changed_hits = 0
                            expected_match_hits = 0
                            for point in expected_points:
                                actual_pixel = actual.getpixel(point)
                                expected_pixel = expected.getpixel(point)
                                source_pixel = source.getpixel(point)
                                if _near(actual_pixel, ANNOTATION_RED, tolerance):
                                    red_hits += 1
                                if _near(actual_pixel, DOCUMENT_TEAL, tolerance):
                                    teal_hits += 1
                                if _pixel_changed(actual_pixel, source_pixel):
                                    changed_hits += 1
                                if _near(actual_pixel, expected_pixel, tolerance):
                                    expected_match_hits += 1
                            expected_count = len(expected_points)
                            red_ratio = red_hits / expected_count
                            match_ratio = expected_match_hits / expected_count
                            component_ok = red_ratio >= MIN_RED_RATIO and match_ratio >= MIN_RED_RATIO
                            if not component_ok:
                                reasons.append("annotation_color_missing")
                                if teal_hits >= max(2, math.ceil(expected_count * 0.12)):
                                    reasons.append("annotation_color_teal")
                                if red_hits and red_ratio < MIN_RED_RATIO:
                                    reasons.append("annotation_color_partial")
                            component_results.append({
                                "region": component_name,
                                "status": "pass" if component_ok else "fail",
                                "expected_red_pixels": expected_count,
                                "red_core_hits": red_hits,
                                "red_ratio": round(red_ratio, 6),
                                "teal_core_hits": teal_hits,
                                "changed_pixels": changed_hits,
                                "expected_match_ratio": round(match_ratio, 6),
                            })
                        marker_changed_points = {
                            point
                            for point in marker_expected_points
                            if _pixel_changed(actual.getpixel(point), source.getpixel(point))
                        }
                        marker_changed_total += len(marker_changed_points)
                        marker_ok = bool(component_results) and all(item["status"] == "pass" for item in component_results)
                        if not marker_changed_points:
                            marker_ok = False
                            reasons.append("annotation_marker_unchanged")
                        result["annotations"].append({
                            "index": marker["index"],
                            "id": marker["id"],
                            "status": "pass" if marker_ok else "fail",
                            "bbox": {
                                "x": marker["bbox"][0], "y": marker["bbox"][1],
                                "width": marker["bbox"][2], "height": marker["bbox"][3],
                            },
                            "badge": {
                                "x": marker["badge"][0], "y": marker["badge"][1],
                                "width": marker["badge"][2], "height": marker["badge"][3],
                            },
                            "cursor": marker.get("cursor"),
                            "scale": marker.get("scale"),
                            "changed_marker_pixels": len(marker_changed_points),
                            "components": component_results,
                            "region": "bbox-badge-cursor",
                        })
                    if marker_changed_total == 0:
                        reasons.append("annotation_output_unchanged")
                    if result["annotations"] and all(item["status"] == "pass" for item in result["annotations"]):
                        result["color_status"] = "pass"
    except (OSError, ValueError, RuntimeError):
        reasons.append("annotation_output_unreadable")

    unique_reasons = sorted(set(reasons))
    result["reason_codes"] = unique_reasons
    result["outputSha256"] = output_hash
    result["parentSha256"] = parent_hash
    if not unique_reasons and result["annotations"]:
        result["status"] = "pass"
    elif any(code in {"annotation_output_missing", "annotation_pixels_unavailable", "annotation_output_unreadable"} for code in unique_reasons):
        result["status"] = "blocked"
    else:
        result["status"] = "fail"
    return result


render_expected_annotations = render_annotation_layer
verify_annotations = verify_annotation_output
