#!/usr/bin/env python3
"""
LLM-enhanced slide segmentation: 좌표 정규화 + 정렬 분석 + 장식 전처리 + LLM 1회 호출.

슬라이드당 LLM 1회 호출로 5가지 영역을 동시 해결:
  1. 세그멘테이션 (shape 그룹핑 + item_count)
  2. 분류 + 타입 확장 (18개 Taxonomy semantic 분류)
  3. 관계성 추출 (컴포넌트 간 논리적 흐름)
  4. 의도 분석 (Design Intent 키워드)
  5. 텍스트 라벨링 (Hook/Data/Body/CTA 등)

규칙으로 충분한 곳(디자인 토큰, zone 분리, 장식 필터)은 변경하지 않는다.
LLM 미설정 시 규칙 기반 fallback (zero regression).

Module API:
    enhance_slide_segmentation(shapes, slide_width, slide_height, component_types, ...) -> dict
    merge_llm_with_rules(rule_segments, llm_result, shapes) -> list[dict]
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

logger = logging.getLogger(__name__)

# --- 유효한 값 목록 (검증용) ---

VALID_COMPONENT_TYPES = {
    "header",
    "footer",
    "accent-bar",
    "card-grid",
    "icon-grid",
    "timeline",
    "process-flow",
    "table-layout",
    "two-column",
    "org-chart",
    "full-page",
    "chart-area",
    # 확장 6개
    "roadmap",
    "value-prop",
    "comparison",
    "hero",
    "kpi-dashboard",
    "checklist",
}

VALID_TEXT_LABELS = {"hook", "data", "body", "cta", "label", "caption"}

VALID_RELATIONSHIP_TYPES = {
    "sequence",
    "comparison",
    "hierarchy",
    "grouping",
    "cause-effect",
    "part-whole",
}

VALID_ZONE_ROLES = {
    "heading",
    "subheading",
    "body",
    "number",
    "image",
    "icon",
    "chart",
    "table",
    "decoration",
}

VALID_SLIDE_INTENTS = {
    "educational-overview",
    "methodology-presentation",
    "team-introduction",
    "data-analysis",
    "comparison-argument",
    "call-to-action",
    "cover",
    "agenda",
    "summary",
    "detail-page",
}

# --- 장식 전처리 임계값 ---

DECORATIVE_AREA_RATIO = 0.005  # 면적 0.5% 미만
DECORATIVE_NARROW_RATIO = 0.03  # 폭/높이 3% 미만


# ============================================================
# 1. 좌표 정규화
# ============================================================


def _normalize_position(left, top, width, height, slide_w, slide_h):
    """절대 좌표(인치) → 0~1000 정규화 정수.

    LLM은 절대 좌표보다 상대적 관계를 더 잘 이해한다.
    """
    if slide_w <= 0 or slide_h <= 0:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    return {
        "x": round(left / slide_w * 1000),
        "y": round(top / slide_h * 1000),
        "w": round(width / slide_w * 1000),
        "h": round(height / slide_h * 1000),
    }


# ============================================================
# 2. 정렬 상태 분석
# ============================================================


def _detect_alignments(shapes_info):
    """shape 간 정렬 관계 감지. shapes_info는 정규화된 좌표를 가진 dict 리스트."""
    # O(n^2) — shape 수가 많으면 건너뜀 (토큰 절약 + 성능)
    if len(shapes_info) > 50:
        return []

    alignments = []
    threshold_pos = 10  # 1% 오차 허용
    threshold_size = 15  # 1.5% 오차 허용

    for i, s1 in enumerate(shapes_info):
        for j, s2 in enumerate(shapes_info):
            if i >= j:
                continue
            # Left-aligned
            if abs(s1["norm_x"] - s2["norm_x"]) < threshold_pos:
                alignments.append(f"[{i}] left-aligned with [{j}]")
            # Top-aligned
            if abs(s1["norm_y"] - s2["norm_y"]) < threshold_pos:
                alignments.append(f"[{i}] top-aligned with [{j}]")
            # Same-width
            if abs(s1["norm_w"] - s2["norm_w"]) < threshold_size:
                alignments.append(f"[{i}] same-width as [{j}]")
            # Same-height
            if abs(s1["norm_h"] - s2["norm_h"]) < threshold_size:
                alignments.append(f"[{i}] same-height as [{j}]")

    return alignments


# ============================================================
# 3. 장식 개체 전처리 (토큰 절약)
# ============================================================


def _is_decorative(shape, slide_w, slide_h):
    """장식 판별: 면적 0.5% 미만이고 텍스트 없음, 또는 좁고 텍스트 없음."""
    area_ratio = (
        (shape.width * shape.height) / (slide_w * slide_h)
        if (slide_w * slide_h) > 0
        else 0
    )
    paragraphs = shape.paragraphs if hasattr(shape, "paragraphs") else []
    has_text = any(p.text.strip() for p in paragraphs)

    if area_ratio < DECORATIVE_AREA_RATIO and not has_text:
        return True

    is_narrow = (
        shape.width < slide_w * DECORATIVE_NARROW_RATIO
        or shape.height < slide_h * DECORATIVE_NARROW_RATIO
    )
    if is_narrow and not has_text:
        return True

    return False


def _summarize_decoratives(decorative_shapes):
    """장식 shape들을 종류별로 요약 텍스트로 변환."""
    if not decorative_shapes:
        return ""

    narrow_bars = []
    small_shapes = []
    for s in decorative_shapes:
        if s.width < s.height * 0.3 or s.height < s.width * 0.3:
            narrow_bars.append(s)
        else:
            small_shapes.append(s)

    parts = []
    if narrow_bars:
        parts.append(f"{len(narrow_bars)} accent bars (narrow shapes, no text)")
    if small_shapes:
        parts.append(f"{len(small_shapes)} small decorative shapes")

    return f"[D] decorative: {', '.join(parts)}" if parts else ""


def _preprocess_decorative_shapes(shapes, slide_w, slide_h):
    """장식용 개체를 분리하여 토큰 절약용 요약 생성."""
    content_shapes = []
    decorative_shapes = []

    for shape in shapes:
        if _is_decorative(shape, slide_w, slide_h):
            decorative_shapes.append(shape)
        else:
            content_shapes.append(shape)

    deco_summary = _summarize_decoratives(decorative_shapes)
    return content_shapes, decorative_shapes, deco_summary


# ============================================================
# 4. 프롬프트 빌더
# ============================================================

SYSTEM_PROMPT = """\
You are a PowerPoint slide layout analyst. Given a list of shapes with normalized positions (0-1000 scale), text content, and font information, analyze the slide structure.

