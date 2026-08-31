
'''
This module will define the Checkpoint and Proof Block classes, which will be used to store the state of the proof at various points in time. 
The Checkpoint class will store the premises and goal of the proof, while the Proof Block class will store the strategy and arguments used to reach that point in the proof.
'''

class Checkpoint:
    premises : list[str]
    goal : list[str]

class NLblock:
    previous_goals: Checkpoint | None
    arguments : list[str]

class FLblock:
    previous_goals: Checkpoint | None
    arguments : list[str]


def create_checkpoint_from_prev_blocks(prev_blocks: list[FLblock]) -> Checkpoint:
    pass






