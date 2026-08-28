
class Checkpoint:
    premises : list[str]
    goal : list[str]

class NLchunk:
    previous_goals: Checkpoint | None
    arguments : list[str]

class FLchunk:
    previous_goals: Checkpoint | None
    arguments : list[str]


def create_checkpoint_from_prev_chunks(prev_chunks: list[FLchunk]) -> Checkpoint:
    pass






