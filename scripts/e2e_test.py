#!/usr/bin/env python3
"""
E2E Test: TOC → Skeleton → Component Select → Layout → HTML → PPTX → Assemble

Usage:
    python scripts/e2e_test.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from pipeline.skeleton_builder import build_skeleton
from pipeline.component_selector import (
    get_component,
    get_fallback_component,
    search_components,
)
from pipeline.layout_calculator import calculate_layout
from pipeline.html_generator import generate_slide_html, save_slide_html
from pipeline.reconstruct import reconstruct_slide
from pipeline.assembler import assemble_presentation

OUTPUT_DIR = PROJECT_ROOT / "workspace" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def build_slide_html(slide: dict, slide_idx: int) -> Path:
    """Build HTML for a single slide from skeleton spec."""
    components_with_zones = []

    for cs in slide["components"]:
        comp_type = cs["type"]

        if comp_type == "full-page":
            comp = get_fallback_component("full-page")
        else:
            results = search_components(
                component_type=comp_type,
                target_item_count=slide.get("item_count"),
                limit=1,
            )
            if results:
                comp = get_component(results[0]["id"])
            else:
                comp = get_fallback_component(comp_type)

        entry = {"component": comp, "zone": cs["zone"]}
        if cs["zone"] == "body" and slide.get("item_count"):
            entry["target_item_count"] = slide["item_count"]
        components_with_zones.append(entry)

    positioned = calculate_layout(components_with_zones)

    # Build content data
    content_data = []
    for pc in positioned:
        ct = pc.get("component_type", "")
        if ct == "header":
            content_data.append(
                {
                    "component_id": pc["component_id"],
                    "title": slide["title"],
                    "subtitle": "",
                }
            )
        elif ct == "footer":
            content_data.append(
                {
                    "component_id": pc["component_id"],
                    "page_number": str(slide_idx + 1),
                }
            )
        elif ct == "full-page":
            content_data.append(
                {
                    "component_id": pc["component_id"],
                    "title": slide["title"],
                    "subtitle": "PwC Korea" if slide["slide_type"] == "cover" else "",
                }
            )
        else:
            n_items = len(pc["items"])
            items = []
            for i in range(n_items):
                items.append(
                    {
                        "number": f"0{i + 1}",
                        "heading": f"항목 {i + 1}",
                        "body": [f"세부내용 {i + 1}-A", f"세부내용 {i + 1}-B"],
                    }
                )
            content_data.append(
                {
                    "component_id": pc["component_id"],
                    "items": items,
                }
            )

    html = generate_slide_html(positioned, content_data)
    html_path = OUTPUT_DIR / f"slide_{slide_idx:02d}.html"
    save_slide_html(html, html_path)
    return html_path


def main():
    toc = "1.세무조정 개요 2.회사자료 확인방법(3단계) 3.주요 조정항목(4개)"
    print(f"TOC: {toc}")

    skeleton = build_skeleton(toc)
    print(f"Skeleton: {len(skeleton)} slides")

    # Phase 1: Generate HTML for all slides
    html_paths = []
    for slide in skeleton:
        idx = slide["slide_index"]
        print(f"  [HTML] Slide {idx}: {slide['title']} ({slide['slide_type']})")
        html_path = build_slide_html(slide, idx)
        html_paths.append(html_path)
        print(f"         → {html_path.name}")

    # Phase 2: Convert each HTML to individual PPTX
    pptx_paths = []
    for html_path in html_paths:
        pptx_path = html_path.with_suffix(".pptx")
        print(f"  [PPTX] {html_path.name} → {pptx_path.name}")
        try:
            reconstruct_slide(html_path, pptx_path)
            pptx_paths.append(pptx_path)
            print("         → OK")
        except Exception as e:
            print(f"         → ERROR: {e}")
            # Continue with remaining slides

    if not pptx_paths:
        print("ERROR: No PPTX files generated.")
        sys.exit(1)

    # Phase 3: Assemble into final presentation
    final_path = OUTPUT_DIR / "final_presentation.pptx"
    print(f"\n  [ASSEMBLE] {len(pptx_paths)} slides → {final_path.name}")
    try:
        assemble_presentation(pptx_paths, final_path)
        print(f"  → Final PPTX: {final_path}")
    except Exception as e:
        print(f"  → ASSEMBLE ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print(f"\n{'=' * 50}")
    print("E2E Test Complete!")
    print(f"  Slides: {len(pptx_paths)}")
    print(f"  Output: {final_path}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
