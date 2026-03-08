# ppt_wizard

PwC 제안서 PPT 자동화 툴. 기존 PPT에서 디자인 컴포넌트를 추출하여 라이브러리를 구축하고, 이를 조합하여 새로운 제안서를 자동 생성한다.

## 핵심 개념

```
기존 PPT 파일들                    새 제안서
┌──────────┐                    ┌──────────┐
│ 제안서A   │──┐                │ 표지     │
│ 제안서B   │  │  인제스트       │ 개요     │ ← header-003 + card-grid-006
│ 제안서C   │  ├─────────→      │ 방법론   │ ← header-003 + card-grid-006 (5칸)
│ ...      │  │  컴포넌트 DB    │ 팀구성   │ ← header-003 + org-chart-002
└──────────┘  │  ┌──────┐      │ 감사     │
              └─→│library│──→  └──────────┘
                 └──────┘   재구성(Reconstruct)
```

**특징:**

- **개별 도형 독립 유지**: 페이지 이미지가 아닌, PowerPoint에서 개별 편집 가능한 shape으로 생성
- **도형 그룹 단위 패턴 추출**: "헤더 영역", "카드 그리드 영역" 등 컴포넌트별로 분리 저장
- **item_count 자동 조정**: 카드 4개 → 5개로 변경하면 그리드를 자동 재계산
- **점진적 DB 축적**: PPT를 지속 제공하면 디자인 패턴 DB가 누적
- **LLM 콘텐츠 생성**: PwC GenAI Gateway를 통해 슬라이드 내용 자동 생성 (선택사항)

---

## 빠른 시작

### 1. 설치

```bash
# 프로젝트 클론
git clone <repo-url> ppt_wizard
cd ppt_wizard

# Python 가상환경
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Node.js 의존성
npm install

# Playwright 브라우저 (HTML→PPTX 변환용)
npx playwright install chromium
```

### 2. (선택) LLM 설정

슬라이드 콘텐츠 자동 생성을 원하면 GenAI Gateway를 설정한다.

```bash
cp .env.example .env
# .env 파일에서 PwC_LLM_API_KEY를 실제 키로 교체
```

### 3. PPT 인제스트

기존 PPT에서 디자인 컴포넌트를 추출한다.

```bash
source venv/bin/activate
python scripts/ingest_pptx.py "경로/제안서.pptx"
```

출력 예시:

```
[1/4] Extracting design tokens...
[2/4] Extracting shape inventory...
[3/4] Segmenting and classifying 58 slides...
[4/4] Saving 166 components to library...

==================================================
Ingest Complete
==================================================
  Source ID:    proposal-example
  Slides:       58
  Components:   166
  By type:
    header: 57
    card-grid: 79
    accent-bar: 24
    process-flow: 3
    full-page: 2
    table-layout: 1
```

### 4. 제안서 생성

목차를 기반으로 새 제안서 PPT를 생성한다.

```bash
# E2E 테스트 스크립트로 전체 파이프라인 실행
source venv/bin/activate
python scripts/e2e_test.py
```

출력: `workspace/output/final_presentation.pptx`

---

## 상세 사용법

### 인제스트 파이프라인

PPT 파일 하나를 컴포넌트 라이브러리로 변환하는 전체 과정.

```
PPT 파일
  │
  ├─ extract_design_tokens.py   테마 색상/폰트 추출
  │
  ├─ inventory.py               shape 인벤토리 (위치, 크기, 텍스트, 폰트)
  │
  ├─ segment_slide.py           공간 클러스터링 → 도형 그룹
  │   ├─ header zone (상단 25%)
  │   ├─ body zone (중앙)
  │   │   ├─ grid 패턴 감지 (3+ 유사 크기)
  │   │   └─ proximity 그룹핑
  │   ├─ footer zone (하단 12%)
  │   └─ decoration (accent bar, 로고)
  │
  ├─ classify_component.py      컴포넌트 타입 분류
  │   ├─ 공간 휴리스틱 (zone, shape 수, 크기)
  │   ├─ 텍스트 분석 (차트, 테이블, 순번)
  │   └─ 키워드 매칭 (component-types.json)
  │
  └─ extract_component_pattern.py   디자인 패턴 추출
      ├─ grid 차원 (rows, cols, gap)
      ├─ item_template (width, height, content_zones)
      └─ design_tokens (colors, fonts)
```

