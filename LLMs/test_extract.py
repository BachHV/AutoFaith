"""No model needed: FakeLLM stands in for the real one.

    python test_extract.py      # or: pytest test_extract.py
"""
import copy
import json
import re
import tempfile
from pathlib import Path

from extract import (
    LLMStepExtractor,
    ProofInput,
    StaticExtractor,
    extract_proof,
    extract_unit_checkpoints,
    parse_json_object,
)
from model import CombineError, ProofLanguage, combine_checkpoints, compose, outline, trace, unproved_claims
from steps import ExtractionError, build_unit_checkpoints, parse_raw_proof

PROMPT = Path(__file__).parent / "nl_unit_steps.prompt.md"
CLAIM = "for every integer k, k(k+1) is even"

# --- Proof 1: an intermediate result proved on the spot ----------------------

ITEM = ProofInput(
    theorem_id="square_plus_n_even",
    language=ProofLanguage.NL,
    statement="For every integer n, n^2 + n is even.",
    proof=(
        "First we show that the product of two consecutive integers is even. "
        "Let k be an integer. One of k and k+1 is even, so k(k+1) is even. "
        "Now n^2 + n = n(n+1). "
        "This is a product of two consecutive integers, hence n^2 + n is even."
    ),
)

GOOD = {
    "premise": ["n is an integer"],
    "goal": ["n^2 + n is even"],
    "steps": [
        {
            "text": (
                "First we show that the product of two consecutive integers is even. "
                "Let k be an integer. One of k and k+1 is even, so k(k+1) is even."
            ),
            "justification": ["of k and k+1 one is even, and a product with an even factor is even"],
            "claims": [{
                "statement": CLAIM,
                "proof": [
                    {
                        "text": "Let k be an integer.",
                        "add_premises": ["k is an integer"],
                        "close_goals": [CLAIM],
                        "add_goals": ["k(k+1) is even"],
                        "justification": ["to prove the statement for every integer k, fix an arbitrary one"],
                    },
                    {
                        "text": "One of k and k+1 is even,",
                        "add_premises": ["one of k and k+1 is even"],
                        "justification": ["of two consecutive integers, one is even"],
                        "dependency": ["k is an integer"],
                    },
                    {
                        "text": "so k(k+1) is even.",
                        "close_goals": ["k(k+1) is even"],
                        "justification": ["a product with an even factor is even"],
                        "dependency": ["one of k and k+1 is even"],
                    },
                ],
            }],
        },
        {
            "text": "Now n^2 + n = n(n+1).",
            "add_premises": ["n^2 + n = n(n+1)"],
            "justification": ["factor out n"],
        },
        {
            "text": "This is a product of two consecutive integers, hence n^2 + n is even.",
            "close_goals": ["n^2 + n is even"],
            "justification": ["n(n+1) is a product of consecutive integers, so it is even by the claim with k = n"],
            "dependency": [CLAIM, "n^2 + n = n(n+1)"],
        },
    ],
}

# --- Proof 2: same theorem, by a case split ---------------------------------

CASES_ITEM = ProofInput(
    theorem_id="square_plus_n_even_by_cases",
    language=ProofLanguage.NL,
    statement="For every integer n, n^2 + n is even.",
    proof=(
        "Let n be an integer. "
        "If n is even, then n^2 and n are both even, so n^2 + n is even. "
        "If n is odd, then n^2 and n are both odd, so n^2 + n is even."
    ),
)


def _case(parity, square_fact, why):
    return {
        "statement": f"if n is {parity}, then n^2 + n is even",
        "premise": [f"n is {parity}"],
        "goal": ["n^2 + n is even"],
        "proof": [
            {
                "text": f"If n is {parity}, then n^2 and n are both {parity},",
                "add_premises": [square_fact],
                "justification": [f"the square of an {parity} number is {parity}"],
                "dependency": [f"n is {parity}"],
            },
            {
                "text": "so n^2 + n is even.",
                "close_goals": ["n^2 + n is even"],
                "justification": [why],
                "dependency": [square_fact, f"n is {parity}"],
            },
        ],
    }


