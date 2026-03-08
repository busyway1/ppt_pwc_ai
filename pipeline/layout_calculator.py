#!/usr/bin/env python3
"""
선택된 컴포넌트들을 슬라이드 위에 배치할 좌표를 계산한다.

- 헤더/바디/푸터 영역에 컴포넌트를 배치
- item_count 변경 시 그리드를 자동 재계산
"""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

# 슬라이드 영역 기본값 (인치)
ZONES = {
    "header": {"top": 0.2, "bottom": 1.5},
    "body": {"top": 1.5, "bottom": 6.5},
    "footer": {"top": 6.8, "bottom": 7.3},
}


def _adjust_grid_for_item_count(
    pattern: dict, target_count: int, zone_width: float
) -> dict:
    """item_count가 변경될 때 그리드 레이아웃을 재계산한다.

    원본 컴포넌트의 전체 너비를 유지하면서
    새로운 아이템 수에 맞게 item width와 gap을 비례 조정한다.
    """
    pattern = deepcopy(pattern)
    original_count = pattern.get("item_count", target_count)
    grid = pattern.get("grid", {})
    item_template = pattern.get("item_template", {})

    if original_count == target_count:
        return pattern

    orientation = pattern.get("orientation", "horizontal")
    original_gap = grid.get("gap_inches", 0.3)
    original_item_w = item_template.get("width", 2.0)

    if orientation == "horizontal":
        # 원본 전체 너비 = items * width + (items-1) * gap
        total_width = (
            original_count * original_item_w + max(0, original_count - 1) * original_gap
        )
        # 사용 가능한 최대 너비
        available_width = min(total_width, zone_width)

        # 새 아이템 수에 맞게 재분배
        if target_count <= 1:
            new_gap = 0.0
            new_item_w = available_width
        else:
            # gap 비율 유지: gap = original_gap * (original_item_w / new_item_w) 근사
            # 단순화: 전체 너비에서 gap 총합을 빼고 아이템 수로 나눔
            new_gap = original_gap
            total_gap = new_gap * (target_count - 1)
            new_item_w = (available_width - total_gap) / target_count

            # 아이템 너비가 너무 작으면 gap을 줄임
            if new_item_w < 0.5:
                new_gap = original_gap * 0.5
                total_gap = new_gap * (target_count - 1)
                new_item_w = (available_width - total_gap) / target_count

        grid["cols"] = target_count
        grid["rows"] = 1
        grid["gap_inches"] = round(new_gap, 3)
        item_template["width"] = round(new_item_w, 3)
    else:
        # vertical 배치
        original_item_h = item_template.get("height", 3.5)
        total_height = (
            original_count * original_item_h + max(0, original_count - 1) * original_gap
        )

        if target_count <= 1:
            new_gap = 0.0
            new_item_h = total_height
        else:
            new_gap = original_gap
            total_gap = new_gap * (target_count - 1)
            new_item_h = (total_height - total_gap) / target_count
            if new_item_h < 0.5:
                new_gap = original_gap * 0.5
                total_gap = new_gap * (target_count - 1)
                new_item_h = (total_height - total_gap) / target_count

        grid["rows"] = target_count
        grid["cols"] = 1
        grid["gap_inches"] = round(new_gap, 3)
        item_template["height"] = round(new_item_h, 3)

    pattern["item_count"] = target_count
    pattern["grid"] = grid
    pattern["item_template"] = item_template
    return pattern


