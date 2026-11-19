import FLproof.TacticRoles

open Lean

/-- Count error messages across all units. -/
def countErrors (output : Json) : Nat := Id.run do
  let .ok units := output.getObjValAs? (Array Json) "units" | return 0
  let mut n := 0
  for unit in units do
    if let .ok msgs := unit.getObjValAs? (Array Json) "messages" then
      n := n + (msgs.filter λ m => match m.getObjValAs? String "severity" with
        | .ok "error" => true
        | _ => false).size
  return n

def main (args : List String) : IO UInt32 := do
  let [fileName] := args
    | IO.eprintln "usage: tactic-roles FILE.lean > output.json"; return 2
  unsafe Pantograph.initSearch ""
  try
    let output ← TacticRoles.processFile fileName
    IO.println output.pretty
    let errors := countErrors output
    if errors > 0 then
      IO.eprintln s!"warning: {fileName} has {errors} error(s); see the \"messages\" field of each unit"
    return 0
  catch e =>
    IO.eprintln s!"error: {e}"
    return 1
