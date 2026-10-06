"""verify.py — exact finite-trace conformance plus diagnostics.

Primary judgement: tau |= C (rendered in the paper as tau models C). A recorded
finite execution conforms when its trace integrity checks pass and an exact walk
through the guarded process exists from the declared initial state to successful
termination with the exit guard satisfied.

The exact walk is the DEFINITION of conformance. Minimum-cost alignment runs only
after exact conformance fails and is diagnostic; edit costs therefore cannot
change the Boolean verdict. Runtime enforcement and post-hoc audit share the same
compiled process, offer function, guards, relational post/frame check, and HOLD
semantics.
"""

import time
INF = float("inf")

import heapq
import itertools

from . import guards
from .atf import validate
from .semantics import (DEFAULT_HOLD_BUDGET, finding_family)

END = ("end",)

def _hold(holds, action, hold_budget):
    """Charge one failed attempt of `action`; None once the budget is spent."""
    d = dict(holds)
    d[action] = d.get(action, 0) + 1
    if d[action] > hold_budget:
        return None
    return tuple(sorted(d.items()))


def _clear_hold(holds, action):
    """A successful occurrence ends the retry episode for this action."""
    d = dict(holds)
    d.pop(action, None)
    return tuple(sorted(d.items()))


# --------------------------------------------------------------------------- #
# literal formal trace: no behavioural hiding or quotienting                     #
# --------------------------------------------------------------------------- #
def literal_trace(trace, adf):
    """Literal formal trace consumed by conformance checking.

    The environment-specific observation adapter has already projected the world
    into the typed store before an event is written. Conformance therefore uses
    the recorded event sequence directly: no cell is hidden
    and no burst is folded, so every action the agent performed is present in
    the sequence conformance is judged over.

    This is a deliberate narrowing of the earlier definition, in which
    `alpha = name . quotient . hide . projection` removed cells asserting no
    state change. That abstraction had two costs. It made the audit check a
    different object from the one the gate enforced — the stepper drives at the
    literal level, so a run could satisfy one and not the other. And because
    hiding was decided by the cell's asserted postcondition, a contract that
    happened to derive `tau` for a step removed that step from the check
    entirely, so typing a query, clicking search, opening a product and adding
    to the cart were invisible to conformance. What the agent did must be what
    is checked.

    The legacy ADF field named ``alpha`` is retained only as an observation
    manifest for format compatibility; it is not applied as a behavioural filter
    during audit.
    """
    cs_all = adf["cell_schema"]
    return [{"seq": e["seq"], "action": e["action"],
             "type": cs_all.get(e["action"], {}).get("type", "action"),
             "reads": cs_all.get(e["action"], {}).get("reads", []),
             "pre": e["pre"], "post": e["post"],
             "applied": e.get("applied", True)}
            for e in trace["events"]]


# Backwards-compatible internal name for callers outside this package.
alpha = literal_trace


# --------------------------------------------------------------------------- #
# compile P -> nested tuples                                                  #
# --------------------------------------------------------------------------- #
class Compiled:
    def __init__(self):
        self.cells = []          # cell dicts, indexed

    def add(self, cell):
        self.cells.append(cell)
        return len(self.cells) - 1


def compile_node(node, cont, cp):
    """Compile the process term. EVERY cell is emitted.

    There is no hidden/visible distinction: the contract is the trace of all the
    agent's actions, so every cell it declares is a step that must occur and be
    checked. The previous `include_hidden` switch let audit and enforcement
    compile different terms from one contract, which is how a run could satisfy
    the gate and be rejected by the verifier.
    """
    op = node["op"]
    if op == "skip":
        return cont
    if op == "stop":
        return ("stop",)
    if op == "cell":
        idx = cp.add(node)
        if node.get("repeatable"):
            # repetition fold == recursion: mu X . ( cell -> X  []  cont )
            return ("rep", idx, cont)
        return ("cell", idx, cont)
    if op in ("seq",):
        out = cont
        for child in reversed(node["children"]):
            out = compile_node(child, out, cp)
        return out
    if op == "call":
        out = cont
        for child in reversed(node["cells"]):
            out = compile_node(child, out, cp)
        return out
    if op == "ext":
        return ("ext", tuple((b["guard"], compile_node(b["node"], cont, cp))
                             for b in node["branches"]))
    if op == "int":
        return ("int", tuple(compile_node(o, cont, cp)
                             for o in node["options"]))
    if op == "par":
        left = compile_node(node["left"], END, cp)
        right = compile_node(node["right"], END, cp)
        return ("par", tuple(node["sync"]), left, right, cont)
    if op == "rec":
        raise NotImplementedError(
            "rec nodes are verified in quotiented normal form (R5); see spec 3.5")
    raise ValueError(f"unknown op {op}")


