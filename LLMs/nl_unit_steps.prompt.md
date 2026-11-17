You are segmenting a mathematical proof into **unit steps** and recording how each step changes the proof state.

## Proof state
A proof state has
- `premise`: facts currently available (hypotheses, introduced variables, facts derived so far)
- `goal`: statements that still have to be proved

## Unit steps
A unit step is the smallest piece of the proof that changes the proof state. A step does one or more of:
- adds premises: introduces a variable or hypothesis, defines an object, derives a fact
- removes premises: when a fact is replaced, e.g. by substitution
- closes goals: proves them, or replaces them with goals that suffice (added with `add_goals`)
- adds goals
- introduces claims (see below)

## Claims
A step can introduce **claims**: results proved separately, each in its own proof state. A claim has
- `statement`: the result as one sentence. Once proved, it becomes a premise automatically, so do not also list it in `add_premises`.
- `premise`: assumptions that hold only inside the claim, such as a case assumption or an induction hypothesis. The claim also has every premise that was available before the step.
- `goal`: what has to be proved inside the claim. Defaults to [`statement`].
- `proof`: the steps proving it, ending with no open goals. Use [] when the text gives no proof.

Use claims for an intermediate result proved within the proof, for each case of a case split, and for the base and inductive cases of an induction. Assumptions made inside a claim stay inside it.

A fact the proof asserts without deriving it (stated as a reason or a known fact: "Since $(\sqrt{x} - \sqrt{y})^2 \ge 0$, ...", "Note that ...", "Recall that ...", "It is well known that ...") is also a claim, with "proof": [] — not an entry in `add_premises`. Every such fact must be proved separately later, so it has to be recorded as a claim. A fact the step derives from the premises it already has (by computing, substituting, or rearranging) stays in `add_premises`.

For a proof by contradiction, the contradiction argument is a claim: its `premise` is the assumption made for contradiction (e.g. "√2 is rational"), its `goal` is ["a contradiction"], and its proof ends with the step that reaches the contradiction. Its `statement` says what it shows, e.g. "√2 is not rational". The step that introduces this claim also closes the main goal. Do not add the assumption as a premise of the main proof, and do not replace the main goal with "a contradiction".

A sentence that only restates what has just been proved (e.g. "Hence √2 is irrational.", "This completes the induction.", "In either case, ...") is not a step: the goal is already closed by the step before it. Leave it out.

## Rules
1. `text` is copied **verbatim** from the proof as one contiguous span. Do not paraphrase, fix typos or re-typeset.
2. One step per state change. Split a sentence only if it changes the state more than once; do not merge sentences that change the state separately.
3. Text that changes nothing on its own (e.g. "We now proceed to the main argument.") is not a step. Leave it out.
4. Report only what changes. Do not restate the whole state.
5. When closing a goal or removing a premise, write it **exactly** as it was written when it was added.
6. `justification` is the evidence for the step, using only what is already known or what the step itself contains. Never point elsewhere ("see below", "used later", "as we will show").
7. `dependency`: definitions, lemmas or premises the step uses.
8. When a claim's proof follows its statement directly, the step's `text` runs from the statement to the end of that proof. When the proof is given elsewhere (e.g. a lemma proved at the end), the step's `text` is just the statement, and the proof steps take their `text` from wherever the proof is.
9. The proof ends with no open goals.

## Output format
Return one JSON object and nothing else. Omitted lists default to []. Escape backslashes in LaTeX (write "\\frac", not "\frac").

```
Proof = { "premise": [string], "goal": [string], "steps": [Step] }
Step  = { "text": string,
          "add_premises": [string], "remove_premises": [string],
          "close_goals": [string],  "add_goals": [string],
          "justification": [string], "dependency": [string],
          "claims": [Claim] }
Claim = { "statement": string, "premise": [string], "goal": [string], "proof": [Step] }
```

## Example 1: an intermediate result
Theorem: If n is an odd integer, then 8 divides n^2 - 1.
Proof: Write n = 2m + 1 for some integer m. Then n^2 - 1 = 4m(m+1). We claim that m(m+1) is even. Indeed, one of m and m+1 is even, so their product is even. Therefore 8 divides 4m(m+1) = n^2 - 1.

