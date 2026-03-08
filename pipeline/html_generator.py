#!/usr/bin/env python3
"""
배치된 컴포넌트와 콘텐츠 데이터로부터 슬라이드 HTML을 생성한다.

layout_calculator의 출력(positioned components)과 콘텐츠 데이터를 조합하여
html2pptx.js가 처리할 수 있는 HTML 파일을 만든다.
"""

import argparse
import json
from html import escape
from pathlib import Path

PX_PER_INCH = 96


def _inches_to_px(inches: float) -> float:
    return inches * PX_PER_INCH


def _auto_distribute_zones(zones: list[dict]) -> None:
    """Ensure all content zones have relative_top/relative_height.

    If any zone is missing these values, redistribute all zones evenly.
    Mutates zones in-place.
    """
    if not zones:
        return
    needs_fix = any(
        "relative_top" not in z or "relative_height" not in z for z in zones
    )
    if not needs_fix:
        return
    n = len(zones)
    for i, z in enumerate(zones):
        z["relative_top"] = round(i / n, 3)
        z["relative_height"] = round(1.0 / n, 3)


def _normalize_color(color: str) -> str:
    """색상 값에서 # 접두사를 제거하고 순수 hex 값만 반환한다."""
    if not color:
        return "000000"
    return color.lstrip("#")


def _build_item_html(
    item_pos: dict,
    content: dict,
    design_tokens: dict,
    item_template: dict,
) -> str:
    """개별 아이템(카드)의 HTML을 생성한다."""
    x_px = _inches_to_px(item_pos["x"])
    y_px = _inches_to_px(item_pos["y"])
    w_px = _inches_to_px(item_pos["width"])
    h_px = _inches_to_px(item_pos["height"])

    fill = _normalize_color(design_tokens.get("item_fill", "F2F2F2"))
    shape_type = item_template.get("shape_type", "rect")
    border_radius_in = item_template.get("border_radius_inches", 0)
    border_radius_px = _inches_to_px(border_radius_in)
    font_family = design_tokens.get("font_family", "맑은 고딕")

    radius_css = (
        f"border-radius: {border_radius_px}px;"
        if shape_type == "roundRect" and border_radius_px > 0
        else ""
    )

    # 아이템 컨테이너 (배경 shape)
    lines = [
        f'<div style="position:absolute; left:{x_px}px; top:{y_px}px; '
        f"width:{w_px}px; height:{h_px}px; "
        f'background-color:#{fill}; {radius_css} overflow:hidden;">',
    ]

    # content_zones 렌더링 (relative_top/height 없으면 자동 분배)
    content_zones = item_template.get("content_zones", [])
    _auto_distribute_zones(content_zones)
    for zone in content_zones:
        role = zone.get("role", "")
        rel_top = zone.get("relative_top", 0)
        rel_height = zone.get("relative_height", 1)
        font_size = zone.get("font_size", 11)
        bold = zone.get("bold", False)
        alignment = zone.get("alignment", "LEFT").lower()
        is_bullet = zone.get("bullet", False)

        # 영역별 색상
        color_key = f"{role}_color"
        color = _normalize_color(
            design_tokens.get(color_key, design_tokens.get("body_color", "2D2D2D"))
        )

        zone_top_px = rel_top * h_px
        zone_height_px = rel_height * h_px
        padding_px = 8

        zone_style = (
            f"position:absolute; left:0; top:{zone_top_px}px; "
            f"width:100%; height:{zone_height_px}px; "
            f"box-sizing:border-box; padding:0 {padding_px}px; "
            f"display:flex; flex-direction:column; justify-content:center;"
        )

        text_value = content.get(role, "")

        if is_bullet and isinstance(text_value, list):
            # 불릿 리스트
            lines.append(f'  <div style="{zone_style}">')
            items_html = "".join(f"<li>{escape(str(item))}</li>" for item in text_value)
            lines.append(
                f'    <ul style="font-size:{font_size}px; color:#{color}; '
                f"font-family:'{font_family}'; margin:0; "
                f'padding-left:16px; list-style-type:disc;">'
                f"{items_html}</ul>"
            )
            lines.append("  </div>")
        else:
            # 일반 텍스트
            text_str = escape(str(text_value)) if text_value else ""
            bold_css = "font-weight:bold;" if bold else ""
            tag = "p"
            lines.append(f'  <div style="{zone_style}">')
            lines.append(
                f'    <{tag} style="font-size:{font_size}px; color:#{color}; '
                f"font-family:'{font_family}'; {bold_css} "
                f'text-align:{alignment}; margin:0;">'
                f"{text_str}</{tag}>"
            )
            lines.append("  </div>")

    lines.append("</div>")
    return "\n".join(lines)


