import Pantograph

/-!
Split a Lean file into units (one per top-level command, as Pantograph's
`frontend.process` does) and each unit's proof into main-flow checkpoints.

* The top-level checkpoints of a unit are the main proof flow.
* Tactics nested inside a goal-steering tactic (`case`, `next`, `all_goals`,
  `induction ... with`, ...) go into that checkpoint's `substeps`.
* Tactics nested inside any other tactic go into its `auxiliary` field, one list
  per separate nested proof (e.g. the two `by` blocks of
  `refine ⟨by ..., by ...⟩` are two auxiliary proofs).

Uses Pantograph's public API only; Pantograph itself is not modified.
-/

open Lean Pantograph Frontend

namespace TacticRoles

/-! ## Output schema -/

structure Hypothesis where
  name : String
  type : String
  /-- Value of a `let`-bound hypothesis -/
  value? : Option String := none
  deriving ToJson, FromJson, Repr

structure Goal where
  /-- Case name, e.g. `inl`, `succ` -/
  tag? : Option String := none
  hypotheses : List Hypothesis
  target : String
  deriving ToJson, FromJson, Repr

structure Checkpoint where
  /-- Pre-order index within the unit -/
  id : Nat
  tactic : String
  /-- Syntax kind of the tactic -/
  kind : String
  /-- Byte range of the tactic in the source file -/
  range : Nat × Nat
  goalsBefore : List Goal
  goalsAfter : List Goal
  usedConstants : List String
  /-- Tactics run by a goal-steering tactic on the goals it was given -/
  substeps : List Checkpoint := []
  /-- Proofs nested inside this tactic, one list per proof -/
  auxiliary : List (List Checkpoint) := []
  deriving ToJson, FromJson, Repr

/-! ## Policy (edit to match your framework) -/

/-- Tactics whose nested tactics keep working on the same goals. Their nested
tactics become `substeps`; tactics nested in anything else are `auxiliary`. -/
def flowTactics : NameSet := [
    ``Lean.Parser.Tactic.case,
    ``Lean.Parser.Tactic.case',
    ``Lean.Parser.Tactic.«tacticNext_=>_»,
    ``Lean.Parser.Tactic.focus,
    ``Lean.Parser.Tactic.allGoals,
    ``Lean.Parser.Tactic.anyGoals,
    ``Lean.Parser.Tactic.tacticTry_,
    ``Lean.Parser.Tactic.first,
    ``Lean.Parser.Tactic.tacticRepeat_,
    ``Lean.Parser.Tactic.tacticIterate____,
    ``Lean.Parser.Tactic.induction,
    ``Lean.Parser.Tactic.cases,
    ``Lean.Parser.Tactic.match,
    ``Lean.Parser.Tactic.tacticSuffices_,
  ].foldl (·.insert ·) {}

/-- Wrappers that Pantograph counts as tactics but that are not a step of their
own. They are skipped, and what they contain is attached to the enclosing tactic. -/
def transparentTactics : NameSet := [
    ``Lean.calcSteps,
    ``Lean.Parser.Termination.decreasingBy,
    ``Lean.Parser.Tactic.Conv.convSeq,
    ``Lean.Parser.Tactic.Conv.convSeq1Indented,
  ].foldl (·.insert ·) {}

/-- Syntax that opens a nested tactic proof. Below a tactic, the first such node
met on the way down starts a new auxiliary proof; everything under it (bullets
included) belongs to that proof. -/
def isProofBlock (kind : Name) : Bool :=
  kind == ``Lean.Parser.Term.byTactic     -- `by ...` used as a term
  || kind == Name.mkSimple "by"           -- `have h : P := by ...` after expansion
  || kind == ``Lean.Parser.Tactic.tacticSeq -- `show P by ...`

/-! ## Walking the info tree -/

/-- A checkpoint before pretty printing. -/
structure RawNode where
  id : Nat
  invocation : TacticInvocation
  substeps : Array RawNode := #[]
  auxiliary : Array (Array RawNode) := #[]

structure WalkState where
  nextId : Nat := 0
  nextBlock : Nat := 0

abbrev WalkM := StateM WalkState

/-- Group nodes by proof block, keeping the order in which blocks first appear. -/
def groupByBlock (xs : Array (Option Nat × RawNode)) : Array (Array RawNode) := Id.run do
  let mut keys : Array (Option Nat) := #[]
  let mut groups : Array (Array RawNode) := #[]
  for (key, x) in xs do
    match keys.findIdx? (· == key) with
    | .some i => groups := groups.modify i (·.push x)
    | .none =>
      keys := keys.push key
      groups := groups.push #[x]
  return groups

