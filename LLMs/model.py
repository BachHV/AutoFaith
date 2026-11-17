"""Core data model: a proof is represented by Checkpoints.

- A unit checkpoint is one state update (one step of the proof).
- Combining checkpoints gives a bigger checkpoint that still remembers the
  unit checkpoints it is made of (`parts`), so a whole proof is one Checkpoint
  and nothing is lost by combining.
- Branching (an intermediate result, the cases of a case split, the cases of an
  induction) goes through intermediate_claims: each claim has its own State,
  so assumptions made inside a claim never leak into the rest of the proof.

Pure data and composition only: nothing here knows how checkpoints are extracted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import reduce
from typing import Iterable


class ProofLanguage(str, Enum):
    NL = "Natural Language"
    FL = "Formal Language"


@dataclass(frozen=True)
class State:
    """What is known (premise) and what is left to prove (goal).

    Frozen, with tuples instead of lists, because one State object is shared by
    two checkpoints (a.next_state is b.prev_state): mutating it through one of
    them would silently change the other.
    """

    premise: tuple[str, ...] = ()
    goal: tuple[str, ...] = ()
    id: int = -1

    @property
    def is_closed(self) -> bool:
        return not self.goal

    def same_content(self, other: State) -> bool:
        return self.premise == other.premise and self.goal == other.goal


@dataclass
class Checkpoint:
    language: ProofLanguage
    theorem_id: str
    prev_state: State
    next_state: State
    justification: list[str] = field(default_factory=list)
    dependency: set[str] = field(default_factory=set)
    # (statement, State the claim is proved in): a claim's statement is a State itself
    intermediate_claims: list[tuple[str, State]] = field(default_factory=list)
    # proofs_intermediate_claims[i] proves intermediate_claims[i]: it runs from
    # that claim's State to a closed state. None when the text states the claim
    # without proving it (e.g. "Since (√x - √y)^2 ≥ 0, ..."); see unproved_claims().
    proofs_intermediate_claims: list[Checkpoint | None] = field(default_factory=list)
    # --- added fields ---
    # the proof text this checkpoint covers
    source: list[str] = field(default_factory=list)
    # the unit checkpoints a combined checkpoint is made of, in order; empty for a unit
    parts: list[Checkpoint] = field(default_factory=list)

    @property
    def is_unit(self) -> bool:
        return not self.parts

    def units(self) -> list[Checkpoint]:
        """The unit checkpoints this checkpoint consists of ([self] for a unit)."""
        return list(self.parts) if self.parts else [self]

    @property
    def is_complete_proof(self) -> bool:
        return self.next_state.is_closed


class CombineError(ValueError):
    """Two checkpoints cannot be combined."""


def combine_checkpoints(a: Checkpoint, b: Checkpoint) -> Checkpoint:
    if a.language != b.language:
        raise CombineError(f"different languages: {a.language.name} vs {b.language.name}")
    if a.theorem_id != b.theorem_id:
        raise CombineError(f"different theorems: {a.theorem_id!r} vs {b.theorem_id!r}")
    if a.next_state != b.prev_state:
        raise CombineError(
            f"states don't chain: first ends at state {a.next_state.id}, "
            f"second starts at state {b.prev_state.id}"
        )
    return Checkpoint(
        language=a.language,
        theorem_id=a.theorem_id,
        prev_state=a.prev_state,
        next_state=b.next_state,
        justification=a.justification + b.justification,
        dependency=a.dependency | b.dependency,
        intermediate_claims=a.intermediate_claims + b.intermediate_claims,
        proofs_intermediate_claims=a.proofs_intermediate_claims + b.proofs_intermediate_claims,
        source=a.source + b.source,
        parts=a.units() + b.units(),
    )


def compose(checkpoints: Iterable[Checkpoint]) -> Checkpoint:
    """Fold a chain of checkpoints into one (combine_checkpoints is associative)."""
    chain = list(checkpoints)
    if not chain:
        raise CombineError("nothing to compose")
    return reduce(combine_checkpoints, chain)


def outline(cp: Checkpoint, indent: int = 0, width: int = 70) -> str:
    """Readable tree of a proof: one line per unit step, each claim's proof nested under it."""
    pad = "  " * indent
    lines = []
    for u in cp.units():
        text = " ".join(" ".join(u.source).split())
        if len(text) > width:
            text = text[: width - 1] + "…"
        lines.append(f"{pad}state {u.prev_state.id} -> {u.next_state.id}: {text}")
        for (statement, state), proof in zip(u.intermediate_claims, u.proofs_intermediate_claims):
            local = [p for p in state.premise if p not in u.prev_state.premise]
            lines.append(f"{pad}  claim {statement!r}" + (f", assuming {local}" if local else "")
                         + ("   (no proof in the text)" if proof is None else ""))
            if proof is not None:
                lines.append(outline(proof, indent + 2, width))
    return "\n".join(lines)