## Your 5 Tasks

1. **Segmentation**: Group shapes into logical components. Each component is a meaningful visual unit (e.g., a set of cards, a header, a table). Assign `item_count` (how many repeating items exist within).

2. **Classification**: Classify each component into one of these 18 types:
   - `header` — top section title/subtitle
   - `footer` — bottom page info
   - `accent-bar` — narrow decoration bars
   - `card-grid` — grid of similar-sized cards
   - `icon-grid` — icons paired with text
   - `timeline` — sequential steps with connectors
   - `process-flow` — flow diagram with arrows
   - `table-layout` — data table structure
   - `two-column` — left/right balanced layout
   - `org-chart` — hierarchical organization
   - `full-page` — cover/closing slide (>80% area)
   - `chart-area` — charts/graphs
   - `roadmap` — roadmap/milestones with dates
   - `value-prop` — value proposition/key benefits
   - `comparison` — comparison (As-Is vs To-Be, before/after)
   - `hero` — key message highlight (large number/text)
   - `kpi-dashboard` — KPI/metrics dashboard
   - `checklist` — checklist/requirements list

3. **Relationships**: Identify logical relationships between components:
   - `sequence` — sequential flow (1→2→3), indicated by arrows, numbers, left-to-right
   - `comparison` — contrast/comparison, symmetric layout, "vs", before/after
   - `hierarchy` — parent-child/nesting, top-down tree
   - `grouping` — same category, similar color/size, close placement
   - `cause-effect` — cause→result, arrows with context
   - `part-whole` — part of a whole, donut chart, classification

