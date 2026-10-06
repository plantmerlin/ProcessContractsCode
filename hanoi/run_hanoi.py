"""Run the agent on Tower of Hanoi and record the run as an ATF trace.

    python hanoi/run_hanoi.py [disks]
"""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Self-contained: the engines live in hanoi/artefact/ and the schemas in
# hanoi/spec/, so atf resolves both from this folder and nothing outside it is
# needed. HERE goes first on the path so the local copies win.
sys.path.insert(0, str(HERE))

from world import Hanoi                                           # noqa: E402
from artefact import atf, guards                                  # noqa: E402
from artefact.stepper import Stepper                              # noqa: E402
from agents import Agent, Runner, function_tool, trace, add_trace_processor  # noqa: E402
from agents.exceptions import MaxTurnsExceeded                    # noqa: E402
from agents.tracing import TracingProcessor                       # noqa: E402

MODEL = os.environ.get("MODEL_SNAPSHOT", "gpt-4o")
MAX_TURNS = int(os.environ.get("MAX_TURNS", "60"))
PROMPT_VARIANT = os.environ.get("PROMPT_VARIANT", "with_rules")
TASK_NAME = "hanoi3"

ENFORCE = os.environ.get("ENFORCE", "0") not in ("0", "false", "no")
NL2 = chr(10) * 2

W = None
EVENTS = None
LEDGER = None
STEP = None          # the gate, when ENFORCE is set
VETOES = None

ENFORCED_NOTE = (
    "\n\nNote: a runtime gate may refuse a move. A refusal means nothing moved "
    "and that the move is not the next step of the process. Adjust and continue."
)

DISPLAY = (
    "After each move you are shown the current position, written like this:\n\n"
    "A (top to bottom): 1 2 3\n"
    "B (top to bottom): -\n"
    "C (top to bottom): -\n\n"
    "Each line lists that peg's disks from the top of the stack down to the "
    "bottom. A dash means the peg is empty.\n\n"
    "Call report when you have finished."
)


def prompt_for(n, variant=None):
    variant = variant or PROMPT_VARIANT
    head = ("You are solving a Tower of Hanoi puzzle.\n\n"
            f"There are three pegs, A, B and C, and {n} disks numbered 1 to {n}, "
            "where 1 is the smallest. Every disk starts on peg A.\n\n")
    variants = {
        "no_rules": head + f"Finish with all {n} disks on peg C.\n\n" + DISPLAY,
        "with_rules": head + (
            "Rules:\n"
            "1. You may only move the disk that is currently on top of a peg.\n"
            "2. You may never place a disk on top of a smaller disk.\n\n"
            f"Desired end state: all {n} disks on peg C, in order, with disk "
            f"{n} at the bottom and disk 1 on top.\n\n") + DISPLAY,
    }
    if variant not in variants:
        sys.exit(f"unknown PROMPT_VARIANT {variant!r}; choose one of {sorted(variants)}")
    return variants[variant]


SPANS = {}


class Collector(TracingProcessor):
    def _e(self, tid, o):
        o["observed_at"] = time.time()
        SPANS.setdefault(tid, []).append(o)

    def on_trace_start(self, t):
        self._e(t.trace_id, {"kind": "trace_start", "trace_id": t.trace_id})

    def on_trace_end(self, t):
        self._e(t.trace_id, {"kind": "trace_end", "trace_id": t.trace_id})

    def on_span_start(self, s):
        self._e(s.trace_id, {"kind": "span_start", "trace_id": s.trace_id,
                             "span_id": s.span_id, "parent_id": s.parent_id})

    def on_span_end(self, s):
        p = s.span_data.export() if s.span_data else None
        self._e(s.trace_id, {"kind": "span_end", "trace_id": s.trace_id,
                             "span_id": s.span_id, "parent_id": s.parent_id,
                             "payload": p})

    def shutdown(self):
        pass

    def force_flush(self):
        pass


add_trace_processor(Collector())


