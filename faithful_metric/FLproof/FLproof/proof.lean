import Mathlib
import Architect

-- Your AutoFaith / Blueprint graph extraction code above ...
-- import FLproof.BlueprintGraph

/-- Hello -/
theorem trivial_theorem (a : Nat) : ∃ p : Nat, Nat.Prime p ∧ p > a := by
  by_contra h
  push Not at h
  let set_prime : Set Nat := {p | Nat.Prime p}
  have h_bounded : set_prime ⊆ Set.Iic a := by intro p hp; exact h p hp
  have h_finite : Set.Finite set_prime := (Set.finite_Iic a).subset h_bounded
  classical
  let prime_product : Nat := (∏ p ∈ h_finite.toFinset, p) + 1
  have h1 : prime_product ∉ set_prime := by
    have easy : ∀ ele ∈ set_prime, prime_product > ele := by sorry
    intro hp
    have hlt := easy prime_product hp
    omega
  have prime_product_has_prime : ∃ p : Nat, Nat.Prime p ∧ p ∣ prime_product := by
    have hgt : prime_product ≠ 1 := by
      dsimp [prime_product]
      have hpos : 0 < ∏ p ∈ h_finite.toFinset, p := by
        apply Finset.prod_pos
        intro p hp
        have hprime : Nat.Prime p := by
          have hm : p ∈ set_prime := h_finite.mem_toFinset.mp hp
          exact hm
        exact hprime.pos
      omega
    exact Nat.exists_prime_and_dvd hgt
  rcases prime_product_has_prime with ⟨p_1, hp_1_prime, hp_1_dvd⟩
  have t_dvd : p_1 ∣ (∏ p ∈ h_finite.toFinset, p) := by
    have hmem : p_1 ∈ h_finite.toFinset := by exact h_finite.mem_toFinset.mpr (by exact hp_1_prime)
    exact Finset.dvd_prod_of_mem (fun p : ℕ => p) hmem
  have t_dvd_contra : p_1 ∣ 1 := by
    have hsub : p_1 ∣ prime_product - ∏ p ∈ h_finite.toFinset, p := by exact Nat.dvd_sub hp_1_dvd t_dvd
    have heq : prime_product - ∏ p ∈ h_finite.toFinset, p = 1 := by
      dsimp [prime_product]
      omega
    rw [heq] at hsub
    exact hsub
  have hp_1_eq_one : p_1 = 1 := Nat.dvd_one.mp t_dvd_contra
  exact hp_1_prime.ne_one hp_1_eq_one


theorem even_add_faithful (a b : Int)
        (ha : Even a) (hb : Even b) :
        Even (a + b) := by
      apply Even.add ha hb


theorem g (p : α → Prop)(h : ∀ x, p x) : ∀ y, p y := by
  intro y
  apply h y


  -- Here you would continue the proof using the assumption `h`


example (x y : ℤ) :
    (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by

  -- Supporting claim
  have h_expand :
      (x + y) ^ 2 =
        x ^ 2 + x * y + y * x + y ^ 2 := by
    -- Auxiliary proof of the supporting claim
    ring

  -- Main proof
  calc
    (x + y) ^ 2
        = x ^ 2 + x * y + y * x + y ^ 2 := h_expand
    _ = x ^ 2 + 2 * x * y + y ^ 2 := by
        ring


lemma square_add_expansion (x y : ℤ) :
    (x + y) ^ 2 =
      x ^ 2 + x * y + y * x + y ^ 2 := by
  ring

example (x y : ℤ) :
    (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by
  calc
    (x + y) ^ 2
        = x ^ 2 + x * y + y * x + y ^ 2 :=
          square_add_expansion x y
    _ = x ^ 2 + 2 * x * y + y ^ 2 := by
        ring

example (x y : ℤ) :
    (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by
  rw [square_add_expansion x y]
  ring



-- #autofaith_decl_info main
#check HAdd
#check Monoid ℝ
#check Set.Finite


/-

theorem A ... : ... := by
    have theorem one () : ... := by



-/
