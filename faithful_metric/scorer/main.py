from enum import Enum
from graph.build_graph import FLNode, FLEdge, NLNode, NLEdge, create_NL_graph, create_FL_graph, create_NL_graph, find_dependencies_for_FL, find_dependencies_for_NL

class ProofStrategy(Enum):
    DIRECT = 1
    CONTRADICTION = 2
    INDUCTION = 3
    CONTRAPOSITIVE = 4
    UNKNOWN = 5 



API_key = "your_api_key_here"



def compare_fl_and_nl_graph(fl_node : FLNode, nl_node: NLNode,
        fl_graph : tuple[list[FLNode], list[FLEdge]], 
        nl_graph : tuple[list[NLNode], list[NLEdge]]):
    if fl_node.category != nl_node.category:
        return 0.0
    NL_dependencies = find_dependencies_for_NL(nl_node, nl_graph)
    FL_dependencies = find_dependencies_for_FL(fl_node, fl_graph)


    

    # Compare the dependencies of the two nodes
    pass


def main(fl_proof_path : str, nl_proof_path : str):
    # TODO: Implement the main logic to process the proof files
    with open(fl_proof_path, "r") as f:
        fl_proof = f.read()
    with open(nl_proof_path, "r") as f:
        nl_proof = f.read()

    fl_graph = create_FL_graph(fl_proof)
    nl_graph = create_NL_graph(nl_proof)


    pass



if __name__ == "__main__":
    main("path/to/fl_proof.txt", "path/to/nl_proof.lean")

