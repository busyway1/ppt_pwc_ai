#!/usr/bin/env python3
"""
PwC GenAI Gateway 클라이언트.

환경 변수:
    GENAI_BASE_URL: Gateway URL (기본: https://genai-sharedservice-americas.pwcinternal.com)
    PwC_LLM_API_KEY: API 키
    PwC_LLM_MODEL: 모델 ID (기본: bedrock.anthropic.claude-sonnet-4-6)

Usage:
    from pipeline.llm_client import get_client

    client = get_client()
    result = client.complete("system prompt", "user prompt")
"""

import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2

# .env 파일에서 환경변수 로드 (python-dotenv 없이 간단 구현)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def _extract_json(raw: str) -> str:
    """LLM 응답에서 JSON 객체를 추출한다."""
    text = raw.strip()

    # ```json ... ``` 코드 펜스 제거
    if "```" in text:
        fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
        if fence_match:
            text = fence_match.group(1).strip()

    if text.startswith("{") or text.startswith("["):
        return text

    # 첫 번째 { 또는 [ 찾기
    first = -1
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            first = i
            break
    if first < 0:
        return ""

    opener = text[first]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape_next = False
    for i in range(first, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[first : i + 1]
    return text[first:]


class GenAIClient:
    """PwC GenAI Gateway 동기 클라이언트.

    httpx가 없으면 urllib 폴백 사용.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("GENAI_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("PwC_LLM_API_KEY", "")
        self.model = model or os.environ.get(
            "PwC_LLM_MODEL", "bedrock.anthropic.claude-sonnet-4-6"
        )
        self.timeout = timeout

        if not self.base_url or not self.api_key:
            raise ValueError(
                "GenAI Gateway 설정 필요. .env에 GENAI_BASE_URL과 PwC_LLM_API_KEY를 설정하세요."
            )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """LLM 호출 (동기). 3회 자동 재시도."""
        import urllib.request
        import urllib.error

        url = f"{self.base_url}/v1/responses"
        payload = json.dumps(
            {
                "model": self.model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                # Responses API format
                if "output" in data:
                    for item in data["output"]:
                        if item.get("type") == "message":
                            for block in item.get("content", []):
                                if block.get("type") == "output_text":
                                    return block["text"]
                            for block in item.get("content", []):
                                if "text" in block:
                                    return block["text"]

                # Chat Completions fallback
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]

                raise ValueError(f"Unexpected response format: {list(data.keys())}")

            except Exception as e:
                last_error = e
                logger.warning("GenAI attempt %d/%d: %s", attempt + 1, MAX_RETRIES, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        raise RuntimeError(f"GenAI 요청 실패 ({MAX_RETRIES}회 시도): {last_error}")

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs,
    ) -> dict | list:
        """JSON 응답 요청 + 파싱. 실패 시 3회 재시도."""
        json_instruction = (
            "\n\nIMPORTANT: Respond ONLY with valid JSON. "
            "No explanation, no markdown. Output must start with { or [ and end with } or ]."
        )
        for attempt in range(3):
            raw = self.complete(
                system_prompt=system_prompt + json_instruction,
                user_prompt=user_prompt,
                **kwargs,
            )
            cleaned = _extract_json(raw)
            if not cleaned:
                logger.warning("JSON attempt %d/3: no JSON found", attempt + 1)
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise json.JSONDecodeError("No JSON found in response", raw, 0)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                if attempt < 2:
                    logger.warning("JSON parse failed (attempt %d/3)", attempt + 1)
                    time.sleep(2 * (attempt + 1))
                else:
                    raise
        raise RuntimeError("JSON parsing failed after 3 attempts")


# Singleton
_client: GenAIClient | None = None


def get_client(**kwargs) -> GenAIClient:
    """싱글톤 GenAI 클라이언트를 반환한다."""
    global _client
    if _client is None:
        _client = GenAIClient(**kwargs)
    return _client


def is_configured() -> bool:
    """GenAI Gateway가 설정되어 있는지 확인한다."""
    base_url = os.environ.get("GENAI_BASE_URL", "")
    api_key = os.environ.get("PwC_LLM_API_KEY", "")
    return bool(base_url and api_key)