def _norm(proc):
    if proc[0] == "par":
        _, sync, l, r, cont = proc
        if l == END and r == END:
            return _norm(cont)
    return proc


def offers(proc, sigma, cp, blind=False):
    """-> list of (cell_idx, continuation-proc).

    `blind` is the control-flow-only mode used by the state-blind baseline: an
    external choice is then treated as a NONDETERMINISTIC structural alternative
    rather than resolved by its guards, because resolving a branch by guard is
    itself a use of state.
    """
    proc = _norm(proc)
    tag = proc[0]
    if tag in ("end", "stop"):
        return []
    if tag == "cell":
        return [(proc[1], proc[2])]
    if tag == "rep":
        _, idx, cont = proc
        return [(idx, proc)] + offers(cont, sigma, cp, blind)
    if tag == "ext":
        out = []
        for guard, br in proc[1]:
            if blind or guards.eval_guard(guard, sigma):
                out.extend(offers(br, sigma, cp, blind))
        return out
    if tag == "int":
        out = []
        for o in proc[1]:
            out.extend(offers(o, sigma, cp, blind))
        return out
    if tag == "par":
        _, sync, l, r, cont = proc
        out = [(ci, _norm(("par", sync, nl, r, cont)))
               for ci, nl in offers(l, sigma, cp, blind)]
        out += [(ci, _norm(("par", sync, l, nr, cont)))
                for ci, nr in offers(r, sigma, cp, blind)]
        return out
    raise ValueError(tag)


def terminated(proc):
    p = _norm(proc)
    while isinstance(p, tuple) and p and p[0] == "rep":
        p = _norm(p[2])
    return p == END


# --------------------------------------------------------------------------- #
# min-cost alignment DFS                                                      #
# --------------------------------------------------------------------------- #
def conforms_exactly(P0, events, sigma0, cp, exit_guard, blind=False,
                    hold_budget=DEFAULT_HOLD_BUDGET):
    """The DEFINITION of conformance: does an exact walk exist?

    A run conforms iff there are residuals P_0..P_n with P_0 = P, each event
    related by one of two transitions, and P_n is terminal with the exit guard
    satisfied:

      ADVANCE  (P,sigma) -c,sigma'-> (P',sigma')  c offered, guard(c) holds on
               sigma, and c's asserted post holds on sigma'
      HOLD     (P,sigma) -c,sigma'-> (P, sigma')  c offered, guard(c) holds on
               sigma, and c's asserted post does NOT hold on sigma'

    HOLD is R12, retry-as-transition, and it is the rule the STEPPER already
    applies at runtime: an action that executed and achieved nothing has not
    moved the process, so the agent may attempt it again. Without it here the
    verifier rejected runs the gate had just certified — the two engines were
    deciding different objects, which is the defect that removing hiding was
    meant to end. It is not a relaxation of the postcondition: the process only
    advances when the asserted effect is observed, the exit guard must still be
    established, and a HOLD is charged against a budget, so a cell cannot fail
    for ever. A FRAME violation is never a HOLD — an unaccounted-for effect is a
    fault regardless of how often it occurs.

    Conformance must not be defined as "the minimum-cost alignment costs zero":
    that makes the specification depend on the edit costs, so changing a cost
    constant would change what conforms. Alignment is a diagnostic applied to
    runs that have already failed this test.
    """
    n = len(events)
    seen = set()
    stack = [(P0, 0, ())]
    while stack:
        proc, i, holds = stack.pop()
        if (proc, i, holds) in seen:
            continue
        seen.add((proc, i, holds))
        sigma = events[i - 1]["post"] if i > 0 else sigma0
        if i == n:
            if terminated(proc) and (blind or guards.eval_guard(exit_guard, sigma)):
                return True
            continue
        e = events[i]
        for ci, cont in offers(proc, sigma, cp, blind):
            cell = cp.cells[ci]
            if cell["action"] != e["action"]:
                continue
            if blind:
                stack.append((cont, i + 1, holds))
                continue
            if not guards.eval_guard(cell["pre"], e["pre"]):
                continue
            asserted, frame = guards.check_post_split(
                cell["post"], e["pre"], e["post"], cell.get("unconstrained", ()))
            if frame:
                continue
            # An operation the environment did not apply cannot advance the
            # process, even when the cell has no explicit assignments (`tau`).
            # It is a HOLD if its frame is intact.
            if (not e.get("applied", True)) or asserted:
                nh = _hold(holds, e["action"], hold_budget)
                if nh is not None:
                    stack.append((proc, i + 1, nh))
            else:
                stack.append((cont, i + 1, _clear_hold(holds, e["action"])))
    return False


