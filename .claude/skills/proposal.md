---
name: proposal
description: PwC 제안서 PPT 자동화 - 인제스트, 재구성, LLM 콘텐츠 생성
---

# /proposal 스킬

PwC 제안서 PPT를 디자인 컴포넌트로 분해(인제스트)하거나, 컴포넌트 라이브러리에서 새 제안서를 재구성(생성)하는 스킬.

## 사전 조건

- 작업 디렉토리: `ppt_wizard/` (프로젝트 루트)
- Python venv: `source venv/bin/activate`
- Node.js 의존성: `node_modules/` 존재 확인

## 명령어

### /proposal ingest \<path\>

PPT 파일을 분석하여 디자인 컴포넌트를 추출하고 라이브러리에 저장한다.

**워크플로우:**

1. **입력 확인**: `<path>`가 유효한 .pptx 파일인지 확인. glob 패턴(\*.pptx)도 지원.
2. **venv 활성화 후 인제스트 실행**:
   ```bash
   source venv/bin/activate
   python scripts/ingest_pptx.py "<path>" [--source-id NAME]
   ```
   - source-id를 지정하지 않으면 파일명에서 자동 생성
3. **결과 보고**: 추출된 컴포넌트 목록을 타입별로 보여준다.
4. **썸네일 생성** (선택):
   ```bash
   python tools/thumbnail.py "<path>" "library/sources/{source_id}/thumbnails"
   ```
5. **사용자에게 썸네일 표시**: Read 도구로 생성된 썸네일 이미지를 보여준다.

**복수 파일 인제스트:**
```
/proposal ingest workspace/input/*.pptx
```
→ glob 패턴을 Python으로 확장하여 각 파일에 대해 순차 실행.

---

### /proposal create --toc "..."

목차(TOC)를 기반으로 제안서 PPT를 재구성한다.

**워크플로우:**

1. **스켈레톤 생성**:
   ```python
   from pipeline.skeleton_builder import build_skeleton
   skeleton = build_skeleton("<toc_string>")
   ```
   → 섹션별 필요 컴포넌트 타입과 파라미터(item_count 등) 출력

2. **사용자에게 스켈레톤 제시**:
   ```
   | # | 섹션 | 필요 컴포넌트 | 아이템 수 |
   |---|------|--------------|----------|
   | 0 | 표지 | full-page | - |
   | 1 | 회사소개 | header + card-grid | 3 |
   ...
   ```

3. **컴포넌트 선택** (각 body 컴포넌트에 대해):
   ```python
   from pipeline.component_selector import search_components, get_component, get_fallback_component

   results = search_components(
       component_type="card-grid",
       target_item_count=5,
       section_keywords=["방법론", "단계"],
       limit=3,
   )
   ```
   → 후보 3개를 사용자에게 제시, 선택 요청. 없으면 `get_fallback_component()` 사용.

4. **내용 입력 또는 LLM 생성**:

   **방법 A — 사용자 직접 입력:**
   각 섹션별로 필요한 내용을 사용자에게 질문.

   **방법 B — LLM 자동 생성 (.env에 GenAI Gateway 설정 시):**
   ```python
   from pipeline.content_generator import generate_content_for_slide
   content_data = generate_content_for_slide(slide_spec, positioned, use_llm=True)
   ```
   LLM이 섹션 제목에 맞는 전문적인 한국어 콘텐츠를 자동 생성.
   Gateway 미설정 시 플레이스홀더 텍스트로 대체.

5. **레이아웃 계산 + HTML 생성**:
   ```python
   from pipeline.layout_calculator import calculate_layout
   from pipeline.html_generator import generate_slide_html, save_slide_html

   positioned = calculate_layout(components_with_zones)
   html = generate_slide_html(positioned, content_data)
   save_slide_html(html, "workspace/output/slide_N.html")
   ```

6. **PPT 변환**:
   ```python
   from pipeline.reconstruct import reconstruct_slide
   reconstruct_slide("workspace/output/slide_N.html", "workspace/output/slide_N.pptx")
   ```

7. **최종 조합**:
   ```python
   from pipeline.assembler import assemble_presentation
   assemble_presentation(pptx_paths, "workspace/output/proposal.pptx")
   ```

8. **검증 + 보고**:
   ```bash
   python tools/thumbnail.py workspace/output/proposal.pptx workspace/output/preview
   ```
   → 썸네일을 사용자에게 보여주고 확인 요청

---

### /proposal status

라이브러리 현황을 보여준다.

```bash
source venv/bin/activate
python -c "
import json
from pathlib import Path
from collections import Counter
reg = json.loads(Path('library/registry.json').read_text(encoding='utf-8'))
print(f'총 {reg[\"total_components\"]}개 컴포넌트, {reg[\"total_sources\"]}개 소스')
types = Counter(c['type'] for c in reg['components'])
for t, n in types.most_common():
    print(f'  {t}: {n}개')
"
```

---

## LLM 설정 (선택사항)

LLM을 사용하면 슬라이드 콘텐츠를 자동 생성할 수 있다.

1. `.env.example`을 `.env`로 복사:
   ```bash
   cp .env.example .env
   ```
2. `.env`에서 `PwC_LLM_API_KEY`를 실제 키로 교체
3. `/proposal create` 실행 시 자동으로 LLM 콘텐츠 생성

---

## 주의사항

- 모든 스크립트는 `source venv/bin/activate` 후 실행
- 경로에 공백이 있을 수 있으므로 항상 따옴표로 감싸기
- 인제스트는 Windows에서 주로 실행 (PPT 파일이 있는 곳)
- 생성은 Mac/Windows 양쪽 모두 가능
- `library/` 변경사항은 git commit 대상 — 인제스트 후 커밋 제안
- `workspace/` 는 .gitignore 대상 — 임시 파일용