/-- Find the nearest substantive tactics in `t`, each tagged with the first
proof block passed on the way down. Each tactic found becomes a checkpoint, and
what is below it is sorted into its substeps or auxiliary proofs. -/
private partial def collectBelow (t : Elab.InfoTree) (ctx? : Option Elab.ContextInfo)
    (block? : Option Nat) : WalkM (Array (Option Nat × RawNode)) := do
  match t with
  | .context inner t => collectBelow t (inner.mergeIntoOuter? ctx?) block?
  | .node info children =>
    let mut block? := block?
    if let .ofTacticInfo ti := info then
      let kind := ti.stx.getKind
      if let .some ctx := ctx? then
        if ti.isSubstantive && !transparentTactics.contains kind then
          let id ← modifyGet λ s => (s.nextId, { s with nextId := s.nextId + 1 })
          let mut below := #[]
          for child in children do
            below := below ++ (← collectBelow child ctx .none)
          let invocation : TacticInvocation := ⟨ti, ctx, children⟩
          let node : RawNode := if flowTactics.contains kind
            then { id, invocation, substeps := below.map (·.2) }
            else { id, invocation, auxiliary := groupByBlock below }
          return #[(block?, node)]
      if block?.isNone && isProofBlock kind then
        block? := .some (← modifyGet λ s => (s.nextBlock, { s with nextBlock := s.nextBlock + 1 }))
    let mut result := #[]
    for child in children do
      result := result ++ (← collectBelow child ctx? block?)
    return result
  | .hole _ => return #[]

/-! ## Pretty printing -/

/-- Display a name the way Lean's goal view does: names the user cannot refer to
(e.g. a hypothesis introduced by `cases h` without naming it) get a `✝` suffix. -/
def displayName (n : Name) : String :=
  if n.hasMacroScopes then n.eraseMacroScopes.toString ++ "✝" else n.toString

def toGoal (g : MVarId) : MetaM Goal := g.withContext do
  let decl ← g.getDecl
  let mut hypotheses := #[]
  for d in decl.lctx do
    if d.isImplementationDetail then continue
    let type := (← Meta.ppExpr d.type).pretty
    let value? ← d.value?.mapM λ v => return (← Meta.ppExpr v).pretty
    hypotheses := hypotheses.push { name := displayName d.userName, type, value? }
  let tag? := if decl.userName.isAnonymous then .none else .some (displayName decl.userName)
  return { tag?, hypotheses := hypotheses.toList, target := (← Meta.ppExpr decl.type).pretty }

partial def RawNode.toCheckpoint (n : RawNode) : IO Checkpoint := do
  let inv := n.invocation
  let tactic ← inv.ctx.runMetaM {} <| Meta.withMCtx inv.info.mctxBefore do
    return (← inv.ctx.ppSyntax {} inv.info.stx).pretty
  let (startPos, endPos) := stxByteRange inv.info.stx
  return {
    id := n.id,
    tactic,
    kind := inv.info.stx.getKind.toString,
    range := (startPos.byteIdx, endPos.byteIdx),
    goalsBefore := ← inv.runMetaMGoalsBefore (·.mapM toGoal),
    goalsAfter := ← inv.runMetaMGoalsAfter (·.mapM toGoal),
    usedConstants := inv.usedConstants.toArray.toList.map toString,
    substeps := (← n.substeps.mapM toCheckpoint).toList,
    auxiliary := (← n.auxiliary.mapM (·.mapM toCheckpoint)).toList.map Array.toList,
  }

/-! ## Entry points -/

/-- The main-flow checkpoints of one compilation unit. -/
def collect (step : CompilationStep) : IO (List Checkpoint) := do
  -- Same first pass as Pantograph: keep only tactics written in the source.
  let trees := step.trees.flatMap λ tree => tree.filter λ
    | info@(.ofTacticInfo _) => info.isOriginal
    | _ => false
  let walk : WalkM (Array (Option Nat × RawNode)) :=
    trees.foldlM (init := #[]) λ acc tree => return acc ++ (← collectBelow tree .none .none)
  let (nodes, _) := walk.run {}
  nodes.toList.mapM (·.2.toCheckpoint)

def messageToJson (m : Message) : IO Json := do
  let severity := match m.severity with
    | .error => "error"
    | .warning => "warning"
    | .information => "information"
  return Json.mkObj [
    ("severity", toJson severity),
    ("pos", toJson [m.pos.line, m.pos.column]),
    ("text", toJson (← m.data.toString)),
  ]

/-- The kind of a command, looking inside `declaration` to tell a `theorem` from
a `def`, `instance`, `example`, `structure`, ... -/
def commandKind (stx : Syntax) : Name :=
  if stx.isOfKind ``Lean.Parser.Command.declaration then stx[1].getKind else stx.getKind

/-- Process a whole file, one unit per top-level command. Fails if the file's
imports cannot be loaded. -/
def processFile (fileName : String) : IO Json := do
  let source ← IO.FS.readFile fileName
  let (context, state) ← createContextStateFromFile source fileName .none {}
  let headerLog := state.commandState.messages
  if headerLog.hasErrors then
    let errors ← headerLog.toList.mapM (·.toString)
    throw <| IO.userError s!"cannot load the imports of {fileName}:\n{String.join errors}"
  let m : FrontendM (List Json) := mapCompilationSteps λ step => do
    let (startPos, endPos) := stxByteRange step.stx
    let declarations := (← (step.newConstants : IO _)).toArray.qsort Name.lt |>.map toString
    return Json.mkObj [
      ("command", toJson (commandKind step.stx).toString),
      ("declarations", toJson declarations),
      ("boundary", toJson [startPos.byteIdx, endPos.byteIdx]),
      ("messages", toJson (← (step.msgs.mapM messageToJson : IO _))),
      ("checkpoints", toJson (← collect step)),
    ]
  let units ← m.run {} |>.run context |>.run' state
  return Json.mkObj [("units", toJson units)]

end TacticRoles