**복수 파일 인제스트:**

```bash
# 디렉토리 내 모든 PPT
for f in workspace/input/*.pptx; do
  python scripts/ingest_pptx.py "$f"
done
```

**특정 소스 ID 지정:**

```bash
python scripts/ingest_pptx.py "제안서.pptx" --source-id "2025-audit-samsung"
```

### 재구성 파이프라인

라이브러리의 컴포넌트를 조합하여 새 PPT를 생성하는 과정.

```
TOC 문자열
  │
  ├─ skeleton_builder.py        슬라이드 구성안 생성
  │   입력: "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)"
  │   출력: 슬라이드별 필요 컴포넌트 타입 + item_count
  │
  ├─ component_selector.py      라이브러리 검색
  │   ├─ 타입 매칭 (10점)
  │   ├─ item_count 근접도 (최대 8점)
  │   ├─ horizontal 배치 우대 (5점)
  │   ├─ 키워드 매칭 (5점/키워드)
  │   └─ 색상 유사도 (최대 3점)
  │
  ├─ layout_calculator.py       좌표 계산
  │   ├─ header/body/footer 영역 분할
  │   ├─ item_count 변경 시 그리드 재계산
  │   └─ 다중 body 컴포넌트 수직 분할
  │
  ├─ content_generator.py       콘텐츠 생성
  │   ├─ LLM 모드: GenAI Gateway로 전문 한국어 콘텐츠 생성
  │   └─ 플레이스홀더 모드: 기본 텍스트 삽입
  │
  ├─ html_generator.py          HTML 슬라이드 생성
  │   ├─ 컴포넌트별 절대 좌표 배치
  │   ├─ design_tokens 적용 (색상, 폰트)
  │   └─ content_zones 렌더링 (제목, 본문, 불릿)
  │
  ├─ reconstruct.py             PPTX 변환
  │   ├─ html2pptx.js (Playwright + pptxgenjs)
  │   └─ 한국어 폰트 후처리 (<a:ea> 태그 교정)
  │
  └─ assembler.py               최종 조합
      ├─ 개별 슬라이드 PPTX → 하나의 프레젠테이션
      ├─ shape + 이미지 관계 복사
      └─ 배경 복사
```

### Python API 사용법

스크립트 내에서 파이프라인 모듈을 직접 호출할 수 있다.

```python
import sys
sys.path.insert(0, ".")

from pipeline.skeleton_builder import build_skeleton
from pipeline.component_selector import search_components, get_component, get_fallback_component
from pipeline.layout_calculator import calculate_layout
from pipeline.html_generator import generate_slide_html, save_slide_html
from pipeline.content_generator import generate_content_for_slide
from pipeline.reconstruct import reconstruct_slide
from pipeline.assembler import assemble_presentation

# 1. 스켈레톤 생성
skeleton = build_skeleton("1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)")

# 2. 슬라이드별 컴포넌트 선택
for slide in skeleton:
    components_with_zones = []
    for comp_spec in slide["components"]:
        results = search_components(
            component_type=comp_spec["type"],
            target_item_count=slide.get("item_count"),
            limit=1,
        )
        if results:
            comp = get_component(results[0]["id"])
        else:
            comp = get_fallback_component(comp_spec["type"])

        entry = {"component": comp, "zone": comp_spec["zone"]}
        if comp_spec["zone"] == "body" and slide.get("item_count"):
            entry["target_item_count"] = slide["item_count"]
        components_with_zones.append(entry)

    # 3. 레이아웃 계산
    positioned = calculate_layout(components_with_zones)

    # 4. 콘텐츠 생성 (LLM 또는 플레이스홀더)
    content = generate_content_for_slide(slide, positioned, use_llm=True)

    # 5. HTML 생성 → PPTX 변환
    html = generate_slide_html(positioned, content)
    save_slide_html(html, f"workspace/output/slide_{slide['slide_index']}.html")
    reconstruct_slide(
        f"workspace/output/slide_{slide['slide_index']}.html",
        f"workspace/output/slide_{slide['slide_index']}.pptx",
    )

# 6. 최종 조합
from pathlib import Path
pptx_files = sorted(Path("workspace/output").glob("slide_*.pptx"))
assemble_presentation(pptx_files, "workspace/output/proposal.pptx")
```

