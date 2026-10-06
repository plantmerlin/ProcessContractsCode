"""induce_codegen.py — build THE contract from one recorded run (M1).

    python induce_codegen.py [run_id_suffix]

Seed-eligible means: every event applied, the run ENDS with report, and the exit
guard holds at the end. The "ends with report" condition closes a gap found in
the Hanoi freeze run, where a seed that reported early and then kept acting
passed eligibility and was only caught by self-verification.

Also runs a P-INVARIANCE check: it induces a contract from the latest eligible
run of EVERY spec and compares the process terms. If one contract really serves
all specs, those terms must be identical.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("ARTEFACT_HOME", str(HERE))
sys.path.insert(0, str(HERE))

from artefact import atf, translate, verify, guards               # noqa: E402

TASK_NAME = "codegen"


def load_task():
    return json.loads((HERE / "tasks" / f"{TASK_NAME}.task.json")
                      .read_text(encoding="utf-8"))


def eligible(tr, task):
    ev = tr.get("events") or []
    if not ev:
        return False, "no events"
    if tr.get("direction") != "undirected":
        return False, "not an undirected run"
    bad = [e["seq"] for e in ev if not e.get("applied", True)]
    if bad:
        return False, f"{len(bad)} rejected event(s)"
    if ev[-1]["action"] != "report":
        return False, "does not end with report"
    if not guards.eval_guard(task["scope"]["exit_guard"], ev[-1]["post"]):
        return False, "exit guard not satisfied"
    return True, "eligible"


def runs():
    out = []
    for d in sorted(atf.RUNS.glob(f"*{TASK_NAME}*")):
        f = d / "trace.json"
        if f.exists():
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def spans_for(run_id):
    sp = atf.RUNS / run_id / "spans.jsonl"
    if not sp.exists():
        return []
    return [json.loads(l) for l in sp.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def cells_of(adf):
    out = []

    def walk(n):
        if n.get("op") == "cell":
            out.append((n["action"], n["pre"], n["post"]))
        for k in ("children", "cells", "options"):
            for c in n.get(k, []):
                walk(c)
        for b in n.get("branches", []):
            walk(b["node"])
    walk(adf["P"])
    return out


def main():
    task = load_task()
    all_runs = runs()
    print(f"{'run':6}{'spec':24}{'ev':>4}  eligible")
    for tr in all_runs:
        ok, why = eligible(tr, task)
        print(f"{tr['run_id'][-4:]:6}{tr['spec']['spec']:24}"
              f"{len(tr['events']):>4}  {'yes' if ok else 'no':4} {why}")
    good = [t for t in all_runs if eligible(t, task)[0]]
    if len(sys.argv) > 1:
        good = [t for t in good if t["run_id"].endswith(sys.argv[1])]
    if not good:
        sys.exit("\nno seed-eligible run")
    seed = good[-1]

    print(f"\nseed: {seed['run_id']}  spec={seed['spec']['spec']}")
    for e in seed["events"]:
        print(f"   seq{e['seq']} {e['action']}")

    adf = translate.translate(task, seed, spans_for(seed["run_id"]))
    adf["version"] = "1.0.0"
    adf["signoff"] = {"status": "signed",
                      "note": ("One contract for every code-creation spec. "
                               f"Induced from a {seed['spec']['spec']} run.")}
    acr = verify.check(seed, adf)
    print(f"\nseed self-verification: {acr['verdict']} "
          f"({len(acr['misalignments'])} misalignments)")
    if acr["verdict"] != "conforms":
        for m in acr["misalignments"][:5]:
            print("   ", m["class"], m.get("expected"), m.get("observed"))
        sys.exit("contract does not accept its own seed - NOT written")

    out = atf.ARTEFACTS / f"{TASK_NAME}.adf.json"
    atf.write_json(out, adf)
    print(f"\ncontract -> {out}")
    print(f"  artefact_id  {adf['artefact_id'][:12]}")
    print(f"  content_hash {adf['content_hash'][:12]}")
    for a, p, q in cells_of(adf):
        print(f"   <{p:15}> {a:16} <{q}>")

    # ---- P invariance across specs ----------------------------------------
    print("\nP-invariance: inducing from the latest eligible run of each spec")
    by_spec = {}
    for t in good if len(sys.argv) <= 1 else [t for t in all_runs
                                               if eligible(t, task)[0]]:
        by_spec[t["spec"]["spec"]] = t
    reference = json.dumps(adf["P"], sort_keys=True)
    rows = []
    for name, t in sorted(by_spec.items()):
        other = translate.translate(task, t, spans_for(t["run_id"]))
        same_p = json.dumps(other["P"], sort_keys=True) == reference
        same_id = other["artefact_id"] == adf["artefact_id"]
        rows.append({"spec": name, "run_id": t["run_id"],
                     "same_P": same_p, "same_artefact_id": same_id})
        print(f"   {name:24} from {t['run_id'][-4:]}  identical P: "
              f"{'YES' if same_p else 'NO'}   same artefact_id: "
              f"{'YES' if same_id else 'NO'}")
    atf.write_json(atf.HOME / "reports" / "_p_invariance.json",
                   {"reference_seed": seed["run_id"],
                    "artefact_id": adf["artefact_id"], "rows": rows})


if __name__ == "__main__":
    main()
