from __future__ import annotations

import os
from dataclasses import dataclass

from huggingface_hub import InferenceClient


@dataclass(frozen=True)
class HFConfig:
    api_token_env: str = "HF_API_TOKEN"
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
        self.client = InferenceClient(model=self.config.model, token=token)

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
            out = self.client.text_generation(
                prompt,
                max_new_tokens=max_new_tokens,
                temperature=0.4,
                do_sample=True,
                return_full_text=False,
            )
            return out

