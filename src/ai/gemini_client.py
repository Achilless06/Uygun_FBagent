"""Google Gemini SDK wrapper.

Mirrors the ClaudeClient interface so the conversation engine can swap models
without changing call sites.

Why Gemini for Georgian:
  Brandbook page 13 specifies Gemini for the actual Georgian text generation.
  In practice gemini-2.0-flash handles Georgian morphology + idioms noticeably
  better than Claude Sonnet, and it's ~10x cheaper for the same workload.

Pricing (gemini-3.5-flash, May 2026 — our default model):
  - Input:  $0.30 / 1M tokens   (approximate; update from ai.google.dev when known)
  - Output: $2.50 / 1M tokens   (approximate)
  Gemini 3.5 Flash is the current-gen workhorse — better Georgian fluency
  and instruction-following than 2.5-flash. Requires billing enabled on
  Google AI Studio.

Used by:
  - src/ai/conversation.py   (chat with the SMM-manager)
  - src/ai/generator.py      (Phase 3: post body text)
"""

from __future__ import annotations

from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src import config, db
from src.logging_setup import get_logger

log = get_logger(__name__)

PRICE_INPUT_PER_M = 0.30
PRICE_OUTPUT_PER_M = 2.50


@dataclass
class GeminiResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _to_gemini_contents(messages: list[dict]) -> list[genai_types.Content]:
    """Convert {"role": "user"/"assistant", "content": "..."} → Gemini Content.

    Gemini uses "model" as the assistant role; we accept both forms.
    """
    out: list[genai_types.Content] = []
    for m in messages:
        role = m["role"]
        if role == "assistant":
            role = "model"
        out.append(
            genai_types.Content(
                role=role,
                parts=[genai_types.Part.from_text(text=m["content"])],
            )
        )
    return out


class GeminiClient:
    def __init__(self, cfg: config.Config) -> None:
        self._client = genai.Client(api_key=cfg.google_api_key)
        self._model = cfg.gemini_text_model

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call_multi(
        self, system: str, messages: list[dict], max_tokens: int
    ) -> tuple[str, int, int]:
        contents = _to_gemini_contents(messages)
        # thinking_budget=0 disables Gemini 2.5's internal chain-of-thought.
        # Without it, the model spends most of max_output_tokens on hidden
        # reasoning and the visible JSON output gets truncated mid-string.
        config_obj = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.7,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        )
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config_obj,
        )
        text = response.text or ""
        usage = response.usage_metadata
        in_tok = (usage.prompt_token_count if usage else 0) or 0
        out_tok = (usage.candidates_token_count if usage else 0) or 0
        return text, in_tok, out_tok

    def generate_multi(
        self,
        *,
        system: str,
        messages: list[dict],
        operation: str = "chat",
        max_tokens: int = 1500,
    ) -> GeminiResponse:
        """Multi-turn variant. `messages` is a list of {"role", "content"} dicts."""
        from src import budget as _budget
        from src.ai.claude_client import BudgetExhausted
        if _budget.is_blocked():
            raise BudgetExhausted(
                "Monthly API budget exhausted — agent auto-paused."
            )
        text, in_tok, out_tok = self._call_multi(system, messages, max_tokens)
        cost = (in_tok / 1_000_000) * PRICE_INPUT_PER_M + (
            out_tok / 1_000_000
        ) * PRICE_OUTPUT_PER_M
        self._record_spend(operation, in_tok, out_tok, cost)
        log.info(
            "gemini_call",
            operation=operation,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
            turns=len(messages),
        )
        return GeminiResponse(
            text=text, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost
        )

    def generate(
        self,
        system: str,
        user: str,
        *,
        operation: str = "generate",
        max_tokens: int = 2000,
    ) -> GeminiResponse:
        """Single-turn convenience wrapper."""
        return self.generate_multi(
            system=system,
            messages=[{"role": "user", "content": user}],
            operation=operation,
            max_tokens=max_tokens,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call_json(self, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        """Single-turn JSON-mode call. Forces application/json output, no fences."""
        config_obj = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.5,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
        )
        contents = _to_gemini_contents([{"role": "user", "content": user}])
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config_obj,
        )
        text = response.text or ""
        usage = response.usage_metadata
        in_tok = (usage.prompt_token_count if usage else 0) or 0
        out_tok = (usage.candidates_token_count if usage else 0) or 0
        return text, in_tok, out_tok

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        operation: str = "generate_json",
        max_tokens: int = 2000,
    ) -> GeminiResponse:
        """JSON-mode generation. Use for structured outputs (strategist, validator).

        Replaces ClaudeClient.generate() at JSON-output call sites for ~10x cost
        reduction. Gemini's response_mime_type="application/json" returns clean
        JSON without markdown fences, so callers can json.loads() directly.
        """
        from src import budget as _budget
        from src.ai.claude_client import BudgetExhausted
        if _budget.is_blocked():
            raise BudgetExhausted("Monthly API budget exhausted — agent auto-paused.")
        text, in_tok, out_tok = self._call_json(system, user, max_tokens)
        cost = (in_tok / 1_000_000) * PRICE_INPUT_PER_M + (
            out_tok / 1_000_000
        ) * PRICE_OUTPUT_PER_M
        self._record_spend(operation, in_tok, out_tok, cost)
        log.info(
            "gemini_json_call",
            operation=operation,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
        )
        return GeminiResponse(
            text=text, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost
        )

    @staticmethod
    def _record_spend(operation: str, in_tok: int, out_tok: int, cost: float) -> None:
        with db.session_scope() as s:
            s.add(
                db.ApiSpend(
                    provider="google",
                    operation=operation,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                )
            )