```json
{
  "premise": ["n is an integer", "n is odd"],
  "goal": ["8 divides n^2 - 1"],
  "steps": [
    {
      "text": "Write n = 2m + 1 for some integer m.",
      "add_premises": ["m is an integer", "n = 2m + 1"],
      "justification": ["n is odd, so by definition n = 2m + 1 for some integer m"],
      "dependency": ["definition of odd", "n is odd"]
    },
    {
      "text": "Then n^2 - 1 = 4m(m+1).",
      "add_premises": ["n^2 - 1 = 4m(m+1)"],
      "justification": ["(2m + 1)^2 - 1 = 4m^2 + 4m = 4m(m+1)"],
      "dependency": ["n = 2m + 1"]
    },
    {
      "text": "We claim that m(m+1) is even. Indeed, one of m and m+1 is even, so their product is even.",
      "justification": ["one of the consecutive integers m and m+1 is even, so their product is even"],
      "dependency": ["m is an integer"],
      "claims": [
        {
          "statement": "m(m+1) is even",
          "proof": [
            {
              "text": "Indeed, one of m and m+1 is even,",
              "add_premises": ["one of m and m+1 is even"],
              "justification": ["of two consecutive integers, one is even"],
              "dependency": ["m is an integer"]
            },
            {
              "text": "so their product is even.",
              "close_goals": ["m(m+1) is even"],
              "justification": ["a product with an even factor is even"],
              "dependency": ["one of m and m+1 is even"]
            }
          ]
        }
      ]
    },
    {
      "text": "Therefore 8 divides 4m(m+1) = n^2 - 1.",
      "close_goals": ["8 divides n^2 - 1"],
      "justification": ["m(m+1) = 2t for an integer t, so n^2 - 1 = 4m(m+1) = 8t"],
      "dependency": ["m(m+1) is even", "n^2 - 1 = 4m(m+1)"]
    }
  ]
}
```

## Example 2: a case split
Theorem: For every real number x, |x| ≥ x.
Proof: Let x be a real number. If x ≥ 0, then |x| = x, so |x| ≥ x. If x < 0, then |x| = -x > 0 > x, so |x| ≥ x.

```json
{
  "premise": [],
  "goal": ["for every real number x, |x| ≥ x"],
  "steps": [
    {
      "text": "Let x be a real number.",
      "add_premises": ["x is a real number"],
      "close_goals": ["for every real number x, |x| ≥ x"],
      "add_goals": ["|x| ≥ x"],
      "justification": ["to prove the statement for every real x, fix an arbitrary one"]
    },
    {
      "text": "If x ≥ 0, then |x| = x, so |x| ≥ x. If x < 0, then |x| = -x > 0 > x, so |x| ≥ x.",
      "close_goals": ["|x| ≥ x"],
      "justification": ["every real number satisfies x ≥ 0 or x < 0, and |x| ≥ x holds in both cases"],
      "dependency": ["x is a real number"],
      "claims": [
        {
          "statement": "if x ≥ 0, then |x| ≥ x",
          "premise": ["x ≥ 0"],
          "goal": ["|x| ≥ x"],
          "proof": [
            {
              "text": "If x ≥ 0, then |x| = x,",
              "add_premises": ["|x| = x"],
              "justification": ["by definition, |x| = x when x ≥ 0"],
              "dependency": ["definition of absolute value", "x ≥ 0"]
            },
            {
              "text": "so |x| ≥ x.",
              "close_goals": ["|x| ≥ x"],
              "justification": ["|x| = x and x ≥ x"],
              "dependency": ["|x| = x"]
            }
          ]
        },
        {
          "statement": "if x < 0, then |x| ≥ x",
          "premise": ["x < 0"],
          "goal": ["|x| ≥ x"],
          "proof": [
            {
              "text": "If x < 0, then |x| = -x > 0 > x,",
              "add_premises": ["|x| > x"],
              "justification": ["when x < 0, |x| = -x, which is positive and therefore greater than x"],
              "dependency": ["definition of absolute value", "x < 0"]
            },
            {
              "text": "so |x| ≥ x.",
              "close_goals": ["|x| ≥ x"],
              "justification": ["|x| > x implies |x| ≥ x"],
              "dependency": ["|x| > x"]
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
Theorem: {{statement}}
Proof: {{proof}}