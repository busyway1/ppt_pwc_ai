# ppt_wizard

PwC 제안서 PPT 자동화 툴. 기존 PPT에서 **슬라이드/개체 단위**로 디자인 컴포넌트를 추출하여 라이브러리를 구축하고, 이를 조합하여 새로운 제안서를 자동 생성한다.

## 핵심 개념: 개체(컴포넌트) 단위 저장

> **PPT 파일 전체를 저장하는 것이 아니다.** 슬라이드 안의 도형 그룹(컴포넌트)을 분리하여 독립적인 디자인 패턴으로 저장한다.

```
하나의 슬라이드                         library/에 저장되는 것
┌─────────────────────────┐
│  [세무조정 개요]  ← 헤더 │───→  header-023.json     (제목 패턴)
│                          │
│ ┌──────┐┌──────┐┌──────┐│
│ │ 01   ││ 02   ││ 03   ││───→  card-grid-045.json  (3칸 카드 패턴)
│ │ 개념 ││ 절차 ││ 유의 ││       - item_count: 3
│ │ ...  ││ ...  ││ ...  ││       - grid: 1행 3열
│ └──────┘└──────┘└──────┘│       - item_template: 번호+제목+본문
│                          │
│ ▌장식바                  │───→  accent-bar-012.json  (좌측 바 패턴)
│                          │
│  Confidential | p.5      │───→  footer-001.json      (푸터 패턴)
└─────────────────────────┘
```

**저장되는 것:**

- 도형 그룹의 **레이아웃 패턴** (그리드 구조, 간격, 상대 위치)
- **디자인 토큰** (색상, 폰트 크기, 정렬)
- **콘텐츠 영역 구조** (번호 → 제목 → 본문의 zone 배치)
- 원본 텍스트 요약 (검색용)

**저장되지 않는 것:**

- PPT 파일 원본
- 슬라이드 이미지/스크린샷
- 개별 도형의 XML

이 방식의 장점:

- 한 슬라이드에서 **여러 컴포넌트**가 독립적으로 추출됨 (58슬라이드 → 166컴포넌트)
- 서로 다른 PPT의 컴포넌트를 **자유롭게 조합** 가능 (A의 헤더 + B의 카드 + C의 푸터)
- `item_count`만 바꾸면 그리드가 **자동 재계산**됨 (카드 3개 → 5개)

---

## PwC 노트북에서 디자인 DB 확장하기

### 전체 흐름

```
[PwC 노트북]

1. 기존 제안서 PPT 준비
         │
         ▼
2. python scripts/ingest_pptx.py "제안서.pptx"
         │
         │  슬라이드별로:
         │  ┌─────────────────────────────────────────────┐
         │  │ (a) 테마 색상/폰트 추출 (XML 파싱)          │
         │  │ (b) 모든 도형의 위치/크기/텍스트 추출       │
         │  │ (c) 도형을 공간적으로 그룹핑 (세그먼테이션)  │
         │  │ (d) [LLM 있으면] 의미 분석으로 그룹핑 보강  │
         │  │ (e) 각 그룹을 18개 타입 중 하나로 분류      │
         │  │ (f) 디자인 패턴 추출 (그리드, 템플릿, 토큰) │
         │  └─────────────────────────────────────────────┘
         │
         ▼
3. library/ 에 컴포넌트 JSON 파일들 생성
         │
         ▼
4. git add library/ && git commit && git push
         │
         ▼
   [GitHub] ←→ 다른 환경에서 git pull로 DB 공유
```

### Step 1: 환경 설정 (최초 1회)

```bash
# 프로젝트 클론
git clone https://github.com/busyway1/ppt_pwc_ai.git ppt_wizard
cd ppt_wizard

# Python 가상환경
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Node.js 의존성 (PPT 생성 시 필요)
npm install
npx playwright install chromium
```

### Step 2: (선택) LLM 설정 — 인제스트 품질 향상

LLM을 설정하면 인제스트 시 **의미 기반 분석**이 추가된다. 없어도 규칙 기반으로 동작하지만, LLM이 있으면 품질이 크게 향상된다.

```bash
cp .env.example .env
# .env 파일 편집:
#   GENAI_BASE_URL=https://genai-sharedservice-americas.pwcinternal.com
#   PwC_LLM_API_KEY=실제-API-키
#   PwC_LLM_MODEL=bedrock.anthropic.claude-sonnet-4-6
```

