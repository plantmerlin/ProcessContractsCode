"""audit.py — verify every recorded run against the contract (M3).

Writes one ACR per run to reports/<run_id>.acr.json and prints a summary.

    python audit.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from artefact import atf, verify                                  # noqa: E402

TASK_NAME = "hanoi3"


def main():
    adf = atf.load_adf(TASK_NAME)
    rows = []
    for d in sorted(atf.RUNS.glob(f"*{TASK_NAME}*")):
        f = d / "trace.json"
        if not f.exists():
            continue
        tr = json.loads(f.read_text(encoding="utf-8"))
        acr = verify.check(tr, adf)
        atf.write_json(atf.REPORTS / f"{tr['run_id']}.acr.json", acr)
        fams = sorted({m.get("family") for m in acr["misalignments"]})
        cls = sorted({m["class"] for m in acr["misalignments"]})
        rows.append({
            "run": tr["run_id"][-4:], "run_id": tr["run_id"],
            "direction": tr.get("direction"), "events": len(tr["events"]),
            "blocked": sum(1 for e in tr["events"] if not e.get("applied", True)),
            "interventions": len(tr.get("interventions") or []),
            "verdict": acr["verdict"], "n_misalignments": len(acr["misalignments"]),
            "families": fams, "classes": cls,
            "is_seed": tr["run_id"] == adf.get("created_from_run"),
        })

    print(f"contract {adf['artefact_id'][:12]} v{adf['version']} "
          f"content {adf['content_hash'][:12]} seed {adf['created_from_run'][-4:]}")
    print(f"\n{'run':6}{'arm':11}{'ev':>4}{'blk':>5}{'iv':>4}  {'verdict':11}{'n':>3}  classes")
    for r in rows:
        print(f"{r['run']:6}{r['direction']:11}{r['events']:>4}{r['blocked']:>5}"
              f"{r['interventions']:>4}  {r['verdict']:11}{r['n_misalignments']:>3}  "
              f"{','.join(r['classes'])}{'   <- SEED' if r['is_seed'] else ''}")

    summ = {}
    for r in rows:
        a = r["direction"]
        s = summ.setdefault(a, {"n": 0, "conform": 0, "interventions": 0,
                                "blocked": 0})
        s["n"] += 1
        s["conform"] += r["verdict"] == "conforms"
        s["interventions"] += r["interventions"]
        s["blocked"] += r["blocked"]
    print()
    for a, s in sorted(summ.items()):
        print(f"{a:11} {s['conform']}/{s['n']} conform   "
              f"blocked-by-world {s['blocked']}   interventions {s['interventions']}")

    atf.write_json(HERE / "reports" / "_audit_summary.json",
                   {"contract": {"artefact_id": adf["artefact_id"],
                                 "version": adf["version"],
                                 "content_hash": adf["content_hash"],
                                 "seed_run": adf["created_from_run"]},
                    "by_arm": summ, "runs": rows})
    print(f"\n{len(rows)} ACRs -> {atf.REPORTS}")


if __name__ == "__main__":
    main()
