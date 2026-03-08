#!/usr/bin/env python3
"""
Extract the design pattern from a classified component segment.

Builds a structured pattern dict describing layout, grid dimensions,
item templates, content zones, and design tokens for each component type.

Module API:
    extract_component_pattern(segment, component_type, design_tokens, source_info) -> dict
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _get_text_summary(shapes, max_len=120):
    """Build a short text summary from shapes."""
    texts = []
    for shape in shapes:
        paragraphs = shape.paragraphs if hasattr(shape, "paragraphs") else []
        for para in paragraphs:
            if para.text.strip():
                texts.append(para.text.strip())
    combined = " | ".join(texts)
    if len(combined) > max_len:
        combined = combined[:max_len] + "..."
    return combined


def _detect_orientation(shapes):
    """Detect horizontal vs vertical arrangement."""
    if len(shapes) < 2:
        return "horizontal"
    # Sort by left, check if more horizontal spread than vertical
    lefts = sorted(s.left for s in shapes)
    tops = sorted(s.top for s in shapes)
    h_spread = lefts[-1] - lefts[0]
    v_spread = tops[-1] - tops[0]
    return "horizontal" if h_spread >= v_spread else "vertical"


def _detect_grid(shapes):
    """Detect grid dimensions (rows, cols) and gap between items."""
    if len(shapes) < 2:
        return {"rows": 1, "cols": 1, "gap_inches": 0}

    # Sort shapes by position
    sorted_by_top = sorted(shapes, key=lambda s: s.top)
    sorted_by_left = sorted(shapes, key=lambda s: s.left)

    # Group into rows (shapes within 0.5" vertically)
    rows = []
    current_row = [sorted_by_top[0]]
    row_top = sorted_by_top[0].top

    for shape in sorted_by_top[1:]:
        if abs(shape.top - row_top) <= 0.5:
            current_row.append(shape)
        else:
            rows.append(current_row)
            current_row = [shape]
            row_top = shape.top
    rows.append(current_row)

    n_rows = len(rows)
    n_cols = max(len(row) for row in rows) if rows else 1

    # Calculate average horizontal gap
    gaps = []
    for row in rows:
        sorted_row = sorted(row, key=lambda s: s.left)
        for i in range(len(sorted_row) - 1):
            gap = sorted_row[i + 1].left - (sorted_row[i].left + sorted_row[i].width)
            if gap > 0:
                gaps.append(gap)

    avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0

    return {"rows": n_rows, "cols": n_cols, "gap_inches": avg_gap}


def _build_content_zones(shapes):
    """Build content zone descriptions from shape paragraphs.

    Assigns relative_top and relative_height to each zone so that
    they are vertically distributed without overlap.
    """
    raw_zones = []
    for shape in shapes:
        paragraphs = shape.paragraphs if hasattr(shape, "paragraphs") else []
        if not paragraphs:
            continue

        for para in paragraphs:
            text = para.text.strip()
            if not text:
                continue

            zone = {}
            font_size = para.font_size or 12
            bold = para.bold or False

            if font_size >= 20:
                zone["role"] = "heading"
            elif font_size >= 14 and bold:
                zone["role"] = "subheading"
            elif para.bullet:
                zone["role"] = "body"
                zone["bullet"] = True
            elif len(text) <= 5 and text.replace(".", "").isdigit():
                zone["role"] = "number"
            else:
                zone["role"] = "body"

            zone["font_size"] = font_size
            if bold:
                zone["bold"] = True
            if para.alignment:
                zone["alignment"] = para.alignment

            raw_zones.append(zone)

    # Deduplicate: keep unique (role, font_size, bold) combos
    seen = set()
    zones = []
    for z in raw_zones:
        key = (
            z["role"],
            z.get("font_size"),
            z.get("bold", False),
            z.get("bullet", False),
        )
        if key not in seen:
            seen.add(key)
            zones.append(z)

    # Assign relative_top / relative_height evenly
    if not zones:
        return []

    # Give heading/number roles less height, body more
    weights = []
    for z in zones:
        if z["role"] in ("number", "heading", "subheading"):
            weights.append(1.0)
        else:
            weights.append(2.0)
    total_weight = sum(weights)

    current_top = 0.0
    for i, z in enumerate(zones):
        rel_h = round(weights[i] / total_weight, 3)
        z["relative_top"] = round(current_top, 3)
        z["relative_height"] = rel_h
        current_top += rel_h

    return zones


def _build_item_template(shapes):
    """Build an item template from the first (reference) shape in a group of similar shapes."""
    if not shapes:
        return {}

    ref = shapes[0]
    template = {
        "width": ref.width,
        "height": ref.height,
    }

    # Get shape type if available
    shape_obj = ref.shape if hasattr(ref, "shape") else None
    if shape_obj and hasattr(shape_obj, "shape_type"):
        template["shape_type"] = str(shape_obj.shape_type).split("(")[0].strip()

    # Build content zones from reference shape
    content_zones = _build_content_zones([ref])
    if content_zones:
        template["content_zones"] = content_zones

    return template


def _extract_fill_color(shape):
    """Try to extract fill color from a shape."""
    shape_obj = shape.shape if hasattr(shape, "shape") else None
    if shape_obj is None:
        return None

    try:
        fill = shape_obj.fill
        if fill and hasattr(fill, "fore_color") and fill.fore_color:
            if hasattr(fill.fore_color, "rgb") and fill.fore_color.rgb:
                return str(fill.fore_color.rgb)
            if hasattr(fill.fore_color, "theme_color") and fill.fore_color.theme_color:
                return fill.fore_color.theme_color.name
    except Exception:
        pass
    return None


def _extract_design_tokens_for_segment(shapes, global_tokens):
    """Extract segment-specific design tokens (colors used in shapes)."""
    tokens = {}

    # Get fill colors from shapes
    for i, shape in enumerate(shapes):
        fill = _extract_fill_color(shape)
        if fill:
            if i == 0:
                tokens["item_fill"] = fill
            else:
                tokens[f"fill_{i}"] = fill

    # Get text colors
    for shape in shapes:
        paragraphs = shape.paragraphs if hasattr(shape, "paragraphs") else []
        for para in paragraphs:
            if para.color:
                tokens.setdefault("text_color", para.color)
            if para.theme_color:
                tokens.setdefault("text_theme_color", para.theme_color)
            break
        if tokens:
            break

    # Include accent color from global tokens if available
    if global_tokens and "colors" in global_tokens:
        colors = global_tokens["colors"]
        if "accent1" in colors:
            tokens.setdefault("accent_color", colors["accent1"])

    return tokens


def _enrich_zones_with_llm(item_template, llm_items):
    """LLM의 text_label 정보로 기존 content_zones를 보강한다.

    LLM items의 zones에서 text_label을 추출하여
    item_template의 content_zones에 매핑한다.
    """
    zones = item_template.get("content_zones", [])
    if not zones or not llm_items:
        return

    # 첫 번째 LLM item의 zones에서 text_label 매핑 구축
    first_item = llm_items[0] if llm_items else {}
    llm_zones = first_item.get("zones", [])

    # role → text_label 매핑
    role_to_label = {}
    for lz in llm_zones:
        role = lz.get("role", "")
        label = lz.get("text_label", "")
        if role and label:
            role_to_label[role] = label

    # 기존 zones에 text_label 추가
    for zone in zones:
        role = zone.get("role", "body")
        if role in role_to_label:
            zone["text_label"] = role_to_label[role]
        else:
            zone.setdefault("text_label", "body")


def extract_component_pattern(segment, component_type, design_tokens, source_info):
    """Extract a structured design pattern from a classified segment.

    Args:
        segment: dict with zone, shapes, bounding_box from segment_slide
        component_type: str type id (e.g. "card-grid", "header")
        design_tokens: dict from extract_design_tokens (colors, fonts, slide_dimensions)
        source_info: dict with source_id, filename, slide_index

    Returns:
        dict matching the component pattern schema
    """
    shapes = segment.get("shapes", [])
    bb = segment.get("bounding_box", {})

    pattern = {}
    # LLM item_count 우선, 없으면 shape 수 사용
    pattern["item_count"] = segment.get("llm_item_count") or len(shapes)

    # Type-specific pattern extraction
    if component_type in ("card-grid", "icon-grid"):
        orientation = _detect_orientation(shapes)
        grid = _detect_grid(shapes)
        pattern["orientation"] = orientation
        pattern["grid"] = grid
        pattern["item_template"] = _build_item_template(shapes)

    elif component_type == "timeline":
        orientation = _detect_orientation(shapes)
        pattern["orientation"] = orientation
        pattern["step_count"] = len(shapes)
        # Detect connector style
        pattern["connector_style"] = "arrow"  # default
        grid = _detect_grid(shapes)
        pattern["grid"] = grid
        pattern["item_template"] = _build_item_template(shapes)

    elif component_type == "header":
        pattern["item_count"] = 1
        pattern["alignment"] = "LEFT"
        if shapes:
            paragraphs = (
                shapes[0].paragraphs if hasattr(shapes[0], "paragraphs") else []
            )
            for para in paragraphs:
                if para.alignment:
                    pattern["alignment"] = para.alignment
                break
        pattern["has_background"] = False
        for shape in shapes:
            fill = _extract_fill_color(shape)
            if fill:
                pattern["has_background"] = True
                break
        # Header item_template: full width, zone height
        pattern["grid"] = {"rows": 1, "cols": 1, "gap_inches": 0}
        pattern["item_template"] = {
            "width": bb.get("width", 12.0),
            "height": bb.get("height", 1.3),
            "shape_type": "rect",
            "content_zones": _build_content_zones(shapes),
        }

    elif component_type == "footer":
        pattern["item_count"] = 1
        pattern["alignment"] = "CENTER"
        if shapes:
            paragraphs = (
                shapes[0].paragraphs if hasattr(shapes[0], "paragraphs") else []
            )
            for para in paragraphs:
                if para.alignment:
                    pattern["alignment"] = para.alignment
                break
        pattern["grid"] = {"rows": 1, "cols": 1, "gap_inches": 0}
        pattern["item_template"] = {
            "width": bb.get("width", 12.0),
            "height": bb.get("height", 0.5),
            "shape_type": "rect",
            "content_zones": _build_content_zones(shapes),
        }

    elif component_type == "two-column":
        sorted_shapes = sorted(shapes, key=lambda s: s.left)
        if len(sorted_shapes) >= 2:
            pattern["left_width"] = sorted_shapes[0].width
            pattern["right_width"] = sorted_shapes[-1].width
            gap = sorted_shapes[-1].left - (
                sorted_shapes[0].left + sorted_shapes[0].width
            )
            pattern["gap_inches"] = round(max(0, gap), 2)

    elif component_type == "process-flow":
        pattern["orientation"] = _detect_orientation(shapes)
        pattern["step_count"] = len(shapes)
        pattern["has_connectors"] = True

    elif component_type == "org-chart":
        pattern["orientation"] = "vertical"
        pattern["item_count"] = len(shapes)

    elif component_type == "accent-bar":
        if shapes:
            pattern["width"] = shapes[0].width
            pattern["height"] = shapes[0].height
            fill = _extract_fill_color(shapes[0])
            if fill:
                pattern["fill_color"] = fill

    elif component_type == "full-page":
        pattern["item_count"] = len(shapes)

    elif component_type == "chart-area":
        pattern["chart_detected"] = True

    elif component_type == "table-layout":
        pattern["table_detected"] = True

    # 확장 6개 타입
    elif component_type == "roadmap":
        pattern["orientation"] = _detect_orientation(shapes)
        pattern["step_count"] = pattern["item_count"]
        grid = _detect_grid(shapes)
        pattern["grid"] = grid
        pattern["item_template"] = _build_item_template(shapes)

    elif component_type == "value-prop":
        pattern["orientation"] = _detect_orientation(shapes)
        grid = _detect_grid(shapes)
        pattern["grid"] = grid
        pattern["item_template"] = _build_item_template(shapes)

    elif component_type == "comparison":
        pattern["orientation"] = _detect_orientation(shapes)
        pattern["grid"] = _detect_grid(shapes)
        pattern["item_template"] = _build_item_template(shapes)

    elif component_type == "hero":
        pattern["item_count"] = 1
        pattern["grid"] = {"rows": 1, "cols": 1, "gap_inches": 0}
        pattern["item_template"] = {
            "width": bb.get("width", 12.0),
            "height": bb.get("height", 4.0),
            "shape_type": "rect",
            "content_zones": _build_content_zones(shapes),
        }

    elif component_type == "kpi-dashboard":
        pattern["orientation"] = _detect_orientation(shapes)
        grid = _detect_grid(shapes)
        pattern["grid"] = grid
        pattern["item_template"] = _build_item_template(shapes)

    elif component_type == "checklist":
        pattern["orientation"] = "vertical"
        pattern["grid"] = {"rows": pattern["item_count"], "cols": 1, "gap_inches": 0.1}
        pattern["item_template"] = _build_item_template(shapes)

    # LLM이 제공한 zones+text_label로 content_zones 보강
    llm_items = segment.get("llm_items", [])
    if llm_items and "item_template" in pattern:
        _enrich_zones_with_llm(pattern.get("item_template", {}), llm_items)

    # Build section types from text content
    texts = _get_text_summary(shapes)

    # Segment-level design tokens
    seg_tokens = _extract_design_tokens_for_segment(shapes, design_tokens)

    # LLM 메타데이터
    design_intent = segment.get("llm_design_intent", [])
    search_tags = segment.get("llm_search_tags", [])
    semantic_summary = segment.get("llm_semantic_summary", "")
    parent_component_id = None  # 저장 시 별도 매핑 필요

    # 관계성 정보 (슬라이드 레벨)
    relationships = segment.get("_slide_relationships", [])
    slide_intent = segment.get("_slide_intent", "")

    result = {
        "id": None,  # Will be set by ingest_pptx.py
        "type": component_type,
        "parent_component_id": parent_component_id,
        "source": {
            "source_id": source_info.get("source_id", ""),
            "filename": source_info.get("filename", ""),
            "slide_index": source_info.get("slide_index", 0),
            "region": bb,
        },
        "pattern": pattern,
        "design_tokens": seg_tokens,
        "design_intent": design_intent,
        "relationships": relationships,
        "context": {
            "section_types": [component_type],
            "text_summary": semantic_summary or texts,
            "search_tags": search_tags,
            "slide_intent": slide_intent,
            "use_count": 0,
            "quality_rating": None,
        },
        "thumbnail_path": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return result


def main():
    """CLI demo: extract patterns from all segments in a PPTX file."""
    parser = argparse.ArgumentParser(
        description="Extract component patterns from a PPTX file."
    )
    parser.add_argument("input", help="Input PowerPoint file (.pptx)")
    args = parser.parse_args()

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

    from inventory import extract_text_inventory, ShapeData
    from segment_slide import segment_slide
    from classify_component import classify_component
    from extract_design_tokens import extract_design_tokens
    from pptx import Presentation

    pptx_path = Path(args.input)
    if not pptx_path.exists():
        print(f"Error: File not found: {pptx_path}")
        sys.exit(1)

    config_path = PROJECT_ROOT / "config" / "component-types.json"
    with open(config_path, "r", encoding="utf-8") as f:
        component_types = json.load(f)["types"]

    tokens = extract_design_tokens(pptx_path)
    prs = Presentation(str(pptx_path))
    slide_width = round(ShapeData.emu_to_inches(prs.slide_width), 2)
    slide_height = round(ShapeData.emu_to_inches(prs.slide_height), 2)

    inventory = extract_text_inventory(pptx_path, prs)
    source_info = {
        "source_id": pptx_path.stem.lower().replace(" ", "-"),
        "filename": pptx_path.name,
    }

    for slide_id, shapes_dict in inventory.items():
        slide_idx = int(slide_id.split("-")[1])
        source_info["slide_index"] = slide_idx

        shapes_list = list(shapes_dict.values())
        segments = segment_slide(shapes_list, slide_width, slide_height)

        print(f"\n=== {slide_id} ===")
        for i, seg in enumerate(segments):
            comp_type = classify_component(
                seg, component_types, slide_width, slide_height
            )
            pattern = extract_component_pattern(seg, comp_type, tokens, source_info)
            print(
                f"  {comp_type}: {json.dumps(pattern['pattern'], indent=2, ensure_ascii=False)}"
            )


if __name__ == "__main__":
    main()
