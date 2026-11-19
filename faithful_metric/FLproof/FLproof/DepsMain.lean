import FLproof.Dependencies

/-!
`tactic-deps`: the tactic-roles checkpoints plus dependencies (see Dependencies.lean).

    tactic-deps FILE.lean > deps.json        # every proof in FILE, with dependencies
    tactic-deps --decl NAME MODULE           # where NAME is declared (used by lookup.py)
-/

open Lean

def main (args : List String) : IO UInt32 := do
  unsafe Pantograph.initSearch ""
  try
    match args with
    | ["--decl", name, module] =>
      IO.println (← Dependencies.declaration name.toName module.toName).pretty
      return 0
    | [fileName] =>
      IO.println (← Dependencies.processFile fileName).pretty
      return 0
    | _ =>
      IO.eprintln "usage: tactic-deps FILE.lean > deps.json\n       tactic-deps --decl NAME MODULE"
      return 2
  catch e =>
    IO.eprintln s!"error: {e}"
    return 1
