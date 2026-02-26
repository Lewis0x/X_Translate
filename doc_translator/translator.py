from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import Callable
from typing import Any
from typing import List
from typing import Protocol


@dataclass
class TranslationConfig:
    source_lang: str
    target_lang: str
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    endpoint: str = "/chat/completions"
    batch_size: int = 20
    max_retries: int = 3
    rate_limit_rpm: int = 60
    model: str = "gpt-4.1-mini"
    temperature: float = 0.0
    timeout_seconds: int = 120


class TranslatorProtocol(Protocol):
    def translate(
        self,
        texts: List[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> List[str]:
        ...


class BaseBatchTranslator(ABC):
    def __init__(self, config: TranslationConfig):
        self.config = config
        self.config.api_key = _resolve_api_key(config.api_key)
        self.config.model = _resolve_model(config.model)
        self.request_interval = 60.0 / max(1, config.rate_limit_rpm)
        self.last_request_at = 0.0

    def _sleep_if_needed(self) -> None:
        now = time.time()
        elapsed = now - self.last_request_at
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)

    @staticmethod
    def _build_prompt(source_lang: str, target_lang: str) -> str:
        return (
            "你是专业技术文档翻译器。"
            f"请将输入数组中的每一项从 {source_lang} 翻译为 {target_lang}。"
            "严格保持数组长度和顺序一致。"
            "只输出 JSON 数组字符串，不要输出任何额外文本。"
        )

    @abstractmethod
    def translate_batch(self, texts: List[str]) -> List[str]:
        raise NotImplementedError

    def translate(
        self,
        texts: List[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> List[str]:
        if not texts:
            return []

        output: List[str] = []
        translated_count = 0
        total = len(texts)
        size = max(1, self.config.batch_size)
        for start in range(0, len(texts), size):
            batch = texts[start : start + size]
            try:
                translated_batch = self.translate_batch(batch)
                output.extend(translated_batch)
                translated_count += len(translated_batch)
                if progress_callback:
                    progress_callback(translated_count, total)
            except Exception:
                for item in batch:
                    translated_item = self.translate_batch([item])
                    output.extend(translated_item)
                    translated_count += len(translated_item)
                    if progress_callback:
                        progress_callback(translated_count, total)
        return output


class OpenAITranslator(BaseBatchTranslator):
    def __init__(self, config: TranslationConfig):
        super().__init__(config)
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少依赖 openai，请先执行: pip install -r requirements.txt") from exc

        if self.config.base_url:
            self.client: Any = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
        else:
            self.client = OpenAI(api_key=self.config.api_key)

    def translate_batch(self, texts: List[str]) -> List[str]:
        if not texts:
            return []

        self._sleep_if_needed()
        prompt = self._build_prompt(self.config.source_lang, self.config.target_lang)

        message = json.dumps(texts, ensure_ascii=False)
        retries = self.config.max_retries
        last_error = ""

        for _ in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    temperature=self.config.temperature,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": message},
                    ],
                )
                self.last_request_at = time.time()
                content = response.choices[0].message.content or "[]"
                translated = _parse_translated_content(content, len(texts))
                return [str(item) for item in translated]
            except Exception as exc:
                last_error = str(exc)
                time.sleep(1.2)

        raise RuntimeError(f"翻译请求失败: {last_error}")


class OpenAICompatibleTranslator(BaseBatchTranslator):
    def __init__(self, config: TranslationConfig):
        super().__init__(config)
        if not self.config.base_url:
            raise RuntimeError("使用 openai_compatible 提供商时，需要配置 base_url")
        self.api_url = _build_api_url(self.config.base_url, self.config.endpoint)

    def translate_batch(self, texts: List[str]) -> List[str]:
        if not texts:
            return []

        self._sleep_if_needed()
        prompt = self._build_prompt(self.config.source_lang, self.config.target_lang)
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
            ],
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        retries = self.config.max_retries
        last_error = ""

        for _ in range(retries):
            request = urllib.request.Request(
                self.api_url,
                data=data,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                self.last_request_at = time.time()
                raw = json.loads(body)
                content = raw["choices"][0]["message"]["content"]
                translated = _parse_translated_content(content, len(texts))
                return [str(item) for item in translated]
            except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                time.sleep(1.2)

        raise RuntimeError(f"翻译请求失败: {last_error}")


def create_translator(config: TranslationConfig) -> TranslatorProtocol:
    provider = (config.provider or "openai").strip().lower()
    if provider == "openai":
        return OpenAITranslator(config)
    if provider in {"openai_compatible", "compatible"}:
        return OpenAICompatibleTranslator(config)
    raise RuntimeError(f"不支持的 provider: {config.provider}")


def _resolve_api_key(config_key: str) -> str:
    api_key = config_key or os.getenv("OPEN_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 API Key，请在 local.config.json 中配置 OPEN_API_KEY 或设置环境变量 OPEN_API_KEY/OPENAI_API_KEY/LLM_API_KEY")
    return api_key


def _resolve_model(config_model: str) -> str:
    model = config_model or os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    return model


def _build_api_url(base_url: str, endpoint: str) -> str:
    cleaned_base = base_url.rstrip("/")
    if cleaned_base.endswith("/chat/completions"):
        return cleaned_base
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    cleaned_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return f"{cleaned_base}{cleaned_endpoint}"


def _parse_translated_content(content: str, expected_len: int) -> List[str]:
    text = (content or "").strip()
    if not text:
        raise ValueError("翻译返回为空")

    candidates = [text]
    code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if code_block_match:
        candidates.insert(0, code_block_match.group(1).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, list):
            if len(parsed) == expected_len:
                return [str(item) for item in parsed]
            continue

        if isinstance(parsed, dict):
            for key in ("translations", "result", "data"):
                value = parsed.get(key)
                if isinstance(value, list) and len(value) == expected_len:
                    return [str(item) for item in value]
                if isinstance(value, str) and expected_len == 1:
                    return [value]

        if isinstance(parsed, str) and expected_len == 1:
            return [parsed]

    if expected_len == 1:
        return [text]

    raise ValueError("翻译返回长度与输入不一致")
