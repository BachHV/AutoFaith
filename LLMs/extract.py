"""Proof -> Checkpoints, with a pluggable extractor.

    extractor (LLM / Lean / fixture)  ->  RawProof  ->  build_unit_checkpoints  ->  [Checkpoint]  -> compose -> Checkpoint
            swappable                    the contract         deterministic           unit steps             whole proof

To work on the prompt you only touch the prompt file (and maybe
LLMStepExtractor). Nothing downstream changes as long as the model returns
the RawProof JSON.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from model import Checkpoint, ProofLanguage, compose
from steps import ExtractionError, RawProof, build_unit_checkpoints, parse_raw_proof


@dataclass(frozen=True)
class ProofInput:
    theorem_id: str
    language: ProofLanguage
    statement: str
    proof: str


class StepExtractor(Protocol):
    def extract(self, item: ProofInput, feedback: str | None = None) -> RawProof:
        """Segment item.proof into unit steps.

        feedback lists what was wrong with the previous attempt at this same
        proof (None on the first attempt). Raise ExtractionError for output
        that is malformed but worth retrying.
        """
        ...


def extract_unit_checkpoints(
    item: ProofInput,
    extractor: StepExtractor,
    max_attempts: int = 3,
    require_verbatim: bool = True,
    require_complete: bool = True,
) -> list[Checkpoint]:
    """Extract, validate, and on failure retry with the problems as feedback."""
    feedback = None
    for _ in range(max_attempts):
        try:
            raw = extractor.extract(item, feedback)
            return build_unit_checkpoints(
                item.theorem_id,
                item.language,
                raw,
                proof_text=item.proof if require_verbatim else None,
                require_complete=require_complete,
            )
        except ExtractionError as err:
            feedback = str(err)
    raise ExtractionError(
        f"{item.theorem_id}: gave up after {max_attempts} attempts. Last problems:\n{feedback}"
    )


def extract_proof(item: ProofInput, extractor: StepExtractor, **kwargs) -> Checkpoint:
    """The whole proof as one Checkpoint; proof.units() gives back the unit checkpoints."""
    return compose(extract_unit_checkpoints(item, extractor, **kwargs))


# ---------------------------------------------------------------------------
# Backend 1: an LLM. The model client and the prompt are both injected.
# ---------------------------------------------------------------------------

LLMClient = Callable[[str], str]
"""Any function prompt -> completion. Wrap whichever SDK/model you use."""

DEFAULT_FEEDBACK = (
    "## Problems with your previous answer\n"
    "A previous answer for this proof was rejected. Fix every problem below:\n"
    "{{problems}}\n"
)


def fill(template: str, **values: str) -> str:
    """Replace {{name}} placeholders in one pass.

    Safer than str.format (JSON braces in the prompt) or string.Template
    (LaTeX dollar signs in the prompt).
    """
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"template placeholder {{{{{key}}}}} has no value")
        return values[key]

    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def parse_json_object(completion: str) -> dict:
    """Pull one JSON object out of a model answer (tolerates ``` fences and chatter)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", completion, re.S)
    body = m.group(1) if m else completion
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end < start:
        raise ExtractionError("the answer contained no JSON object")
    try:
        return json.loads(body[start : end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"the answer was not valid JSON ({e}); remember to escape backslashes in LaTeX"
        ) from None


class LLMStepExtractor:
    def __init__(self, client: LLMClient, template: str, feedback_template: str = DEFAULT_FEEDBACK):
        self.client = client
        self.template = template
        self.feedback_template = feedback_template

    @classmethod
    def from_file(cls, client: LLMClient, path: str | Path, **kwargs) -> LLMStepExtractor:
        return cls(client, Path(path).read_text(encoding="utf-8"), **kwargs)

    def render(self, item: ProofInput, feedback: str | None = None) -> str:
        fb = fill(self.feedback_template, problems=feedback) if feedback else ""
        return fill(self.template, statement=item.statement, proof=item.proof, feedback=fb)

    def extract(self, item: ProofInput, feedback: str | None = None) -> RawProof:
        completion = self.client(self.render(item, feedback))
        return parse_raw_proof(parse_json_object(completion))


# ---------------------------------------------------------------------------
# Backend 2: stored annotations (hand-made gold data, or cached LLM answers)
# ---------------------------------------------------------------------------

class StaticExtractor:
    """Serves pre-made RawProofs, so everything downstream runs with no model."""

    def __init__(self, proofs: Mapping[str, RawProof]):
        self.proofs = dict(proofs)

    @classmethod
    def from_json_dir(cls, directory: str | Path) -> StaticExtractor:
        """One <theorem_id>.json per proof, as written by RawProof.to_dict()."""
        return cls({
            p.stem: parse_raw_proof(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(Path(directory).glob("*.json"))
        })

    def extract(self, item: ProofInput, feedback: str | None = None) -> RawProof:
        if feedback:  # a stored answer can't improve, so don't retry it
            raise RuntimeError(f"stored annotation for {item.theorem_id} is invalid:\n{feedback}")
        return self.proofs[item.theorem_id]