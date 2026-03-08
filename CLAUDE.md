# ppt_wizard

PwC 제안서 PPT 자동화 툴. Design Component Library + Reconstruct Engine 접근.

## 도구 경로

- 모든 도구는 프로젝트 내 `tools/` 디렉토리 참조
- 인제스트 스크립트: `scripts/` 디렉토리
- 파이프라인 스크립트: `pipeline/` 디렉토리
- 라이브러리 DB: `library/` 디렉토리 (git 추적 대상)
- 컴포넌트 타입 정의: `config/component-types.json`
- LLM 클라이언트: `pipeline/llm_client.py` (PwC GenAI Gateway)
- 콘텐츠 생성기: `pipeline/content_generator.py` (LLM 또는 플레이스홀더)

## 실행 환경

- Python venv: `source venv/bin/activate` 필수
- Node.js: `npm install` (pptxgenjs, playwright, sharp)
- LLM (선택): `.env`에 GenAI Gateway 키 설정

## 스킬

- `/proposal ingest <path>`: PPT를 디자인 컴포넌트로 분해하여 library에 저장
- `/proposal create --toc "..."`: 목차 기반으로 제안서 PPT 재구성
- `/proposal status`: 라이브러리 현황 조회

## 크로스플랫폼 규칙

- 경로: `pathlib.Path` 사용
- 인코딩: `encoding='utf-8'` 명시
- 도구 참조: `PROJECT_ROOT / "tools" / "xxx.py"` 패턴
