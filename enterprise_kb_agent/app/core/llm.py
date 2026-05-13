import json
import time
from typing import Generator, Optional

import requests

from app.core.config import settings


class LLMClient:
    """LLM client with Ollama-first local inference and OpenAI-compatible fallbacks."""

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        fallback_text: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        if not settings.enable_llm_generation:
            if fallback_text:
                return f"{fallback_text}\n\n提示：当前已关闭 LLM 生成，答案由本地检索与规则兜底生成。"
            raise RuntimeError("LLM 生成已关闭，且没有可用兜底答案")

        try:
            if settings.llm_provider == "ollama":
                return self._generate_with_ollama(prompt, system_prompt, temperature, model)
            return self._generate_with_openai_compatible(prompt, system_prompt, temperature)
        except Exception as exc:
            if settings.fallback_when_llm_unavailable and fallback_text:
                provider_name = settings.llm_provider.upper() if settings.llm_provider != "ollama" else "Ollama"
                return (
                    f"{fallback_text}\n\n"
                    f"提示：{provider_name} 已连接，但模型未在限定时间内产出正式回答，以上内容由本地检索兜底生成。错误信息：{exc}"
                )
            raise

    def stream_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        fallback_text: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Generator[str, None, None]:
        if not settings.enable_llm_generation:
            if not fallback_text:
                raise RuntimeError("LLM 生成已关闭，且没有可用兜底答案")
            text = f"{fallback_text}\n\n提示：当前已关闭 LLM 生成，答案由本地检索与规则兜底生成。"
            yield from self.iter_text_chunks(text)
            return

        try:
            if settings.llm_provider == "ollama":
                yield from self._stream_with_ollama(prompt, system_prompt, temperature, model)
            else:
                yield from self._stream_with_openai_compatible(prompt, system_prompt, temperature)
        except Exception as exc:
            if not settings.fallback_when_llm_unavailable or not fallback_text:
                raise
            provider_name = settings.llm_provider.upper() if settings.llm_provider != "ollama" else "Ollama"
            text = f"{fallback_text}\n\n提示：{provider_name} 已连接，但模型未在限定时间内产出正式回答，已使用本地检索兜底。错误信息：{exc}"
            yield from self.iter_text_chunks(text)

    def stream_generate_typed(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        fallback_text: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        """Like stream_generate but yields {"token": str, "kind": "thinking"|"response"}."""
        if not settings.enable_llm_generation:
            if not fallback_text:
                raise RuntimeError("LLM 生成已关闭，且没有可用兜底答案")
            text = f"{fallback_text}\n\n提示：当前已关闭 LLM 生成，答案由本地检索与规则兜底生成。"
            for chunk in self.iter_text_chunks(text):
                yield {"token": chunk, "kind": "response"}
            return

        try:
            if settings.llm_provider == "ollama":
                yield from self._stream_with_ollama_typed(prompt, system_prompt, temperature, model)
            else:
                for token in self._stream_with_openai_compatible(prompt, system_prompt, temperature):
                    yield {"token": token, "kind": "response"}
        except Exception as exc:
            if not settings.fallback_when_llm_unavailable or not fallback_text:
                raise
            provider_name = settings.llm_provider.upper() if settings.llm_provider != "ollama" else "Ollama"
            text = f"{fallback_text}\n\n提示：{provider_name} 已连接，但模型未在限定时间内产出正式回答，已使用本地检索兜底。错误信息：{exc}"
            for chunk in self.iter_text_chunks(text):
                yield {"token": chunk, "kind": "response"}

    def _generate_with_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        model: Optional[str] = None,
    ) -> str:
        text = "".join(self._stream_with_ollama(prompt, system_prompt, temperature, model)).strip()
        if not text:
            raise RuntimeError("Ollama 未在超时时间内返回正式回答")
        return text

    def _stream_with_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        model: Optional[str] = None,
    ) -> Generator[str, None, None]:
        for item in self._stream_with_ollama_typed(prompt, system_prompt, temperature, model):
            yield item["token"]

    def _stream_with_ollama_typed(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        model: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        deadline = time.monotonic() + settings.llm_timeout
        payload = {
            "model": model or settings.ollama_model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "num_predict": settings.ollama_num_predict,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        with self._post_with_retry(
            url,
            json=payload,
            timeout=settings.llm_timeout,
            stream=True,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Ollama 生成超过 {settings.llm_timeout} 秒")
                if not line:
                    continue
                data = json.loads(line)
                resp_token = data.get("response", "")
                think_token = data.get("thinking", "")
                if resp_token:
                    yield {"token": resp_token, "kind": "response"}
                elif think_token:
                    yield {"token": think_token, "kind": "thinking"}
                if data.get("done"):
                    break

    def _generate_with_openai_compatible(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
    ) -> str:
        provider_config = self._get_openai_compatible_config()
        headers = {
            "Authorization": f"Bearer {provider_config['api_key']}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": provider_config["model"],
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
        }
        url = f"{provider_config['base_url'].rstrip('/')}/chat/completions"
        response = self._post_with_retry(
            url,
            headers=headers,
            json=payload,
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _stream_with_openai_compatible(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
    ) -> Generator[str, None, None]:
        provider_config = self._get_openai_compatible_config()
        headers = {
            "Authorization": f"Bearer {provider_config['api_key']}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": provider_config["model"],
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
            "stream": True,
        }
        url = f"{provider_config['base_url'].rstrip('/')}/chat/completions"
        with self._post_with_retry(
            url,
            headers=headers,
            json=payload,
            timeout=settings.llm_timeout,
            stream=True,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                payload_text = line.removeprefix("data:").strip()
                if payload_text == "[DONE]":
                    break
                data = json.loads(payload_text)
                token = data["choices"][0].get("delta", {}).get("content")
                if token:
                    yield token

    def _get_openai_compatible_config(self) -> dict:
        if settings.llm_provider == "openai":
            api_key = settings.openai_api_key
            base_url = settings.openai_base_url
            model = settings.openai_model
        elif settings.llm_provider == "deepseek":
            api_key = settings.deepseek_api_key
            base_url = settings.deepseek_base_url
            model = settings.deepseek_model
        elif settings.llm_provider == "qwen":
            api_key = settings.qwen_api_key
            base_url = settings.qwen_base_url
            model = settings.qwen_model
        else:
            raise ValueError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")

        if not api_key:
            raise ValueError(f"{settings.llm_provider} API key 未配置")

        return {"api_key": api_key, "base_url": base_url, "model": model}

    def _post_with_retry(self, url: str, **kwargs) -> requests.Response:
        retries = max(settings.llm_max_retries, 0)
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                response = requests.post(url, **kwargs)
                if response.status_code >= 500 and attempt < retries:
                    response.close()
                    time.sleep(self._retry_delay(attempt))
                    continue
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= retries:
                    raise
                time.sleep(self._retry_delay(attempt))

        if last_error:
            raise last_error
        raise RuntimeError("LLM 请求失败，且未返回可用响应")

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return settings.llm_retry_backoff_seconds * (2**attempt)

    @staticmethod
    def iter_text_chunks(text: str, chunk_size: int = 32) -> Generator[str, None, None]:
        for start in range(0, len(text), chunk_size):
            yield text[start : start + chunk_size]

    @staticmethod
    def parse_json_from_text(text: str) -> dict | list | None:
        try:
            return json.loads(text)
        except Exception:
            pass

        start = min([idx for idx in [text.find("{"), text.find("[")] if idx >= 0], default=-1)
        if start < 0:
            return None
        end = max(text.rfind("}"), text.rfind("]"))
        if end <= start:
            return None

        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
