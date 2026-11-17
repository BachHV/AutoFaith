"""Prompts for llm.py.

The prompt text lives in nl_unit_steps.prompt.md. It is split at the
{{feedback}} placeholder:
  NL_SYSTEM_PROMPT  everything before it (instructions + worked examples);
                    identical for every proof, so it can be cached
  USER_TEMPLATE     {{feedback}} and the task ({{statement}}, {{proof}})
"""
from __future__ import annotations

from pathlib import Path

from extract import DEFAULT_FEEDBACK, fill

__all__ = ["NL_SYSTEM_PROMPT", "USER_TEMPLATE", "FEEDBACK_TEMPLATE", "fill"]

NL_PROMPT_FILE = Path(__file__).parent / "nl_unit_steps.prompt.md"

_SPLIT = "{{feedback}}"
_text = NL_PROMPT_FILE.read_text(encoding="utf-8")
if _text.count(_SPLIT) != 1:
    raise ValueError(f"{NL_PROMPT_FILE.name} must contain {_SPLIT} exactly once")
_system, _task = _text.split(_SPLIT)

NL_SYSTEM_PROMPT: str = _system.rstrip() + "\n"
USER_TEMPLATE: str = _SPLIT + _task

# Filled with {{problems}} and put in USER_TEMPLATE's {{feedback}} on a retry.
FEEDBACK_TEMPLATE: str = DEFAULT_FEEDBACK
