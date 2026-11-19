import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
src = open(sys.argv[2], encoding="utf-8").read().encode()

def first_line(s, n=44):
    return s.splitlines()[0][:n] if s else ""

def show(cp, indent, label):
    gb = " | ".join(g["target"] for g in cp["goalsBefore"])
    print(f"{'  ' * indent}{label}#{cp['id']} {first_line(cp['tactic']):<44}  ⊢ {gb[:40]}")
    for sub in cp["substeps"]:
        show(sub, indent + 1, "sub ")
    for k, proof in enumerate(cp["auxiliary"]):
        print(f"{'  ' * (indent + 1)}aux proof {k}:")
        for step in proof:
            show(step, indent + 2, "")

for unit in data["units"]:
    if not unit["checkpoints"]:
        continue
    names = ", ".join(unit.get("declarations", [])) or "(anonymous)"
    print("==", unit.get("command", "").split(".")[-1], names)
    for cp in unit["checkpoints"]:
        show(cp, 1, "MAIN ")
