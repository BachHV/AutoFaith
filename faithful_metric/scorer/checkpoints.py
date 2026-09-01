
'''
This module will define the Checkpoint and Proof Block classes, which will be used to store the state of the proof at various points in time. 
The Checkpoint class will store the premises and goal of the proof, while the Proof Block class will store the strategy and arguments used to reach that point in the proof.
'''

from dataclasses import dataclass

@dataclass(frozen=True)
class Checkpoint:
    premises : list[str]
    goal : list[str]

@dataclass(frozen=True)
class NLBlock:
    previous_checkpoint: Checkpoint
    arguments: list[str]
    next_checkpoint: Checkpoint


@dataclass(frozen=True)
class FLBlock:
    previous_checkpoint: Checkpoint | None
    arguments : list[str]
    next_checkpoint : Checkpoint | None





