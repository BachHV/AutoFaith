You are segmenting a **Lean 4** proof into **unit steps** and recording how each step changes the proof state, i.e. the tactic state Lean would show.

## Proof state
A proof state has
- `premise`: the local context, one entry per variable or hypothesis, written `name : type` as Lean shows it (e.g. "n : ℕ", "h : a ∣ b"). Instance arguments such as `[Fintype α]` may be left out.
- `goal`: the goals still to prove, written as Lean shows them after `⊢` (without the `⊢`).

The starting state comes from the theorem statement: its binders are the premises and its conclusion is the goal. The proof is the text after `:=`: either `by` followed by tactics, or a term.

## Unit steps
A unit step is one tactic that changes the proof state. Its `text` is the tactic exactly as written, with its arguments. Leave out structure that is not a tactic: the leading `by`, focusing dots `·`, case labels such as `| zero =>` or `case succ =>`, and comments.
- Tactics on separate lines, or separated by `;`, are separate steps. A combinator such as `tac₁ <;> tac₂`, `all_goals tac`, `try tac` or `first | tac₁ | tac₂` is one step.
- A tactic that changes nothing (e.g. `skip`) is not a step.
- A term-mode proof (no `by`), and a term given to `exact`, is one step, except for the `by` blocks nested inside it (see Claims).

How common tactics change the state:
- `intro x h`, `rintro ⟨x, hx⟩`: close the goal, add the introduced premises, and add the new goal.
- `obtain ⟨x, hx⟩ := h`, `rcases h with ⟨x, hx⟩`, `cases h` with a single case: remove `h` and add its parts.
- `rw [...]`, `simp only [...]`, `norm_num`, `ring_nf`, `push_neg`, `unfold`, `change`, `show`: on the goal, close the old goal and add the new one; with `at h`, remove the old `h` and add the new `h`; `at h ⊢` does both. If the tactic finishes the goal, add no new goal.
- `exact`, `simp`, `omega`, `linarith`, `nlinarith`, `positivity`, `ring`, `norm_num`, `decide`, `rfl`, `assumption`, `tauto`, `aesop` that finish a goal: close it.
- `apply h`, `refine`, `exact` leaving `?_` holes, `constructor`, `cases`/`rcases` with several alternatives (`h | h`), `induction`, `by_cases`, `by_contra`, `interval_cases`, `match`: whenever a tactic leaves **more than one** goal, the step closes the goal it acted on and every goal it leaves becomes a **claim** (see Claims), even when the proofs are not written under `·` or `case`. When it leaves exactly one goal, close the old goal and add the new one, adding any new hypotheses to `add_premises`.
- `sorry`: the goal is not proved. The step closes the goal and introduces a claim for it with `"proof": []`.

## Claims
A claim is a goal proved in its own proof state. A claim has
- `statement`: what the claim establishes, as a Lean proposition. For `have h : P`, write "h : P" (once proved it is the hypothesis `h`). For a goal left by a tactic, write the goal, with its local hypotheses as an implication, e.g. "∀ k : ℕ, k < 2 ^ k → k + 1 < 2 ^ (k + 1)". Once proved, the statement becomes a premise automatically, so do not also list it in `add_premises`.
- `premise`: hypotheses that exist only in that goal, such as the variables and hypothesis of a case (`k : ℕ`, `ih : ...`) or the hypothesis named by `by_cases h : P`. The claim also has every premise available before the step, except those the step removes (e.g. `induction n` removes `n : ℕ`).
- `goal`: the goal to prove inside the claim. Defaults to [`statement`]; for `have h : P` it is ["P"].
- `proof`: the tactic steps proving that goal, ending with no open goals. Use [] when the proof is `sorry`.

Use claims for `have` (and `obtain ... : P := ...`, `suffices`) with its proof, for each goal left by a tactic that leaves several goals, and for a `by` block nested inside a term (e.g. `exact ⟨w, by simp⟩`: the `by` block proves a side goal). A `have h : P := term` has a one-step proof whose `text` is the term. Hypotheses introduced inside a claim stay inside it.

## Rules
1. `text` is copied **verbatim** from the proof as one contiguous span. Do not paraphrase or re-indent tokens; line breaks may become spaces.
2. One step per tactic that changes the state; do not merge tactics, and do not split one tactic.
3. Report only what changes. Do not restate the whole state.
4. When closing a goal or removing a premise, write it **exactly** as it was written when it was added.
5. Write premises and goals in Lean syntax with the symbols Lean prints (ℕ, ℤ, ℝ, ∣, ≤, ≠, →, ∀, ∃, ∧, ∨, ¬).
6. `justification` says why the tactic succeeds: what it does and which facts make it work (e.g. "omega: from ih, 2 ^ k ≥ k + 1"). Never point elsewhere ("see below").
7. `dependency`: lemma names and hypothesis names the step uses (e.g. "pow_succ", "ih").
8. When a claim's proof follows its statement directly (a `have ... := by` block, the cases of `induction ... with`, `·` bullets), the step's `text` runs from the tactic to the end of those proofs, and each proof step's `text` lies inside it.
9. The proof ends with no open goals.

