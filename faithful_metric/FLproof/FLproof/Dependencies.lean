import FLproof.TacticRoles

/-!
# Dependencies

Runs the `TacticRoles` extraction unchanged, then adds to every checkpoint:

* `path`: where the checkpoint sits, e.g. `proof.lean::square_mul/3` or
  `proof.lean::even_or_odd'/0/sub/2` (`sub` = substeps, `auxK` = K-th auxiliary proof).
* `usage` on every *fact* (hypothesis whose type is a proposition) of each goal in
  `goalsBefore`:
  - `"used"`: the proof term the step built refers to it;
  - `"changed"`: the step removed or replaced it (`obtain ... := h`, `rw ... at h`);
  - `"unused"`;
  - `"not computed"`: the step is `omega` or a `simp`-family tactic, whose proof
    terms may mention hypotheses they did not need.
  Variables (`a : ℤ`, `b : ℕ := ...`) get no `usage`.
* `dependency`: `[name, file]` pairs of what the step uses from outside the proof:
  - every constant written in the step (`rw [a, b]`, `simp [c]`, `exact d x`);
  - every definition mentioned in the step's goals and hypotheses (before or
    after), so `Even a` gives `Even` even when nothing unfolds it explicitly.
  Automation (`ring`, `omega`, `linarith`, ...) adds nothing: only what is written
  or stated counts. Direct dependencies only: what a nested proof uses belongs to
  that proof's checkpoints.
* `notationDependency`: the same for notation and instances (`+` is `HAdd.hAdd`,
  `instHAdd`, `¬`, `>`, ...), kept apart so a viewer can hide them.

`file` is the `.lean` source of the module that declares the constant (relative to
the working directory when inside it), or the processed file itself for constants
it declares.
-/

open Lean Elab Meta Pantograph Frontend

namespace Dependencies

/-! ## Policy -/

/-- Steps whose premise usage is not computed. -/
def usageNotComputed (kind : Name) : Bool :=
  kind == ``Lean.Parser.Tactic.omega || (kind.toString.toLower.splitOn "simp").length > 1

/-- Definitions that are notation rather than mathematical content. Projections
(`HAdd.hAdd`, `LE.le`, ...) and instances count as notation too. -/
def notationDefs : NameSet :=
  [``Not, ``Ne, ``GT.gt, ``GE.ge, ``id, ``Function.comp, ``outParam, ``semiOutParam].foldl (·.insert ·) {}

/-! ## Finding the tactic node of each checkpoint -/

structure Step where
  info : TacticInfo
  ctx : ContextInfo
  children : PersistentArray InfoTree

/-- The same test `TacticRoles` uses for "this tactic is a checkpoint". -/
def stepInfo? (info : Info) : Option TacticInfo :=
  match info with
  | .ofTacticInfo ti =>
    if info.isOriginal && ti.isSubstantive && !TacticRoles.transparentTactics.contains ti.stx.getKind
    then some ti else none
  | _ => none

def keyOf (start stop : Nat) (kind : String) : String := s!"{start}:{stop}:{kind}"

def stxKey (stx : Syntax) : String :=
  let (s, e) := stxByteRange stx
  keyOf s.byteIdx e.byteIdx stx.getKind.toString

/-- Every checkpoint-worthy tactic node, by source range and kind (outermost first). -/
partial def allSteps (t : InfoTree) (ctx? : Option ContextInfo)
    (acc : Std.HashMap String Step) : Std.HashMap String Step :=
  match t with
  | .context inner t => allSteps t (inner.mergeIntoOuter? ctx?) acc
  | .node info children =>
    let acc := match stepInfo? info, ctx? with
      | some ti, some ctx =>
        let k := stxKey ti.stx
        if acc.contains k then acc else acc.insert k ⟨ti, ctx, children⟩
      | _, _ => acc
    children.foldl (fun acc c => allSteps c ctx? acc) acc
  | .hole _ => acc

/-! ## What a step does directly -/