| LLM 없음 (규칙 기반)       | LLM 있음 (의미 분석)               |
| -------------------------- | ---------------------------------- |
| 도형 크기/위치로 그룹핑    | + 텍스트 의미로 정확한 그룹핑      |
| 12개 기본 타입 분류        | 18개 타입 (roadmap, comparison 등) |
| content zone = 전부 "body" | hook/data/body/cta 등 세분화       |
| 컴포넌트 간 관계 없음      | 순차/비교/계층 관계 추출           |
| 의도 분석 없음             | design_intent 키워드 생성          |

### Step 3: PPT 인제스트 (DB 확장)

```bash
source venv/bin/activate

# 단일 파일 인제스트
python scripts/ingest_pptx.py "경로/제안서.pptx"

# 소스 ID 지정 (나중에 어디서 왔는지 추적용)
python scripts/ingest_pptx.py "제안서.pptx" --source-id "2025-audit-samsung"

# 디렉토리 내 모든 PPT 일괄 인제스트
for f in workspace/input/*.pptx; do
  python scripts/ingest_pptx.py "$f"
done
```

**출력 예시:**

```
[1/4] Extracting design tokens...
[2/4] Extracting shape inventory...
[*] LLM 세그멘테이션 활성화 (슬라이드당 1회 호출)
[3/4] Segmenting and classifying 58 slides...
[4/4] Saving 166 components to library...

==================================================
Ingest Complete
==================================================
  Source ID:    2025-audit-samsung
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

### Step 4: 결과 확인

인제스트 후 `library/` 디렉토리에 컴포넌트가 생성된다.

```
library/
├── registry.json                    # 전체 인덱스 (검색용)
├── components/
│   ├── header/
│   │   ├── header-001.json          # 슬라이드 0의 헤더 패턴
│   │   ├── header-002.json          # 슬라이드 1의 헤더 패턴
│   │   └── ...
│   ├── card-grid/
│   │   ├── card-grid-001.json       # 3칸 카드 패턴
│   │   ├── card-grid-002.json       # 4칸 카드 패턴
│   │   └── ...
│   ├── process-flow/
│   ├── table-layout/
│   ├── accent-bar/
│   └── ...
└── sources/
    └── 2025-audit-samsung/
        ├── metadata.json            # 인제스트 요약
        └── design-tokens.json       # 원본 PPT의 테마 색상/폰트
