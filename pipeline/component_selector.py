#!/usr/bin/env python3
"""
컴포넌트 라이브러리에서 조건에 맞는 컴포넌트를 검색한다.

Usage:
    python pipeline/component_selector.py --type card-grid --keywords "방법론,단계"
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = PROJECT_ROOT / "library"
REGISTRY_PATH = LIBRARY_DIR / "registry.json"
COMPONENTS_DIR = LIBRARY_DIR / "components"


def _load_registry() -> dict:
    """registry.json 로드."""
    if not REGISTRY_PATH.exists():
        return {"components": []}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _color_distance(hex_a: str, hex_b: str) -> float:
    """두 hex 색상 간 유클리드 거리 (0~441)."""
    hex_a = hex_a.lstrip("#").upper()
    hex_b = hex_b.lstrip("#").upper()
    if len(hex_a) != 6 or len(hex_b) != 6:
        return 441.0  # 최대 거리
    r1, g1, b1 = int(hex_a[:2], 16), int(hex_a[2:4], 16), int(hex_a[4:], 16)
    r2, g2, b2 = int(hex_b[:2], 16), int(hex_b[2:4], 16), int(hex_b[4:], 16)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def get_component(component_id: str) -> dict | None:
    """컴포넌트 ID로 전체 JSON을 로드한다.

    library/components/{type}/{id}.json 경로에서 찾는다.
    레지스트리의 type 정보를 사용하거나, 디렉토리를 순회한다.
    """
    registry = _load_registry()

    # 레지스트리에서 타입 정보 탐색
    for entry in registry.get("components", []):
        if entry.get("id") == component_id:
            comp_type = entry.get("type", "")
            comp_path = COMPONENTS_DIR / comp_type / f"{component_id}.json"
            if comp_path.exists():
                return json.loads(comp_path.read_text(encoding="utf-8"))

    # 레지스트리에 없으면 디렉토리 순회
    for type_dir in COMPONENTS_DIR.iterdir():
        if not type_dir.is_dir():
            continue
        comp_path = type_dir / f"{component_id}.json"
        if comp_path.exists():
            return json.loads(comp_path.read_text(encoding="utf-8"))

    return None


def search_components(
    component_type: str,
    section_keywords: list[str] | None = None,
    accent_color: str | None = None,
    target_item_count: int | None = None,
    prefer_horizontal: bool = True,
    limit: int = 5,
    query_intent: list[str] | None = None,
    slide_intent: str | None = None,
) -> list[dict]:
    """조건에 맞는 컴포넌트를 검색하여 점수 순으로 반환한다.

    Multi-Vector Search: design_intent + search_tags + slide_intent 가중치 매칭.

    Args:
        component_type: 필수. 컴포넌트 타입 (예: "card-grid").
        section_keywords: 선택. 섹션 키워드 목록.
        accent_color: 선택. 유사 색상 매칭용 hex 코드.
        target_item_count: 선택. 원하는 아이템 수 (가까울수록 높은 점수).
        prefer_horizontal: True이면 horizontal 배치 우대 (기본 True).
        limit: 반환할 최대 개수.
        query_intent: 선택. design_intent 매칭용 키워드 리스트.
        slide_intent: 선택. 슬라이드 전체 의도 매칭.

    Returns:
        점수 순으로 정렬된 컴포넌트 목록 (레지스트리 엔트리 + score).
    """
    registry = _load_registry()
    candidates = []

    for entry in registry.get("components", []):
        if entry.get("type") != component_type:
            continue

        score = 10.0  # 타입 매칭 기본 점수

        # item_count 근접도 (최대 8점)
        entry_count = entry.get("item_count") or 1
        if target_item_count and entry_count >= 2:
            diff = abs(entry_count - target_item_count)
            if diff == 0:
                score += 8.0
            elif diff == 1:
                score += 5.0
            elif diff == 2:
                score += 2.0
        elif entry_count >= 3:
            score += 3.0

        # design_intent 교집합 (가장 높은 가중치: 8점/intent)
        if query_intent:
            entry_intent = set(entry.get("design_intent", []))
            intent_overlap = len(set(query_intent) & entry_intent)
            score += intent_overlap * 8.0

        # search_tags 교집합 (5점/tag)
        if section_keywords:
            entry_tags = set(entry.get("search_tags", []))
            entry_keywords = entry.get("section_types", [])
            entry_summary = entry.get("text_summary", "")
            # 기존 키워드 매칭 (section_types + text_summary)
            keyword_text = " ".join(entry_keywords) + " " + entry_summary
            overlap = sum(1 for kw in section_keywords if kw in keyword_text)
            # search_tags 매칭
            tag_overlap = len(set(section_keywords) & entry_tags)
            score += (overlap + tag_overlap) * 5.0

        # slide_intent 일치 (6점)
        if slide_intent and entry.get("slide_intent"):
            if entry["slide_intent"] == slide_intent:
                score += 6.0

        # 색상 유사도
        if accent_color and entry.get("accent_color"):
            dist = _color_distance(accent_color, entry["accent_color"])
            score += max(0, 3.0 - (dist / 441.0) * 3.0)

        # 인기도 (use_count)
        use_count = entry.get("use_count", 0)
        score += min(use_count * 0.5, 5.0)

        candidates.append({**entry, "score": round(score, 2)})

    # Orientation 우대: full component를 로드하여 확인
    if prefer_horizontal and component_type in (
        "card-grid",
        "icon-grid",
        "timeline",
        "roadmap",
        "value-prop",
        "kpi-dashboard",
    ):
        for c in candidates:
            comp = get_component(c["id"])
            if comp:
                orientation = comp.get("pattern", {}).get("orientation", "")
                if orientation == "horizontal":
                    c["score"] += 5.0

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:limit]


def get_fallback_component(component_type: str) -> dict:
    """Generate a minimal fallback component when none found in library.

    Returns a component dict with sensible defaults for the given type.
    """
    now = (
        __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat()
    )

    base = {
        "id": f"{component_type}-fallback",
        "type": component_type,
        "source": {
            "source_id": "fallback",
            "filename": "",
            "slide_index": 0,
            "region": {},
        },
        "design_tokens": {
            "accent_color": "D04A02",
            "heading_color": "2D2D2D",
            "body_color": "666666",
            "number_color": "D04A02",
            "item_fill": "F2F2F2",
            "font_family": "맑은 고딕",
        },
        "context": {"section_types": [], "text_summary": "", "use_count": 0},
        "thumbnail_path": None,
        "created_at": now,
    }

    if component_type == "header":
        base["pattern"] = {
            "item_count": 1,
            "grid": {"rows": 1, "cols": 1, "gap_inches": 0},
            "item_template": {
                "width": 12.33,
                "height": 1.3,
                "shape_type": "rect",
                "content_zones": [
                    {
                        "role": "heading",
                        "font_size": 28,
                        "bold": True,
                        "relative_top": 0.0,
                        "relative_height": 0.6,
                    },
                    {
                        "role": "body",
                        "font_size": 14,
                        "relative_top": 0.6,
                        "relative_height": 0.4,
                    },
                ],
            },
        }
    elif component_type == "footer":
        base["pattern"] = {
            "item_count": 1,
            "grid": {"rows": 1, "cols": 1, "gap_inches": 0},
            "item_template": {
                "width": 12.33,
                "height": 0.5,
                "shape_type": "rect",
                "content_zones": [
                    {
                        "role": "body",
                        "font_size": 9,
                        "relative_top": 0.0,
                        "relative_height": 1.0,
                    },
                ],
            },
        }
    elif component_type == "full-page":
        base["pattern"] = {"item_count": 1}
    else:
        # Default card-grid style
        base["pattern"] = {
            "item_count": 3,
            "orientation": "horizontal",
            "grid": {"rows": 1, "cols": 3, "gap_inches": 0.3},
            "item_template": {
                "width": 3.5,
                "height": 4.0,
                "shape_type": "roundRect",
                "border_radius_inches": 0.1,
                "content_zones": [
                    {
                        "role": "number",
                        "font_size": 24,
                        "bold": True,
                        "relative_top": 0.0,
                        "relative_height": 0.15,
                        "alignment": "CENTER",
                    },
                    {
                        "role": "heading",
                        "font_size": 16,
                        "bold": True,
                        "relative_top": 0.15,
                        "relative_height": 0.15,
                    },
                    {
                        "role": "body",
                        "font_size": 11,
                        "bullet": True,
                        "relative_top": 0.35,
                        "relative_height": 0.65,
                    },
                ],
            },
        }

    return base


def main():
    parser = argparse.ArgumentParser(
        description="컴포넌트 라이브러리에서 조건에 맞는 컴포넌트를 검색한다.",
    )
    parser.add_argument("--type", required=True, help="컴포넌트 타입 (예: card-grid)")
    parser.add_argument("--keywords", default=None, help="쉼표로 구분된 섹션 키워드")
    parser.add_argument("--color", default=None, help="Accent 색상 hex 코드")
    parser.add_argument("--limit", type=int, default=5, help="최대 결과 수")
    parser.add_argument("--get", default=None, help="특정 컴포넌트 ID의 전체 JSON 조회")

    args = parser.parse_args()

    if args.get:
        component = get_component(args.get)
        if component is None:
            print(f"Component not found: {args.get}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(component, ensure_ascii=False, indent=2))
        return

    keywords = args.keywords.split(",") if args.keywords else None
    results = search_components(
        component_type=args.type,
        section_keywords=keywords,
        accent_color=args.color,
        limit=args.limit,
    )

    if not results:
        print(f"No components found for type '{args.type}'", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