def _build_header_html(
    item_pos: dict,
    content: dict,
    design_tokens: dict,
) -> str:
    """헤더 컴포넌트 HTML."""
    x_px = _inches_to_px(item_pos["x"])
    y_px = _inches_to_px(item_pos["y"])
    w_px = _inches_to_px(item_pos["width"])
    h_px = _inches_to_px(item_pos["height"])
    font_family = design_tokens.get("font_family", "맑은 고딕")
    heading_color = _normalize_color(design_tokens.get("heading_color", "2D2D2D"))
    accent_color = _normalize_color(design_tokens.get("accent_color", "D04A02"))

    title = escape(str(content.get("title", "")))
    subtitle = escape(str(content.get("subtitle", "")))

    lines = []
    # 제목
    if title:
        lines.append(
            f'<h1 style="position:absolute; left:{x_px}px; top:{y_px}px; '
            f"width:{w_px}px; height:{h_px * 0.6}px; margin:0; "
            f"font-size:28px; font-family:'{font_family}'; "
            f'color:#{heading_color}; font-weight:bold;">{title}</h1>'
        )
    # 부제목
    if subtitle:
        sub_top = y_px + h_px * 0.55
        lines.append(
            f'<p style="position:absolute; left:{x_px}px; top:{sub_top}px; '
            f"width:{w_px}px; height:{h_px * 0.35}px; margin:0; "
            f"font-size:14px; font-family:'{font_family}'; "
            f'color:#{accent_color};">{subtitle}</p>'
        )
    # 악센트 바
    bar_top = y_px + h_px - 4
    lines.append(
        f'<div style="position:absolute; left:{x_px}px; top:{bar_top}px; '
        f'width:{w_px}px; height:3px; background-color:#{accent_color};"></div>'
    )
    return "\n".join(lines)


def _build_footer_html(
    item_pos: dict,
    content: dict,
    design_tokens: dict,
) -> str:
    """푸터 컴포넌트 HTML."""
    x_px = _inches_to_px(item_pos["x"])
    y_px = _inches_to_px(item_pos["y"])
    w_px = _inches_to_px(item_pos["width"])
    h_px = _inches_to_px(item_pos["height"])
    font_family = design_tokens.get("font_family", "맑은 고딕")
    body_color = _normalize_color(design_tokens.get("body_color", "999999"))

    page_text = escape(str(content.get("page_number", "")))
    confidential = escape(str(content.get("confidential", "")))

    lines = []
    if page_text:
        lines.append(
            f'<p style="position:absolute; left:{x_px}px; top:{y_px}px; '
            f"width:{w_px}px; height:{h_px}px; margin:0; "
            f"font-size:9px; font-family:'{font_family}'; "
            f'color:#{body_color}; text-align:right;">{page_text}</p>'
        )
    if confidential:
        lines.append(
            f'<p style="position:absolute; left:{x_px}px; top:{y_px}px; '
            f"width:{w_px * 0.5}px; height:{h_px}px; margin:0; "
            f"font-size:8px; font-family:'{font_family}'; "
            f'color:#{body_color};">{confidential}</p>'
        )
    return "\n".join(lines)


def _build_full_page_html(
    content: dict,
    design_tokens: dict,
    body_w_px: float,
    body_h_px: float,
) -> str:
    """표지/감사 페이지 등 전체 페이지 컴포넌트 HTML."""
    font_family = design_tokens.get("font_family", "맑은 고딕")
    accent_color = _normalize_color(design_tokens.get("accent_color", "D04A02"))
    heading_color = _normalize_color(design_tokens.get("heading_color", "2D2D2D"))
    bg_color = _normalize_color(design_tokens.get("bg_color", "FFFFFF"))

    title = escape(str(content.get("title", "")))
    subtitle = escape(str(content.get("subtitle", "")))

    lines = [
        f'<div style="position:absolute; left:0; top:0; '
        f"width:{body_w_px}px; height:{body_h_px}px; "
        f"background-color:#{bg_color}; display:flex; flex-direction:column; "
        f'justify-content:center; align-items:center;">',
    ]
    if title:
        lines.append(
            f"  <h1 style=\"font-size:36px; font-family:'{font_family}'; "
            f"color:#{heading_color}; font-weight:bold; margin:0 0 16px 0; "
            f'text-align:center;">{title}</h1>'
        )
    if subtitle:
        lines.append(
            f"  <p style=\"font-size:18px; font-family:'{font_family}'; "
            f'color:#{accent_color}; margin:0; text-align:center;">{subtitle}</p>'
        )
    lines.append("</div>")
    return "\n".join(lines)


