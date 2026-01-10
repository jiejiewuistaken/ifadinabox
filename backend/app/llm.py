from __future__ import annotations

import os
from dataclasses import dataclass

from openai import AzureOpenAI


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
        api_key = os.getenv(self.config.api_key_env)
        endpoint = os.getenv(self.config.base_url_env)
        deployment = os.getenv(self.config.model_env)
        if not api_key:
            raise RuntimeError(f"Missing env var {self.config.api_key_env} for Azure OpenAI api_key.")
        if not endpoint:
            raise RuntimeError(f"Missing env var {self.config.base_url_env} for Azure OpenAI azure_endpoint.")
        if not deployment:
            raise RuntimeError(f"Missing env var {self.config.model_env} for Azure OpenAI deployment name.")

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

