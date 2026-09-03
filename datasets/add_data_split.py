#!/usr/bin/env python3
import csv
import random
import sys
from collections import defaultdict

REPS = 12
SEED = 42

def main(path: str) -> None:
    rows = list(csv.DictReader(open(path)))
    seen = defaultdict(int)
    holdout = []
    for r in rows:
        key = (r["vCPU_cores"], r["VNF_memory_MB"], r["Link_Capacity_limit_Mbps"])
        seen[key] += 1
        if seen[key] <= REPS:
            r["data_split"] = "train"
        else:
            holdout.append(r)
    random.Random(SEED).shuffle(holdout)
    half = len(holdout) // 2
    for i, r in enumerate(holdout):
        r["data_split"] = "validation" if i < half else "test"

    fields = ["data_split"] + [f for f in rows[0] if f != "data_split"]
    w = csv.DictWriter(sys.stdout, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)

if __name__ == "__main__":
    main(sys.argv[1])
