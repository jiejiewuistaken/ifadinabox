from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Type, TypeVar

from openai import AzureOpenAI
from pydantic import BaseModel


def _get_env_any(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v is not None:
            return v
    return None


@dataclass(frozen=True)
class AzureConfig:
    """
    Matches the env var names you provided:
      - API_KEY
      - BASE_URL  (e.g. https://YOUR-RESOURCE.openai.azure.com)
      - MODEL     (your deployment name)
      - API_VERSION (optional; default set below)
    """

    api_key_env: str = "API_KEY"
    base_url_env: str = "BASE_URL"
    model_env: str = "MODEL"
    api_version: str = os.getenv("API_VERSION", "2024-08-01-preview")


class AzureChatLLM:
    def __init__(self, config: AzureConfig | None = None) -> None:
        self.config = config or AzureConfig()
        # Be forgiving: accept both uppercase and lowercase env var names.
        api_key = _get_env_any(self.config.api_key_env, self.config.api_key_env.lower())
        endpoint = _get_env_any(self.config.base_url_env, self.config.base_url_env.lower())
        deployment = _get_env_any(self.config.model_env, self.config.model_env.lower())

        # Treat empty string as missing (common when .env has api_key="").
        if not api_key:
            raise RuntimeError(
                f"Missing/empty Azure OpenAI api_key. Set {self.config.api_key_env}=... (or api_key=...) in backend/.env."
            )
        if not endpoint:
            raise RuntimeError(
                f"Missing/empty Azure OpenAI azure_endpoint. Set {self.config.base_url_env}=... (or base_url=...) in backend/.env."
            )
        if not deployment:
            raise RuntimeError(
                f"Missing/empty Azure OpenAI deployment name. Set {self.config.model_env}=... (or model=...) in backend/.env."
            )

        self.deployment = deployment
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=self.config.api_version,
        )

    def chat(self, *, system: str, messages: list[dict[str, str]], max_new_tokens: int = 1400) -> str:
        # Azure uses "model=<deployment_name>"
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=0.4,
            max_tokens=max_new_tokens,
        )
        return resp.choices[0].message.content or ""


T = TypeVar("T", bound=BaseModel)


class AzureStructuredLLM(AzureChatLLM):
    """
    Supports your exact pattern:
      resp = client.chat.completions.create(..., response_format=SomePydanticModel)
    If the SDK/runtime doesn't support it for your account/version, we fall back to JSON parsing.
    """

    def chat_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        response_format: Type[T],
        max_new_tokens: int = 1200,
    ) -> T:
        # Try direct `response_format=...` first (matches your snippet)
        try:
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "system", "content": system}, *messages],
                temperature=0.2,
                max_tokens=max_new_tokens,
                response_format=response_format,
            )
            text = resp.choices[0].message.content or ""
            # Some SDKs still return JSON string content; validate into the model
            return response_format.model_validate_json(text)
        except Exception:
            # Fallback: force JSON-only and parse/validate
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "system", "content": system + "\nReturn ONLY valid JSON."}, *messages],
                temperature=0.2,
                max_tokens=max_new_tokens,
            )
            text = resp.choices[0].message.content or ""
            return response_format.model_validate_json(text)

