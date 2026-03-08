#!/usr/bin/env python3
"""
Main orchestrator: ingest a PPTX file into the design component library.

Processes a single PPTX file through the full pipeline:
  1. Extract design tokens (theme colors, fonts, dimensions)
  2. Extract shape inventory for all slides
  3. Segment each slide into spatial groups
  4. Classify each segment into a component type
  5. Extract design patterns for each component
  6. Save components, source metadata, and update the registry

Usage:
    python scripts/ingest_pptx.py input.pptx [--source-id NAME]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from extract_design_tokens import extract_design_tokens
from segment_slide import segment_slide
from classify_component import classify_component
from extract_component_pattern import extract_component_pattern
from llm_segmentation import enhance_slide_segmentation, merge_llm_with_rules  # noqa: E402


LIBRARY_DIR = PROJECT_ROOT / "library"
COMPONENTS_DIR = LIBRARY_DIR / "components"
SOURCES_DIR = LIBRARY_DIR / "sources"
REGISTRY_PATH = LIBRARY_DIR / "registry.json"
CONFIG_PATH = PROJECT_ROOT / "config" / "component-types.json"


def _sanitize_source_id(filename):
    """Generate a sanitized source_id from filename."""
    stem = Path(filename).stem
    # Lowercase, replace spaces and special chars with hyphens
    sanitized = re.sub(r"[^a-z0-9]+", "-", stem.lower())
    return sanitized.strip("-")


def _load_registry():
    """Load the component registry."""
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": "1.0",
        "updated_at": None,
        "total_components": 0,
        "total_sources": 0,
        "components": [],
    }


def _save_registry(registry):
    """Save the component registry."""
    registry["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


# 세션 내 ID 카운터 — 한 번의 인제스트에서 동일 타입 충돌 방지
_id_counters: dict[str, int] = {}


def _next_component_id(component_type):
    """Find the next available sequential ID for a component type.

    Uses both disk state and in-memory counter to prevent collisions
    within a single ingest session.
    """
    type_dir = COMPONENTS_DIR / component_type
    type_dir.mkdir(parents=True, exist_ok=True)

    if component_type not in _id_counters:
        # 초기화: 디스크에서 최대 번호 탐색
        existing = list(type_dir.glob(f"{component_type}-*.json"))
        max_num = 0
        for f in existing:
            match = re.search(r"-(\d+)\.json$", f.name)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
        _id_counters[component_type] = max_num

    _id_counters[component_type] += 1
    return f"{component_type}-{_id_counters[component_type]:03d}"


def ingest_pptx(pptx_path, source_id=None):
    """Process a PPTX file and add its components to the library.

    Args:
        pptx_path: Path to the .pptx file
        source_id: Optional source identifier (auto-generated from filename if not provided)

    Returns:
        dict with ingest summary
    """
    pptx_path = Path(pptx_path)

    if not pptx_path.exists():
        raise FileNotFoundError(f"File not found: {pptx_path}")

    # Generate source_id
    if not source_id:
        source_id = _sanitize_source_id(pptx_path.name)

    # Load component types config
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        component_types = json.load(f)["types"]

    # Step 1: Extract design tokens
    print("[1/4] Extracting design tokens...")
    design_tokens = extract_design_tokens(pptx_path)

    slide_dims = design_tokens.get("slide_dimensions", {})
    slide_width = slide_dims.get("width_inches", 13.33)
    slide_height = slide_dims.get("height_inches", 7.5)

    # Step 2: Extract shape inventory
    print("[2/4] Extracting shape inventory...")
    from inventory import extract_text_inventory
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    inventory = extract_text_inventory(pptx_path, prs)

    # LLM 설정 확인
    sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
    from llm_client import is_configured

    use_llm = is_configured()
    if use_llm:
        print("[*] LLM 세그멘테이션 활성화 (슬라이드당 1회 호출)")
    else:
        print("[*] LLM 미설정 — 규칙 기반 세그멘테이션 사용")

    # Step 3-4: Segment, classify, and extract patterns
    print(f"[3/4] Segmenting and classifying {len(inventory)} slides...")
    components = []
    type_counts = {}

    for slide_id, shapes_dict in inventory.items():
        slide_idx = int(slide_id.split("-")[1])
        shapes_list = list(shapes_dict.values())

        source_info = {
            "source_id": source_id,
            "filename": pptx_path.name,
            "slide_index": slide_idx,
        }

        # 규칙 기반 세그멘테이션 (항상 실행)
        segments = segment_slide(shapes_list, slide_width, slide_height)

        # LLM 세그멘테이션 (설정 시 → 규칙 결과와 병합)
        if use_llm:
            try:
                llm_result = enhance_slide_segmentation(
                    shapes_list, slide_width, slide_height, component_types
                )
                segments = merge_llm_with_rules(
                    segments, llm_result, shapes_list, slide_width, slide_height
                )
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    "Slide %d LLM 실패, 규칙 기반 fallback: %s", slide_idx, e
                )

        for seg in segments:
            # Classify: LLM 타입 우선, 없으면 규칙 기반
            comp_type = classify_component(
                seg, component_types, slide_width, slide_height
            )

            # Generate ID
            comp_id = _next_component_id(comp_type)

            # Track counts for summary
            type_counts[comp_type] = type_counts.get(comp_type, 0) + 1

            # Extract pattern (LLM 메타데이터 포함)
            pattern = extract_component_pattern(
                seg, comp_type, design_tokens, source_info
            )
            pattern["id"] = comp_id

            components.append(pattern)

    # Step 5: Save to library
    print(f"[4/4] Saving {len(components)} components to library...")

    # Save each component JSON
    for comp in components:
        comp_type = comp["type"]
        comp_id = comp["id"]
        type_dir = COMPONENTS_DIR / comp_type
        type_dir.mkdir(parents=True, exist_ok=True)

        comp_path = type_dir / f"{comp_id}.json"
        with open(comp_path, "w", encoding="utf-8") as f:
            json.dump(comp, f, indent=2, ensure_ascii=False)

    # Save source metadata
    source_dir = SOURCES_DIR / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "source_id": source_id,
        "filename": pptx_path.name,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "slide_count": len(inventory),
        "component_count": len(components),
        "component_types": type_counts,
        "slide_dimensions": slide_dims,
    }
    with open(source_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Save design tokens for this source
    with open(source_dir / "design-tokens.json", "w", encoding="utf-8") as f:
        json.dump(design_tokens, f, indent=2, ensure_ascii=False)

    # Update registry
    registry = _load_registry()

    for comp in components:
        registry_entry = {
            "id": comp["id"],
            "type": comp["type"],
            "source_id": source_id,
            "slide_index": comp["source"]["slide_index"],
            "item_count": comp.get("pattern", {}).get("item_count"),
            "section_types": comp.get("context", {}).get("section_types", []),
            "accent_color": comp.get("design_tokens", {}).get("accent_color"),
            "text_summary": comp.get("context", {}).get("text_summary", ""),
            "use_count": 0,
            "created_at": comp["created_at"],
        }
        # LLM 메타데이터 (있으면 추가)
        if comp.get("design_intent"):
            registry_entry["design_intent"] = comp["design_intent"]
        ctx = comp.get("context", {})
        if ctx.get("search_tags"):
            registry_entry["search_tags"] = ctx["search_tags"]
        if ctx.get("slide_intent"):
            registry_entry["slide_intent"] = ctx["slide_intent"]

        registry["components"].append(registry_entry)

    # Check if source already registered
    existing_sources = {c.get("source_id") for c in registry["components"]}
    registry["total_components"] = len(registry["components"])
    registry["total_sources"] = len(existing_sources)

    _save_registry(registry)

    return {
        "source_id": source_id,
        "slides_processed": len(inventory),
        "components_created": len(components),
        "type_counts": type_counts,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a PPTX file into the design component library."
    )
    parser.add_argument("input", help="Input PowerPoint file (.pptx)")
    parser.add_argument(
        "--source-id",
        default=None,
        help="Source identifier (auto-generated from filename if not provided)",
    )
    args = parser.parse_args()

    pptx_path = Path(args.input)
    if not pptx_path.exists():
        print(f"Error: File not found: {pptx_path}")
        sys.exit(1)

    if not pptx_path.suffix.lower() == ".pptx":
        print("Error: Input must be a PowerPoint file (.pptx)")
        sys.exit(1)

    try:
        result = ingest_pptx(pptx_path, args.source_id)

        print(f"\n{'=' * 50}")
        print("Ingest Complete")
        print(f"{'=' * 50}")
        print(f"  Source ID:    {result['source_id']}")
        print(f"  Slides:       {result['slides_processed']}")
        print(f"  Components:   {result['components_created']}")
        print("  By type:")
        for comp_type, count in sorted(result["type_counts"].items()):
            print(f"    {comp_type}: {count}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
