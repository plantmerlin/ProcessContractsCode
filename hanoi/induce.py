"""induce.py — build the process contract from one recorded run (M1).

    python hanoi/induce.py [run_id]

With no run_id it picks the most recent SEED-ELIGIBLE run. Eligible means:

  * the run attained the goal (the exit guard holds at the end), and
  * every recorded event was APPLIED.

The second condition is what keeps a recording honest. A blocked move is a
stutter — the agent chose it, the world refused it, the process did not advance
— so it must not contribute a cell to P. Were it included, the contract would
demand that a replay attempt an illegal move, which is plainly not the process
anyone intends to record. The blocked events stay in the trace, because they are
evidence about the run; they simply do not shape the specification.

The contract must then accept the run it came from. If it does not, the
induction is rejected and nothing is written.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Self-contained — see run_hanoi.py.
sys.path.insert(0, str(HERE))

from artefact import atf, translate, verify, guards               # noqa: E402

TASK_NAME = "hanoi3"


def load_task():
    return json.loads((HERE / "tasks" / f"{TASK_NAME}.task.json")
                      .read_text(encoding="utf-8"))


def eligible(tr, task):
    ev = tr.get("events") or []
    if not ev:
        return False, "no events"
    if not guards.eval_guard(task["scope"]["exit_guard"], ev[-1]["post"]):
        return False, "goal not attained"
    bad = [e["seq"] for e in ev if not e.get("applied", True)]
    if bad:
        return False, f"{len(bad)} blocked event(s) at seq {bad[:6]}"
    return True, "eligible"


def candidates(task):
    out = []
    for d in sorted(atf.RUNS.glob(f"*{TASK_NAME}*")):
        f = d / "trace.json"
        if not f.exists():
            continue
        tr = json.loads(f.read_text(encoding="utf-8"))
        ok, why = eligible(tr, task)
        out.append((tr, ok, why))
    return out


def main():
    task = load_task()
    cands = candidates(task)
    if not cands:
        sys.exit("no runs found — run hanoi/run_hanoi.py first")

    if len(sys.argv) > 1:
        pick = [t for t, _, _ in cands if t["run_id"].endswith(sys.argv[1])]
        if not pick:
            sys.exit(f"no run matching {sys.argv[1]!r}")
        seed = pick[-1]
        ok, why = eligible(seed, task)
        if not ok:
            sys.exit(f"run is not seed-eligible: {why}")
    else:
        print(f"{'run':6} {'events':>7} {'eligible':>9}  reason")
        for tr, ok, why in cands:
            print(f"{tr['run_id'][-4:]:6} {len(tr['events']):>7} "
                  f"{('yes' if ok else 'no'):>9}  {why}")
        good = [t for t, ok, _ in cands if ok]
        if not good:
            sys.exit("\nno seed-eligible run — need one that solves the puzzle "
                     "with no blocked moves")
        seed = good[-1]
        print()

    print(f"seed: {seed['run_id']}  ({len(seed['events'])} events, "
          f"{seed['agent']['model']})")
    for e in seed["events"]:
        print(f"   seq{e['seq']:>2} {e['action']:12} {e['post']['config']}")

    spans = []
    sp = atf.RUNS / seed["run_id"] / "spans.jsonl"
    if sp.exists():
        spans = [json.loads(l) for l in sp.read_text(encoding="utf-8").splitlines()
                 if l.strip()]

    adf = translate.translate(task, seed, spans)
    adf["version"] = "1.0.0"
    adf["signoff"] = {"status": "signed",
                      "note": "Option 1 — the contract is a recording of the seed "
                              "run. Move cells release the configuration and the "
                              "legality predicates, which the environment decides."}

    acr = verify.check(seed, adf)
    print(f"\nseed self-verification: {acr['verdict']} "
          f"({len(acr['misalignments'])} misalignments), "
          f"completeness={acr['completeness']['result']}")
    if acr["verdict"] != "conforms":
        for m in acr["misalignments"][:5]:
            print("   ", m["class"], "|", m.get("expected"), "|", m.get("observed"))
        sys.exit("contract does not accept its own seed — NOT written")

    out = atf.ARTEFACTS / f"{TASK_NAME}.adf.json"
    atf.write_json(out, adf)
    print(f"\ncontract -> {out}")
    print(f"  artefact_id  {adf['artefact_id'][:12]}")
    print(f"  content_hash {adf['content_hash'][:12]}")
    print(f"  seed run     {adf['created_from_run'][-4:]}")


if __name__ == "__main__":
    main()
