import Mathlib
import Architect

-- Your AutoFaith / Blueprint graph extraction code above ...
import FLproof.BlueprintGraph

theorem mathlibExample
    (x : ℝ) :
    Real.sqrt (x ^ 2) = |x| := by
  exact Real.sqrt_sq_eq_abs x


#autofaith_graph mathlibExample
#check HAdd
#check Monoid ℝ