### Claude Code 스킬 사용법

Claude Code에서 `/proposal` 명령으로 사용할 수 있다.

```
# PPT 인제스트
/proposal ingest workspace/input/제안서.pptx

# 제안서 생성
/proposal create --toc "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명) 4.일정 5.보수"

# 라이브러리 현황
/proposal status
```

---

## 프로젝트 구조

```
ppt_wizard/
├── CLAUDE.md                    # Claude Code 설정
├── README.md                    # 이 파일
├── requirements.txt             # Python 의존성
├── package.json                 # Node.js 의존성
├── .env.example                 # GenAI Gateway 설정 템플릿
├── .gitignore
│
├── config/
│   └── component-types.json     # 12개 컴포넌트 타입 정의 + 키워드
│
├── scripts/                     # 인제스트 파이프라인
│   ├── ingest_pptx.py           # 메인 오케스트레이터
│   ├── extract_design_tokens.py # 테마 색상/폰트 추출
│   ├── segment_slide.py         # 슬라이드 → 도형 그룹 분할
│   ├── classify_component.py    # 도형 그룹 → 컴포넌트 타입 분류
│   ├── extract_component_pattern.py  # 디자인 패턴 추출
│   └── e2e_test.py              # E2E 테스트 스크립트
│
├── pipeline/                    # 재구성 파이프라인
│   ├── skeleton_builder.py      # TOC → 슬라이드 구성안
│   ├── component_selector.py    # 라이브러리 검색 + 폴백
│   ├── layout_calculator.py     # 컴포넌트 좌표 계산
│   ├── content_generator.py     # LLM/플레이스홀더 콘텐츠 생성
│   ├── html_generator.py        # HTML 슬라이드 생성
│   ├── reconstruct.py           # HTML → PPTX 변환
│   ├── assembler.py             # 다수 슬라이드 조합
│   └── llm_client.py            # PwC GenAI Gateway 클라이언트
│
├── tools/                       # PPTX 도구 (크로스플랫폼)
│   ├── html2pptx.js             # HTML → 독립 OOXML shape 변환
│   ├── inventory.py             # shape 인벤토리 추출
│   ├── thumbnail.py             # 썸네일 생성
│   ├── unpack.py / pack.py      # PPTX ↔ XML
│   ├── validate.py              # OOXML 유효성 검증
│   └── rearrange.py             # 슬라이드 재배치
│
├── library/                     # 디자인 컴포넌트 DB (git 추적)
│   ├── registry.json            # 전체 컴포넌트 인덱스
│   ├── components/              # 타입별 JSON 컴포넌트
│   │   ├── header/
│   │   ├── card-grid/
│   │   ├── timeline/
│   │   ├── table-layout/
│   │   └── ...
│   └── sources/                 # 인제스트 소스별 메타데이터
│
├── workspace/                   # 작업 디렉토리 (.gitignore)
│   ├── input/                   # 인제스트할 PPT
│   └── output/                  # 생성된 HTML/PPTX
│
└── .claude/
    └── skills/
        └── proposal.md          # /proposal 스킬 정의
```

---

## 컴포넌트 타입