def align(P0, events, sigma0, cp, exit_guard, blind=False,
          hold_budget=DEFAULT_HOLD_BUDGET):
    """Minimum-cost alignment, as a shortest-path search.

    States are (residual process, event index); edges are the three moves —
    match, insert, delete — each with a non-negative cost. Dijkstra settles the
    cheapest state first and never revisits a settled one, so the search
    terminates without a depth cut-off and returns a provably minimum-cost
    alignment. The previous formulation was a depth-first search bounded at 200
    levels, which rejected valid runs longer than the bound and could reuse a
    value cached after an early cut-off. Ties are broken on a deterministic key
    so that two equally cheap explanations always yield the same findings.
    """
    n = len(events)

    def sigma_at(i):
        return events[i - 1]["post"] if i > 0 else sigma0

    start = (P0, 0, ())
    dist = {start: 0}
    prev = {}                      # state -> (parent, findings contributed)
    pq = [(0, 0, start)]
    seq = itertools.count(1)
    goal = None

    while pq:
        d, _, st = heapq.heappop(pq)
        if d > dist.get(st, INF):
            continue
        proc, i, holds = st
        sigma = sigma_at(i)

        if i == n:
            if terminated(proc) and (blind or guards.eval_guard(exit_guard, sigma)):
                goal = st
                break

        def relax(nst, w, findings):
            nd = d + w
            if nd < dist.get(nst, INF):
                dist[nst] = nd
                prev[nst] = (st, findings)
                heapq.heappush(pq, (nd, next(seq), nst))

        offs = offers(proc, sigma, cp, blind)

        if i == n:
            # only deletions remain; termination is handled on pop
            for ci, cont in offs:
                relax((cont, i, holds), 1,
                      [_mis(-1, "STRUCTURAL",
                            f"cell '{cp.cells[ci]['action']}' required by artefact",
                            "run ended before it occurred")])
            continue

        e = events[i]
        for ci, cont in offs:                                   # match
            cell = cp.cells[ci]
            if cell["action"] != e["action"]:
                continue
            if blind:
                # control-flow only: no precondition, postcondition or frame check
                relax((cont, i + 1, holds), 0, [])
                continue
            pre_mis = []
            if not guards.eval_guard(cell["pre"], e["pre"]):
                pre_mis.append(_mis(e["seq"], "GUARD_PRE",
                                    f"<{cell['pre']}> before '{e['action']}'",
                                    _render_store(e["pre"], cell["pre"])))
            asserted, frame = guards.check_post_split(
                cell["post"], e["pre"], e["post"], cell.get("unconstrained", ()))
            frame_mis = [_mis(e["seq"], "GUARD_POST",
                              f"'{e['action']}' leaves {f} {exp}", f"{f}={got}")
                         for f, exp, got in frame]

            if ((not e.get("applied", True)) or asserted) and not frame:
                # R12: the action was not applied or its asserted effect was not
                # observed, so the process has not moved; same reading as gate.
                nh = _hold(holds, e["action"], hold_budget)
                if nh is not None:
                    relax((proc, i + 1, nh), len(pre_mis), pre_mis)
                else:
                    relax((proc, i + 1, holds), len(pre_mis) + 1, pre_mis + [
                        _mis(e["seq"], "GUARD_POST",
                             f"'{e['action']}' establishes its effect within "
                             f"{hold_budget} attempts",
                             f"attempt {dict(holds).get(e['action'], 0) + 1} still "
                             f"had no effect")])
                continue

            mis = pre_mis + frame_mis + [
                _mis(e["seq"], "GUARD_POST",
                     f"'{e['action']}' asserts {f}:={exp}", f"{f}={got}")
                for f, exp, got in asserted]
            relax((cont, i + 1, _clear_hold(holds, e["action"])), len(mis), mis)

        offered = ", ".join(sorted({cp.cells[ci]["action"] for ci, _ in offs})) or "(none)"
        relax((proc, i + 1, holds), 1,                           # insert
              [_mis(e["seq"], "STRUCTURAL", f"one of: {offered}",
                    f"'{e['action']}' occurred (not offered here)")])

        for ci, cont in offs:                                    # delete
            relax((cont, i, holds), 1,
                  [_mis(e["seq"], "STRUCTURAL",
                        f"cell '{cp.cells[ci]['action']}' required by artefact",
                        f"'{e['action']}' occurred instead / cell missing")])

    if goal is None:
        # No admitted path reaches termination: report the cheapest incompleteness.
        detail = "process not at SKIP"
        best = min((s for s in dist if s[1] == n), key=lambda s: dist[s], default=None)
        if best is not None:
            p = _norm(best[0])
            if p == ("stop",):
                detail = "process at STOP (artefact-permitted partial halt)"
            elif terminated(best[0]):
                detail = "exit guard unsatisfied"
        base, chain = (dist.get(best, 0), best) if best is not None else (0, None)
        out = []
        while chain is not None and chain in prev:
            chain, f = prev[chain]
            out = f + out
        return base + 1, out + [_mis(-1, "COMPLETENESS",
                                     f"termination with exit guard '{exit_guard}'",
                                     detail)]

    out, chain = [], goal
    while chain in prev:
        chain, f = prev[chain]
        out = f + out
    return dist[goal], out


