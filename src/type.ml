type arg = string

type proof_strategy = 
  DIRECT 
| CONTRADICTION 
| CONTRAPOSITIVE 
| INDUCTION 
| UNKNOWN of string

type proof = proof_strategy * (arg list)

