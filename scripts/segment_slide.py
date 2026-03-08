#!/usr/bin/env python3
"""
Segment a slide's shapes into spatial groups (component regions).

Separates shapes into header/body/footer zones, then groups by spatial
proximity, size similarity, and grid patterns.

Module API:
    segment_slide(shapes, slide_width, slide_height) -> list[dict]
"""

import argparse
import sys
from pathlib import Path

# Zone thresholds (relative to slide height)
HEADER_ZONE_RATIO = 0.25
FOOTER_ZONE_RATIO = 0.12

# Grid detection
SIZE_TOLERANCE = 0.15  # 15% tolerance for "similar size"
MIN_GRID_SHAPES = 3

# Decoration detection
NARROW_THRESHOLD_RATIO = 0.03  # < 3% of slide dimension = narrow
SMALL_AREA_THRESHOLD = 0.02  # < 2% of slide area = small (possible logo/icon)


def _bounding_box(shapes):
    """Calculate bounding box for a list of shapes."""
    if not shapes:
        return {"left": 0, "top": 0, "width": 0, "height": 0}

    min_left = min(s.left for s in shapes)
    min_top = min(s.top for s in shapes)
    max_right = max(s.left + s.width for s in shapes)
    max_bottom = max(s.top + s.height for s in shapes)

    return {
        "left": round(min_left, 2),
        "top": round(min_top, 2),
        "width": round(max_right - min_left, 2),
        "height": round(max_bottom - min_top, 2),
    }


def _shapes_similar_size(s1, s2, tolerance=SIZE_TOLERANCE):
    """Check if two shapes have similar width and height within tolerance."""
    if s1.width == 0 or s1.height == 0 or s2.width == 0 or s2.height == 0:
        return False
    w_ratio = abs(s1.width - s2.width) / max(s1.width, s2.width)
    h_ratio = abs(s1.height - s2.height) / max(s1.height, s2.height)
    return w_ratio <= tolerance and h_ratio <= tolerance


def _is_narrow_shape(shape, slide_width, slide_height):
    """Check if shape is a narrow decoration (accent bar)."""
    # Very narrow relative to slide
    narrow_w = shape.width < slide_width * NARROW_THRESHOLD_RATIO
    narrow_h = shape.height < slide_height * NARROW_THRESHOLD_RATIO
    return narrow_w or narrow_h


def _is_decoration(shape, slide_width, slide_height):
    """Check if shape is a decoration element (accent bar, logo, etc.)."""
    # Narrow bars
    if _is_narrow_shape(shape, slide_width, slide_height):
        # Check if it has no text or very minimal text
        paragraphs = shape.paragraphs if hasattr(shape, "paragraphs") else []
        total_text = "".join(p.text for p in paragraphs).strip()
        if len(total_text) <= 2:
            return True

    # Small shapes in corners (potential logos)
    slide_area = slide_width * slide_height
    shape_area = shape.width * shape.height
    if slide_area > 0 and (shape_area / slide_area) < SMALL_AREA_THRESHOLD:
        # Check if in a corner
        in_left_edge = shape.left < slide_width * 0.15
        in_right_edge = (shape.left + shape.width) > slide_width * 0.85
        in_top_edge = shape.top < slide_height * 0.15
        in_bottom_edge = (shape.top + shape.height) > slide_height * 0.85
        if (in_left_edge or in_right_edge) and (in_top_edge or in_bottom_edge):
            return True

    return False


def _detect_grid_group(shapes):
    """Detect if shapes form a grid pattern (3+ similar-sized at regular intervals).

    Returns list of shapes in the grid, or empty list if no grid detected.
    """
    if len(shapes) < MIN_GRID_SHAPES:
        return []

    # Find groups of similar-sized shapes
    used = set()
    best_group = []

    for i, ref in enumerate(shapes):
        if i in used:
            continue
        group = [ref]
        group_indices = {i}
        for j, other in enumerate(shapes):
            if j in used or j == i:
                continue
            if _shapes_similar_size(ref, other):
                group.append(other)
                group_indices.add(j)

        if len(group) >= MIN_GRID_SHAPES and len(group) > len(best_group):
            best_group = group
            used.update(group_indices)

    return best_group


def _group_by_proximity(shapes, gap_threshold=1.0):
    """Group shapes that are spatially close to each other.

    Uses simple distance-based clustering with the given gap threshold (inches).
    """
    if not shapes:
        return []

    groups = []
    remaining = list(shapes)

    while remaining:
        current = [remaining.pop(0)]
        changed = True

        while changed:
            changed = False
            still_remaining = []
            for shape in remaining:
                # Check if close to any shape in current group
                close = False
                for grouped in current:
                    # Horizontal gap
                    h_gap = max(
                        0,
                        max(
                            shape.left - (grouped.left + grouped.width),
                            grouped.left - (shape.left + shape.width),
                        ),
                    )
                    # Vertical gap
                    v_gap = max(
                        0,
                        max(
                            shape.top - (grouped.top + grouped.height),
                            grouped.top - (shape.top + shape.height),
                        ),
                    )
                    if h_gap <= gap_threshold and v_gap <= gap_threshold:
                        close = True
                        break
                if close:
                    current.append(shape)
                    changed = True
                else:
                    still_remaining.append(shape)
            remaining = still_remaining

        groups.append(current)

    return groups


