#!/usr/bin/env python3
"""
LLM을 활용하여 슬라이드 콘텐츠를 자동 생성한다.

GenAI Gateway가 설정되어 있으면 LLM으로 콘텐츠 생성,
설정이 없으면 플레이스홀더 텍스트를 생성한다.

Usage:
    from pipeline.content_generator import generate_content_for_slide

    content = generate_content_for_slide(slide_spec, positioned_components)
"""

import json
import logging

from pipeline.llm_client import is_configured

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a PwC professional proposal writer. Generate slide content in Korean.
Output valid JSON only. Follow the exact structure requested.
Keep text concise and professional — suitable for PowerPoint slides.
Use bullet points (as arrays) where appropriate.
"""


def _generate_with_llm(slide_spec: dict, positioned: list[dict]) -> list[dict]:
    """LLM으로 슬라이드 콘텐츠를 생성한다."""
    from pipeline.llm_client import get_client

    client = get_client()

    # Build prompt describing what content is needed
    components_desc = []
    for pc in positioned:
        ct = pc.get("component_type", "")
        n_items = len(pc.get("items", []))
        comp_id = pc.get("component_id", "")

        if ct == "header":
            components_desc.append(
                f'- component_id: "{comp_id}", type: "header" → '
                f'needs: {{"component_id": "{comp_id}", "title": "...", "subtitle": "..."}}'
            )
        elif ct == "footer":
            components_desc.append(
                f'- component_id: "{comp_id}", type: "footer" → '
                f'needs: {{"component_id": "{comp_id}", "page_number": "N"}}'
            )
        elif ct == "full-page":
            components_desc.append(
                f'- component_id: "{comp_id}", type: "full-page" → '
                f'needs: {{"component_id": "{comp_id}", "title": "...", "subtitle": "..."}}'
            )
        else:
            items_template = json.dumps(
                {"number": "01", "heading": "제목", "body": ["내용1", "내용2"]},
                ensure_ascii=False,
            )
            components_desc.append(
                f'- component_id: "{comp_id}", type: "{ct}", items: {n_items} → '
                f'needs: {{"component_id": "{comp_id}", "items": [{items_template}, ...]}}'
            )

    user_prompt = f"""\
슬라이드 제목: "{slide_spec.get("title", "")}"
슬라이드 타입: {slide_spec.get("slide_type", "content")}
섹션 번호: {slide_spec.get("section_number", "N/A")}
아이템 수: {slide_spec.get("item_count", "N/A")}

아래 컴포넌트들의 콘텐츠를 JSON 배열로 생성하세요:
{chr(10).join(components_desc)}

JSON 배열로 응답하세요. 각 항목은 위에 명시된 구조를 따릅니다.
body는 항상 문자열 배열입니다 (불릿 리스트).
"""

    try:
        result = client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=4096,
        )
        # Ensure it's a list
        if isinstance(result, dict):
            result = [result]
        return result
    except Exception as e:
        logger.warning("LLM 콘텐츠 생성 실패, 플레이스홀더 사용: %s", e)
        return _generate_placeholder(slide_spec, positioned)


def _generate_placeholder(slide_spec: dict, positioned: list[dict]) -> list[dict]:
    """플레이스홀더 콘텐츠를 생성한다 (LLM 없이)."""
    title = slide_spec.get("title", "제목")
    slide_type = slide_spec.get("slide_type", "content")
    slide_idx = slide_spec.get("slide_index", 0)

    content_data = []
    for pc in positioned:
        ct = pc.get("component_type", "")
        comp_id = pc.get("component_id", "")

        if ct == "header":
            content_data.append(
                {
                    "component_id": comp_id,
                    "title": title,
                    "subtitle": "",
                }
            )
        elif ct == "footer":
            content_data.append(
                {
                    "component_id": comp_id,
                    "page_number": str(slide_idx + 1),
                }
            )
        elif ct == "full-page":
            subtitle = ""
            if slide_type == "cover":
                subtitle = "PwC Korea"
            content_data.append(
                {
                    "component_id": comp_id,
                    "title": title,
                    "subtitle": subtitle,
                }
            )
        else:
            n_items = len(pc.get("items", []))
            items = []
            for i in range(n_items):
                items.append(
                    {
                        "number": f"0{i + 1}",
                        "heading": f"항목 {i + 1}",
                        "body": ["내용을 입력하세요"],
                    }
                )
            content_data.append(
                {
                    "component_id": comp_id,
                    "items": items,
                }
            )

    return content_data


def generate_content_for_slide(
    slide_spec: dict,
    positioned_components: list[dict],
    use_llm: bool = True,
) -> list[dict]:
    """슬라이드 콘텐츠를 생성한다.

    Args:
        slide_spec: skeleton_builder의 슬라이드 스펙.
        positioned_components: layout_calculator의 출력.
        use_llm: True이고 Gateway가 설정되어 있으면 LLM 사용.

    Returns:
        content_data: html_generator에 전달할 콘텐츠 목록.
    """
    if use_llm and is_configured():
        logger.info("LLM으로 콘텐츠 생성: %s", slide_spec.get("title", ""))
        return _generate_with_llm(slide_spec, positioned_components)

    return _generate_placeholder(slide_spec, positioned_components)
