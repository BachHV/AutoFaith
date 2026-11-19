# tactic-roles

Splits each proof in a Lean file into main-flow checkpoints. Tactics nested in
goal-steering tactics (`case`, `all_goals`, `induction ... with`, ...) go into
`substeps`; nested proofs (`have h : P := by ...`, `exact ⟨by ..., _⟩`, ...) go
into `auxiliary`, one list per proof. Built on unmodified Pantograph.

## Build

Requires [elan](https://github.com/leanprover/elan). The `lean-toolchain` file
makes elan fetch Lean v4.35.0, the version Pantograph is pinned to.

```sh
cd tactic-roles
lake build        # first build fetches and compiles Pantograph (a few minutes)
```

The program is `.lake/build/bin/tactic-roles`.

## Run

Input is one `.lean` file. Output is JSON on stdout.

```sh
# A file that only imports Lean core (Init, Std, Lean), or has no imports:
.lake/build/bin/tactic-roles MyFile.lean > out.json

# A file that imports a project's modules (e.g. Mathlib): run it from that
# project with `lake env`, so the project's compiled modules can be found.
cd /path/to/your-project
lake build
lake env /path/to/tactic-roles/.lake/build/bin/tactic-roles MyFile.lean > out.json

# Human-readable outline:
python3 /path/to/tactic-roles/outline.py out.json MyFile.lean
```

The project you run against must use the same Lean version as this tool
(v4.35.0). Compiled modules from a different Lean version cannot be loaded.

## Input requirements

- Imports at the top of the file are honored; they must be built and on the
  search path (see `lake env` above).
- A file can hold any mix of theorems, definitions, instances, namespaces and
  so on. Each command becomes one unit, and later commands see everything
  declared before them, as in Lean itself.
- Only tactic blocks produce checkpoints: `:= by ...` proofs (in theorems,
  but also in `def`s and `instance`s), and `decreasing_by` proofs. Other
  commands appear as units with an empty `checkpoints` list. To keep only
  theorems, filter units on `command`.
- A `mutual` block is one command, so it is one unit listing several
  declarations, with their checkpoints in one list (in source order; use
  `range` to tell them apart).
- The file should compile. Errors do not stop extraction, but the proof state
  after an error may be incomplete. Errors are listed in each unit's
  `messages`, and a warning with the error count is printed to stderr.

Exit codes: `0` success (possibly with errors in the file), `1` the file's
imports could not be loaded, `2` wrong arguments.

## Output

One unit per top-level command, in file order. `command` is the kind of
command (`theorem`, `definition`, `instance`, `example`, `structure`,
`namespace`, ...) and `declarations` the names it declares.

```json
{"units": [
  {"command": "Lean.Parser.Command.theorem",
   "declarations": ["MyList.sum_append"],
   "boundary": [start, end],
   "messages": [{"severity": "error", "pos": [line, col], "text": "..."}],
   "checkpoints": [Checkpoint, ...]}
]}
```

Each `Checkpoint` has `id`, `tactic`, `kind`, `range` (byte offsets in the
file), `goalsBefore`, `goalsAfter` (each goal: `tag`, `hypotheses`, `target`),
`usedConstants`, `substeps`, and `auxiliary`.

## Changing the rules

The classification policy is three definitions near the top of
`TacticRoles.lean`: `flowTactics`, `transparentTactics`, and `isProofBlock`.
