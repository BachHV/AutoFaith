"""Lean 4 (Mathlib) proofs to run through llm.py.

    uv run python llm.py                       # every proof here and in nl_proofs.py
    uv run python llm.py --only le_and_ne_zero # just one (repeat --only for more)
    uv run python llm.py --list                # print the ids of all proofs

Every proof here is declared ProofLanguage.FL, which is what makes llm.py use
the Lean prompt. A proof that formalises a theorem from nl_proofs.py uses the
same theorem_id, so the natural-language and Lean checkpoints of a theorem can
be compared; `--only <id>` runs both.

statement is the theorem header and proof is the text after `:=` (`by` + tactics,
or a term), so lean_source(item) is the full Lean source. Add a proof by
appending to PROOFS; theorem_id must be unique within this file.
"""
from __future__ import annotations

import textwrap

from extract import ProofInput
from model import ProofLanguage

FL = ProofLanguage.FL


def _by(tactics: str) -> str:
    """A tactic proof: `by` followed by the tactics, indented by two spaces."""
    return "by\n" + textwrap.indent(textwrap.dedent(tactics).strip("\n"), "  ")


def lean_source(item: ProofInput) -> str:
    """The full Lean source of a proof, e.g. to check it with Lean."""
    return f"{item.statement} := {item.proof}"


PROOFS: list[ProofInput] = [
    # --- direct proofs -----------------------------------------------------
    ProofInput(
        theorem_id="odd_plus_odd",
        language=FL,
        statement="theorem odd_plus_odd (a b : ℤ) (ha : Odd a) (hb : Odd b) : Even (a + b)",
        proof=_by("""
            obtain ⟨k, hk⟩ := ha
            obtain ⟨l, hl⟩ := hb
            exact ⟨k + l + 1, by rw [hk, hl]; ring⟩
        """),
    ),
    ProofInput(
        theorem_id="divides_transitive",
        language=FL,
        statement="theorem divides_transitive {a b c : ℤ} (h₁ : a ∣ b) (h₂ : b ∣ c) : a ∣ c",
        proof=_by("""
            obtain ⟨m, hm⟩ := h₁
            obtain ⟨n, hn⟩ := h₂
            refine ⟨m * n, ?_⟩
            rw [hn, hm]
            ring
        """),
    ),
    ProofInput(
        theorem_id="am_gm_two",
        language=FL,
        statement="theorem am_gm_two (x y : ℝ) (hx : 0 ≤ x) (hy : 0 ≤ y) : Real.sqrt (x * y) ≤ (x + y) / 2",
        proof=_by("""
            have h : 0 ≤ (Real.sqrt x - Real.sqrt y) ^ 2 := sq_nonneg _
            rw [Real.sqrt_mul hx y]
            nlinarith [Real.sq_sqrt hx, Real.sq_sqrt hy]
        """),
    ),
    ProofInput(
        theorem_id="le_and_ne_zero",
        language=FL,
        statement="theorem le_and_ne_zero (n : ℕ) (h : 2 ≤ n) : 1 ≤ n ∧ n ≠ 0",
        proof=_by("""
            constructor
            · omega
            · omega
        """),
    ),
    # --- case splits -------------------------------------------------------
    ProofInput(
        theorem_id="square_plus_n_even_by_cases",
        language=FL,
        statement="theorem square_plus_n_even_by_cases (n : ℤ) : Even (n ^ 2 + n)",
        proof=_by("""
            rcases Int.even_or_odd n with ⟨k, hk⟩ | ⟨k, hk⟩
            · exact ⟨2 * k ^ 2 + k, by rw [hk]; ring⟩
            · exact ⟨2 * k ^ 2 + 3 * k + 1, by rw [hk]; ring⟩
        """),
    ),
    # --- a term-mode proof and an existence proof ----------------------------
    ProofInput(
        theorem_id="sqrt2_irrational",
        language=FL,
        statement="theorem sqrt2_irrational : Irrational (Real.sqrt 2)",
        proof="irrational_sqrt_two",
    ),
    ProofInput(
        theorem_id="infinitely_many_primes",
        language=FL,
        statement="theorem infinitely_many_primes (n : ℕ) : ∃ p, n ≤ p ∧ Nat.Prime p",
        proof=_by("""
            obtain ⟨p, hp, hprime⟩ := Nat.exists_infinite_primes n
            exact ⟨p, hp, hprime⟩
        """),
    ),
    # --- induction ---------------------------------------------------------
    ProofInput(
        theorem_id="sum_first_n",
        language=FL,
        statement="theorem sum_first_n (n : ℕ) : 2 * ∑ i ∈ Finset.range (n + 1), i = n * (n + 1)",
        proof=_by("""
            induction n with
            | zero => simp
            | succ k ih =>
              rw [Finset.sum_range_succ, mul_add, ih]
              ring
        """),
    ),
    # --- a lemma proved first ----------------------------------------------
    ProofInput(
        theorem_id="square_plus_n_even",
        language=FL,
        statement="theorem square_plus_n_even (n : ℤ) : Even (n ^ 2 + n)",
        proof=_by("""
            have h : ∀ k : ℤ, Even (k * (k + 1)) := by
              intro k
              exact Int.even_mul_succ_self k
            have hn : n ^ 2 + n = n * (n + 1) := by ring
            rw [hn]
            exact h n
        """),
    ),
]

BY_ID: dict[str, ProofInput] = {p.theorem_id: p for p in PROOFS}
assert len(BY_ID) == len(PROOFS), "theorem_id values in PROOFS must be unique"