4. **Design Intent**: For each component, provide 1-3 intent keywords from:
   `step-breakdown`, `methodology-overview`, `sequential-info`, `data-comparison`,
   `value-highlight`, `team-introduction`, `timeline-visualization`,
   `section-title`, `topic-introduction`, `call-to-action`, `detail-enumeration`,
   `metric-display`, `process-visualization`, `requirement-listing`

5. **Text Labeling**: Label each zone's text with its communicative role:
   - `hook` — attention-grabbing headline/title
   - `data` — numbers/statistics/metrics (e.g., "01", "95%", "300억")
   - `body` — explanatory text/bullets
   - `cta` — call-to-action text
   - `label` — axis/category label (e.g., "As-Is", "Phase 1")
   - `caption` — supplementary note/source

## Nesting Rules

- Use `parent_component_index` to express nesting (e.g., a checklist inside a card).
- `null` = top-level component. An integer = index of the parent in `components` array.

## Output Format

Respond with a single JSON object matching this exact schema:
```json
{
  "components": [
    {
      "type": "<one of 18 types>",
      "parent_component_index": null,
      "shape_indices": [0, 1, 2],
      "item_count": 3,
      "design_intent": ["step-breakdown"],
      "semantic_summary": "short description in Korean",
      "search_tags": ["keyword1", "keyword2"],
      "items": [
        {
          "shape_indices": [0],
          "zones": [
            {"shape_index": 0, "role": "heading", "text_label": "hook"}
          ]
        }
      ]
    }
  ],
  "relationships": [
    {
      "from_component": 0,
      "to_component": 1,
      "type": "sequence",
      "description": "순차적 흐름"
    }
  ],
  "slide_intent": "educational-overview"
}
```

## Important Rules

