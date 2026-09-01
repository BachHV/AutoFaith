import Mathlib
import Architect
import Lean.Elab.DeclarationRange

open Lean
open Lean Meta
open Lean Elab Command
open Architect

namespace AutoFaith

structure GraphNode where
  name : String
  category : String
  statement : String
  moduleName : String
  sourceStartLine : Option Nat := none
  sourceStartColumn : Option Nat := none
  sourceEndLine : Option Nat := none
  sourceEndColumn : Option Nat := none
deriving ToJson

structure GraphEdge where
  source : String
  target : String
  kind : String
deriving ToJson

structure Graph where
  root : String
  nodes : Array GraphNode
  edges : Array GraphEdge
deriving ToJson

/-- Direct constants occurring in a declaration's value/proof. -/
def directValueConstants (info : ConstantInfo) : Array Name :=
  match info with
  | .thmInfo v => v.value.getUsedConstants
  | .defnInfo v => v.value.getUsedConstants
  | .opaqueInfo v => v.value.getUsedConstants
  | .inductInfo v => v.ctors.toArray
  | _ => #[]

/-- Register a declaration as a temporary Blueprint node. -/
def registerAsBlueprint (name : Name) : CoreM Unit := do
  let env ← getEnv
  if (blueprintExt.find? env name).isSome then
    return
  unless env.contains name do
    return
  let node ← Architect.mkNode name {}
  Architect.blueprintExt.add name node
  modifyEnv fun env =>
    Architect.addLeanNameOfLatexLabel env node.latexLabel name

/--
For one root, mark the root and every DIRECT constant in its statement/proof
as Blueprint nodes. Then LeanArchitect stops at those constants instead of
opening their implementations.
-/
def prepareBlueprintBoundary (root : Name) : CoreM Unit := do
  let info ← getConstInfo root
  registerAsBlueprint root
  for dependency in info.type.getUsedConstants do
    registerAsBlueprint dependency
  for dependency in directValueConstants info do
    registerAsBlueprint dependency

def categoryOf (info : ConstantInfo) : String :=
  match info with
  | .thmInfo _ => "THEOREM"
  | _ => "DEFINITION"

def moduleOf (name : Name) : CoreM String := do
  let env ← getEnv
  if let some modIdx := env.const2ModIdx.get? name then
    return env.header.moduleNames[modIdx.toNat]!.toString
  else
    return env.header.mainModule.toString

def prettyStatement (name : Name) : MetaM String := do
  let info ← getConstInfo name
  return (← Meta.ppExpr info.type).pretty

def makeNode (name : Name) : MetaM GraphNode := do
  let info ← getConstInfo name
  let statement ← prettyStatement name
  let moduleName ← moduleOf name
  let ranges? ← findDeclarationRanges? name
  let sourceStartLine := ranges?.map fun ranges => ranges.range.pos.line
  let sourceStartColumn := ranges?.map fun ranges => ranges.range.pos.column
  let sourceEndLine := ranges?.map fun ranges => ranges.range.endPos.line
  let sourceEndColumn := ranges?.map fun ranges => ranges.range.endPos.column
  return {
    name := name.toString
    category := categoryOf info
    statement := statement
    moduleName := moduleName
    sourceStartLine := sourceStartLine
    sourceStartColumn := sourceStartColumn
    sourceEndLine := sourceEndLine
    sourceEndColumn := sourceEndColumn
  }

syntax (name := autofaithGraphCmd) "#autofaith_graph" ident : command

@[command_elab autofaithGraphCmd]
def elabAutoFaithGraph : CommandElab := fun stx => do
  match stx with
  | `(command| #autofaith_graph $rootSyntax:ident) =>
      let root ← liftCoreM <| realizeGlobalConstNoOverloadWithInfo rootSyntax

      -- Build the direct Blueprint boundary.
      liftCoreM <| prepareBlueprintBoundary root

      -- LeanArchitect separates statement dependencies and proof dependencies.
      let (statementUsed, proofUsed) ← liftCoreM <| Architect.collectUsed root

      let mut names : NameSet := {}
      names := names.insert root
      for name in statementUsed do
        names := names.insert name
      for name in proofUsed do
        names := names.insert name

      let mut nodes : Array GraphNode := #[]
      for name in names do
        let node ← liftTermElabM <| makeNode name
        nodes := nodes.push node

      let mut edges : Array GraphEdge := #[]
      for dependency in statementUsed do
        edges := edges.push {
          source := root.toString
          target := dependency.toString
          kind := "STATEMENT_USES"
        }
      for dependency in proofUsed do
        edges := edges.push {
          source := root.toString
          target := dependency.toString
          kind := "PROOF_USES"
        }

      let graph : Graph := {
        root := root.toString
        nodes := nodes
        edges := edges
      }

      liftIO <| IO.println s!"AUTOFAITH_BLUEPRINT_JSON:{(toJson graph).compress}"
  | _ => throwUnsupportedSyntax

end AutoFaith