GOOD_CASES = {
    "premise": [],
    "goal": ["for every integer n, n^2 + n is even"],
    "steps": [
        {
            "text": "Let n be an integer.",
            "add_premises": ["n is an integer"],
            "close_goals": ["for every integer n, n^2 + n is even"],
            "add_goals": ["n^2 + n is even"],
            "justification": ["to prove the statement for every integer n, fix an arbitrary one"],
        },
        {
            "text": CASES_ITEM.proof.split("Let n be an integer. ", 1)[1],
            "close_goals": ["n^2 + n is even"],
            "justification": ["every integer is even or odd, and n^2 + n is even in both cases"],
            "dependency": ["n is an integer"],
            "claims": [
                _case("even", "n^2 is even", "a sum of two even numbers is even"),
                _case("odd", "n^2 is odd", "a sum of two odd numbers is even"),
            ],
        },
    ],
}


def build(d, item=ITEM):
    return build_unit_checkpoints(item.theorem_id, item.language, parse_raw_proof(d), proof_text=item.proof)


def broken(edit, base=GOOD):
    d = copy.deepcopy(base)
    edit(d)
    return d


def expect_problem(d, fragment, item=ITEM):
    try:
        build(d, item)
    except ExtractionError as e:
        assert fragment in str(e), str(e)
        return str(e)
    raise AssertionError("expected an ExtractionError")


def expect_parse_error(d, fragment):
    try:
        parse_raw_proof(d)
    except ExtractionError as e:
        assert fragment in str(e), str(e)
    else:
        raise AssertionError("expected an ExtractionError")