@function_tool
def move(disk: int, to_peg: str) -> str:
    """Move a disk onto a peg. Pegs are 'A', 'B' or 'C'."""
    to = (to_peg or "").strip().upper()
    pre = W.observe()
    cell = W.cell(disk, to)          # None when the request is not in the vocabulary
    op = {"operation_seq": len(LEDGER), "kind": "move",
          "disk": disk, "to": to, "cell": cell, "pre": pre,
          # `dispatched`/`executed`: crossed the runtime gate and reached the
          # environment. `applied`: the environment accepted the requested
          # state change. A pre-execution veto is neither.
          "dispatched": False, "executed": False, "applied": False,
          "observed_at": time.time()}
    LEDGER.append(op)

    permit = None
    if STEP is not None:
        # FAIL CLOSED. A request outside the vocabulary cannot be judged against
        # the contract, so it is refused rather than executed. Letting it through
        # would put an effect in the world that the process never accounted for.
        if cell is None:
            op["outcome"] = "refused:UNCLASSIFIED"
            VETOES.append({"action": f"<unclassified:{disk}->{to}>",
                           "kind": "UNCLASSIFIED", "detail": "not a process step",
                           "observed_at": time.time()})
            return ("Refused: that is not a step of the process. "
                    "Nothing moved." + NL2 + W.render())
        allowed, info = STEP.check(cell, sigma=pre)
        permit = info.get("permit")
        if not allowed:
            # Refused BEFORE the world is touched, so nothing happened and no
            # event is recorded. The attempt lives in the ledger and in the
            # intervention list — which is what an intervention IS.
            op["outcome"] = f"refused:{info.get('veto')}"
            VETOES.append({"action": cell, "kind": info.get("veto"),
                           "detail": f"attempted {disk}->{to}",
                           "operation_seq": op["operation_seq"],
                           "observed_at": time.time()})
            note = ("This move belongs to the process but does not come next."
                    if info.get("not_yet") else
                    "This move is not part of the process from here.")
            return f"Refused: {note} Nothing moved." + NL2 + W.render()

    ok, reason = W.move(disk, to)
    post = W.observe()
    op.update({"dispatched": True, "executed": True, "applied": ok,
               "post": post,
               "outcome": "applied" if ok else f"not_applied:{reason}"})
    if STEP is not None:
        STEP.advance_transaction([cell], pre, post,
                                 args={"disk": disk, "to": to},
                                 discriminator="move", permit=permit,
                                 applied=ok)

    # Every operation that REACHES THE WORLD is an execution event, whether or
    # not the environment applies its requested state change. A proposal vetoed
    # before dispatch stays in the operation/intervention ledger and is not an
    # event, because no world transition was attempted.
    EVENTS.append({"seq": len(EVENTS), "layer": "SYS", "type": "action",
                   "action": cell or "move_invalid",
                   "args": {"disk": disk, "to": to},
                   "pre": pre, "post": post, "applied": ok,
                   "note": reason[:120], "observed_at": time.time()})

    head = f"Moved {disk} to {to}." if ok else f"Blocked: {reason}. Nothing moved."
    return head + "\n\n" + W.render()


@function_tool
def report(note: str = "") -> str:
    """Say that you have finished."""
    pre = W.observe()
    op = {"operation_seq": len(LEDGER), "kind": "report", "cell": "report",
          "pre": pre, "dispatched": False, "executed": False,
          "applied": False, "observed_at": time.time()}
    LEDGER.append(op)

    permit = None
    if STEP is not None:
        allowed, info = STEP.check("report", sigma=pre)
        permit = info.get("permit")
        if not allowed:
            op["outcome"] = f"refused:{info.get('veto')}"
            VETOES.append({"action": "report", "kind": info.get("veto"),
                           "detail": "attempted report",
                           "operation_seq": op["operation_seq"],
                           "observed_at": time.time()})
            return ("Refused: the process cannot finish in this state. "
                    "Nothing was recorded." + NL2 + W.render())

    post = W.observe()
    op.update({"post": post, "dispatched": True, "executed": True,
               "applied": True, "outcome": "executed"})
    EVENTS.append({"seq": len(EVENTS), "layer": "SYS", "type": "report",
                   "action": "report", "args": {"note": note[:120]},
                   "pre": pre, "post": post, "applied": True,
                   "observed_at": time.time()})
    if STEP is not None:
        STEP.advance_transaction(["report"], pre, post,
                                 args={"note": note[:120]}, permit=permit,
                                 applied=True)
    return "Recorded."