| 타입           | 이름            | 설명                                   |
| -------------- | --------------- | -------------------------------------- |
| `header`       | 헤더/제목 영역  | 슬라이드 상단 제목 + 부제 + accent bar |
| `card-grid`    | 카드 그리드     | N개 카드의 수평/수직 배열              |
| `timeline`     | 타임라인        | 순차적 단계/일정 표현                  |
| `table-layout` | 표/테이블       | 데이터 테이블                          |
| `icon-grid`    | 아이콘+텍스트   | 아이콘과 텍스트 조합                   |
| `two-column`   | 2단 레이아웃    | 좌우 대비 레이아웃                     |
| `process-flow` | 프로세스 플로우 | 화살표/커넥터 기반 흐름도              |
| `org-chart`    | 조직도          | 팀/인력 구성                           |
| `footer`       | 푸터            | 페이지 번호, confidential 표시         |
| `accent-bar`   | 장식 바         | 색상 구분선/장식                       |
| `full-page`    | 전체 페이지     | 표지/감사 페이지                       |
| `chart-area`   | 차트 영역       | 그래프/차트                            |

---

## 크로스플랫폼 (Mac ↔ Windows)

```
[Mac (개발)] ←── git ──→ [PwC Windows (실행)]

Mac: 코드 개발 → git push
Windows: git pull → pip install → npm install
         workspace/input/에 PPT → /proposal ingest
         → library/ 에 컴포넌트 생성
         → git push

Mac: git pull → library/ 수신 → /proposal create 가능
```

- `library/` 폴더는 git 추적 대상 (양방향 동기화)
- `workspace/` 는 `.gitignore` (PPT 원본은 git에 올리지 않음)
- 모든 경로는 `pathlib.Path` 사용
- 인코딩은 `utf-8` 명시

---

## LLM 연동 (PwC GenAI Gateway)

슬라이드 콘텐츠를 LLM으로 자동 생성할 수 있다. 선택사항이며, 미설정 시 플레이스홀더 텍스트가 삽입된다.

### 설정

```bash
cp .env.example .env
```

`.env` 파일:

```
GENAI_BASE_URL=https://genai-sharedservice-americas.pwcinternal.com
PwC_LLM_API_KEY=your-actual-api-key
PwC_LLM_MODEL=bedrock.anthropic.claude-sonnet-4-6
```

### 사용 가능한 모델

| 모델 ID                               | 설명                     |
| ------------------------------------- | ------------------------ |
| `bedrock.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (기본) |
| `vertex_ai.gemini-3.1-pro-preview`    | Gemini 3.1 Pro Preview   |

### 동작 방식

```python
from pipeline.content_generator import generate_content_for_slide

# LLM이 설정되어 있으면 자동으로 LLM 사용
content = generate_content_for_slide(slide_spec, positioned, use_llm=True)

# 강제로 플레이스홀더 사용
content = generate_content_for_slide(slide_spec, positioned, use_llm=False)
```

LLM은 슬라이드 제목과 컴포넌트 구조를 보고 전문적인 한국어 콘텐츠를 생성한다. 생성된 콘텐츠는 즉시 PPT 파이프라인에 투입된다.

---

## 트러블슈팅

| 문제                                       | 원인                   | 해결                                         |
| ------------------------------------------ | ---------------------- | -------------------------------------------- |
| `ModuleNotFoundError: defusedxml`          | venv 미활성화          | `source venv/bin/activate`                   |
| `html2pptx failed: dimensions don't match` | 슬라이드 크기 불일치   | `reconstruct.py`가 자동으로 커스텀 크기 설정 |
| `No components found for type 'footer'`    | PPT에 footer zone 없음 | 자동으로 fallback 컴포넌트 사용              |
| `GenAI 요청 실패`                          | API 키 만료/미설정     | `.env` 확인, 없으면 플레이스홀더로 대체      |
| 한국어 폰트 깨짐                           | OOXML 폰트 태그 누락   | `reconstruct.py`가 자동으로 `<a:ea>` 패치    |
| `playwright` 브라우저 없음                 | chromium 미설치        | `npx playwright install chromium`            |

---

## 의존성

### Python (requirements.txt)

- `python-pptx`: PPT 파일 읽기/쓰기
- `Pillow`: 이미지 처리 (썸네일)
- `defusedxml`: 안전한 XML 파싱 (테마 추출)
- `markitdown`: PPT 텍스트 마크다운 변환
- `six`: Python 호환성

### Node.js (package.json)

- `pptxgenjs`: PPT 생성 엔진
- `playwright`: 헤드리스 브라우저 (HTML 렌더링)
- `sharp`: 이미지 처리