def generate_slide_html(
    positioned_components: list[dict],
    content_data: list[dict],
    slide_width: float = 13.33,
    slide_height: float = 7.5,
) -> str:
    """배치된 컴포넌트와 콘텐츠 데이터로 슬라이드 HTML을 생성한다.

    Args:
        positioned_components: layout_calculator의 출력.
        content_data: 각 컴포넌트에 대한 콘텐츠.
            {
                "component_id": "card-grid-003",
                "items": [
                    {"number": "01", "heading": "계획수립", "body": ["범위 결정", "일정 수립"]},
                ],
                # 또는 header/footer용:
                "title": "감사방법론",
                "subtitle": "...",
                "page_number": "3",
            }
        slide_width: 슬라이드 너비 (인치).
        slide_height: 슬라이드 높이 (인치).

    Returns:
        완전한 HTML 문자열.
    """
    body_w = _inches_to_px(slide_width)
    body_h = _inches_to_px(slide_height)

    # content_data를 component_id로 인덱싱
    content_map: dict[str, dict] = {}
    for cd in content_data:
        cid = cd.get("component_id", "")
        if cid:
            content_map[cid] = cd

    elements_html: list[str] = []

    for pc in positioned_components:
        comp_id = pc.get("component_id", "")
        comp_type = pc.get("component_type", "")
        design_tokens = pc.get("design_tokens", {})
        pattern = pc.get("pattern", {})
        item_template = pattern.get("item_template", {})
        items_positions = pc.get("items", [])

        content = content_map.get(comp_id, {})

        if comp_type == "header":
            if items_positions:
                elements_html.append(
                    _build_header_html(items_positions[0], content, design_tokens)
                )

        elif comp_type == "footer":
            if items_positions:
                elements_html.append(
                    _build_footer_html(items_positions[0], content, design_tokens)
                )

        elif comp_type == "full-page":
            # 표지/감사 페이지: 전체 화면 배경 + 중앙 텍스트
            elements_html.append(
                _build_full_page_html(content, design_tokens, body_w, body_h)
            )

        else:
            # 일반 컴포넌트 (card-grid, timeline, etc.)
            content_items = content.get("items", [])
            for i, item_pos in enumerate(items_positions):
                item_content = content_items[i] if i < len(content_items) else {}
                elements_html.append(
                    _build_item_html(
                        item_pos, item_content, design_tokens, item_template
                    )
                )

    body_html = "\n".join(elements_html)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {body_w}px;
    height: {body_h}px;
    position: relative;
    overflow: hidden;
    background-color: #FFFFFF;
  }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

    return html


def save_slide_html(html_content: str, output_path: str | Path) -> Path:
    """HTML 콘텐츠를 파일로 저장한다."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="배치된 컴포넌트와 콘텐츠로부터 슬라이드 HTML을 생성한다.",
    )
    parser.add_argument("positioned_json", help="positioned_components JSON 파일")
    parser.add_argument("content_json", help="content_data JSON 파일")
    parser.add_argument(
        "-o", "--output", default="slide.html", help="출력 HTML 파일 경로"
    )
    parser.add_argument(
        "--width", type=float, default=13.33, help="슬라이드 너비 (인치)"
    )
    parser.add_argument(
        "--height", type=float, default=7.5, help="슬라이드 높이 (인치)"
    )

    args = parser.parse_args()

    positioned = json.loads(Path(args.positioned_json).read_text(encoding="utf-8"))
    content = json.loads(Path(args.content_json).read_text(encoding="utf-8"))

    html = generate_slide_html(
        positioned, content, slide_width=args.width, slide_height=args.height
    )
    out = save_slide_html(html, args.output)
    print(f"Saved HTML to: {out}")


if __name__ == "__main__":
    main()