## Output format
Return one JSON object and nothing else. Omitted lists default to []. In JSON strings write line breaks as \n and escape `\` and `"`.

```
Proof = { "premise": [string], "goal": [string], "steps": [Step] }
Step  = { "text": string,
          "add_premises": [string], "remove_premises": [string],
          "close_goals": [string],  "add_goals": [string],
          "justification": [string], "dependency": [string],
          "claims": [Claim] }
Claim = { "statement": string, "premise": [string], "goal": [string], "proof": [Step] }
```

## Example 1: a `have` with a tactic proof
Theorem:
```lean
theorem dvd_mul_of_dvd' {a b c : ℤ} (h : a ∣ b) : a ∣ b * c
```
Proof:
```lean
by
  obtain ⟨m, hm⟩ := h
  have hbc : b * c = a * (m * c) := by
    rw [hm]
    ring
  exact ⟨m * c, hbc⟩
```

```json
{
  "premise": ["a : ℤ", "b : ℤ", "c : ℤ", "h : a ∣ b"],
  "goal": ["a ∣ b * c"],
  "steps": [
    {
      "text": "obtain ⟨m, hm⟩ := h",
      "remove_premises": ["h : a ∣ b"],
      "add_premises": ["m : ℤ", "hm : b = a * m"],
      "justification": ["a ∣ b unfolds to ∃ m, b = a * m; obtain takes the witness m and the equation hm"],
      "dependency": ["h"]
    },
    {
      "text": "have hbc : b * c = a * (m * c) := by\n    rw [hm]\n    ring",
      "justification": ["substituting b = a * m gives a * m * c, which is a * (m * c) by associativity"],
      "dependency": ["hm"],
      "claims": [
        {
          "statement": "hbc : b * c = a * (m * c)",
          "goal": ["b * c = a * (m * c)"],
          "proof": [
            {
              "text": "rw [hm]",
              "close_goals": ["b * c = a * (m * c)"],
              "add_goals": ["a * m * c = a * (m * c)"],
              "justification": ["rewrite b as a * m using hm"],
              "dependency": ["hm"]
            },
            {
              "text": "ring",
              "close_goals": ["a * m * c = a * (m * c)"],
              "justification": ["both sides are equal by associativity of multiplication"]
            }
          ]
        }
      ]
    },
    {
      "text": "exact ⟨m * c, hbc⟩",
      "close_goals": ["a ∣ b * c"],
      "justification": ["a ∣ b * c means ∃ d, b * c = a * d, and hbc shows d = m * c works"],
      "dependency": ["hbc"]
    }
  ]
}
```

## Example 2: induction
Theorem:
```lean
theorem lt_two_pow' (n : ℕ) : n < 2 ^ n
```
Proof:
```lean
by
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [pow_succ]
    omega
```

```json
{
  "premise": ["n : ℕ"],
  "goal": ["n < 2 ^ n"],
  "steps": [
    {
      "text": "induction n with\n  | zero => norm_num\n  | succ k ih =>\n    rw [pow_succ]\n    omega",
      "remove_premises": ["n : ℕ"],
      "close_goals": ["n < 2 ^ n"],
      "justification": ["induction on n: the statement holds for 0 and passes from k to k + 1"],
      "claims": [
        {
          "statement": "0 < 2 ^ 0",
          "proof": [
            {
              "text": "norm_num",
              "close_goals": ["0 < 2 ^ 0"],
              "justification": ["2 ^ 0 = 1 and 0 < 1"]
            }
          ]
        },
        {
          "statement": "∀ k : ℕ, k < 2 ^ k → k + 1 < 2 ^ (k + 1)",
          "premise": ["k : ℕ", "ih : k < 2 ^ k"],
          "goal": ["k + 1 < 2 ^ (k + 1)"],
          "proof": [
            {
              "text": "rw [pow_succ]",
              "close_goals": ["k + 1 < 2 ^ (k + 1)"],
              "add_goals": ["k + 1 < 2 ^ k * 2"],
              "justification": ["pow_succ rewrites 2 ^ (k + 1) as 2 ^ k * 2"],
              "dependency": ["pow_succ"]
            },
            {
              "text": "omega",
              "close_goals": ["k + 1 < 2 ^ k * 2"],
              "justification": ["from ih, 2 ^ k ≥ k + 1, so 2 ^ k * 2 ≥ 2 * k + 2 > k + 1"],
              "dependency": ["ih"]
            }
          ]
        }
      ]
    }
  ]
}
```

{{feedback}}
## Your task
Theorem:
```lean
{{statement}}
```
Proof:
```lean
{{proof}}
```