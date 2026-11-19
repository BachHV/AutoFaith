
import Mathlib

theorem twice_sum_range_unfaithful (n : ℕ) :
    2 * (∑ k ∈ Finset.range (n + 1), k) = n * (n + 1) := by
  calc
    2 * (∑ k ∈ Finset.range (n + 1), k)
        = (∑ k ∈ Finset.range (n + 1), k) * 2 := by ring
    _ = (n + 1) * ((n + 1) - 1) :=
          Finset.sum_range_id_mul_two (n + 1)
    _ = n * (n + 1) := by simp [Nat.mul_comm]

open Polynomial
def p (x : ℝ) : ℝ := x^3 - x^2 - x + 1

noncomputable def p_poly : ℝ[X] := X^3 - X^2 - X + 1

theorem p_poly_eval (x : ℝ) : p_poly.eval x = p x := by
  simp [p_poly, p]

theorem p_root_one : p_poly.rootMultiplicity (1 : ℝ) = 2 := by
  have hfactor : p_poly = (X + C (1 : ℝ)) * (X - C (1 : ℝ))^2 := by
    unfold p_poly
    simp only [map_one]
    ring
  rw [hfactor, rootMultiplicity_mul_X_sub_C_pow (X_add_C_ne_zero (1 : ℝ))]
  have hnot : ¬ IsRoot (X + C (1 : ℝ)) (1 : ℝ) := by
    norm_num [IsRoot]
  rw [rootMultiplicity_eq_zero hnot]

theorem p_nonneg {x : ℝ} (hx : -1 ≤ x) : 0 ≤ p x := by
  have hfactor : p x = (x - 1)^2 * (x + 1) := by
    unfold p
    ring
  rw [hfactor]
  exact mul_nonneg (sq_nonneg (x - 1)) (by linarith)

namespace SumCubesFaithful

-- Twice the sum of the first n positive integers equals n(n + 1).
lemma twice_sum_first_n (n : ℕ) :
    2 * (∑ i ∈ Finset.range n, (i + 1)) = n * (n + 1) := by
  induction n with
  | zero => simp
  | succ n ih =>
      rw [Finset.sum_range_succ]
      nlinarith

theorem h (n : ℕ) :
    (∑ i ∈ Finset.range n, (i + 1) : ℚ) = n * (n + 1) / 2 := by
  have hq : (2 : ℚ) * (∑ i ∈ Finset.range n, (i + 1) : ℚ) =
      n * (n + 1) := by
    exact_mod_cast twice_sum_first_n n
  linarith

-- The twice-sum identity implies that n(n + 1)/2 is a natural number.
theorem twice_sum_first_n_implies_triangular_number_is_natural (n : ℕ) :
    2 * (∑ i ∈ Finset.range n, (i + 1)) = n * (n + 1) →
    ∃ k : ℕ, (k : ℚ) = (n : ℚ) * ((n : ℚ) + 1) / 2 := by
  intro h_twice
  refine ⟨∑ i ∈ Finset.range n, (i + 1), ?_⟩
  have h : (2 : ℚ) * (↑(∑ i ∈ Finset.range n, (i + 1)) : ℚ) =
      (n : ℚ) * ((n : ℚ) + 1) := by
    exact_mod_cast h_twice
  calc
    (↑(∑ i ∈ Finset.range n, (i + 1)) : ℚ) =
        ((2 : ℚ) * (↑(∑ i ∈ Finset.range n, (i + 1)) : ℚ)) / 2 := by ring
    _ = (n : ℚ) * ((n : ℚ) + 1) / 2 := by rw [h]

theorem triangular_number_is_natural (n : ℕ) :
    ∃ k : ℕ, (k : ℚ) = (n : ℚ) * ((n : ℚ) + 1) / 2 :=
  twice_sum_first_n_implies_triangular_number_is_natural n (twice_sum_first_n n)