def _diff(before: tuple[str, ...], after: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """(added, removed) going from before to after, keeping order."""
    return [x for x in after if x not in before], [x for x in before if x not in after]


def _state_lines(state: State, pad: str) -> list[str]:
    def block(name: str, items: tuple[str, ...]) -> list[str]:
        if not items:
            return [f"{pad}  {name}: (none)"]
        return [f"{pad}  {name}:"] + [f"{pad}    - {x}" for x in items]

    return block("premise", state.premise) + block("goal", state.goal)


def trace(cp: Checkpoint, indent: int = 0) -> str:
    """The proof as a sequence of checkpoints, showing the whole state after every update.

    For each unit checkpoint: the text it covers, what it changed (+ added, - removed),
    its justification and dependencies, then the full state it leads to. A claim's
    proof is traced, indented, from the claim's own state.
    """
    pad = "  " * indent
    units = cp.units()
    lines = [f"{pad}state {units[0].prev_state.id} (start)"] + _state_lines(units[0].prev_state, pad)
    for k, u in enumerate(units, 1):
        prev, nxt = u.prev_state, u.next_state
        lines.append("")
        lines.append(f"{pad}[{k}/{len(units)}] state {prev.id} -> {nxt.id}: {' '.join(' '.join(u.source).split())}")
        claimed = {s for s, _ in u.intermediate_claims}
        added_p, removed_p = _diff(prev.premise, nxt.premise)
        added_g, removed_g = _diff(prev.goal, nxt.goal)
        unproved = {s for (s, _), p in zip(u.intermediate_claims, u.proofs_intermediate_claims) if p is None}
        lines += [f"{pad}  + premise: {x}" + ("   (claim, no proof in the text)" if x in unproved
                                              else "   (proved as a claim below)" if x in claimed else "")
                  for x in added_p]
        lines += [f"{pad}  - premise: {x}" for x in removed_p]
        lines += [f"{pad}  - goal:    {x}   (closed)" for x in removed_g]
        lines += [f"{pad}  + goal:    {x}" for x in added_g]
        if u.justification:
            lines.append(f"{pad}  because:  " + "; ".join(u.justification))
        if u.dependency:
            lines.append(f"{pad}  uses:     " + "; ".join(sorted(u.dependency)))
        for (statement, state), proof in zip(u.intermediate_claims, u.proofs_intermediate_claims):
            local = [p for p in state.premise if p not in prev.premise]
            lines.append(f"{pad}  claim: {statement}" + (f"   assuming {local}" if local else ""))
            if proof is None:
                lines.append(f"{pad}    proof: none in the text (to be proved formally)")
                lines += _state_lines(state, pad + "    ")
                continue
            lines.append(trace(proof, indent + 2))
            lines.append(f"{pad}  end of claim: {statement}")
        lines.append(f"{pad}-> state {nxt.id}" + ("   (all goals closed)" if nxt.is_closed else ""))
        lines += _state_lines(nxt, pad)
    return "\n".join(lines)


def unproved_claims(cp: Checkpoint) -> list[tuple[str, State]]:
    """Every claim the text states without proving, at any depth, in proof order.

    Each comes with the State it has to be proved in (its premises and goal), so
    a formal proof can be required for it.
    """
    found: list[tuple[str, State]] = []
    for u in cp.units():
        for claim, proof in zip(u.intermediate_claims, u.proofs_intermediate_claims):
            if proof is None:
                found.append(claim)
            else:
                found += unproved_claims(proof)
    return found
