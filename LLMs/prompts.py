"""Prompts for llm.py, one per proof language.

Each prompt's text lives in a markdown file and is split at the {{feedback}}
placeholder:
  system prompt   everything before it (instructions + worked examples);
                  identical for every proof, so it can be cached
  user template   {{feedback}} and the task ({{statement}}, {{proof}})

    nl_unit_steps.prompt.md   ProofLanguage.NL   natural-language proofs
    fl_unit_steps.prompt.md   ProofLanguage.FL   Lean 4 proofs

llm.py picks the prompt with prompt_for(item.language).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from extract import DEFAULT_FEEDBACK, fill
from model import ProofLanguage

__all__ = [
    "Prompt", "PROMPTS", "prompt_for", "load_prompt",
    "NL_SYSTEM_PROMPT", "USER_TEMPLATE", "FL_SYSTEM_PROMPT", "FL_USER_TEMPLATE",
    "FEEDBACK_TEMPLATE", "fill",
]

_SPLIT = "{{feedback}}"
_HERE = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    system: str  # instructions + worked examples
    user_template: str  # {{feedback}} + the task ({{statement}}, {{proof}})


def load_prompt(path: Path) -> Prompt:
    text = path.read_text(encoding="utf-8")
    if text.count(_SPLIT) != 1:
        raise ValueError(f"{path.name} must contain {_SPLIT} exactly once")
    system, task = text.split(_SPLIT)
    return Prompt(system=system.rstrip() + "\n", user_template=_SPLIT + task)


NL_PROMPT_FILE = _HERE / "nl_unit_steps.prompt.md"
FL_PROMPT_FILE = _HERE / "fl_unit_steps.prompt.md"

PROMPTS: dict[ProofLanguage, Prompt] = {
    ProofLanguage.NL: load_prompt(NL_PROMPT_FILE),
    ProofLanguage.FL: load_prompt(FL_PROMPT_FILE),
}


def prompt_for(language: ProofLanguage) -> Prompt:
    """The prompt for proofs written in `language`."""
    try:
        return PROMPTS[language]
    except KeyError:
        raise ValueError(f"no prompt for {language!r}; add one to PROMPTS in prompts.py") from None


# The NL names stay as before, so existing code keeps working.
NL_SYSTEM_PROMPT: str = PROMPTS[ProofLanguage.NL].system
USER_TEMPLATE: str = PROMPTS[ProofLanguage.NL].user_template
FL_SYSTEM_PROMPT: str = PROMPTS[ProofLanguage.FL].system
FL_USER_TEMPLATE: str = PROMPTS[ProofLanguage.FL].user_template

# Filled with {{problems}} and put in the user template's {{feedback}} on a retry.
FEEDBACK_TEMPLATE: str = DEFAULT_FEEDBACK
