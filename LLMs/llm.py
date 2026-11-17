"""Call a language model to turn a proof into unit checkpoints.

    from extract import ProofInput
    from llm import proof_to_unit_checkpoints
    from model import ProofLanguage

    item = ProofInput("odd_sum", ProofLanguage.NL, statement="...", proof="...")
    units = proof_to_unit_checkpoints(item, "openrouter/anthropic/claude-sonnet-5.5")

Models are called through LiteLLM (pip install litellm), which reaches most
providers with one interface. Name the model as "provider/model-name":

    "anthropic/claude-sonnet-5-5"    Claude API (ANTHROPIC_API_KEY)
    "openrouter/<vendor>/<model>"    OpenRouter (OPENROUTER_API_KEY), e.g. "openrouter/anthropic/claude-sonnet-5.5"
    "openai/<model>"                 OpenAI (OPENAI_API_KEY)
    "gemini/<model>", "bedrock/<model>", "vertex_ai/<model>", "deepseek/<model>", ...
    "openai/<model>" with api_base=  any OpenAI-compatible server (vLLM, a local endpoint, ...)

Each provider reads its usual API key environment variable; see the LiteLLM docs.
Anything with __call__(system: str, user: str) -> str also works as a model.

The prompt is chosen by the proof's language (item.language): prompts.py has one
for natural-language proofs (ProofLanguage.NL) and one for Lean 4 proofs
(ProofLanguage.FL). For a Lean proof, statement is the theorem header and proof
is the text after `:=` (see fl_proofs.py).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Protocol

import prompts
from extract import ProofInput, extract_unit_checkpoints
from model import Checkpoint
from steps import ExtractionError, RawProof, parse_raw_proof


class ChatModel(Protocol):
    def __call__(self, system: str, user: str) -> str:
        """Send one system + user message, return the text of the reply."""
        ...


class TruncatedOutput(RuntimeError):
    """The model hit its output limit, so the answer is cut off.

    Not retried: the same limit would cut it off again. Raise max_tokens instead.
    """


# ---------------------------------------------------------------------------
# The model adapter: one class for every provider LiteLLM supports.
# ---------------------------------------------------------------------------

class LiteLLMModel:
    def __init__(
        self,
        model: str,  # "provider/model-name", e.g. "openrouter/anthropic/claude-sonnet-5.5"
        # Long proofs give long JSON. Lower it for models with small output limits, and on
        # OpenRouter, which checks your credit covers all max_tokens before the call.
        max_tokens: int = 16000,
        cache_system_prompt: bool = False,  # ask the provider to cache the system prompt (useful for Claude)
        completion: Callable[..., Any] | None = None,  # defaults to litellm.completion; tests pass a fake
        **params: Any,  # passed to litellm.completion, e.g. api_base=, api_key=, temperature=
    ):
        if completion is None:
            import litellm  # pip install litellm

            completion = litellm.completion
        self.completion = completion
        self.model = model
        self.max_tokens = max_tokens
        self.cache_system_prompt = cache_system_prompt
        # drop_params: skip settings a provider doesn't support instead of failing
        self.params = {"drop_params": True, **params}
        self.name = model

    def __call__(self, system: str, user: str) -> str:
        options = dict(self.params)
        if self.cache_system_prompt:
            # The system prompt is identical for every proof; LiteLLM marks it for caching.
            options["cache_control_injection_points"] = [{"location": "message", "role": "system"}]
        resp = self.completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=self.max_tokens,
            **options,
        )
        choice = resp.choices[0]
        # LiteLLM reports every provider's stop reason in OpenAI terms: "length" = cut off.
        if choice.finish_reason == "length":
            raise TruncatedOutput(f"{self.name} stopped at max_tokens={self.max_tokens}; raise max_tokens")
        return choice.message.content or ""


def get_model(spec: str | ChatModel, **options: Any) -> ChatModel:
    """A LiteLLMModel for a "provider/model-name" string; any other model object is returned as is.

    get_model("openrouter/anthropic/claude-sonnet-5.5", cache_system_prompt=True)
    get_model("openai/qwen3-32b", api_base="http://localhost:8000/v1", api_key="local")
    """
    if isinstance(spec, str):
        return LiteLLMModel(spec, **options)
    if options:
        raise TypeError("options only apply when the model is given as a 'provider/model-name' string")
    return spec


# ---------------------------------------------------------------------------
# Extractor: prompt -> model -> RawProof
# ---------------------------------------------------------------------------

def parse_json_object(answer: str) -> dict:
    """Pull one JSON object out of a model answer (tolerates ``` fences and chatter).

    Prefers a ```json block. Other fenced blocks (e.g. ```lean code, whose `{x | ...}`
    braces would confuse the search) are skipped.
    """
    fenced = re.findall(r"```(\w*)[ \t]*\n?(.*?)```", answer, re.S)
    candidates = [body for lang, body in fenced if lang.lower() == "json"]
    candidates += [body for lang, body in fenced if lang == "" and body.lstrip().startswith("{")]
    body = candidates[0] if candidates else re.sub(r"```.*?```", "", answer, flags=re.S)
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end < start:
        raise ExtractionError("the answer contained no JSON object")
    try:
        return json.loads(body[start : end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"the answer was not valid JSON ({e}); remember to escape backslashes (LaTeX) and write line breaks in strings as \\n"
        ) from None


class LLMStepExtractor:
    """Prompt -> model -> RawProof. The prompt comes from prompts.prompt_for(item.language)
    unless system_prompt / user_template are given, which then apply to every proof."""

    def __init__(
        self,
        model: ChatModel,
        system_prompt: str | None = None,
        user_template: str | None = None,
        feedback_template: str = prompts.FEEDBACK_TEMPLATE,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.user_template = user_template
        self.feedback_template = feedback_template

    def messages(self, item: ProofInput, feedback: str | None = None) -> tuple[str, str]:
        prompt = prompts.prompt_for(item.language)
        system = self.system_prompt if self.system_prompt is not None else prompt.system
        template = self.user_template if self.user_template is not None else prompt.user_template
        fb = prompts.fill(self.feedback_template, problems=feedback) if feedback else ""
        user = prompts.fill(template, statement=item.statement, proof=item.proof, feedback=fb)
        return system, user

    def extract(self, item: ProofInput, feedback: str | None = None) -> RawProof:
        return parse_raw_proof(parse_json_object(self.model(*self.messages(item, feedback))))


# ---------------------------------------------------------------------------
# The function to call
# ---------------------------------------------------------------------------

def proof_to_unit_checkpoints(
    item: ProofInput,
    model: str | ChatModel,
    *,
    max_tokens: int | None = None,
    max_attempts: int = 3,
    system_prompt: str | None = None,
    require_verbatim: bool = True,
    require_complete: bool = True,
) -> list[Checkpoint]:
    """Ask `model` to split `item.proof` into steps and return the unit checkpoints.

    Works for natural-language and Lean proofs alike: the prompt is chosen by
    item.language (prompts.prompt_for) unless `system_prompt` is given.

    model: "provider/model-name" (e.g. "openrouter/anthropic/claude-sonnet-5.5"), or a model
        object such as LiteLLMModel(..., max_tokens=..., api_base=...) for custom settings.
    max_tokens: output limit when `model` is a string (default: LiteLLMModel's 16000).
        On OpenRouter your credit must cover all of it, so lower it if you get a
        "402 Payment Required ... can only afford N" error.
    max_attempts: if an answer is invalid, the problems found are sent back to the
        model and it tries again, up to this many attempts in total.

    Raises ExtractionError if no attempt gives a valid answer, and TruncatedOutput
    if an answer is cut off by the output limit. compose() the result to get the
    whole proof as one Checkpoint.
    """
    options = {} if max_tokens is None else {"max_tokens": max_tokens}
    extractor = LLMStepExtractor(get_model(model, **options), system_prompt=system_prompt)
    return extract_unit_checkpoints(
        item,
        extractor,
        max_attempts=max_attempts,
        require_verbatim=require_verbatim,
        require_complete=require_complete,
    )


if __name__ == "__main__":
    # python llm.py                                   every proof in nl_proofs.py and fl_proofs.py
    # python llm.py sqrt2_irrational sum_first_n      just these ids (or --only ID, repeatable);
    #                                                 an id in both files runs both proofs
    # python llm.py openrouter/<vendor>/<model> sum_first_n --max-tokens 4000
    # python llm.py --lang FL                         only the Lean proofs (or --lang NL)
    # Each proof's language comes from its ProofInput, and picks the prompt,
    # the default --max-tokens and the output folder.
    import argparse
    import textwrap
    from datetime import datetime
    from pathlib import Path

    from fl_proofs import PROOFS as FL_PROOFS
    from model import ProofLanguage, compose, outline, trace
    from nl_proofs import PROOFS as NL_PROOFS

    DEFAULT_MODEL = "openrouter/anthropic/claude-sonnet-5.5"
    # These proofs are short, so a small limit is plenty (and cheap to reserve on OpenRouter).
    # Lean answers are longer: goals are written out in full after every tactic.
    DEFAULT_MAX_TOKENS = {ProofLanguage.NL: 1000, ProofLanguage.FL: 2000}
    OUT_DIRS = {ProofLanguage.NL: "NL_checkpoints", ProofLanguage.FL: "FL_checkpoints"}

    parser = argparse.ArgumentParser(
        description="Split the proofs in nl_proofs.py and fl_proofs.py into unit checkpoints.")
    parser.add_argument("targets", nargs="*", metavar="MODEL_OR_THEOREM_ID",
                        help="proof ids (default: all) and/or one LiteLLM model name "
                             f'containing "/", e.g. "openrouter/<vendor>/<model>" (default: {DEFAULT_MODEL})')
    parser.add_argument("--max-tokens", type=int, default=None,
                        help="output limit; OpenRouter checks your credit covers all of it "
                             "(default: 1000 for NL proofs, 2000 for Lean proofs)")
    parser.add_argument("--only", action="append", default=[], metavar="THEOREM_ID",
                        help="run only this proof; repeat for several (default: all)")
    parser.add_argument("--lang", type=str.upper, choices=["NL", "FL"], default=None,
                        help="run only natural-language (NL) or only Lean (FL) proofs (default: both)")
    parser.add_argument("--list", action="store_true", help="print the proof ids and exit")
    parser.add_argument("--outline", action="store_true",
                        help="print a compact outline instead of the full state after every checkpoint")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="folder for the results: <out-dir>/NL_checkpoints/<theorem_id>.txt and "
                             "<out-dir>/FL_checkpoints/<theorem_id>.txt (default: the LLMs folder)")
    args = parser.parse_args()

    # A model name always has a provider prefix ("openrouter/..."); anything else is a proof id.
    models = [t for t in args.targets if "/" in t]
    if len(models) > 1:
        parser.error(f"give at most one model, got {', '.join(models)}")
    args.model = models[0] if models else DEFAULT_MODEL
    args.only += [t for t in args.targets if "/" not in t]

    pool = NL_PROOFS + FL_PROOFS
    if args.lang:
        pool = [p for p in pool if p.language.name == args.lang]
    by_id: dict[str, list[ProofInput]] = {}
    for p in pool:
        by_id.setdefault(p.theorem_id, []).append(p)

    if args.list:
        for p in pool:
            print(f"{p.language.name}  {p.theorem_id:32} {p.statement}")
        raise SystemExit

    unknown = [i for i in args.only if i not in by_id]
    if unknown:
        scope = f" among the {args.lang} proofs" if args.lang else ""
        parser.error(f"unknown theorem_id {', '.join(unknown)}{scope}; see --list" + (f" --lang {args.lang}" if args.lang else ""))
    items = [p for i in dict.fromkeys(args.only) for p in by_id[i]] if args.only else pool

    def describe_proof(item: ProofInput) -> str:
        if "\n" not in item.proof:
            return f"proof:      {item.proof}\n"
        return "proof:\n" + textwrap.indent(item.proof, "    ") + "\n"

    failed = []
    for n, item in enumerate(items, 1):
        lang = item.language
        print(f"\n=== [{n}/{len(items)}] {item.theorem_id} ({lang.name}): {item.statement}")
        max_tokens = args.max_tokens or DEFAULT_MAX_TOKENS[lang]
        try:
            units = proof_to_unit_checkpoints(item, args.model, max_tokens=max_tokens)
        except (ExtractionError, TruncatedOutput) as err:
            # No file is written, so an earlier successful result for this proof is kept.
            print(f"FAILED: {err}")
            failed.append(f"{item.theorem_id} ({lang.name})")
            continue
        result = (outline if args.outline else trace)(compose(units))
        print(result)
        # One folder per language, also under --out-dir: an NL and a Lean proof of the same
        # theorem share a theorem_id, so one folder would make one overwrite the other.
        out_dir = (args.out_dir or Path(__file__).parent) / OUT_DIRS[lang]
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{item.theorem_id}.txt"
        out.write_text(
            f"theorem_id: {item.theorem_id}\n"
            f"language:   {lang.name}\n"
            f"model:      {args.model}\n"
            f"run at:     {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"statement:  {item.statement}\n"
            + describe_proof(item)
            + f"\n{result}\n",
            encoding="utf-8",
        )
        print(f"saved to {out}")

    print(f"\n{len(items) - len(failed)}/{len(items)} succeeded" + (f"; failed: {', '.join(failed)}" if failed else ""))
    raise SystemExit(1 if failed else 0)
