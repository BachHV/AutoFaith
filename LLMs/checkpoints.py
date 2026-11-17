from dataclasses import dataclass
import enum
from typing import List, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ProofLanguage(str, Enum):
    NL = "Natural Language"
    FL = "Formal Language"

class State: 
    premise : List[str]
    goal : List[str]
    id : int


class Checkpoint:
    language : ProofLanguage
    theorem_id : str
    prev_state : State
    next_state : State
    justification : List[str]
    dependency : set[str]
    intermediate_claims : List[Tuple[str, State]] # Statement is a state itself
    proofs_intermediate_claims : List["Checkpoint"] 


"""
I want to create a function that from a proof and generate a list of unit Checkpoint here
Unit checkpoint is a special kind of checkpoint that cannot be decomposed, meaning that this checkpoint
is created everytime the proof state is updated. 

This can be done by LLM. But how can i develop it independently or design it to be modular so that I can 
develop the LLM with prompt seperately ?
"""


def combine_checkpoints(a : Checkpoint, b : Checkpoint) -> Checkpoint:
    if a.next_state != b.prev_state:
        raise "Unable to combine"
    if a.language != b.language:
        raise "Invalid Combination"
    if a.theorem_id != b.theorem_id:
        raise "Not the same theorem"

    new_language = a.language
    theorem_id = a.theorem_id
    justification = a.justification + b.justification
    dependency = a.dependency | b.dependency
    intermediate_claims = a.intermediate_claims + b.intermediate_claims
    proof_intermedidate_claims = a.proofs_intermediate_claims + b.proofs_intermediate_claims
    return Checkpoint(
        language = new_language,
        theorem_id = theorem_id, 
        prev_state = a.prev_state, 
        next_state = b.next_state,
        justification = justification, 
        dependency = dependency,
        intermediate_claims = intermediate_claims,
        proof_intermedidate_claims = proof_intermedidate_claims
    )



    




