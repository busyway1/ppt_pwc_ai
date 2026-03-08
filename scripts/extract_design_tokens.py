#!/usr/bin/env python3
"""
Extract design tokens (theme colors, fonts, slide dimensions) from a PPTX file.

Usage:
    python scripts/extract_design_tokens.py input.pptx [output.json]

Module API:
    extract_design_tokens(pptx_path) -> dict
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

import defusedxml.minidom

# Theme color slots in Office theme XML
THEME_COLOR_SLOTS = [
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
]

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _parse_color_element(color_node):
    """Extract hex color from a theme color element (srgbClr or sysClr).

    Args:
        color_node: minidom Element whose children are srgbClr/sysClr nodes.
    """
    for child in color_node.childNodes:
        if not hasattr(child, "tagName"):
            continue
        local_tag = child.tagName.split(":")[-1]
        if local_tag == "srgbClr":
            return child.getAttribute("val") or None
        if local_tag == "sysClr":
            # sysClr has lastClr as the resolved value
            return child.getAttribute("lastClr") or child.getAttribute("val") or None
    return None


def _parse_theme_xml(theme_root):
    """Parse theme XML element tree to extract colors and fonts."""
    colors = {}
    fonts = {
        "major_latin": None,
        "major_ea": None,
        "minor_latin": None,
        "minor_ea": None,
    }

    # Walk all elements looking for color scheme and font scheme
    for elem in theme_root.childNodes:
        if not hasattr(elem, "tagName"):
            continue

        # themeElements contains clrScheme and fontScheme
        local_tag = elem.tagName.split(":")[-1]
        if local_tag == "themeElements":
            for child in elem.childNodes:
                if not hasattr(child, "tagName"):
                    continue
                child_tag = child.tagName.split(":")[-1]

                if child_tag == "clrScheme":
                    for color_node in child.childNodes:
                        if not hasattr(color_node, "tagName"):
                            continue
                        slot_name = color_node.tagName.split(":")[-1]
                        if slot_name in THEME_COLOR_SLOTS:
                            hex_val = _parse_color_element(color_node)
                            if hex_val:
                                colors[slot_name] = hex_val

                elif child_tag == "fontScheme":
                    for font_node in child.childNodes:
                        if not hasattr(font_node, "tagName"):
                            continue
                        font_tag = font_node.tagName.split(":")[-1]
                        if font_tag in ("majorFont", "minorFont"):
                            prefix = "major" if font_tag == "majorFont" else "minor"
                            for f_child in font_node.childNodes:
                                if not hasattr(f_child, "tagName"):
                                    continue
                                f_local = f_child.tagName.split(":")[-1]
                                if f_local == "latin":
                                    fonts[f"{prefix}_latin"] = f_child.getAttribute(
                                        "typeface"
                                    )
                                elif f_local == "ea":
                                    fonts[f"{prefix}_ea"] = f_child.getAttribute(
                                        "typeface"
                                    )

    return colors, fonts


def _get_slide_dimensions(pptx_path):
    """Extract slide width/height from presentation.xml."""
    width_inches = None
    height_inches = None

    with zipfile.ZipFile(str(pptx_path), "r") as zf:
        if "ppt/presentation.xml" in zf.namelist():
            content = zf.read("ppt/presentation.xml").decode("utf-8")
            dom = defusedxml.minidom.parseString(content)
            for elem in dom.getElementsByTagName("p:sldSz"):
                cx = elem.getAttribute("cx")
                cy = elem.getAttribute("cy")
                if cx and cy:
                    width_inches = round(int(cx) / 914400.0, 2)
                    height_inches = round(int(cy) / 914400.0, 2)
                break

    return width_inches, height_inches


def extract_design_tokens(pptx_path):
    """Extract design tokens from a PPTX file.

    Args:
        pptx_path: Path to the .pptx file (str or Path)

    Returns:
        dict with keys: colors, fonts, slide_dimensions
    """
    pptx_path = Path(pptx_path)

    colors = {}
    fonts = {
        "major_latin": None,
        "major_ea": None,
        "minor_latin": None,
        "minor_ea": None,
    }

    # Extract theme XML from the PPTX zip
    with zipfile.ZipFile(str(pptx_path), "r") as zf:
        # Find theme file (usually ppt/theme/theme1.xml)
        theme_files = [
            n
            for n in zf.namelist()
            if n.startswith("ppt/theme/theme") and n.endswith(".xml")
        ]
        if theme_files:
            theme_content = zf.read(theme_files[0]).decode("utf-8")
            dom = defusedxml.minidom.parseString(theme_content)
            colors, fonts = _parse_theme_xml(dom.documentElement)

    # Get slide dimensions
    width, height = _get_slide_dimensions(pptx_path)

    return {
        "colors": colors,
        "fonts": fonts,
        "slide_dimensions": {
            "width_inches": width,
            "height_inches": height,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract design tokens (colors, fonts, dimensions) from a PPTX file."
    )
    parser.add_argument("input", help="Input PowerPoint file (.pptx)")
    parser.add_argument(
        "output", nargs="?", default=None, help="Output JSON file (optional)"
    )
    args = parser.parse_args()

    pptx_path = Path(args.input)
    if not pptx_path.exists():
        print(f"Error: File not found: {pptx_path}")
        sys.exit(1)

    tokens = extract_design_tokens(pptx_path)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2, ensure_ascii=False)
        print(f"Design tokens saved to: {args.output}")
    else:
        print(json.dumps(tokens, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
