from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from huggingface_hub.utils import HfHubHTTPError

from huggingface_hub import InferenceClient


@dataclass(frozen=True)
class HFConfig:
    api_token_env: str = "HF_API_TOKEN"
    # If set, use a dedicated Inference Endpoint URL (recommended; avoids 410 "Gone" issues).
    endpoint_url: Optional[str] = os.getenv("HF_ENDPOINT_URL") or None
    # Default model is a chat-capable HF Inference model; change as you like.
    # Examples: "mistralai/Mistral-7B-Instruct-v0.3", "meta-llama/Meta-Llama-3-8B-Instruct"
    model: str = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")


class HFLLM:
    def __init__(self, config: HFConfig | None = None) -> None:
        self.config = config or HFConfig()
        token = os.getenv(self.config.api_token_env)
        if not token:
            raise RuntimeError(
                f"Missing Hugging Face token. Set env var {self.config.api_token_env}=<your_token> "
                "(and optionally HF_MODEL=<model_id>)."
            )
        model_or_endpoint = self.config.endpoint_url or self.config.model
        self.client = InferenceClient(model=model_or_endpoint, token=token)
        self._model_or_endpoint = model_or_endpoint

    def chat(self, *, system: str, messages: list[dict[str, str]], max_new_tokens: int = 1400) -> str:
        """
        Uses HF Inference chat completions if available; falls back to a single prompt if not.
        """
        # Try chat API (works for many instruct/chat models on HF Inference)
        try:
            resp = self.client.chat_completion(
                messages=[{"role": "system", "content": system}, *messages],
                max_tokens=max_new_tokens,
                temperature=0.4,
            )
            return resp.choices[0].message.content
        except Exception:
            # Fallback to text-generation: flatten messages to prompt
            prompt = system + "\n\n"
            for m in messages:
                prompt += f"{m['role'].upper()}: {m['content']}\n\n"
            try:
                out = self.client.text_generation(
                    prompt,
                    max_new_tokens=max_new_tokens,
                    temperature=0.4,
                    do_sample=True,
                    return_full_text=False,
                )
                return out
            except HfHubHTTPError as e:
                # Common failure mode: model repo exists (so from_pretrained works),
                # but the shared Inference API does not serve it => 410 Gone.
                status = getattr(e.response, "status_code", None)
                if status == 410:
                    raise RuntimeError(
                        "Hugging Face Inference API returned 410 Gone. "
                        "This usually means the model repo exists (tokenizer/weights downloadable), "
                        "but it is NOT available on the shared Inference API. "
                        "Fix: either (a) set HF_ENDPOINT_URL to your dedicated Inference Endpoint URL, "
                        "or (b) set HF_MODEL to a model that is served by the shared Inference API.\n"
                        f"Current target: {self._model_or_endpoint}"
                    ) from e
                raise