def segment_slide(shapes, slide_width, slide_height):
    """Segment shapes into spatial groups by zone and pattern.

    Args:
        shapes: list of ShapeData objects (from inventory.py)
        slide_width: slide width in inches
        slide_height: slide height in inches

    Returns:
        list of segment dicts, each with:
            zone: "header" | "body" | "footer" | "decoration"
            shapes: list of ShapeData objects
            bounding_box: dict with left, top, width, height
    """
    if not shapes:
        return []

    header_y = slide_height * HEADER_ZONE_RATIO
    footer_y = slide_height * (1 - FOOTER_ZONE_RATIO)

    decorations = []
    header_shapes = []
    footer_shapes = []
    body_shapes = []

    # Phase 1: classify each shape into a zone
    for shape in shapes:
        shape_center_y = shape.top + shape.height / 2

        # Decoration check first
        if _is_decoration(shape, slide_width, slide_height):
            decorations.append(shape)
            continue

        if shape_center_y <= header_y:
            header_shapes.append(shape)
        elif shape_center_y >= footer_y:
            footer_shapes.append(shape)
        else:
            body_shapes.append(shape)

    segments = []

    # Header segment
    if header_shapes:
        segments.append(
            {
                "zone": "header",
                "shapes": header_shapes,
                "bounding_box": _bounding_box(header_shapes),
            }
        )

    # Footer segment
    if footer_shapes:
        segments.append(
            {
                "zone": "footer",
                "shapes": footer_shapes,
                "bounding_box": _bounding_box(footer_shapes),
            }
        )

    # Body zone: detect grids first, then group remaining by proximity
    if body_shapes:
        grid_shapes = _detect_grid_group(body_shapes)
        non_grid = [s for s in body_shapes if s not in grid_shapes]

        if grid_shapes:
            segments.append(
                {
                    "zone": "body",
                    "shapes": grid_shapes,
                    "bounding_box": _bounding_box(grid_shapes),
                    "is_grid": True,
                }
            )

        # Group remaining body shapes by spatial proximity
        if non_grid:
            proximity_groups = _group_by_proximity(non_grid)
            for group in proximity_groups:
                segments.append(
                    {
                        "zone": "body",
                        "shapes": group,
                        "bounding_box": _bounding_box(group),
                    }
                )

    # Decoration segments (one per decoration shape)
    for deco in decorations:
        segments.append(
            {
                "zone": "decoration",
                "shapes": [deco],
                "bounding_box": _bounding_box([deco]),
            }
        )

    return segments


def main():
    """CLI: demonstrate segmentation on a PPTX file (requires inventory.py)."""
    parser = argparse.ArgumentParser(
        description="Segment slide shapes into spatial groups."
    )
    parser.add_argument("input", help="Input PowerPoint file (.pptx)")
    parser.add_argument(
        "--slide", type=int, default=None, help="Slide index (0-based, default: all)"
    )
    args = parser.parse_args()

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from inventory import extract_text_inventory, ShapeData

    from pptx import Presentation

    pptx_path = Path(args.input)
    if not pptx_path.exists():
        print(f"Error: File not found: {pptx_path}")
        sys.exit(1)

    prs = Presentation(str(pptx_path))
    slide_width = round(ShapeData.emu_to_inches(prs.slide_width), 2)
    slide_height = round(ShapeData.emu_to_inches(prs.slide_height), 2)

    inventory = extract_text_inventory(pptx_path, prs)

    for slide_id, shapes_dict in inventory.items():
        slide_idx = int(slide_id.split("-")[1])
        if args.slide is not None and slide_idx != args.slide:
            continue

        shapes_list = list(shapes_dict.values())
        segments = segment_slide(shapes_list, slide_width, slide_height)

        print(
            f"\n=== {slide_id} ({len(shapes_list)} shapes -> {len(segments)} segments) ==="
        )
        for i, seg in enumerate(segments):
            zone = seg["zone"]
            n = len(seg["shapes"])
            bb = seg["bounding_box"]
            grid_label = " [GRID]" if seg.get("is_grid") else ""
            print(
                f"  Segment {i}: zone={zone}{grid_label}, shapes={n}, "
                f"bbox=({bb['left']}, {bb['top']}, {bb['width']}x{bb['height']})"
            )


if __name__ == "__main__":
    main()
