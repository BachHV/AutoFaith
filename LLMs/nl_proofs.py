"""Natural-language proofs to run through llm.py.

    uv run python llm.py                         # every proof below
    uv run python llm.py --only sqrt2_irrational # just one (repeat --only for more)
    uv run python llm.py --list                  # print the ids

Add a proof by appending a ProofInput to PROOFS. theorem_id must be unique.
The proofs cover different shapes so the prompt gets exercised: direct
proofs, case splits, contradiction, induction, and a lemma proved first.
"""
from __future__ import annotations

from extract import ProofInput
from model import ProofLanguage

NL = ProofLanguage.NL

PROOFS: list[ProofInput] = [
    # --- direct proofs -----------------------------------------------------
    ProofInput(
        theorem_id="odd_plus_odd",
        language=NL,
        statement="The sum of two odd integers is even.",
        proof=(
            "Let a and b be odd integers. Write a = 2k + 1 and b = 2l + 1 for integers k and l. "
            "Then a + b = 2(k + l + 1). Hence a + b is even."
        ),
    ),
    ProofInput(
        theorem_id="divides_transitive",
        language=NL,
        statement="For integers a, b, c, if a divides b and b divides c, then a divides c.",
        proof=(
            "Suppose a divides b and b divides c. "
            "Then b = am for some integer m, and c = bn for some integer n. "
            "Substituting, c = (am)n = a(mn). "
            "Since mn is an integer, a divides c."
        ),
    ),
    ProofInput(
        theorem_id="am_gm_two",
        language=NL,
        statement=r"For all real numbers $x, y \ge 0$, $\frac{x + y}{2} \ge \sqrt{xy}$.",
        proof=(
            r"Let $x, y \ge 0$. "
            r"Since $(\sqrt{x} - \sqrt{y})^2 \ge 0$, expanding gives $x - 2\sqrt{xy} + y \ge 0$. "
            r"Rearranging, $x + y \ge 2\sqrt{xy}$. "
            r"Dividing by 2 gives $\frac{x + y}{2} \ge \sqrt{xy}$."
        ),
    ),
    # --- case splits -------------------------------------------------------
    ProofInput(
        theorem_id="square_plus_n_even_by_cases",
        language=NL,
        statement="For every integer n, n^2 + n is even.",
        proof=(
            "Let n be an integer. "
            "If n is even, then n^2 and n are both even, so n^2 + n is even. "
            "If n is odd, then n^2 and n are both odd, so n^2 + n is even."
        ),
    ),
    ProofInput(
        theorem_id="square_mod_4",
        language=NL,
        statement="The square of every integer leaves remainder 0 or 1 when divided by 4.",
        proof=(
            "Let n be an integer. Then n is even or n is odd. "
            "If n is even, write n = 2k. Then n^2 = 4k^2, which leaves remainder 0. "
            "If n is odd, write n = 2k + 1. Then n^2 = 4k^2 + 4k + 1 = 4(k^2 + k) + 1, "
            "which leaves remainder 1. "
            "In either case n^2 leaves remainder 0 or 1 when divided by 4."
        ),
    ),
    # --- contradiction -----------------------------------------------------
    ProofInput(
        theorem_id="sqrt2_irrational",
        language=NL,
        statement=r"$\sqrt{2}$ is irrational.",
        proof=(
            r"Suppose, for contradiction, that $\sqrt{2}$ is rational. "
            r"Then $\sqrt{2} = p/q$ for integers $p, q$ with $q \neq 0$ and $\gcd(p, q) = 1$. "
            r"Squaring gives $p^2 = 2q^2$, so $p^2$ is even, and therefore $p$ is even. "
            r"Write $p = 2r$. Then $4r^2 = 2q^2$, so $q^2 = 2r^2$, and therefore $q$ is even. "
            r"Thus 2 divides both $p$ and $q$, contradicting $\gcd(p, q) = 1$. "
            r"Hence $\sqrt{2}$ is irrational."
        ),
    ),
    ProofInput(
        theorem_id="infinitely_many_primes",
        language=NL,
        statement="There are infinitely many prime numbers.",
        proof=(
            "Suppose there are only finitely many primes p_1, ..., p_n. "
            "Let N = p_1 p_2 ... p_n + 1. "
            "Since N > 1, N has a prime factor p. "
            "Then p is one of p_1, ..., p_n, so p divides p_1 p_2 ... p_n. "
            "Since p also divides N, p divides N - p_1 p_2 ... p_n = 1, which is impossible. "
            "Therefore there are infinitely many primes."
        ),
    ),
    # --- induction ---------------------------------------------------------
    ProofInput(
        theorem_id="sum_first_n",
        language=NL,
        statement="For every positive integer n, 1 + 2 + ... + n = n(n+1)/2.",
        proof=(
            "We proceed by induction on n. "
            "For n = 1, the left side is 1 and the right side is 1(2)/2 = 1. "
            "Now suppose 1 + 2 + ... + k = k(k+1)/2 for some positive integer k. "
            "Then 1 + 2 + ... + k + (k+1) = k(k+1)/2 + (k+1) = (k+1)(k+2)/2, "
            "which is the formula for n = k + 1. "
            "By induction, the formula holds for every positive integer n."
        ),
    ),
    ProofInput(
        theorem_id="three_divides_n_cubed_minus_n",
        language=NL,
        statement="For every natural number n, 3 divides n^3 - n.",
        proof=(
            "We use induction on n. "
            "When n = 0, n^3 - n = 0, which is divisible by 3. "
            "Assume 3 divides k^3 - k for some natural number k. "
            "Then (k+1)^3 - (k+1) = (k^3 - k) + 3(k^2 + k). "
            "Both terms are divisible by 3, so 3 divides (k+1)^3 - (k+1). "
            "This completes the induction."
        ),
    ),
    # --- a lemma proved first ----------------------------------------------
    ProofInput(
        theorem_id="square_plus_n_even",
        language=NL,
        statement="For every integer n, n^2 + n is even.",
        proof=(
            "First we show that the product of two consecutive integers is even. "
            "Let k be an integer. One of k and k+1 is even, so k(k+1) is even. "
            "Now n^2 + n = n(n+1). "
            "This is a product of two consecutive integers, hence n^2 + n is even."
        ),
    ),
]

BY_ID: dict[str, ProofInput] = {p.theorem_id: p for p in PROOFS}
assert len(BY_ID) == len(PROOFS), "theorem_id values in PROOFS must be unique"
