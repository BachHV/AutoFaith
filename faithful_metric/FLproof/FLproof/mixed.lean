namespace MyList

def sum : List Nat → Nat
  | [] => 0
  | x :: xs => x + sum xs

def double (n : Nat) : Nat := by
  exact n + n

theorem sum_nil : sum [] = 0 := rfl

theorem sum_cons (x : Nat) (xs : List Nat) : sum (x :: xs) = x + sum xs := by
  rfl

theorem sum_append (xs ys : List Nat) : sum (xs ++ ys) = sum xs + sum ys := by
  induction xs with
  | nil => simp [sum]
  | cons x xs ih =>
    simp [sum, ih]
    omega

variable (n : Nat)

theorem double_eq : double n = 2 * n := by
  unfold double
  omega

theorem broken (p q : Prop) (hp : p) : q := by
  exact hp

theorem after_broken : sum [1, 2] = 3 := by
  rw [sum_cons, sum_cons, sum_nil]

end MyList

structure Point where
  x : Nat
  y : Nat

instance : Inhabited Point := ⟨⟨0, 0⟩⟩

def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib n + fib (n + 1)

def countdown (n : Nat) : List Nat :=
  if h : n = 0 then [] else n :: countdown (n - 1)
termination_by n
decreasing_by omega

example : fib 5 = 5 := by
  decide

mutual
theorem even_or_odd_a (n : Nat) : n = n := by
  rfl
theorem even_or_odd_b (n : Nat) : n + 0 = n := by
  simp
end