def calculate_layout(
    components_with_zones: list[dict],
    slide_width: float = 13.33,
    slide_height: float = 7.5,
) -> list[dict]:
    """컴포넌트와 영역 정보를 받아 절대 좌표를 계산한다.

    Args:
        components_with_zones: 각 항목은 다음 구조:
            {
                "component": <컴포넌트 JSON>,
                "zone": "header" | "body" | "footer",
                "target_item_count": <int, optional>,
                "left_margin": <float, optional>,
            }
        slide_width: 슬라이드 너비 (인치).
        slide_height: 슬라이드 높이 (인치).

    Returns:
        positioned_components: 각 항목에 "items" 리스트가 추가됨.
            각 item은 {"x", "y", "width", "height"} 절대 좌표를 가짐.
    """
    side_margin = 0.5
    results = []

    # body zone 충돌 방지: 다중 body 컴포넌트를 수직 분할
    body_entries = [e for e in components_with_zones if e.get("zone") == "body"]
    body_zone_offsets: dict[int, float] = {}
    if len(body_entries) > 1:
        body_zone = ZONES["body"]
        total_body_h = body_zone["bottom"] - body_zone["top"]
        gap = 0.2
        per_body_h = (total_body_h - gap * (len(body_entries) - 1)) / len(body_entries)
        for i, be in enumerate(body_entries):
            body_zone_offsets[id(be)] = body_zone["top"] + i * (per_body_h + gap)

    for entry in components_with_zones:
        component = deepcopy(entry["component"])
        zone_name = entry.get("zone", "body")
        target_count = entry.get("target_item_count")
        left_margin = entry.get("left_margin", side_margin)

        zone = ZONES.get(zone_name, ZONES["body"])
        zone_top = zone["top"]
        zone_bottom = min(zone["bottom"], slide_height)

        # body zone 수직 분할 적용
        if zone_name == "body" and id(entry) in body_zone_offsets:
            zone_top = body_zone_offsets[id(entry)]
            total_body_h = ZONES["body"]["bottom"] - ZONES["body"]["top"]
            gap = 0.2
            per_body_h = (total_body_h - gap * (len(body_entries) - 1)) / len(
                body_entries
            )
            zone_bottom = zone_top + per_body_h

        zone_height = zone_bottom - zone_top
        zone_width = slide_width - left_margin - side_margin

        pattern = component.get("pattern", {})
        if target_count is not None:
            pattern = _adjust_grid_for_item_count(pattern, target_count, zone_width)

        item_count = pattern.get("item_count", 1)
        grid = pattern.get("grid", {})
        item_template = pattern.get("item_template", {})
        orientation = pattern.get("orientation", "horizontal")

        # Header/footer should span full zone width by default
        if zone_name in ("header", "footer"):
            item_w = item_template.get("width", zone_width)
            # Clamp to zone width if template width is too small
            if item_w < zone_width * 0.5:
                item_w = zone_width
        else:
            item_w = item_template.get("width", 2.0)
        item_h = item_template.get("height", zone_height)
        gap = grid.get("gap_inches", 0.3)

        # 아이템 높이가 영역보다 크면 축소
        if item_h > zone_height:
            item_h = zone_height

        # 아이템 최소 크기 보장
        item_w = max(item_w, 0.3)
        item_h = max(item_h, 0.3)

        # 각 아이템의 절대 좌표 계산
        items = []
        for i in range(item_count):
            if orientation == "horizontal":
                total_items_width = item_count * item_w + max(0, item_count - 1) * gap
                # 전체 너비가 영역을 초과하면 좌측 정렬
                if total_items_width > zone_width:
                    start_x = left_margin
                else:
                    start_x = left_margin + (zone_width - total_items_width) / 2
                x = start_x + i * (item_w + gap)
                y = zone_top + (zone_height - item_h) / 2
            else:
                total_items_height = item_count * item_h + max(0, item_count - 1) * gap
                if total_items_height > zone_height:
                    start_y = zone_top
                else:
                    start_y = zone_top + (zone_height - total_items_height) / 2
                x = left_margin + (zone_width - item_w) / 2
                y = start_y + i * (item_h + gap)

            items.append(
                {
                    "index": i,
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "width": round(item_w, 3),
                    "height": round(item_h, 3),
                }
            )

        results.append(
            {
                "component_id": component.get("id", ""),
                "component_type": component.get("type", ""),
                "zone": zone_name,
                "pattern": pattern,
                "design_tokens": component.get("design_tokens", {}),
                "items": items,
            }
        )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="컴포넌트를 슬라이드 위에 배치할 좌표를 계산한다.",
    )
    parser.add_argument(
        "input_json",
        help="components_with_zones JSON 파일 경로",
    )
    parser.add_argument(
        "--width", type=float, default=13.33, help="슬라이드 너비 (인치)"
    )
    parser.add_argument(
        "--height", type=float, default=7.5, help="슬라이드 높이 (인치)"
    )

    args = parser.parse_args()
    input_path = Path(args.input_json)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    result = calculate_layout(data, slide_width=args.width, slide_height=args.height)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