class FakeLLM:
    """Stand-in for a real model: returns canned answers in order, records prompts."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0)


# --- the proof as Checkpoints ----------------------------------------------

def test_whole_proof_is_one_checkpoint_and_keeps_its_units():
    units = build(GOOD)
    proof = compose(units)
    assert proof.is_complete_proof and not proof.is_unit
    assert proof.units() == units and all(u.is_unit for u in units)
    for a, b in zip(units, units[1:]):
        assert a.next_state is b.prev_state

    # The claim's proof is itself a Checkpoint, and it keeps its own unit steps.
    (statement, claim_state), = proof.intermediate_claims
    claim_proof, = proof.proofs_intermediate_claims
    assert statement == CLAIM and claim_state.goal == (CLAIM,)
    assert claim_proof.prev_state is claim_state and claim_proof.is_complete_proof
    assert [u.source for u in claim_proof.units()] == [
        ["Let k be an integer."], ["One of k and k+1 is even,"], ["so k(k+1) is even."],
    ]
    assert CLAIM in units[0].next_state.premise  # proved claim became a premise


def test_case_assumptions_stay_inside_their_case():
    units = build(GOOD_CASES, CASES_ITEM)
    cases_step = units[1]
    (_, even_state), (_, odd_state) = cases_step.intermediate_claims
    assert "n is even" in even_state.premise and "n is odd" not in even_state.premise
    assert "n is odd" in odd_state.premise and "n is even" not in odd_state.premise
    after = cases_step.next_state.premise
    assert "n is even" not in after and "n is odd" not in after  # no leak
    assert all(p.is_complete_proof for p in cases_step.proofs_intermediate_claims)
    assert compose(units).is_complete_proof


def test_extract_proof_returns_a_checkpoint():
    proof = extract_proof(CASES_ITEM, StaticExtractor({CASES_ITEM.theorem_id: parse_raw_proof(GOOD_CASES)}))
    assert proof.is_complete_proof
    assert "assuming ['n is odd']" in outline(proof)


def test_combine_rejects_steps_that_do_not_chain():
    units = build(GOOD)
    try:
        combine_checkpoints(units[0], units[2])
    except CombineError as e:
        assert "don't chain" in str(e)
    else:
        raise AssertionError("expected a CombineError")


# --- what the builder accepts ----------------------------------------------

def test_any_state_change_can_be_expressed():
    # Rewrites a premise AND the goal in one step.
    proof = "Substituting x = 2, it remains to show 3 > 2. This is true."
    raw = {
        "premise": ["x = 2", "y = x + 1"],
        "goal": ["y > x"],
        "steps": [
            {
                "text": "Substituting x = 2, it remains to show 3 > 2.",
                "remove_premises": ["y = x + 1"],
                "add_premises": ["y = 3"],
                "close_goals": ["y > x"],
                "add_goals": ["3 > 2"],
                "justification": ["substitute x = 2 into y = x + 1 and into the goal"],
            },
            {"text": "This is true.", "close_goals": ["3 > 2"], "justification": ["arithmetic"]},
        ],
    }
    units = build_unit_checkpoints("t", ProofLanguage.NL, parse_raw_proof(raw), proof_text=proof)
    assert units[0].next_state.premise == ("x = 2", "y = 3")


def test_claim_proved_elsewhere_in_the_text():
    proof = (
        "We use that k(k+1) is even for every integer k, proved at the end. "
        "Now n^2 + n = n(n+1), which is therefore even. "
        "Proof of the fact: let k be an integer; one of k and k+1 is even, so k(k+1) is even."
    )
    raw = copy.deepcopy(GOOD)
    raw["steps"][0]["text"] = "We use that k(k+1) is even for every integer k, proved at the end."
    for step, text in zip(raw["steps"][0]["claims"][0]["proof"],
                          ["let k be an integer;", "one of k and k+1 is even,", "so k(k+1) is even."]):
        step["text"] = text
    raw["steps"][1]["text"] = "Now n^2 + n = n(n+1),"
    raw["steps"][2]["text"] = "which is therefore even."
    units = build_unit_checkpoints("t", ProofLanguage.NL, parse_raw_proof(raw), proof_text=proof)
    assert compose(units).is_complete_proof


def test_claims_may_have_proofs_of_any_length():
    # Several claims, each proved in one step.
    def shorten(d):
        for claim in d["steps"][1]["claims"]:
            claim["proof"] = claim["proof"][1:]  # keep only "so n^2 + n is even."
    assert compose(build(broken(shorten, base=GOOD_CASES), CASES_ITEM)).is_complete_proof

    # A single claim proved in one step.
    def one_step(d):
        claim = d["steps"][0]["claims"][0]
        claim["goal"] = ["k(k+1) is even"]
        claim["proof"] = claim["proof"][2:]  # keep only "so k(k+1) is even."
        claim["proof"][0]["dependency"] = []
    assert compose(build(broken(one_step))).is_complete_proof


# --- what the builder rejects ----------------------------------------------


def test_claim_proof_must_close_its_goal():
    d = broken(lambda d: d["steps"][1]["claims"][0]["proof"].pop(), base=GOOD_CASES)
    expect_problem(d, "leaves goals open: ['n^2 + n is even']", CASES_ITEM)


def test_every_step_needs_a_justification():
    d = broken(lambda d: d["steps"][1].update(justification=[]))
    expect_problem(d, "has no justification")


def test_reports_goal_that_is_not_open():
    d = broken(lambda d: d["steps"][2].update(close_goals=["n^2 is even"]))
    msg = expect_problem(d, "cannot close goal 'n^2 is even'")
    assert "steps[2]" in msg and "ends with goals still open" in msg


def test_rejects_step_that_changes_nothing():
    d = broken(lambda d: d["steps"].insert(2, {
        "text": "This is a product of two consecutive integers",
        "justification": ["n and n+1 are consecutive"],
    }))
    expect_problem(d, "not a unit step")


RESTATEMENT = {"text": "hence n^2 + n is even.", "justification": ["it was just proved"]}


def test_drops_conclusion_restated_after_goal_is_closed():
    units = build(broken(lambda d: d["steps"].append(RESTATEMENT)))
    assert len(units) == len(build(GOOD))
    assert all("hence n^2 + n is even." != u.source[0] for u in units)


def test_drops_conclusion_restated_at_end_of_claim():
    d = broken(lambda d: d["steps"][1]["claims"][0]["proof"].append(
        {"text": "so n^2 + n is even.", "justification": ["it was just proved"]}), GOOD_CASES)
    assert len(build(d, CASES_ITEM)) == len(build(GOOD_CASES, CASES_ITEM))


def test_rejects_step_that_changes_state_after_goal_is_closed():
    d = broken(lambda d: d["steps"].append(dict(RESTATEMENT, add_premises=["n^2 + n is even"])))
    expect_problem(d, "comes after every goal is already closed")


def test_claim_stated_without_proof_is_kept_as_unproved():
    # "One of k and k+1 is even" asserted as a fact: a claim with no proof.
    fact = "one of k and k+1 is even"
    def edit(d):
        claim_step = d["steps"][0]["claims"][0]["proof"][1]
        del claim_step["add_premises"]
        claim_step["claims"] = [{"statement": fact, "proof": []}]
    units = build(broken(edit))
    proof = compose(units)
    assert unproved_claims(proof) and unproved_claims(proof)[0][0] == fact
    statement, state = unproved_claims(proof)[0]
    assert state.goal == (fact,) and "k is an integer" in state.premise
    assert "no proof in the text" in trace(proof) and "no proof in the text" in outline(proof)


def test_rejects_text_not_in_proof():
    d = broken(lambda d: d["steps"][1].update(text="We factor: n^2 + n = n(n+1)."))
    expect_problem(d, "not a verbatim span of the proof")


# --- parsing ---------------------------------------------------------------

def test_bad_shape_reports_json_path():
    d = broken(lambda d: d["steps"][0]["claims"][0]["proof"][0].update(add_premises="k"))
    expect_parse_error(d, "steps[0].claims[0].proof[0].add_premises must be a list of strings")


def test_claim_goal_defaults_to_statement():
    raw = parse_raw_proof(GOOD)
    assert raw.steps[0].claims[0].goal == [CLAIM]


# --- LLM backend -----------------------------------------------------------

def test_llm_retries_with_feedback():
    bad = broken(lambda d: d["steps"][2].update(close_goals=["n^2 is even"]))
    llm = FakeLLM(
        "Sure! Here it is: not json",
        "```json\n" + json.dumps(bad) + "\n```",
        json.dumps(GOOD),
    )
    units = extract_unit_checkpoints(ITEM, LLMStepExtractor.from_file(llm, PROMPT))
    assert len(units) == 3 and len(llm.prompts) == 3
    assert "Problems with your previous answer" not in llm.prompts[0]
    assert "no JSON object" in llm.prompts[1]
    assert "cannot close goal 'n^2 is even'" in llm.prompts[2]


def test_gives_up_after_max_attempts():
    llm = FakeLLM("nope", "nope")
    extractor = LLMStepExtractor(llm, "{{statement}}\n{{proof}}\n{{feedback}}")
    try:
        extract_unit_checkpoints(ITEM, extractor, max_attempts=2)
    except ExtractionError as e:
        assert "gave up after 2 attempts" in str(e)
    else:
        raise AssertionError("expected an ExtractionError")


def test_prompt_renders_and_its_examples_are_valid():
    text = PROMPT.read_text(encoding="utf-8")
    rendered = LLMStepExtractor(lambda p: "", text).render(ITEM, feedback="- some problem")
    assert "{{" not in rendered and ITEM.proof in rendered and "- some problem" in rendered
    assert "kind" not in text

    # Every worked example inside the prompt must itself pass the builder.
    sections = text.split("## Example ")[1:]
    assert len(sections) == 2
    for section in sections:
        proof = re.search(r"^Proof: (.+)$", section, re.M).group(1)
        example = parse_raw_proof(parse_json_object(section))
        units = build_unit_checkpoints("example", ProofLanguage.NL, example, proof_text=proof)
        assert compose(units).is_complete_proof


# --- stored annotations ----------------------------------------------------

def test_static_extractor_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        for item, raw in [(ITEM, GOOD), (CASES_ITEM, GOOD_CASES)]:
            path = Path(tmp) / f"{item.theorem_id}.json"
            path.write_text(json.dumps(parse_raw_proof(raw).to_dict()))
        extractor = StaticExtractor.from_json_dir(tmp)
        assert len(extract_unit_checkpoints(ITEM, extractor)) == 3
        assert len(extract_unit_checkpoints(CASES_ITEM, extractor)) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)