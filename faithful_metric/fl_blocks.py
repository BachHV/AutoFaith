import json
import subprocess

from dataclasses import dataclass
from pathlib import Path

try:
    from .checkpoints import Checkpoint, FLTacticCategory, FLBlock, Block
except ImportError:
    from faithful_metric.checkpoints import Checkpoint, FLTacticCategory, FLBlock, Block


@dataclass
class RawTactic:
    tactic: str
    proof_state: int
    goals: str | list[str]
    line: int
    column: int
    end_line: int
    end_column: int

    @property
    def start(self) -> tuple[int, int]:
        return self.line, self.column


@dataclass(frozen=True)
class ParsedGoal:
    """One Lean goal together with its own local context."""
    premises: tuple[str, ...]
    target: str


@dataclass
class TacticStep:
    raw: RawTactic
    before: list[ParsedGoal]
    after: list[ParsedGoal]
    block: Block


class LeanREPL:
    def __init__(self, project_path: Path):
        self.project_path = project_path.resolve()
        self.process = subprocess.Popen(
            ["lake", "exe", "repl"],
            cwd=self.project_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, request: dict) -> dict:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("Lean REPL is not running.")

        self.process.stdin.write(json.dumps(request) + "\n\n")
        self.process.stdin.flush()

        response = ""
        while True:
            line = self.process.stdout.readline()
            if line == "":
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(f"Lean REPL terminated unexpectedly.\n{stderr}")

            response += line
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                continue

    def extract_fl_blocks(self, file_path: Path) -> list[FLBlock]:
        relative_path = file_path.resolve().relative_to(self.project_path)
        file_result = self.send({"path": str(relative_path), "allTactics": True})

        if "tactics" not in file_result:
            raise RuntimeError(f"No tactics returned by REPL:\n{file_result}")

        raw_tactics = self._parse_raw_tactics(file_result["tactics"])
        steps = self._prepare_steps(raw_tactics)
        return self._build_goal_tree(steps)

    @staticmethod
    def _parse_raw_tactics(tactics: list[dict]) -> list[RawTactic]:
        result = [
            RawTactic(
                tactic=t["tactic"],
                proof_state=t["proofState"],
                goals=t["goals"],
                line=t["pos"]["line"],
                column=t["pos"]["column"],
                end_line=t["endPos"]["line"],
                end_column=t["endPos"]["column"],
            )
            for t in tactics
        ]
        result.sort(key=lambda tactic: tactic.start)
        return result

    @staticmethod
    def _is_internal(tactic: RawTactic) -> bool:
        return not tactic.tactic.strip() or tactic.goals == "no goals"

    def _prepare_steps(self, raw_tactics: list[RawTactic]) -> list[TacticStep]:
        steps: list[TacticStep] = []

        for tactic in raw_tactics:
            if self._is_internal(tactic):
                continue

            before = self._goals_to_states(tactic.goals)
            after_result = self.send(
                {"tactic": tactic.tactic, "proofState": tactic.proof_state}
            )
            after = self._goals_to_states(after_result.get("goals", []))

            block = Block(
                previous_checkpoint=self._states_to_checkpoint(before),
                arguments=[tactic.tactic.strip()],
                next_checkpoint=self._states_to_checkpoint(after),
            )

            steps.append(TacticStep(tactic, before, after, block))

        return steps

    def _goals_to_states(self, goals: str | list[str]) -> list[ParsedGoal]:
        """
        Parse each Lean goal separately.

        This is essential for tactics such as `by_cases` because the two
        resulting goals have different local contexts (`hp : p` vs `hp : ¬p`).
        """
        if not goals or goals == "no goals":
            return []
        if isinstance(goals, str):
            goals = [goals]

        states: list[ParsedGoal] = []
        for state in goals:
            premises, target = self._parse_single_goal(state)
            if target:
                states.append(ParsedGoal(tuple(premises), target))
        return states

    @staticmethod
    def _parse_single_goal(state: str) -> tuple[list[str], str]:
        state = state.strip()
        if state == "no goals":
            return [], ""
        if "⊢" not in state:
            return [], state

        context, target = state.rsplit("⊢", 1)
        premises = [
            line.strip()
            for line in context.splitlines()
            if line.strip() and not line.strip().startswith("case ")
        ]
        return premises, target.strip()

    @staticmethod
    def _states_to_checkpoint(states: list[ParsedGoal]) -> Checkpoint:
        """
        Keep compatibility with your existing Checkpoint(premises, goal).

        For multiple goals, use only premises common to all branches. This
        avoids incorrectly merging both `hp : p` and `hp : ¬p` into one state.
        """
        if not states:
            return Checkpoint([], [])

        if len(states) == 1:
            return Checkpoint(list(states[0].premises), [states[0].target])

        common = list(states[0].premises)
        for state in states[1:]:
            premise_set = set(state.premises)
            common = [p for p in common if p in premise_set]

        return Checkpoint(common, [state.target for state in states])

    @staticmethod
    def _goal_matches(expected: ParsedGoal, actual: ParsedGoal) -> bool:
        return expected.target == actual.target and expected.premises == actual.premises

    @classmethod
    def _step_starts_from_goal(cls, step: TacticStep, goal: ParsedGoal) -> bool:
        return any(cls._goal_matches(goal, before_goal) for before_goal in step.before)

    def _build_goal_tree(self, steps: list[TacticStep]) -> list[FLBlock]:
        """
        Build the tactic tree from GOAL TRANSITIONS, not source-span containment.

        For the example:

            by_cases hp : p
            · left
              constructor
              · exact hp
              · exact hq
            · right
              constructor
              · exact hp
              · exact hq

        the result is conceptually:

            by_cases
            ├── left
            │   └── constructor
            │       ├── exact hp
            │       └── exact hq
            └── right
                └── constructor
                    ├── exact hp
                    └── exact hq
        """
        used: set[int] = set()

        def find_next_for_goal(goal: ParsedGoal, start_index: int) -> int | None:
            for index in range(start_index, len(steps)):
                if index in used:
                    continue
                if self._step_starts_from_goal(steps[index], goal):
                    return index
            return None

        def build_step(index: int) -> tuple[FLBlock, int]:
            used.add(index)
            step = steps[index]
            children: list[FLBlock] = []
            cursor = index + 1

            # Each after-goal is one continuation branch.
            for output_goal in step.after:
                child_index = find_next_for_goal(output_goal, cursor)
                if child_index is None:
                    continue

                child, next_cursor = build_step(child_index)
                children.append(child)
                cursor = max(cursor, next_cursor)

            kind = (
                FLTacticCategory.COMPOUND
                if children
                else FLTacticCategory.LEAF
            )

            return FLBlock(kind=kind, block=step.block, children=children), cursor

        roots: list[FLBlock] = []
        for index in range(len(steps)):
            if index in used:
                continue
            root, _ = build_step(index)
            roots.append(root)

        return roots

    @staticmethod
    def save_json(blocks: list[FLBlock], output_path: Path) -> None:
        data = {"blocks": [block.to_dict() for block in blocks]}
        output_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait()


def main() -> None:
    project_path = Path("/Users/vietbachhoang/AutoFaith/faithful_metric/FLproof")
    proof_file = project_path / "FLProof/proof.lean"
    output_file = project_path / "fl_blocks.json"

    repl = LeanREPL(project_path)
    try:
        blocks = repl.extract_fl_blocks(proof_file)

        for block in blocks:
            print(block)

        repl.save_json(blocks, output_file)
        print(f"\nSaved to {output_file}")
    finally:
        repl.close()


if __name__ == "__main__":
    main()