```

**컴포넌트 JSON 구조 예시** (`card-grid-045.json`):

```json
{
  "id": "card-grid-045",
  "type": "card-grid",
  "source": {
    "source_id": "2025-audit-samsung",
    "filename": "감사제안서_삼성.pptx",
    "slide_index": 12,
    "region": { "left": 0.5, "top": 1.5, "width": 12.3, "height": 5.0 }
  },
  "pattern": {
    "item_count": 4,
    "orientation": "horizontal",
    "grid": { "rows": 1, "cols": 4, "gap_inches": 0.3 },
    "item_template": {
      "width": 2.8,
      "height": 4.0,
      "content_zones": [
        {
          "role": "number",
          "text_label": "data",
          "relative_top": 0.0,
          "relative_height": 0.15
        },
        {
          "role": "heading",
          "text_label": "hook",
          "relative_top": 0.15,
          "relative_height": 0.15
        },
        {
          "role": "body",
          "text_label": "body",
          "relative_top": 0.35,
          "relative_height": 0.65
        }
      ]
    }
  },
  "design_tokens": {
    "accent_color": "D04A02",
    "item_fill": "F2F2F2",
    "text_color": "2D2D2D"
  },
  "design_intent": ["step-breakdown", "methodology-overview"],
  "relationships": [
    {
      "from_component": 1,
      "to_component": 1,
      "type": "sequence",
      "description": "카드 간 순차 흐름"
    }
  ],
  "context": {
    "text_summary": "감사 방법론 4단계: 계획수립, 현장감사, 보고, 후속관리",
    "search_tags": ["감사", "방법론", "4단계"],
    "slide_intent": "methodology-presentation"
  }
}
```

핵심: **PPT 파일 자체가 아니라, 슬라이드 안의 도형 그룹에서 추출한 레이아웃 패턴만 저장한다.**

### Step 5: Git으로 DB 공유

```bash
git add library/
git commit -m "feat: 삼성 감사제안서 166개 컴포넌트 인제스트"
git push
```

다른 환경(Mac 개발 환경 등)에서 `git pull`하면 동일한 DB 사용 가능.

---

## 인제스트 파이프라인 상세

PPT 파일 하나가 컴포넌트로 분해되는 과정:

```
PPT 파일
  │
  ├─ extract_design_tokens.py    테마 색상/폰트 추출 (XML 파싱)
  │    → {colors: {accent1: "D04A02", ...}, fonts: {major: "맑은고딕", ...}}
  │
  ├─ inventory.py                모든 shape의 위치/크기/텍스트/폰트 추출
  │    → {slide-0: {shape-0: ShapeData, shape-1: ShapeData, ...}, ...}
  │
  ├─ segment_slide.py            공간 클러스터링 → 도형 그룹 (세그먼트)
  │   ├─ header zone (상단 25%)
  │   ├─ body zone (중앙)
  │   │   ├─ grid 패턴 감지 (3+ 유사 크기 shape)
  │   │   └─ proximity 그룹핑 (1" 이내 근접 shape 묶기)
  │   ├─ footer zone (하단 12%)
  │   └─ decoration (면적 0.5% 미만, 텍스트 없는 shape)
  │
  ├─ [LLM] llm_segmentation.py  의미 기반 세그멘테이션 강화
  │   ├─ 좌표 정규화 (0~1000 스케일)
  │   ├─ 정렬 관계 분석 (left-aligned, same-width 등)
  │   ├─ 장식 개체 사전 필터링 (토큰 절약)
  │   ├─ LLM 1회 호출 → 5가지 동시 분석:
  │   │   1. 세그멘테이션 (shape 그룹핑 + item_count)
  │   │   2. 분류 (18개 타입 semantic 분류)
  │   │   3. 관계성 (순차/비교/계층/그룹핑)
  │   │   4. 의도 (design_intent 키워드)
  │   │   5. 텍스트 라벨링 (hook/data/body/cta/label/caption)
  │   └─ 규칙 결과와 병합 (LLM 실패 시 규칙 기반 fallback)
  │
  ├─ classify_component.py       컴포넌트 타입 분류 (18타입)
  │   ├─ LLM 타입 있으면 바로 사용
  │   └─ 없으면 규칙 기반: zone → shape 특성 → 키워드 → 기본값
  │
  └─ extract_component_pattern.py   디자인 패턴 추출
      ├─ grid 차원 (rows, cols, gap)
      ├─ item_template (width, height, content_zones + text_label)
      ├─ design_tokens (colors, fonts)
      ├─ design_intent, search_tags, relationships
      └─ → library/components/{type}/{id}.json 으로 저장
```

---

## 제안서 생성 (Reconstruct)

라이브러리의 컴포넌트를 조합하여 새 PPT를 생성하는 과정.

```
TOC 문자열 "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명)"
  │
  ├─ skeleton_builder.py        슬라이드 구성안 생성
  │   출력: 슬라이드별 필요 컴포넌트 타입 + item_count
  │
  ├─ component_selector.py      라이브러리 Multi-Vector 검색
  │   ├─ 타입 매칭 (10점)
  │   ├─ design_intent 교집합 (8점/intent)
  │   ├─ item_count 근접도 (최대 8점)
  │   ├─ slide_intent 일치 (6점)
  │   ├─ search_tags 매칭 (5점/tag)
  │   ├─ horizontal 배치 우대 (5점)
  │   └─ 색상 유사도 (최대 3점)
  │
  ├─ layout_calculator.py       좌표 계산 (item_count 변경 시 그리드 재계산)
  ├─ content_generator.py       LLM 콘텐츠 생성 또는 플레이스홀더
  ├─ html_generator.py          HTML 슬라이드 생성
  ├─ reconstruct.py             HTML → PPTX 변환 (pptxgenjs)
  └─ assembler.py               다수 슬라이드 → 하나의 프레젠테이션
```

```bash
# E2E 테스트 (전체 파이프라인 실행)
source venv/bin/activate
python scripts/e2e_test.py

# 출력: workspace/output/final_presentation.pptx
```

### Claude Code 스킬

```
# PPT 인제스트
/proposal ingest workspace/input/제안서.pptx

# 제안서 생성
/proposal create --toc "1.회사소개 2.감사방법론(5단계) 3.팀구성(6명) 4.일정 5.보수"

# 라이브러리 현황
/proposal status
```

---

## DB 확장 실전 가이드

### 어떤 PPT를 인제스트하면 좋은가?

| 우선순위 | PPT 종류               | 이유                                |
| -------- | ---------------------- | ----------------------------------- |
| **높음** | PwC 제안서 (최종본)    | 깔끔한 레이아웃, 일관된 디자인 토큰 |
| **높음** | 산업별 다양한 제안서   | 컴포넌트 타입 다양성 확보           |
| 중간     | 내부 교육자료          | card-grid, process-flow 패턴 풍부   |
| 중간     | 경영진 보고서          | kpi-dashboard, hero 패턴 확보       |
| 낮음     | 외부 발표자료          | PwC 디자인 토큰과 불일치 가능       |
| **제외** | 이미지만 있는 슬라이드 | shape 텍스트가 없어 패턴 추출 불가  |

### 인제스트할수록 좋아지는 것

```
PPT 1개 인제스트 (58슬라이드)
  → 166 컴포넌트
  → 대부분 header + card-grid

PPT 5개 인제스트 (다양한 산업)
  → ~800 컴포넌트
  → timeline, process-flow, org-chart 등 다양
  → 같은 card-grid라도 3칸/4칸/5칸 변형 확보

PPT 20개 인제스트
  → ~3000 컴포넌트
  → roadmap, kpi-dashboard, comparison 등 희귀 타입 확보
  → 검색 시 "감사 방법론 4단계" 같은 의미 매칭 가능
```

### 현재 라이브러리 현황 확인

```bash
python -c "
import json
with open('library/registry.json') as f:
    r = json.load(f)
print(f'총 컴포넌트: {r[\"total_components\"]}개')
print(f'소스 PPT: {r[\"total_sources\"]}개')
types = {}
for c in r['components']:
    types[c['type']] = types.get(c['type'], 0) + 1
for t, n in sorted(types.items(), key=lambda x: -x[1]):
    print(f'  {t}: {n}')
"
```

### LLM 인제스트 품질 비교 테스트

```bash
# 규칙 기반 vs LLM 보강 A/B 비교 (슬라이드별 상세 출력)
python scripts/test_llm_segmentation.py "경로/제안서.pptx"

# 특정 슬라이드만 테스트
python scripts/test_llm_segmentation.py "제안서.pptx" --slides 0,3,5
```

---

## 컴포넌트 타입 (18종)

### 기본 12타입

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

### 확장 6타입 (LLM 세그멘테이션으로 분류)

| 타입            | 이름             | 설명                      | 빈출 장면                 |
| --------------- | ---------------- | ------------------------- | ------------------------- |
| `roadmap`       | 로드맵/마일스톤  | 시간축 기반 계획          | 감사 일정, 프로젝트 단계  |
| `value-prop`    | 가치 제안        | 핵심 장점/차별화 포인트   | Why PwC, 핵심 역량        |
| `comparison`    | 비교/As-Is To-Be | 전후 비교, 대칭 레이아웃  | 현행 vs 개선, 경쟁사 비교 |
| `hero`          | 핵심 메시지 강조 | 큰 숫자/문구 한 가지 강조 | "300억 절감", 핵심 KPI    |
| `kpi-dashboard` | KPI/성과 지표    | 여러 수치를 한 눈에       | 성과 보고, 실적 요약      |
| `checklist`     | 체크리스트       | 요구사항/확인 항목 나열   | RFP 요구사항, 준비물 목록 |

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
│   └── component-types.json     # 18개 컴포넌트 타입 정의 + 키워드
│
├── scripts/                     # 인제스트 파이프라인
│   ├── ingest_pptx.py           # 메인 오케스트레이터
│   ├── extract_design_tokens.py # 테마 색상/폰트 추출
│   ├── segment_slide.py         # 슬라이드 → 도형 그룹 분할 (규칙 기반)
│   ├── llm_segmentation.py      # LLM 의미 분석 세그멘테이션 (18타입)
│   ├── classify_component.py    # 도형 그룹 → 컴포넌트 타입 분류
│   ├── extract_component_pattern.py  # 디자인 패턴 추출
│   ├── test_llm_segmentation.py # A/B 비교 테스트
│   └── e2e_test.py              # E2E 테스트 스크립트
│
├── pipeline/                    # 재구성 파이프라인
│   ├── skeleton_builder.py      # TOC → 슬라이드 구성안
│   ├── component_selector.py    # Multi-Vector 라이브러리 검색
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
│   ├── components/              # 타입별 JSON 컴포넌트 (개체 단위)
│   │   ├── header/              # header-001.json, header-002.json, ...
│   │   ├── card-grid/           # card-grid-001.json, ...
│   │   ├── timeline/
│   │   ├── roadmap/             # (LLM 분류 시)
│   │   ├── kpi-dashboard/       # (LLM 분류 시)
│   │   └── ...
│   └── sources/                 # 인제스트 소스별 메타데이터
│       └── {source-id}/
│           ├── metadata.json    # 인제스트 요약 정보
│           └── design-tokens.json  # 원본 테마 색상/폰트
│
├── workspace/                   # 작업 디렉토리 (.gitignore)
│   ├── input/                   # 인제스트할 PPT (git 미추적)
│   └── output/                  # 생성된 HTML/PPTX
│
└── .claude/
    └── skills/
        └── proposal.md          # /proposal 스킬 정의
```

---

## 크로스플랫폼 (Mac ↔ PwC Windows)

```
[Mac (개발)] ←── git ──→ [PwC Windows (실행)]

Mac: 코드 개발 → git push
Windows: git pull → pip install → npm install
         workspace/input/에 PPT → python scripts/ingest_pptx.py
         → library/ 에 컴포넌트 생성
         → git add library/ → git push

Mac: git pull → library/ 수신 → 제안서 생성 가능
```

- `library/` 폴더는 git 추적 대상 (양방향 동기화)
- `workspace/` 는 `.gitignore` (PPT 원본은 git에 올리지 않음)
- 모든 경로는 `pathlib.Path` 사용
- 인코딩은 `utf-8` 명시

---

## LLM 연동 (PwC GenAI Gateway)

두 곳에서 LLM을 사용한다:

| 단계            | 용도                                 | LLM 없으면               |
| --------------- | ------------------------------------ | ------------------------ |
| **인제스트**    | 의미 기반 세그멘테이션 + 18타입 분류 | 규칙 기반 12타입 분류    |
| **제안서 생성** | 슬라이드 콘텐츠 자동 작성            | 플레이스홀더 텍스트 삽입 |

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

| 모델 ID                               | 설명                           |
| ------------------------------------- | ------------------------------ |
| `bedrock.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (기본, 권장) |
| `vertex_ai.gemini-3.1-pro-preview`    | Gemini 3.1 Pro Preview         |

### 비용 추정 (인제스트)

| 항목                 | 값                  |
| -------------------- | ------------------- |
| 슬라이드당 LLM 호출  | 1회                 |
| 호출당 토큰          | ~2,000-2,500        |
| 20슬라이드 PPT       | ~40,000-50,000 토큰 |
| 비용 (Claude Sonnet) | < $0.15/PPT         |

---

## 트러블슈팅

| 문제                              | 원인                    | 해결                                                  |
| --------------------------------- | ----------------------- | ----------------------------------------------------- |
| `ModuleNotFoundError: defusedxml` | venv 미활성화           | `source venv/bin/activate`                            |
| `html2pptx failed`                | 슬라이드 크기 불일치    | `reconstruct.py`가 자동으로 커스텀 크기 설정          |
| `No components found`             | 해당 타입 컴포넌트 없음 | 자동으로 fallback 컴포넌트 사용, 또는 PPT 더 인제스트 |
| `GenAI 요청 실패`                 | API 키 만료/미설정      | `.env` 확인, 없으면 규칙 기반으로 대체                |
| 한국어 폰트 깨짐                  | OOXML 폰트 태그 누락    | `reconstruct.py`가 자동으로 `<a:ea>` 패치             |
| `playwright` 브라우저 없음        | chromium 미설치         | `npx playwright install chromium`                     |
| 인제스트 시 `card-grid`만 생성됨  | LLM 미설정              | `.env` 설정하면 18타입 분류 가능                      |

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