/-- Below a step, down to (not into) the nested steps: the goals of the nested
steps (their work is not this step's) and the constants written in this step. -/
structure Below where
  nestedGoals : Array MVarId := #[]
  written : Array Name := #[]

/-- Syntax that names a constant: `foo`, the fields of `h.foo.bar`, `(e).foo`, `.inl`. -/
def namesConstant (stx : Syntax) : Bool :=
  stx.isIdent || stx.isOfKind `Lean.Parser.Term.identProj || stx.isOfKind `Lean.Parser.Term.proj
    || stx.isOfKind `Lean.Parser.Term.dotIdent

partial def below (t : InfoTree) (acc : Below) : Below :=
  match t with
  | .context _ t => below t acc
  | .node info children =>
    if let some ti := stepInfo? info then
      { acc with nestedGoals := acc.nestedGoals ++ ti.goalsBefore.toArray }
    else
      let acc := match info with
        | .ofTermInfo ti =>
          if info.isOriginal && namesConstant ti.stx then
            match ti.expr.getAppFn with
            | .const n _ => { acc with written := acc.written.push n }
            | _ => acc
          else acc
        | _ => acc
      children.foldl (fun acc c => below c acc) acc
  | .hole _ => acc

/-- All constants in a goal: target, hypothesis types and `let` values. -/
def goalConstants (g : MVarId) : MetaM (Array Name) := do
  let decl ← g.getDecl
  let mut exprs := #[decl.type]
  for d in decl.lctx do
    if d.isImplementationDetail then continue
    exprs := exprs.push d.type
    if let some v := d.value? then exprs := exprs.push v
  let mut out := #[]
  for e in exprs do
    out := out ++ (← instantiateMVars e).getUsedConstants
  return out

/-- A generated name (`double.eq_1`, `Point.mk.injEq`) stands for the declaration
it was generated from: the closest prefix that has a source position. -/
def declaredName (n : Name) : MetaM Name := do
  let mut m := n
  while !m.isAnonymous do
    if (← findDeclarationRanges? m).isSome then return m
    m := m.getPrefix
  return n

def isNotation (env : Environment) (n : Name) : Bool :=
  env.isProjectionFn n || isInstanceCore env n || notationDefs.contains n

def isAuxiliary (env : Environment) (n : Name) : Bool :=
  n.isInternal || isMatcherCore env n || isAuxRecursor env n || isNoConfusion env n

structure Analysis where
  /-- One entry per goal of `goalsBefore`, one per displayed hypothesis -/
  usage : List (List (Option String))
  /-- (name, declaring module; none = the processed file) -/
  dependency : Array (Name × Option Name)
  notations : Array (Name × Option Name)

def analyse (s : Step) : IO Analysis := do
  let b := s.children.foldl (fun acc c => below c acc) ({} : Below)
  let notComputed := usageNotComputed s.info.stx.getKind
  s.ctx.runMetaM {} do
    let env ← getEnv
    -- After the step: which hypotheses survive, and the constants mentioned.
    let (survivors, constsAfter) ← withMCtx s.info.mctxAfter do
      let mut ids : Std.HashSet FVarId := {}
      let mut cs := #[]
      for g in s.info.goalsAfter do
        for d in (← g.getDecl).lctx do ids := ids.insert d.fvarId
        cs := cs ++ (← goalConstants g)
      return (ids, cs)
    -- The step's own proof term, without what the nested steps proved. Some
    -- tactics (`exact`, `refine`) store their term with the nested proofs already
    -- filled in, so the nested proofs are cut out of the term rather than left as
    -- placeholders.
    let closesOrKeeps := s.info.goalsAfter.isEmpty
    let usage ← withMCtx s.info.mctxAfter do
      let nested ← b.nestedGoals.filterMapM fun g => do
        let v ← instantiateMVars (.mvar g)
        return if v.isMVar then none else some v
      s.info.goalsBefore.mapM fun g => do
        let mut term ← instantiateMVars (.mvar g)
        for v in nested do
          term := term.replace fun e => if e == v then some (mkConst `_nested) else none
        let used := (collectFVars {} term).fvarSet
        g.withContext do
          let mut out := #[]
          for d in (← g.getDecl).lctx do
            if d.isImplementationDetail then continue
            if !(← isProp d.type) then
              out := out.push none
            else if !closesOrKeeps && !survivors.contains d.fvarId then
              out := out.push (some "changed")
            else if notComputed then
              out := out.push (some "not computed")
            else
              out := out.push (some (if used.contains d.fvarId then "used" else "unused"))
          return out.toList
    let constsBefore ← withMCtx s.info.mctxBefore do
      s.info.goalsBefore.foldlM (init := #[]) fun acc g => return acc ++ (← goalConstants g)
    -- Constants written in the step count whatever they are; constants that only
    -- appear in the statements count when they are definitions.
    let mut seen : NameSet := {}
    let mut dependency := #[]
    let mut notations := #[]
    let candidates := b.written.map (·, true) ++ (constsBefore ++ constsAfter).map (·, false)
    for (n, written) in candidates do
      let some ci := env.find? n | continue
      if isAuxiliary env n then continue
      let isDef := match ci with
        | .defnInfo _ | .opaqueInfo _ => true
        | _ => false
      if !written && !isDef then continue
      let n ← declaredName n
      if seen.contains n then continue
      seen := seen.insert n
      let mod := (env.getModuleIdxFor? n).map fun i => env.header.moduleNames[i.toNat]!
      if isNotation env n then notations := notations.push (n, mod)
      else dependency := dependency.push (n, mod)
    return { usage := usage, dependency, notations }

/-! ## Locations -/

/-- The `.lean` source of a module, relative to the working directory when inside it. -/
def sourceOf (cache : IO.Ref (Std.HashMap Name String)) (mod : Name) : IO String := do
  if let some p := (← cache.get)[mod]? then return p
  let srcPath := System.SearchPath.parse ((← IO.getEnv "LEAN_SRC_PATH").getD "")
  let sysroot ← findSysroot
  let found ← Lean.SearchPath.findWithExt (srcPath ++ [sysroot / "src" / "lean"]) "lean" mod
  let path ← match found with
    | some f =>
      let full := (← IO.FS.realPath f).toString
      let cwd := (← IO.FS.realPath (← IO.currentDir)).toString ++ "/"
      pure (if cwd.isPrefixOf full then (full.drop cwd.length).toString else full)
    | none => pure mod.toString
  cache.modify (·.insert mod path)
  return path

/-! ## Adding the fields to the checkpoints -/

structure Env where
  steps : Std.HashMap String Step
  fileName : String
  sources : IO.Ref (Std.HashMap Name String)

def pairs (env : Env) (xs : Array (Name × Option Name)) : IO Json := do
  let out ← xs.mapM fun (n, mod?) => do
    let loc ← match mod? with
      | some m => sourceOf env.sources m
      | none => pure env.fileName
    return toJson [n.toString, loc]
  return toJson out

def markGoals (goals : Json) (usage : List (List (Option String))) : Json := Id.run do
  let .ok gs := goals.getArr? | return goals
  let mut out := #[]
  for (g, marks) in gs.toList.zip usage do
    let .ok hs := g.getObjValAs? (Array Json) "hypotheses" | out := out.push g; continue
    let hs := (hs.toList.zip (marks ++ List.replicate hs.size none)).map fun
      | (h, some m) => h.setObjVal! "usage" (toJson m)
      | (h, none) => h
    out := out.push (g.setObjVal! "hypotheses" (toJson hs))
  return toJson out

partial def enrich (env : Env) (parent : String) (j : Json) : IO Json := do
  let id := (j.getObjValAs? Nat "id").toOption.getD 0
  let path := s!"{parent}/{id}"
  let mut j := j.setObjVal! "path" (toJson path)
  let key := match j.getObjValAs? (Nat × Nat) "range", j.getObjValAs? String "kind" with
    | .ok (s, e), .ok k => keyOf s e k
    | _, _ => ""
  match env.steps[key]? with
  | some st =>
    let a ← analyse st
    j := j.setObjVal! "goalsBefore" (markGoals (j.getObjValD "goalsBefore") a.usage)
    j := j.setObjVal! "dependency" (← pairs env a.dependency)
    j := j.setObjVal! "notationDependency" (← pairs env a.notations)
  | none =>
    j := j.setObjVal! "dependency" (toJson ([] : List Json))
    j := j.setObjVal! "dependencyError" (toJson "tactic node not found")
  if let .ok subs := j.getObjValAs? (Array Json) "substeps" then
    j := j.setObjVal! "substeps" (toJson (← subs.mapM (enrich env s!"{path}/sub")))
  if let .ok auxs := j.getObjValAs? (Array (Array Json)) "auxiliary" then
    let mut out := #[]
    for h : k in [0:auxs.size] do
      out := out.push (toJson (← auxs[k].mapM (enrich env s!"{path}/aux{k}")))
    j := j.setObjVal! "auxiliary" (toJson out)
  return j

/-! ## Entry point -/

/-- Like `TacticRoles.processFile`, with the dependency fields added. -/
def processFile (fileName : String) : IO Json := do
  let source ← IO.FS.readFile fileName
  let (context, state) ← createContextStateFromFile source fileName .none {}
  let headerLog := state.commandState.messages
  if headerLog.hasErrors then
    let errors ← headerLog.toList.mapM (·.toString)
    throw <| IO.userError s!"cannot load the imports of {fileName}:\n{String.join errors}"
  let sources ← IO.mkRef {}
  let label := (System.FilePath.mk fileName).fileName.getD fileName
  let m : Pantograph.Frontend.FrontendM (List Json) := mapCompilationSteps λ step => do
    let (startPos, endPos) := stxByteRange step.stx
    let declarations := (← (step.newConstants : IO _)).toArray.qsort Name.lt |>.map toString
    let steps := step.trees.foldl (fun acc t => allSteps t none acc) {}
    let env : Env := { steps, fileName, sources }
    -- Name the unit after the declaration written in the source (a command can
    -- add several, e.g. `@[to_additive]` adds the additive version).
    let written := (step.stx.find? (·.isOfKind ``Lean.Parser.Command.declId)).map (·[0].getId.toString)
    let unitName := match written.bind (fun w => declarations.find? (·.endsWith w)), declarations[0]? with
      | some d, _ => d
      | none, some d => d
      | none, none => s!"{(TacticRoles.commandKind step.stx).toString.splitOn "." |>.getLast!}@{startPos.byteIdx}"
    let checkpoints ← (TacticRoles.collect step : IO _)
    let checkpoints ← (checkpoints.mapM (enrich env s!"{label}::{unitName}" ∘ toJson) : IO _)
    return Json.mkObj [
      ("command", toJson (TacticRoles.commandKind step.stx).toString),
      ("declarations", toJson declarations),
      ("boundary", toJson [startPos.byteIdx, endPos.byteIdx]),
      ("messages", toJson (← (step.msgs.mapM TacticRoles.messageToJson : IO _))),
      ("checkpoints", toJson checkpoints),
    ]
  let units ← m.run {} |>.run context |>.run' state
  return Json.mkObj [("file", toJson fileName), ("units", toJson units)]

/-! ## Looking up one declaration (used by lookup.py) -/

/-- Where `name` is declared, after importing `module`: its kind, statement,
source file and line range. -/
def declaration (name : Name) (module : Name) : IO Json := do
  let env ← importModules #[{ module }] {} (loadExts := true)
  let ctx : Core.Context := { fileName := "<lookup>", fileMap := default }
  let (j, _) ← (MetaM.run' (do
    let some ci := env.find? name | throwError "unknown constant {name} in {module}"
    let kind := match ci with
      | .thmInfo _ => "theorem" | .defnInfo _ => "definition" | .axiomInfo _ => "axiom"
      | .opaqueInfo _ => "opaque" | .inductInfo _ => "inductive" | .ctorInfo _ => "constructor"
      | .recInfo _ => "recursor" | .quotInfo _ => "quotient"
    let type := (← ppExpr ci.type).pretty
    let ranges ← findDeclarationRanges? name
    let mod := (env.getModuleIdxFor? name).map fun i => env.header.moduleNames[i.toNat]!
    let mut fields := [("name", toJson name.toString), ("kind", toJson kind), ("type", toJson type),
      ("module", toJson (mod.map toString))]
    if let some r := ranges then
      fields := fields ++ [("startLine", toJson r.range.pos.line), ("endLine", toJson r.range.endPos.line)]
    return Json.mkObj fields) : CoreM Json).toIO ctx { env }
  let file ← match env.getModuleIdxFor? name with
    | some i => sourceOf (← IO.mkRef {}) env.header.moduleNames[i.toNat]!
    | none => pure ""
  return j.setObjVal! "file" (toJson file)

end Dependencies
