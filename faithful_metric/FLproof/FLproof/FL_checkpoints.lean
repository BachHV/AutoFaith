import Lean
import Pantograph

structure State where
  premise : List String
  goal : List String

structure Checkpoint where
  name_id : String
  stateBefore : State
  stateAfter : State
  tactic : String
  depdendencies : List String
  auxiliary : Option (List Checkpoint)