def _mis(seq, cls, expected, observed, detail=""):
    m = {"seq": int(seq), "class": cls, "family": finding_family(cls),
         "expected": expected, "observed": observed}
    if detail:
        m["detail"] = detail
    return m


def _render_store(store, guard):
    fields = guards.guard_fields(guard)
    return " /\\ ".join(f"{f}={guards.render_value(store.get(f))}" for f in sorted(fields))


# --------------------------------------------------------------------------- #
# entry point                                                                 #
# --------------------------------------------------------------------------- #
def check(trace, adf, state_blind=False):
    misal = []
    # SCHEMA pass: typing of every event against the artefact's store schema
    # (skipped in state_blind mode: control-flow-only baseline for step-6 comparison)
    if not state_blind:
        for e in trace["events"]:
            for which in ("pre", "post"):
                errs = guards.typecheck(adf["store_schema"], e[which],
                                        f"event {e['seq']} {which}")
                for err in errs:
                    misal.append(_mis(e["seq"], "SCHEMA", "store typing per schema", err))

    # STATE-CHAIN INTEGRITY. A trace is sigma_0 -a1-> sigma_1 -a2-> ... , so the
    # first event's pre must be the declared initial state and each event's post
    # must be the next event's pre. Without this a trace can claim states that
    # never followed one another and still conform — the events would not
    # describe a single history.
    evs_raw = trace["events"]
    if not state_blind and evs_raw:
        init = adf["alpha"]["initial_store"]
        if evs_raw[0]["pre"] != init:
            misal.append(_mis(evs_raw[0]["seq"], "CONTINUITY",
                              f"first pre-state equals the declared initial state",
                              f"differs in {sorted(k for k in set(init) | set(evs_raw[0]['pre']) if init.get(k) != evs_raw[0]['pre'].get(k))}"))
        for a, b in zip(evs_raw, evs_raw[1:]):
            if a["post"] != b["pre"]:
                misal.append(_mis(b["seq"], "CONTINUITY",
                                  "pre-state equals the previous post-state",
                                  f"differs in {sorted(k for k in set(a['post']) | set(b['pre']) if a['post'].get(k) != b['pre'].get(k))}"))

    # LEDGER / EVENT CORRESPONDENCE. The physical history and the audited event
    # sequence must be the same history. Checking only that no unclassified
    # operation executed still allowed an executed CLASSIFIED operation to be
    # missing from the trace, which would make strict conformance meaningless.
    led = trace.get("operation_ledger")
    if not state_blind and led:
        # Which ledger operations SHOULD have produced events depends on the
        # harness's recording policy, and the two harnesses differ on purpose.
        # The browser harness records only operations that executed: a call that
        # raised did not happen, and recording it would invent a step. The Hanoi
        # harness records every action the agent chose, applied or not, because
        # the environment refuses moves BY DESIGN and a refusal is the
        # interesting datum. A trace declares its policy rather than the
        # verifier guessing, so this check tests correspondence rather than
        # imposing one harness's convention on the other.
        keep_all = bool(trace.get("unapplied_events_recorded"))
        # Compare like with like: only operations that CLASSIFY to a declared
        # cell. An operation outside the vocabulary has no cell to put in the
        # ledger, while the harness must still name its event something, so the
        # two lists could never align on it. Such events are not thereby
        # excused — they are unoffered, and STRUCTURAL reports them.
        declared = set(adf.get("cell_schema") or ())
        executed = [o.get("cell") for o in led
                    if o.get("cell") and (keep_all or o.get("executed"))]
        recorded = [e["action"] for e in evs_raw if e["action"] in declared]
        if executed != recorded:
            misal.append(_mis(-1, "LEDGER_MISMATCH",
                              f"executed classified operations equal recorded events "
                              f"({len(executed)})",
                              f"recorded {len(recorded)}: {recorded[:8]} vs "
                              f"executed {executed[:8]}"))

    # An operation that EXECUTED without classifying is a real effect on the
    # world that the contract never saw. A run containing one cannot be called
    # conforming: the verifier would be certifying a history that is not the
    # one performed. Reported as its own class so it is never confused with a
    # process deviation.
    for o in trace.get("operation_ledger", []) or []:
        if o.get("executed") and not o.get("cell"):
            misal.append(_mis(o.get("operation_seq", -1), "UNMEDIATED",
                              "every executed operation classifies to a cell",
                              f"'{o.get('kind')}' executed unclassified"))

    evs = literal_trace(trace, adf)
    cp = Compiled()
    # The verifier compiles the SAME term the stepper drives: every cell,
    # hidden or not. Audit and enforcement then judge one object.
    P = compile_node(adf["P"], END, cp)
    sigma0 = adf["alpha"]["initial_store"]  # legacy ADF location; not abstraction
    hold_budget = int(adf.get("semantics", {}).get("hold_budget",
                                                   DEFAULT_HOLD_BUDGET))
    # Conformance is decided by the exact relation; alignment runs only to
    # localise a failure, so edit costs cannot change the verdict.
    if conforms_exactly(P, evs, sigma0, cp, adf["scope"]["exit_guard"],
                        blind=state_blind, hold_budget=hold_budget):
        cost, mis = 0, []
    else:
        cost, mis = align(P, evs, sigma0, cp, adf["scope"]["exit_guard"],
                          blind=state_blind, hold_budget=hold_budget)
        if not mis:
            mis = [_mis(-1, "STRUCTURAL", "an exact walk through the process",
                        "no exact walk exists; alignment found no localised cause")]
    misal += mis

    final = evs[-1]["post"] if evs else sigma0
    # In state-blind mode the exit STATE is not consulted either: the baseline
    # is control-flow conformance, so completeness is structural termination.
    full = True if state_blind else guards.eval_guard(adf["scope"]["exit_guard"], final)
    completeness = {"result": "full" if full else "partial"}
    if not full:
        rep = next((e for e in reversed(trace["events"]) if e["type"] == "report"), None)
        completeness["reason"] = (rep or {}).get("args", {}).get("reason", "exit_guard_unsatisfied")

    integrity_ok = not any(m.get("family") == "TRACE_INTEGRITY" for m in misal)
    process_ok = not any(m.get("family") == "PROCESS_CONFORMANCE" for m in misal)

    acr = {
        "acr_version": "1.0",
        "run_id": trace["run_id"],
        "artefact_id": adf["artefact_id"],
        "artefact_version": adf["version"],
        "verdict": "conforms" if not misal else "violations",
        "trace_integrity": "pass" if integrity_ok else "fail",
        "process_conformance": "pass" if process_ok else "fail",
        "misalignments": misal,
        "completeness": completeness,
        "checked_at": time.time(),
    }
    errs = validate("acr", acr)
    if errs:
        raise ValueError("ACR validation failed:\n" + "\n".join(errs))
    return acr