- Every content shape must belong to exactly one component.
- `shape_indices` reference the [N] index from the input shape list.
- `item_count` must equal the number of entries in `items` array.
- Each item's `zones` must reference shapes that belong to that item's `shape_indices`.
- `search_tags` should be Korean keywords useful for retrieval.
- `slide_intent` options: `educational-overview`, `methodology-presentation`, `team-introduction`, `data-analysis`, `comparison-argument`, `call-to-action`, `cover`, `agenda`, `summary`, `detail-page`
"""


def _build_text_prompt(
    content_shapes, slide_w, slide_h, component_types, alignments, deco_summary
):
    """텍스트 기반 프롬프트 생성 (Phase 1)."""
    lines = ["Slide: 1000 x 1000 (normalized)"]
    lines.append(
        f"{len(content_shapes)} shapes{' (decorative shapes pre-grouped)' if deco_summary else ''}:"
    )

    shapes_info = []
    for idx, shape in enumerate(content_shapes):
        norm = _normalize_position(
            shape.left, shape.top, shape.width, shape.height, slide_w, slide_h
        )

        # 텍스트 추출
        paragraphs = shape.paragraphs if hasattr(shape, "paragraphs") else []
        text_parts = []
        font_info_parts = []

        for para in paragraphs:
            text = para.text.strip()
            if not text:
                continue
            text_parts.append(text)

            # 폰트 정보
            info = []
            if para.font_size:
                info.append(f"{para.font_size}pt")
            if para.bold:
                info.append("bold")
            if para.bullet:
                info.append("bullet")
            if para.color:
                info.append(f"color=#{para.color}")
            font_info_parts.append(" ".join(info))

        display_text = " | ".join(text_parts)
        if len(display_text) > 100:
            display_text = display_text[:97] + "..."
        font_desc = font_info_parts[0] if font_info_parts else ""

        line = (
            f"  [{idx}] pos=({norm['x']}, {norm['y']}) size=({norm['w']}x{norm['h']})"
        )
        if display_text:
            line += f' text="{display_text}"'
        if font_desc:
            line += f" {font_desc}"

        lines.append(line)

        shapes_info.append(
            {
                "norm_x": norm["x"],
                "norm_y": norm["y"],
                "norm_w": norm["w"],
                "norm_h": norm["h"],
            }
        )

    if deco_summary:
        lines.append(f"  {deco_summary}")

    # 정렬 정보 추가
    if alignments:
        lines.append("")
        lines.append("Alignments:")
        # 최대 20개만 (토큰 절약)
        for align in alignments[:20]:
            lines.append(f"  {align}")
        if len(alignments) > 20:
            lines.append(f"  ... and {len(alignments) - 20} more alignments")

    # 컴포넌트 타입 목록 (간결하게)
    lines.append("")
    lines.append(
        "Available component types: " + ", ".join(ct["id"] for ct in component_types)
    )

    return "\n".join(lines)


def _build_vision_prompt(content_shapes, slide_w, slide_h, component_types, image_path):
    """멀티모달 프롬프트 (Phase 4 향후 구현).

    텍스트 프롬프트와 이미지를 함께 보내는 구조.
    현재는 NotImplementedError를 발생시킨다.
    """
    raise NotImplementedError(
        "Vision prompt is planned for Phase 4. "
        "Use text-based prompt (use_vision=False) for now."
    )


# ============================================================
# 5. LLM 응답 파싱 + 검증
# ============================================================


def _parse_llm_response(raw_result, num_shapes, component_types_set=None):
    """LLM 응답 JSON을 검증하고 정제한다.

    검증 항목:
      - components 배열 존재
      - 각 component의 type이 유효한 18타입 중 하나
      - shape_indices가 0~num_shapes-1 범위 내
      - item_count == len(items) (있는 경우)
      - text_label이 유효한 6종 중 하나
      - relationships의 from/to가 components 범위 내
      - parent_component_index가 유효한 범위

    Returns:
        검증/정제된 dict (components, relationships, slide_intent)

    Raises:
        ValueError: 응답 구조가 근본적으로 잘못된 경우
    """
    if component_types_set is None:
        component_types_set = VALID_COMPONENT_TYPES

    if not isinstance(raw_result, dict):
        raise ValueError(f"LLM 응답이 dict가 아님: {type(raw_result)}")

    components = raw_result.get("components", [])
    if not isinstance(components, list) or not components:
        raise ValueError("LLM 응답에 components 배열이 없거나 비어 있음")

    valid_indices = set(range(num_shapes))
    validated_components = []
    # 원본 인덱스 → validated 인덱스 매핑 (필터링 후 인덱스 보정용)
    original_to_validated = {}

    for ci, comp in enumerate(components):
        # 타입 검증 — 유효하지 않으면 card-grid로 대체
        comp_type = comp.get("type", "card-grid")
        if comp_type not in component_types_set:
            logger.warning(
                "LLM이 알 수 없는 타입 '%s' 반환 → card-grid로 대체", comp_type
            )
            comp_type = "card-grid"

        # shape_indices 검증
        shape_indices = comp.get("shape_indices", [])
        shape_indices = [si for si in shape_indices if si in valid_indices]
        if not shape_indices:
            logger.warning("Component %d: shape_indices가 모두 범위 밖, 건너뜀", ci)
            continue

        # parent_component_index — 일단 원본 인덱스 보관 (아래서 리맵)
        raw_parent_idx = comp.get("parent_component_index")

        # items 검증/정제
        items = comp.get("items", [])
        validated_items = []
        for item in items:
            item_indices = [
                si for si in item.get("shape_indices", []) if si in valid_indices
            ]
            if not item_indices:
                continue
            zones = []
            for zone in item.get("zones", []):
                si = zone.get("shape_index")
                if si not in valid_indices:
                    continue
                role = zone.get("role", "body")
                if role not in VALID_ZONE_ROLES:
                    role = "body"
                text_label = zone.get("text_label", "body")
                if text_label not in VALID_TEXT_LABELS:
                    text_label = "body"
                zones.append(
                    {
                        "shape_index": si,
                        "role": role,
                        "text_label": text_label,
                    }
                )
            validated_items.append(
                {
                    "shape_indices": item_indices,
                    "zones": zones,
                }
            )

        # item_count 보정
        item_count = (
            len(validated_items) if validated_items else comp.get("item_count", 1)
        )

        # design_intent 검증 — 문자열 배열이면 그대로
        design_intent = comp.get("design_intent", [])
        if not isinstance(design_intent, list):
            design_intent = []

        new_idx = len(validated_components)
        original_to_validated[ci] = new_idx

        validated_components.append(
            {
                "type": comp_type,
                "_raw_parent_index": raw_parent_idx,  # 임시, 아래서 리맵
                "shape_indices": shape_indices,
                "item_count": item_count,
                "design_intent": design_intent,
                "semantic_summary": comp.get("semantic_summary", ""),
                "search_tags": comp.get("search_tags", []),
                "items": validated_items,
            }
        )

    # parent_component_index 리맵 (원본 → validated 인덱스)
    for vc in validated_components:
        raw_parent = vc.pop("_raw_parent_index", None)
        if raw_parent is not None and raw_parent in original_to_validated:
            vc["parent_component_index"] = original_to_validated[raw_parent]
        else:
            vc["parent_component_index"] = None

    # relationships 검증 — 원본 인덱스를 validated 인덱스로 리맵
    relationships = raw_result.get("relationships", [])
    validated_rels = []
    for rel in relationships:
        from_c = rel.get("from_component")
        to_c = rel.get("to_component")
        rel_type = rel.get("type", "")

        # 원본 인덱스 → validated 인덱스 변환
        mapped_from = original_to_validated.get(from_c)
        mapped_to = original_to_validated.get(to_c)

        if (
            mapped_from is not None
            and mapped_to is not None
            and rel_type in VALID_RELATIONSHIP_TYPES
        ):
            validated_rels.append(
                {
                    "from_component": mapped_from,
                    "to_component": mapped_to,
                    "type": rel_type,
                    "description": rel.get("description", ""),
                }
            )

    slide_intent = raw_result.get("slide_intent", "detail-page")
    if slide_intent not in VALID_SLIDE_INTENTS:
        slide_intent = "detail-page"

    return {
        "components": validated_components,
        "relationships": validated_rels,
        "slide_intent": slide_intent,
    }


# ============================================================
# 6. 메인 함수
# ============================================================


def enhance_slide_segmentation(
    shapes,
    slide_width,
    slide_height,
    component_types,
    slide_image_path=None,
    use_vision=False,
):
    """슬라이드 shape 목록에 대해 LLM 1회 호출로 5가지 분석을 수행한다.

    Args:
        shapes: ShapeData 객체 리스트 (inventory.py)
        slide_width: 슬라이드 너비 (인치)
        slide_height: 슬라이드 높이 (인치)
        component_types: component-types.json의 types 배열
        slide_image_path: 슬라이드 이미지 경로 (Phase 4, 현재 None)
        use_vision: 멀티모달 사용 여부 (Phase 4, 현재 False)

    Returns:
        dict: {components, relationships, slide_intent}
              각 component에 type, item_count, design_intent, items(zones+text_label) 등 포함

    Raises:
        RuntimeError: LLM 호출 실패 시
        ValueError: LLM 응답 파싱 실패 시
    """
    from llm_client import get_client

    if not shapes:
        return {"components": [], "relationships": [], "slide_intent": "detail-page"}

    # 장식 전처리 — 토큰 절약
    content_shapes, decorative_shapes, deco_summary = _preprocess_decorative_shapes(
        shapes, slide_width, slide_height
    )

    if not content_shapes:
        return {"components": [], "relationships": [], "slide_intent": "detail-page"}

    # 정규화 좌표 정보 생성 (정렬 분석용)
    shapes_info = []
    for shape in content_shapes:
        norm = _normalize_position(
            shape.left,
            shape.top,
            shape.width,
            shape.height,
            slide_width,
            slide_height,
        )
        shapes_info.append(
            {
                "norm_x": norm["x"],
                "norm_y": norm["y"],
                "norm_w": norm["w"],
                "norm_h": norm["h"],
            }
        )

    # 정렬 관계 감지
    alignments = _detect_alignments(shapes_info)

    # 프롬프트 빌드
    if use_vision and slide_image_path:
        user_prompt = _build_vision_prompt(
            content_shapes, slide_width, slide_height, component_types, slide_image_path
        )
    else:
        user_prompt = _build_text_prompt(
            content_shapes,
            slide_width,
            slide_height,
            component_types,
            alignments,
            deco_summary,
        )

    # LLM 호출
    client = get_client()
    raw_result = client.complete_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=4096,
    )

    # 응답 검증
    types_set = {ct["id"] for ct in component_types}
    result = _parse_llm_response(raw_result, len(content_shapes), types_set)

    # 전처리 결과를 캐시하여 merge 시 재계산 방지 (I2)
    result["_content_shapes"] = content_shapes
    result["_decorative_shapes"] = decorative_shapes

    return result


# ============================================================
# 7. 규칙 결과와 LLM 결과 병합
# ============================================================


def merge_llm_with_rules(rule_segments, llm_result, shapes, slide_width, slide_height):
    """규칙 기반 세그멘테이션 결과와 LLM 분석 결과를 병합한다.

    LLM 결과를 우선하되, 규칙 기반의 zone 정보(header/footer/decoration)를 보존한다.

    Args:
        rule_segments: segment_slide() 결과 (zone, shapes, bounding_box)
        llm_result: enhance_slide_segmentation() 결과
        shapes: 원본 shape 리스트 (인덱스 매핑용)
        slide_width: 슬라이드 너비
        slide_height: 슬라이드 높이

    Returns:
        list[dict]: 병합된 세그먼트 리스트. 각 세그먼트에 LLM 메타데이터 포함.
    """
    if not llm_result or not llm_result.get("components"):
        return rule_segments

    # enhance_slide_segmentation 에서 캐시된 결과 사용 (재계산 방지)
    content_shapes = llm_result.pop("_content_shapes", None)
    decorative_shapes = llm_result.pop("_decorative_shapes", None)
    if content_shapes is None or decorative_shapes is None:
        content_shapes, decorative_shapes, _ = _preprocess_decorative_shapes(
            shapes, slide_width, slide_height
        )

    # 슬라이드 레벨 메타데이터 (모든 content 세그먼트에 전파)
    slide_relationships = llm_result.get("relationships", [])
    slide_intent = llm_result.get("slide_intent", "detail-page")

    merged_segments = []
    llm_components = llm_result.get("components", [])

    for comp in llm_components:
        # LLM의 shape_indices → 실제 shape 객체 매핑
        comp_shapes = []
        for si in comp.get("shape_indices", []):
            if 0 <= si < len(content_shapes):
                comp_shapes.append(content_shapes[si])

        if not comp_shapes:
            continue

        # 규칙 기반 zone 결정 (shape들이 주로 어느 zone에 있는지)
        zone = _determine_zone(comp_shapes, slide_height)

        # bounding box 계산
        bb = _bounding_box_from_shapes(comp_shapes)

        segment = {
            "zone": zone,
            "shapes": comp_shapes,
            "bounding_box": bb,
            "is_grid": comp.get("item_count", 1) > 1,
            # LLM 메타데이터
            "llm_type": comp["type"],
            "llm_item_count": comp.get("item_count", 1),
            "llm_items": comp.get("items", []),
            "llm_design_intent": comp.get("design_intent", []),
            "llm_semantic_summary": comp.get("semantic_summary", ""),
            "llm_search_tags": comp.get("search_tags", []),
            "llm_parent_component_index": comp.get("parent_component_index"),
            # 슬라이드 레벨 메타데이터 — 모든 content 세그먼트에 전파
            "_slide_relationships": slide_relationships,
            "_slide_intent": slide_intent,
        }
        merged_segments.append(segment)

    # 장식 shape를 개별 세그먼트로 유지 (규칙 기반과 동일)
    for deco in decorative_shapes:
        merged_segments.append(
            {
                "zone": "decoration",
                "shapes": [deco],
                "bounding_box": _bounding_box_from_shapes([deco]),
            }
        )

    return merged_segments


def _determine_zone(shapes, slide_height):
    """shape 목록의 중심 Y좌표로 zone을 결정한다."""
    if not shapes:
        return "body"

    avg_center_y = sum(s.top + s.height / 2 for s in shapes) / len(shapes)
    header_y = slide_height * 0.25
    footer_y = slide_height * 0.88

    if avg_center_y <= header_y:
        return "header"
    elif avg_center_y >= footer_y:
        return "footer"
    return "body"


def _bounding_box_from_shapes(shapes):
    """shape 리스트의 bounding box 계산."""
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