-- The sum of the first n cubes is the square of their bases' sum.
theorem sum_cubes (n : ℕ) :
    (∑ i ∈ Finset.range n, (i + 1) ^ 3) =
      (∑ i ∈ Finset.range n, (i + 1)) ^ 2 := by
  induction n with
  | zero => simp
  | succ n ih =>
      simp only [Finset.sum_range_succ]
      rw [ih]
      let s := ∑ i ∈ Finset.range n, (i + 1)
      let t := n + 1
      -- The triangular-sum formula, written without natural-number division.
      have hs : 2 * s = n * t := by
        simpa only [s, t] using twice_sum_first_n n
      -- Difference of squares: (s + t)² - s² = t ((s + t) + s).
      have hdiff : (s + t) ^ 2 = s ^ 2 +
          ((s + t) - s) * ((s + t) + s) := by
        simp only [Nat.add_sub_cancel_left]
        ring
      have hleft : (s + t) - s = t := by omega
      have hright : (s + t) + s = t ^ 2 := by
        dsimp [t] at hs ⊢
        nlinarith
      rw [hleft, hright] at hdiff
      change s ^ 2 + t ^ 3 = (s + t) ^ 2
      calc
        s ^ 2 + t ^ 3 = s ^ 2 + t * t ^ 2 := by ring
        _ = (s + t) ^ 2 := hdiff.symm

-- A small example of splitting a proof into two cases.
theorem zero_or_positive (n : ℕ) : n = 0 ∨ 0 < n := by
  by_cases h : n = 0
  · exact Or.inl h
  · exact Or.inr (Nat.pos_of_ne_zero h)

/-
n : ℕ
⊢ n = 0 ∨ 0 < n


by_cases h : n = 0
  · exact Or.inl h
  · exact Or.inr (Nat.pos_of_ne_zero h).  ------>.    n : ℕ
                                          |            h : n = 0
                                          |           ⊢ n = 0 ∨ 0 < n
                                          |           -> exact Or.inl h
                                          |           No goals
                                          |
                                          |
                                          |------>.   n : ℕ
                                                      h : ¬n = 0
                                                      ⊢ n = 0 ∨ 0 < n

                                                      -> exact Or.inr (Nat.pos_of_ne_zero h)
                                                      No goals

No goal
-/


theorem h1 (a : ℕ) (h : Prime a) : True := by
  sorry

theorem h2 (a : ℕ) (h : Nat.Prime a) : True := by
  sorry


end SumCubesFaithful

theorem trace_square_nonneg {n : Type*} [Fintype n] [DecidableEq n]
    (A : Matrix n n ℝ) (hA : A.IsSymm) : 0 ≤ Matrix.trace (A ^ 2) := by
  -- The spectral theorem supplies an orthonormal eigenbasis and a diagonal form.
  let hHerm : A.IsHermitian := Matrix.isHermitian_iff_isSymm.mpr hA
  let U := hHerm.eigenvectorUnitary
  let D : Matrix n n ℝ := Matrix.diagonal hHerm.eigenvalues
  have hdiag : A = (U : Matrix n n ℝ) * D * (star U : Matrix n n ℝ) := by
    simpa [U, D, Unitary.conjStarAlgAut_apply, Function.comp_def] using
      hHerm.spectral_theorem
  have hunit : (star (U : Matrix n n ℝ)) * (U : Matrix n n ℝ) = 1 :=
    Unitary.coe_star_mul_self U
  -- Squaring a diagonal matrix squares each diagonal entry.
  have hDsq : D * D = Matrix.diagonal (fun i => (hHerm.eigenvalues i) ^ 2) := by
    simp [D, Matrix.diagonal_mul_diagonal, pow_two]
  -- Cyclicity of trace makes the change of orthonormal basis disappear.
  have htrace : Matrix.trace (A ^ 2) = ∑ i, (hHerm.eigenvalues i) ^ 2 := by
    conv_lhs => rw [hdiag, pow_two]
    calc
      Matrix.trace (((U : Matrix n n ℝ) * D * (star U : Matrix n n ℝ)) *
          ((U : Matrix n n ℝ) * D * (star U : Matrix n n ℝ))) =
          Matrix.trace ((U : Matrix n n ℝ) * (D * D) * (star U : Matrix n n ℝ)) := by
            have hprod :
                ((U : Matrix n n ℝ) * D * (star U : Matrix n n ℝ)) *
                    ((U : Matrix n n ℝ) * D * (star U : Matrix n n ℝ)) =
                  (U : Matrix n n ℝ) * D *
                    ((star U : Matrix n n ℝ) * (U : Matrix n n ℝ)) * D *
                    (star U : Matrix n n ℝ) := by
              simp only [mul_assoc]
            rw [hprod, hunit]
            simp only [mul_one, mul_assoc]
      _ = Matrix.trace (D * D) := by
        rw [Matrix.trace_mul_cycle, hunit, one_mul]
      _ = ∑ i, (hHerm.eigenvalues i) ^ 2 := by
        rw [hDsq, Matrix.trace_diagonal]
  rw [htrace]
  exact Finset.sum_nonneg (fun i _ => sq_nonneg (hHerm.eigenvalues i))
