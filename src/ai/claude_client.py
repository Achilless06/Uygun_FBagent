"""Anthropic Claude SDK wrapper.

Why a wrapper, not direct SDK calls:
  - Centralizes retries (network blips, 5xx, 429)
  - Auto-records every call into `api_spend` so the $20 cap is enforceable
  - Strips ```json fences from responses (Claude sometimes wraps JSON)

Pricing (Claude Sonnet 4.6 — claude-sonnet-4-6, May 2026):
  - Input: $3 / 1M tokens
  - Output: $15 / 1M tokens

Used by:
  - src/ai/advisor.py        (daily tips)
  - src/ai/generator.py      (Phase 3: post generation + validation)
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src import config, db
from src.logging_setup import get_logger

log = get_logger(__name__)

# Per-million-token prices in USD. Update when Anthropic changes pricing.
PRICE_INPUT_PER_M = 3.0
PRICE_OUTPUT_PER_M = 15.0


class BudgetExhausted(Exception):
    """Raised when the monthly cap is hit and the agent is auto-paused.

    Caller should catch this and either show a graceful "budget hit"
    message OR re-raise if the calling path needs to fail loudly.
    """


@dataclass
class ClaudeResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ClaudeClient:
    def __init__(self, cfg: config.Config) -> None:
        self._client = Anthropic(api_key=cfg.anthropic_api_key)
        self._model = cfg.anthropic_model

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call(self, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens

    def generate(
        self,
        system: str,
        user: str,
        *,
        operation: str = "generate",
        max_tokens: int = 2000,
    ) -> ClaudeResponse:
        """Call Claude. Records cost into api_spend automatically.

        Returns ClaudeResponse with text + token counts + cost in USD.
        Raises BudgetExhausted if monthly budget is already maxed out.
        """
        # Circuit breaker: refuse to make the call if the agent has been
        # auto-paused by the budget cap. Local import dodges circular deps.
        from src import budget as _budget
        if _budget.is_blocked():
            raise BudgetExhausted(
                "Monthly API budget exhausted — agent auto-paused. "
                "Raise /set_budget or /set_active true to resume."
            )
        text, in_tok, out_tok = self._call(system, user, max_tokens)
        cost = (in_tok / 1_000_000) * PRICE_INPUT_PER_M + (
            out_tok / 1_000_000
        ) * PRICE_OUTPUT_PER_M
        self._record_spend(operation, in_tok, out_tok, cost)
        log.info(
            "claude_call",
            operation=operation,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
        )
        return ClaudeResponse(text=text, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call_multi(self, system: str, messages: list, max_tokens: int) -> tuple[str, int, int]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens

    def generate_multi(
        self,
        *,
        system: str,
        messages: list,
        operation: str = "chat",
        max_tokens: int = 1500,
    ) -> ClaudeResponse:
        """Multi-turn variant of generate(). `messages` is a list of
        {"role": "user"|"assistant", "content": "..."} dicts. Used by the chat
        engine to give Claude the full conversation history.
        """
        from src import budget as _budget
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
            "claude_call",
            operation=operation,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
            turns=len(messages),
        )
        return ClaudeResponse(text=text, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)

    @staticmethod
    def _record_spend(operation: str, in_tok: int, out_tok: int, cost: float) -> None:
        with db.session_scope() as s:
            s.add(
                db.ApiSpend(
                    provider="anthropic",
                    operation=operation,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                )
            )

    @staticmethod
    def strip_json_fences(text: str) -> str:
        """Remove ```json ... ``` wrapper if present. Claude sometimes adds it."""
        text = text.strip()
        if text.startswith("```"):
            # Drop first fence.
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            # Drop language tag if first line.
            # Drop trailing fence.
            if text.endswith("```"):
                text = text[: -3].rstrip()
        return text.strip()