def one_run(idx, disks, task, adf=None):
    global W, EVENTS, LEDGER, STEP, VETOES
    W, EVENTS, LEDGER, VETOES = Hanoi(disks, goal=task["goal_peg"]), [], [], []
    t0 = time.time()
    initial = W.observe()

    # The gate reads the SAME projection the contract is written over.
    STEP = Stepper(adf, W.observe) if (ENFORCE and adf) else None

    instructions = prompt_for(disks) + (ENFORCED_NOTE if STEP is not None else "")
    agent = Agent(name="hanoi", model=MODEL,
                  instructions=instructions, tools=[move, report])
    tid, outcome = {}, "completed"
    try:
        with trace(f"hanoi_{idx}") as t:
            tid["id"] = t.trace_id
            opening = ("Here is the starting position:\n\n" + W.render()
                       + "\n\nSolve the puzzle.")
            Runner.run_sync(agent, opening, max_turns=MAX_TURNS)
    except MaxTurnsExceeded:
        outcome = "max_turns"
    except Exception as e:                                    # noqa: BLE001
        outcome = f"error:{type(e).__name__}"
        print(f"run error: {str(e)[:200]}")

    run_id = atf.make_run_id(TASK_NAME)
    env = {
        "atf_version": "1.0", "run_id": run_id, "task": TASK_NAME,
        "artefact_ref": (f"{adf['artefact_id']}@{adf['version']}" if adf else None),
        "agent": {"framework": "openai-agents", "model": MODEL},
        "store_schema": task["store_schema"], "scope": task["scope"],
        "provenance_default": "runtime_observed",
        "started_at": EVENTS[0]["observed_at"] if EVENTS else t0,
        "harness": "hanoi-v1",
        "direction": "enforced" if STEP is not None else "undirected",
        # Unenforced, the world refuses moves and the choice is still recorded.
        # Enforced, a refusal happens BEFORE the world is touched, so there is
        # no event to record — the attempt is an intervention, not a step.
        "unapplied_events_recorded": STEP is None,
        "interventions": list(VETOES),
        "runtime_findings": list(STEP.runtime_findings) if STEP is not None else [],
        "transactions": list(STEP.transactions) if STEP is not None else [],
        "attempts": list(STEP.attempts) if STEP is not None else [],
        "monitor_transitions": list(STEP.transitions) if STEP is not None else [],
        "adapter_version": task["adapter_version"],
        "prompt_variant": PROMPT_VARIANT, "disks": disks,
        "runner_outcome": outcome,
        "determinism_ok": initial == task["initial_store"],
        "wall_seconds": round(time.time() - t0, 1),
        "events": EVENTS, "operation_ledger": LEDGER,
        "env_stats": {"moves": sum(e["applied"] for e in EVENTS
                                   if e["action"] != "report"),
                      "blocked": sum(1 for e in EVENTS if not e["applied"]),
                      "attempted_operations": len(LEDGER)},
    }
    atf.write_run(env, SPANS.pop(tid.get("id"), []))

    final = EVENTS[-1]["post"] if EVENTS else initial
    solved = guards.eval_guard(task["scope"]["exit_guard"], final)
    clean = all(e["applied"] for e in EVENTS)
    print(f"[{idx:02d}] {outcome:10} moves={env['env_stats']['moves']:3} "
          f"blocked={env['env_stats']['blocked']:3} "
          f"refused={len(VETOES):2} solved={'Y' if solved else 'n'} "
          f"events={len(EVENTS):3} {env['wall_seconds']:5.1f}s  {run_id[-4:]}"
          + ("   <- SEED CANDIDATE" if solved and clean else ""))
    return env, solved, clean


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    disks = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    task = json.loads((HERE / "tasks" / f"{TASK_NAME}.task.json").read_text(encoding="utf-8"))
    adf = atf.load_adf(TASK_NAME) if ENFORCE else None
    print(f"HANOI | {disks} disks | {MODEL} | prompt={PROMPT_VARIANT} | "
          f"{'ENFORCED vs ' + adf['artefact_id'][:12] if adf else 'undirected'}",
          flush=True)
    for i in range(n):
        one_run(i, disks, task, adf)


if __name__ == "__main__":
    main()
