"""audit_codegen.py — verify every run against THE contract (M3).

    python audit_codegen.py

One contract, every spec. Writes reports/<run_id>.acr.json per run and
reports/_audit_summary.json, and prints results by spec and arm.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("ARTEFACT_HOME", str(HERE))
sys.path.insert(0, str(HERE))

from artefact import atf, verify                                  # noqa: E402

TASK_NAME = "codegen"


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
        ev = tr["events"]
        fs = tr.get("final_state") or (ev[-1]["post"] if ev else {})
        rows.append({
            "run": tr["run_id"][-4:], "run_id": tr["run_id"],
            "spec": tr["spec"]["spec"], "arm": tr["direction"],
            "events": len(ev),
            "sequence": [e["action"] for e in ev],
            "rejected_by_world": sum(1 for e in ev if not e.get("applied", True)),
            "interventions": len(tr.get("interventions") or []),
            "intervention_kinds": sorted({v.get("kind") for v in
                                          (tr.get("interventions") or [])}),
            "test_passed": bool(fs.get("test_passed")),
            "verified": bool(fs.get("verified")),
            "reported": any(e["action"] == "report" and e.get("applied", True)
                            for e in ev),
            "verdict": acr["verdict"],
            "classes": sorted({m["class"] for m in acr["misalignments"]}),
            "families": sorted({m.get("family") for m in acr["misalignments"]
                                if m.get("family")}),
            "is_seed": tr["run_id"] == adf.get("created_from_run"),
            "runner_outcome": tr.get("runner_outcome"),
            "wall_seconds": tr.get("wall_seconds"),
        })

    print(f"contract {adf['artefact_id'][:12]} content {adf['content_hash'][:12]} "
          f"seed {adf['created_from_run'][-4:]}\n")
    print(f"{'run':5}{'spec':23}{'arm':11}{'ev':>3}{'rej':>4}{'iv':>4} "
          f"{'test':5}{'verdict':11} classes")
    for r in rows:
        print(f"{r['run']:5}{r['spec']:23}{r['arm']:11}{r['events']:>3}"
              f"{r['rejected_by_world']:>4}{r['interventions']:>4} "
              f"{'PASS' if r['test_passed'] else 'fail':5}{r['verdict']:11}"
              f"{','.join(r['classes'])}{'  <- SEED' if r['is_seed'] else ''}")

    summary = {}
    for r in rows:
        k = f"{r['spec']}|{r['arm']}"
        s = summary.setdefault(k, {"spec": r["spec"], "arm": r["arm"], "n": 0,
                                   "conform": 0, "test_passed": 0,
                                   "passed_but_nonconforming": 0,
                                   "interventions": 0, "rejected_by_world": 0})
        s["n"] += 1
        s["conform"] += r["verdict"] == "conforms"
        s["test_passed"] += r["test_passed"]
        s["passed_but_nonconforming"] += (r["test_passed"]
                                          and r["verdict"] != "conforms")
        s["interventions"] += r["interventions"]
        s["rejected_by_world"] += r["rejected_by_world"]

    print(f"\n{'spec':23}{'arm':11}{'n':>3}{'conform':>9}{'test':>6}"
          f"{'pass&nonconf':>13}{'iv':>5}")
    for s in sorted(summary.values(), key=lambda x: (x["arm"], x["spec"])):
        print(f"{s['spec']:23}{s['arm']:11}{s['n']:>3}{s['conform']:>6}/{s['n']:<2}"
              f"{s['test_passed']:>4}/{s['n']:<2}{s['passed_but_nonconforming']:>8}"
              f"{s['interventions']:>9}")

    atf.write_json(atf.REPORTS / "_audit_summary.json",
                   {"contract": {"artefact_id": adf["artefact_id"],
                                 "content_hash": adf["content_hash"],
                                 "version": adf["version"],
                                 "seed_run": adf["created_from_run"]},
                    "summary": list(summary.values()), "runs": rows})
    print(f"\n{len(rows)} ACRs -> {atf.REPORTS}")


if __name__ == "__main__":
    main()
