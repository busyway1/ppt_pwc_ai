#!/usr/bin/env python3
"""
목차(TOC) 문자열을 파싱하여 슬라이드 구성 계획(skeleton)을 생성한다.

Usage:
    python pipeline/skeleton_builder.py "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)"
"""

import argparse
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_TYPES_PATH = PROJECT_ROOT / "config" / "component-types.json"


def _load_component_types() -> list[dict]:
    """config/component-types.json에서 컴포넌트 타입 정의를 로드한다."""
    if not COMPONENT_TYPES_PATH.exists():
        return []
    data = json.loads(COMPONENT_TYPES_PATH.read_text(encoding="utf-8"))
    return data.get("types", [])


def _parse_toc_sections(toc_string: str) -> list[dict]:
    """TOC 문자열을 섹션 목록으로 파싱한다.

    "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)"
    → [
        {"section_number": 1, "title": "회사소개", "params": []},
        {"section_number": 2, "title": "감사방법론", "params": ["5단계"]},
        {"section_number": 3, "title": "팀구성", "params": ["6명"]},
      ]

    다중 단어 제목도 지원: "1.회사 소개 2.감사 방법론(5단계)"
    """
    # 패턴: 숫자 + 구분자(. 또는 )) + 제목(다음 숫자+구분자 또는 끝까지)
    # 제목 부분에서 괄호 내 파라미터를 별도 추출
    pattern = r"(\d+)\s*[.\)]\s*(.*?)(?=\s*\d+\s*[.\)]|$)"
    matches = re.findall(pattern, toc_string.strip())

    sections = []
    for num_str, raw_title in matches:
        raw_title = raw_title.strip()
        if not raw_title:
            continue

        # 제목에서 괄호 파라미터 추출 (마지막 괄호만)
        params = []
        param_match = re.search(r"\(([^)]+)\)\s*$", raw_title)
        if param_match:
            params_str = param_match.group(1)
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            raw_title = raw_title[: param_match.start()].strip()

        sections.append(
            {
                "section_number": int(num_str),
                "title": raw_title,
                "params": params,
            }
        )

    return sections


def _extract_item_count(params: list[str]) -> int | None:
    """파라미터에서 아이템 수를 추출한다. 예: '5단계' → 5, '6명' → 6."""
    for p in params:
        match = re.match(r"(\d+)", p)
        if match:
            return int(match.group(1))
    return None


def _infer_component_types(
    title: str,
    params: list[str],
    component_types: list[dict],
) -> list[str]:
    """제목과 파라미터로부터 필요한 컴포넌트 타입을 추론한다.

    가장 많은 키워드가 매칭된 타입 하나만 반환하여 body 컴포넌트 충돌을 방지한다.
    """
    search_text = title + " " + " ".join(params)
    scored: dict[str, int] = {}

    for ct in component_types:
        ct_id = ct.get("id", "")
        # header/footer/accent-bar/full-page는 키워드 매칭으로 추론하지 않음
        if ct_id in ("header", "footer", "accent-bar", "full-page"):
            continue
        keywords = ct.get("keywords", [])
        match_count = sum(1 for kw in keywords if kw and kw in search_text)
        if match_count > 0:
            scored[ct_id] = match_count

    if not scored:
        return ["card-grid"]

    # 가장 높은 점수의 타입 하나만 반환
    best_type = max(scored, key=scored.get)
    return [best_type]


def build_skeleton(
    toc_string: str,
    component_types: list[dict] | None = None,
) -> list[dict]:
    """TOC 문자열을 파싱하여 슬라이드 구성 계획을 생성한다.

    Args:
        toc_string: "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)" 형식의 문자열.
        component_types: 컴포넌트 타입 정의 목록. None이면 파일에서 로드.

    Returns:
        슬라이드 스펙 목록:
        [
            {
                "slide_index": 0,
                "slide_type": "cover",
                "section_number": null,
                "title": "표지",
                "components": [{"zone": "body", "type": "full-page"}],
                "item_count": null,
            },
            ...
        ]
    """
    if component_types is None:
        component_types = _load_component_types()

    sections = _parse_toc_sections(toc_string)
    slides = []

    # 슬라이드 0: 표지
    slides.append(
        {
            "slide_index": 0,
            "slide_type": "cover",
            "section_number": None,
            "title": "표지",
            "components": [{"zone": "body", "type": "full-page"}],
            "item_count": None,
        }
    )

    # 본문 슬라이드
    for section in sections:
        body_types = _infer_component_types(
            section["title"], section["params"], component_types
        )
        item_count = _extract_item_count(section["params"])

        components = [
            {"zone": "header", "type": "header"},
        ]
        for bt in body_types:
            components.append({"zone": "body", "type": bt})
        components.append({"zone": "footer", "type": "footer"})

        slides.append(
            {
                "slide_index": len(slides),
                "slide_type": "content",
                "section_number": section["section_number"],
                "title": section["title"],
                "components": components,
                "item_count": item_count,
            }
        )

    # 마지막 슬라이드: 감사 페이지
    slides.append(
        {
            "slide_index": len(slides),
            "slide_type": "thank_you",
            "section_number": None,
            "title": "감사합니다",
            "components": [{"zone": "body", "type": "full-page"}],
            "item_count": None,
        }
    )

    return slides


def main():
    parser = argparse.ArgumentParser(
        description="목차(TOC) 문자열을 파싱하여 슬라이드 구성 계획을 생성한다.",
    )
    parser.add_argument(
        "toc",
        help='TOC 문자열 (예: "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)")',
    )

    args = parser.parse_args()
    result = build_skeleton(args.toc)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
