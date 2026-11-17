"""The contract between extractors and the checkpoint builder.

An extractor (an LLM prompt, a Lean REPL, a hand-written fixture) produces a
RawProof: the theorem's starting state plus a list of RawSteps. A RawStep
mirrors a unit Checkpoint field by field, except that it states what the step
*changes* instead of repeating whole states:

    RawStep                                    ->  Checkpoint
    text                                           source
    add/remove_premises, close/add_goals           prev_state -> next_state
    justification, dependency                      justification, dependency
    claims[i] (statement, premise, goal)           intermediate_claims[i] (statement, State)
    claims[i].proof (list[RawStep])                proofs_intermediate_claims[i] (a Checkpoint;
                                                   None when the text states the claim without proof)

Everything mechanical (state ids, chaining states, nesting claim proofs,
consistency checks) happens here, deterministically. A step is rejected only
when a Checkpoint couldn't represent it (a goal that isn't open, a claim whose
proof doesn't close it, ...) or when it isn't a proper unit step: it must
change the state and have a justification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from model import Checkpoint, ProofLanguage, State, compose


class ExtractionError(ValueError):
    """Extractor output that can't be turned into checkpoints.

    Messages are written to be shown back to the extractor as-is (for example
    pasted into a repair prompt).
    """


# ---------------------------------------------------------------------------
# Intermediate representation: exactly the JSON an LLM is asked to return
# ---------------------------------------------------------------------------

@dataclass
class RawClaim:
    statement: str  # becomes a premise once proved
    premise: list[str] = field(default_factory=list)  # assumptions local to the claim
    goal: list[str] = field(default_factory=list)  # defaults to [statement]
    proof: list[RawStep] = field(default_factory=list)


@dataclass
class RawStep:
    text: str  # verbatim span of the proof
    add_premises: list[str] = field(default_factory=list)
    remove_premises: list[str] = field(default_factory=list)
    close_goals: list[str] = field(default_factory=list)
    add_goals: list[str] = field(default_factory=list)
    justification: list[str] = field(default_factory=list)
    dependency: list[str] = field(default_factory=list)
    claims: list[RawClaim] = field(default_factory=list)


@dataclass
class RawProof:
    premise: list[str]
    goal: list[str]
    steps: list[RawStep]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready, e.g. to cache an LLM answer as a test fixture."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Parsing (dict -> IR), with error messages that point at the JSON path
# ---------------------------------------------------------------------------

def _obj(x: Any, where: str) -> dict:
    if not isinstance(x, dict):
        raise ExtractionError(f"{where} must be a JSON object, got {type(x).__name__}")
    return x


def _text(d: dict, key: str, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ExtractionError(f"{where}.{key} must be a non-empty string")
    return v


def _strs(d: dict, key: str, where: str) -> list[str]:
    v = d.get(key, [])
    if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
        raise ExtractionError(f"{where}.{key} must be a list of strings")
    return list(v)


def _list(d: dict, key: str, where: str) -> list:
    v = d.get(key, [])
    if not isinstance(v, list):
        raise ExtractionError(f"{where}.{key} must be a list")
    return v


def _parse_claim(x: Any, where: str) -> RawClaim:
    d = _obj(x, where)
    statement = _text(d, "statement", where)
    return RawClaim(
        statement=statement,
        premise=_strs(d, "premise", where),
        goal=_strs(d, "goal", where) or [statement],
        proof=[_parse_step(s, f"{where}.proof[{i}]") for i, s in enumerate(_list(d, "proof", where))],
    )


def _parse_step(x: Any, where: str) -> RawStep:
    d = _obj(x, where)
    return RawStep(
        text=_text(d, "text", where),
        add_premises=_strs(d, "add_premises", where),
        remove_premises=_strs(d, "remove_premises", where),
        close_goals=_strs(d, "close_goals", where),
        add_goals=_strs(d, "add_goals", where),
        justification=_strs(d, "justification", where),
        dependency=_strs(d, "dependency", where),
        claims=[_parse_claim(c, f"{where}.claims[{j}]") for j, c in enumerate(_list(d, "claims", where))],
    )


def parse_raw_proof(x: Any) -> RawProof:
    d = _obj(x, "the answer")
    steps = _list(d, "steps", "the answer")
    if not steps:
        raise ExtractionError("the answer has no steps")
    return RawProof(
        premise=_strs(d, "premise", "the answer"),
        goal=_strs(d, "goal", "the answer"),
        steps=[_parse_step(s, f"steps[{i}]") for i, s in enumerate(steps)],
    )


# ---------------------------------------------------------------------------
# Builder (IR -> unit checkpoints). Deterministic; no model involved.
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return " ".join(s.split())


def _short(s: str, n: int = 50) -> str:
    s = _norm(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _check_step(step: RawStep) -> list[str]:
    if not step.justification:
        return ["has no justification; give the evidence for this step"]
    return []


def _restates_conclusion(step: RawStep) -> bool:
    """A step that changes nothing. After every goal is closed it can only be the
    proof restating what it has proved, so it is dropped rather than rejected."""
    return not (step.add_premises or step.remove_premises or step.close_goals
                or step.add_goals or step.claims)


def _remove(items: list[str], targets: list[str], verb: str, noun: str, errs: list[str]) -> int | None:
    """Remove targets from items (whitespace-insensitive); return the first index removed."""
    first = None
    for t in targets:
        keys = [_norm(x) for x in items]
        if _norm(t) in keys:
            i = keys.index(_norm(t))
            del items[i]
            first = i if first is None else min(first, i)
        else:
            errs.append(f"cannot {verb} {noun} {t!r}: it is not in the current state. Current {noun}s: {items}")
    return first


def _add(items: list[str], new: list[str], at: int | None = None) -> None:
    seen = {_norm(x) for x in items}
    fresh = []
    for x in new:
        if _norm(x) not in seen:
            fresh.append(x)
            seen.add(_norm(x))
    if at is None:
        items.extend(fresh)
    else:
        items[at:at] = fresh


@dataclass
class _Ctx:
    theorem_id: str
    language: ProofLanguage
    proof_text: str | None  # normalised; None skips the verbatim check
    problems: list[str] = field(default_factory=list)
    next_id: int = 0

    def new_state(self, premise, goal) -> State:
        s = State(tuple(premise), tuple(goal), self.next_id)
        self.next_id += 1
        return s


def _build(ctx: _Ctx, start: State, steps: list[RawStep], where: str) -> list[Checkpoint]:
    units: list[Checkpoint] = []
    state = start
    for i, step in enumerate(steps):
        here = f"{where}[{i}]"
        if state.is_closed and _restates_conclusion(step):
            continue  # e.g. "Hence √2 is irrational." after the goal is closed: nothing to record

        mark = len(ctx.problems)  # so this step's problems are listed before its claims'
        errs = _check_step(step)
        if state.is_closed:
            errs.append("comes after every goal is already closed")
        if ctx.proof_text is not None and _norm(step.text) not in ctx.proof_text:
            errs.append("its text is not a verbatim span of the proof; copy the text exactly")

        premises, goals = list(state.premise), list(state.goal)
        _remove(premises, step.remove_premises, "remove", "premise", errs)
        _add(premises, step.add_premises)
        at = _remove(goals, step.close_goals, "close", "goal", errs)
        # New goals take the place of the goal they came from; otherwise they go first.
        _add(goals, step.add_goals, at=at if at is not None else 0)

        # Claims: each is proved in its own State (premises available before
        # this step + its own local premises), so its assumptions stay inside it.
        claims: list[tuple[str, State]] = []
        claim_proofs: list[Checkpoint | None] = []
        for j, claim in enumerate(step.claims):
            local = list(state.premise)
            _add(local, claim.premise)
            claim_state = ctx.new_state(local, claim.goal)
            claims.append((claim.statement, claim_state))
            _add(premises, [claim.statement])  # once proved, the claim is usable
            sub = _build(ctx, claim_state, claim.proof, f"{here}.claims[{j}].proof") if claim.proof else []
            if not sub:
                # The text states the claim without proving it ("Since (√x - √y)^2 ≥ 0, ...").
                # Kept as a claim with no proof, so a formal proof can be required for it later.
                claim_proofs.append(None)
                continue
            if not sub[-1].next_state.is_closed:
                errs.append(f"the proof of claim {claim.statement!r} leaves goals open: {list(sub[-1].next_state.goal)}")
            claim_proofs.append(compose(sub))

        if (tuple(premises), tuple(goals)) == (state.premise, state.goal):
            errs.append(
                "does not change the proof state, so it is not a unit step; "
                "merge it into a neighbouring step or leave it out"
            )

        nxt = ctx.new_state(premises, goals)
        ctx.problems[mark:mark] = [f"{here} {_short(step.text)!r}: {e}" for e in errs]
        units.append(Checkpoint(
            language=ctx.language,
            theorem_id=ctx.theorem_id,
            prev_state=state,
            next_state=nxt,
            justification=list(step.justification),
            dependency=set(step.dependency),
            intermediate_claims=claims,
            proofs_intermediate_claims=claim_proofs,
            source=[step.text],
        ))
        state = nxt
    return units


def build_unit_checkpoints(
    theorem_id: str,
    language: ProofLanguage,
    raw: RawProof,
    proof_text: str | None = None,
    require_complete: bool = True,
) -> list[Checkpoint]:
    """Turn a RawProof into a chain of unit checkpoints.

    compose() the result to get the whole proof as one Checkpoint. Raises
    ExtractionError listing *every* problem found, so one repair round can fix
    them all. If proof_text is given, every step's text (at any depth) must be
    a verbatim span of it, which catches invented or paraphrased steps.
    """
    ctx = _Ctx(theorem_id, language, _norm(proof_text) if proof_text is not None else None)
    if not raw.goal:
        ctx.problems.append("the theorem has no goal")
    if not raw.steps:
        ctx.problems.append("the proof has no steps")
    start = ctx.new_state(raw.premise, raw.goal)
    units = _build(ctx, start, raw.steps, "steps")
    if require_complete and units and not units[-1].next_state.is_closed:
        ctx.problems.append(f"the proof ends with goals still open: {list(units[-1].next_state.goal)}")
    if ctx.problems:
        raise ExtractionError("\n".join(f"- {p}" for p in ctx.problems))
    return units