"""Quick inspection of the latest eval results: high-stakes outcomes and failures."""

import json
from pathlib import Path

data = json.loads(
    (Path(__file__).resolve().parent.parent / "eval" / "results" / "latest.json").read_text(
        encoding="utf-8"
    )
)

print("--- high-stakes cases ---")
for r in data["behavior"]["cases"]:
    if r["high_stakes"]:
        mark = "OK  " if r["decision"] == "escalated" else "MISS"
        print(f"{mark} {r['id']}: decision={r['decision']} expect={r['expect']}")

print("\n--- all failures ---")
for r in data["behavior"]["cases"]:
    if not r["passed"]:
        print(f"{r['id']}: {r['failures']}")
