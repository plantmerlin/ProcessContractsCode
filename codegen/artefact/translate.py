"""translate.py — the v1.0 mechanical translator (ARTEFACT_SPEC R1–R10).

Input:  task definition (M0), ATF trace envelope, optional span lines (surface S).
Output: schema-valid ADF artefact package.

Mechanical pipeline: R1 cells -> R8 grouping (span pairing; declared fallback)
-> R5 quotient -> P assembly with declared R6/R7 choice structure (taken
branch/option determined by evaluating guards against the observed state) ->
artefact_id hash -> schema validation.

There is no hiding stage. The contract is the trace of every action the agent
performed, each with the state observed before and after it, and that is the
surface both the verifier and the stepper work on.
"""

from . import atf, guards
from .atf import artefact_id, validate
from .semantics import SEMANTICS_VERSION, DEFAULT_HOLD_BUDGET


# --------------------------------------------------------------------------- #
# R1 + R2: events -> guarded cells                                            #
# --------------------------------------------------------------------------- #
def build_cells(trace, task):
    order = list(task["store_schema"].keys())
    cs_all = task["cell_schema"]
    # R11 (exit-guard closure): a cell that terminates the scope must read every
    # field the scope's exit guard mentions. Without this the gate can permit a
    # terminating step in a state the exit guard will reject, and a run that the
    # runtime allowed to finish is then reported incomplete. Derived, not declared.
    exit_fields = [f for f in order
                   if f in guards.guard_fields(task["scope"]["exit_guard"])]
    cells = []
    for e in trace["events"]:
        cs = cs_all.get(e["action"])
        if cs is None:
            raise ValueError(f"event {e['seq']}: action '{e['action']}' not in cell schema")
        reads = list(cs["reads"])
        if cs["type"] == "report":
            reads += [f for f in exit_fields if f not in reads]
        delta = [f for f in order if e["pre"][f] != e["post"][f]]
        pre = cs.get("pre_override") or guards.render_pre(reads, e["pre"], order)
        # post_unconstrained (M0-declared): ranged/free fields are RELEASED from the
        # literal post assertion — they are bound by guards at their consumer cells
        pu = cs.get("post_unconstrained", [])
        post = guards.render_post([f for f in delta if f not in pu], e["post"], order)
        cell = {
            "op": "cell", "action": e["action"], "type": cs["type"],
            "layer": cs["layer"], "reads": reads, "pre": pre, "post": post,
            "group": cs["group"], "seq": e["seq"],
            "sigma_post": e["post"],
            "pre_overridden": "pre_override" in cs,
        }
        if pu:
            cell["unconstrained"] = list(pu)
        # R12 (retry on unmet effect). A cell that asserts an effect can fail to
        # achieve it, and the agent must then be free to try again by another
        # means. This is NOT expressed as repetition in the process term.
        #
        # An earlier version compiled such cells to mu X . (cell -> X [] cont),
        # but `offers` on that node yields the cell AND the continuation, which
        # is zero-or-more rather than "retry until one success" — it made the
        # cell skippable and so weakened the ordering it was meant to preserve.
        #
        # Retry is instead a property of the TRANSITION, not of the term: the
        # stepper holds when the asserted effect is unmet but the frame remains
        # intact, leaving the residual process unchanged. The executed attempt
        # stays in the literal trace and the post-hoc verifier consumes it with
        # the same HOLD rule. An attempt is evidence and is never hidden.
        cells.append(cell)
    return cells


# --------------------------------------------------------------------------- #
# R8: grouping by span pairing (fallback: declared groups)                    #
# --------------------------------------------------------------------------- #
def pair_groups(cells, trace, spans):
    """If surface S has function spans, group by enclosing-span interval (D10);
    else keep the task-declared groups (fallback, recorded in alpha)."""
    fn_spans = []
    starts = {s["span_id"]: s["observed_at"] for s in spans
              if s.get("kind") == "span_start" and s.get("span_type") == "function"}
    for s in spans:
        if s.get("kind") == "span_end" and s.get("span_type") == "function":
            fn_spans.append({"span_id": s["span_id"], "name": s["payload"]["name"],
                             "t0": starts.get(s["span_id"], 0), "t1": s["observed_at"]})
    if not fn_spans:
        return "declared-groups(no surface S)"
    by_seq = {e["seq"]: e for e in trace["events"]}
    for c in cells:
        ev = by_seq[c["seq"]]
        ref, t = ev.get("span_ref"), ev.get("observed_at")
        hit = next((f for f in fn_spans if f["span_id"] == ref), None) or \
              next((f for f in fn_spans if f["t0"] <= t <= f["t1"]), None)
        if hit:
            c["paired_span"] = hit["span_id"]
    return "span-pairing"


# --------------------------------------------------------------------------- #
# R5: quotient — fold same-action bursts (all-but-last silent)                #
# --------------------------------------------------------------------------- #
QUOTIENT_ENABLED = False


def quotient(cells, order):
    """R5 fold — DISABLED.

    The fold collapses a burst of one repeated action into a single cell in the
    TERM while alpha, now literal, keeps every observed event. A seed containing
    a burst therefore induces a contract that rejects that very seed: three
    `poll` events against one `await_ready` cell, a name the classifier can
    never produce. It cannot fire without breaking the contract it produces.

    It is retained as code because an explicit guarded repetition operator is
    the intended replacement, but a seed that would activate it is now REJECTED
    at induction rather than silently turned into a self-rejecting contract.
    """
    if not QUOTIENT_ENABLED:
        i = 0
        while i < len(cells):
            j = i
            while (j + 1 < len(cells) and cells[j + 1]["action"] == cells[i]["action"]
                   and cells[j]["post"] == "tau"):
                j += 1
            if j > i:
                raise ValueError(
                    f"R5 quotient is disabled: the seed repeats "
                    f"'{cells[i]['action']}' {j - i + 1} times consecutively. "
                    "Folding it would produce a contract that rejects this seed; "
                    "re-seed, or add an explicit repetition operator.")
            i = j + 1
        return list(cells), []

    out, folds, i = [], [], 0
    while i < len(cells):
        j = i
        # A burst is consecutive occurrences of one action where all but the
        # last assert no change. Only the TERM is folded; the observed run is
        # never filtered, so conformance still sees every action the agent took.
        while (j + 1 < len(cells) and cells[j + 1]["action"] == cells[i]["action"]
               and cells[j]["post"] == "tau"):
            j += 1
        run = cells[i:j + 1]
        if len(run) >= 2 and all(c["post"] == "tau" for c in run[:-1]):
            last = run[-1]
            changed = list(guards.parse_post(last["post"]).keys())
            # R5 proper (polling/control loop) -> await_<field>; a repetition of
            # the SAME action cell (e.g. typing many form fields) keeps its name
            # and records the count, so the term stays readable and actionable.
            if last["type"] in ("check", "control"):
                await_field = next((f for f in changed if f in last["reads"]),
                                   changed[0] if changed else "state")
                new_name, new_type = f"await_{await_field}", "control"
            else:
                new_name, new_type = last["action"], last["type"]
            folded = dict(last)
            folded.update({"action": new_name, "type": new_type,
                           "pre": run[0]["pre"], "post": last["post"],
                           "count": len(run), "folded_from": last["action"]})
            out.append(folded)
            folds.append({"folded_action": folded["action"],
                          "source_action": last["action"], "count": len(run)})
        else:
            out.extend(run)
        i = j + 1
    return out, folds


# --------------------------------------------------------------------------- #
# P assembly (seq / call / ext / int / par / stop / skip)                     #
# --------------------------------------------------------------------------- #
def _cell_node(c):
    node = {k: c[k] for k in ("op", "action", "type", "reads", "pre", "post")}
    for k in ("unconstrained", "count", "folded_from", "provenance", "repeatable"):
        if k in c:
            node[k] = c[k]
    return node


def _decl_cell(d):
    return {"op": "cell", "action": d["action"], "type": d["type"],
            "reads": d.get("reads", []), "pre": d["pre"], "post": d["post"],
            "provenance": d.get("provenance", "declared")}


def _embed_ext(group_cells, decl, ext_record):
    """Split group at the anchor, release the choice field on the anchor (R6),
    build ext node with declared + observed branches; return node list."""
    idx = next(i for i, c in enumerate(group_cells) if c["action"] == decl["after"])
    anchor, tail = group_cells[idx], group_cells[idx + 1:]
    field = decl["field"]
    asg = guards.parse_post(anchor["post"])
    asg.pop(field, None)
    anchor["post"] = (" /\\ ".join(f"{f}:={guards.render_value(v)}" for f, v in asg.items())
                      or "tau")
    anchor["unconstrained"] = [field]
    sigma = anchor["sigma_post"]
    tail_nodes = [_cell_node(c) for c in tail]
    branches = []
    for b in decl["branches"]:
        taken = guards.eval_guard(b["guard"], sigma)
        children = [_decl_cell(d) for d in b.get("cells", [])]
        if b.get("use_observed_continuation") or b.get("then_observed_continuation"):
            children += tail_nodes
        if b.get("stop"):
            children.append({"op": "stop"})
        branches.append({"guard": b["guard"],
                         "node": {"op": "seq", "children": children}})
        if taken:
            ext_record["taken"] = b["guard"]
    nodes = [_cell_node(c) for c in group_cells[:idx]] + [_cell_node(anchor)]
    nodes.append({"op": "ext", "branches": branches})
    return nodes


def _embed_int(group_cells, decl, int_record):
    """R7: internal choice — observed option + declared alternatives."""
    observed = [_cell_node(c) for c in group_cells]
    options = [{"op": "seq", "children": observed}]
    int_record["chosen"] = " -> ".join(c["action"] for c in group_cells)
    alts = []
    for opt in decl["options"]:
        if opt.get("observed"):
            continue
        children = [_decl_cell(d) for d in opt.get("cells", [])]
        for act in opt.get("then_actions", []):
            src = next(c for c in group_cells if c["action"] == act)
            children.append(_cell_node(src))
        options.append({"op": "seq", "children": children})
        alts.append(" -> ".join(ch["action"] for ch in children))
    int_record["alternatives"] = alts
    return [{"op": "int", "options": options}]


def build_P(cells, task, ext_records, int_records):
    # partition cells by group, keep first-occurrence order
    group_order, by_group = [], {}
    for c in cells:
        if c["group"] not in by_group:
            by_group[c["group"]] = []
            group_order.append(c["group"])
        by_group[c["group"]].append(c)

    ext_by_group = {d["group"]: d for d in task.get("external_choices", [])}
    int_by_group = {d["group"]: d for d in task.get("internal_choices", [])}

    def call_node(g):
        gcells = by_group[g]
        if g in ext_by_group:
            rec = {"at": g, "field": ext_by_group[g]["field"], "taken": None,
                   "branches": ext_by_group[g]["branches"]}
            ext_records.append(rec)
            children = _embed_ext(gcells, ext_by_group[g], rec)
        elif g in int_by_group:
            rec = {"at": g, "chosen": None, "alternatives": []}
            int_records.append(rec)
            children = _embed_int(gcells, int_by_group[g], rec)
        else:
            children = [_cell_node(c) for c in gcells]
        return {"op": "call", "name": g, "cells": children}

    par = task.get("parallel")
    children, done = [], set()
    for g in group_order:
        if g in done:
            continue
        if par and g in par["groups"]:
            pgs = [x for x in par["groups"]]
            done.update(pgs)
            node = call_node(pgs[-1])
            for x in reversed(pgs[:-1]):
                node = {"op": "par", "sync": par["sync"],
                        "left": call_node(x), "right": node}
            children.append(node)
        else:
            done.add(g)
            children.append(call_node(g))
    children.append({"op": "skip"})
    return {"op": "seq", "children": children}


# --------------------------------------------------------------------------- #
# entry point                                                                 #
# --------------------------------------------------------------------------- #
def translate(task, trace, spans=None, version="1.0.0"):
    order = list(task["store_schema"].keys())

    # The adapter version is part of task-model identity: changing HOW a field
    # is derived changes what the contract means even when the declared schema
    # is untouched. It must therefore be the adapter that actually produced the
    # seed run, not a string in the task file that a change to the harness can
    # silently outdate. Where the task also declares one, disagreement is an
    # error rather than a preference.
    adapter = trace.get("adapter_version") or task.get("adapter_version")
    declared = task.get("adapter_version")
    if trace.get("adapter_version") and declared and declared != trace["adapter_version"]:
        raise ValueError(
            f"adapter mismatch: the task declares {declared!r} but the seed run "
            f"was produced by {trace['adapter_version']!r}. Identity would record "
            f"an observation model that did not observe this run.")

    # R9 mechanical: every declared guard must be inside the band
    band_errs = []
    for a, cs in task["cell_schema"].items():
        if "pre_override" in cs:
            band_errs += [f"{a}: {e}" for e in guards.band_check(cs["pre_override"], task["store_schema"])]
        for f in cs["reads"]:
            if f not in task["store_schema"]:
                band_errs.append(f"{a}: reads undeclared field '{f}'")
    band_errs += guards.band_check(task["scope"]["exit_guard"], task["store_schema"])
    # R9 also requires that external choice be resolved UNIQUELY by the state.
    # `offers` unions the transitions of every branch whose guard holds, so
    # overlapping guards make the choice nondeterministic; enforce disjointness
    # statically rather than document it as an assumption.
    for ec in task.get("external_choices", []):
        gs = [b["guard"] for b in ec["branches"]]
        for e in guards.branches_disjoint(gs, task["store_schema"]):
            band_errs.append(f"external choice at '{ec['group']}': {e}")
        for g in gs:
            band_errs += [f"external choice at '{ec['group']}': {e}"
                          for e in guards.band_check(g, task["store_schema"])]
    if band_errs:
        raise ValueError("R9 determinism-band violations:\n" + "\n".join(band_errs))

    # P1 store invariants: relationships the projection must satisfy at EVERY
    # observation. They are properties of the observation model, not of the
    # process, so a violation means the instrument is unsound and no contract
    # induced from it can be trusted.
    inv_errs = []
    for ev in trace["events"]:
        for which in ("pre", "post"):
            st = ev[which]
            for inv in task.get("store_invariants", []):
                if (guards.eval_guard(inv["guard"], st)
                        and not guards.eval_guard(inv["implies"], st)):
                    inv_errs.append(
                        f"event {ev['seq']} {which}: <{inv['guard']}> holds but "
                        f"<{inv['implies']}> does not ({inv.get('why', '')})")
    if inv_errs:
        raise ValueError("store invariant violated by the seed: "
                         + "; ".join(sorted(set(inv_errs))[:6]))

    cells = build_cells(trace, task)
    naming = pair_groups(cells, trace, spans or [])
    cells, folds = quotient(cells, order)

    ext_records, int_records = [], []
    P = build_P(cells, task, ext_records, int_records)

    # R13 (exit-guard establishment): every field the scope's exit guard names
    # must be ESTABLISHED by some cell's postcondition. A contract that demands
    # an outcome while containing no step that produces it has not captured how
    # the goal is achieved — the seed failed to observe the effect, typically
    # because it landed after the transaction that caused it.
    #
    # None of the other gates can catch this. Seed self-acceptance in particular
    # cannot: a cell asserting `tau` is satisfied by a run in which nothing
    # happened, so a vacuous contract replays its own seed cleanly.
    needed = set(guards.guard_fields(task["scope"]["exit_guard"]))
    established = set()

    def _collect(n):
        if not isinstance(n, dict):
            return
        if n.get("op") == "cell":
            established.update(guards.parse_post(n["post"]).keys())
        for k in ("children", "cells", "options"):
            for c in n.get(k, []) or []:
                _collect(c)
        for b in n.get("branches", []) or []:
            _collect(b.get("node", b))
        for k in ("left", "right"):
            if n.get(k):
                _collect(n[k])

    _collect(P)
    unestablished = sorted(needed - established)
    if unestablished:
        raise ValueError(
            "R13 exit-guard establishment failed: the exit guard "
            f"'{task['scope']['exit_guard']}' depends on {unestablished}, but no "
            f"cell asserts {'it' if len(unestablished) == 1 else 'them'}. The seed "
            "did not observe the effect that establishes "
            f"{unestablished[0]}; re-seed rather than use this contract.")

    adf_cell_schema = {}
    exit_fields = [f for f in order
                   if f in guards.guard_fields(task["scope"]["exit_guard"])]
    for a, cs in task["cell_schema"].items():
        reads = list(cs["reads"])
        if cs["type"] == "report":
            reads += [f for f in exit_fields if f not in reads]
        entry = {"type": cs["type"], "layer": cs["layer"],
                 "reads": reads, "group": cs["group"]}
        if cs.get("post_unconstrained"):
            # the verifier must apply the SAME release when computing deltas,
            # or hiding and quotient-naming diverge between the two engines
            entry["post_unconstrained"] = list(cs["post_unconstrained"])
        adf_cell_schema[a] = entry
    adf = {
        "adf_version": "1.0",
        "artefact_id": artefact_id(task["store_schema"], adf_cell_schema,
                                   task["scope"],
                                   task_params=task.get("target"),
                                   adapter_version=adapter),
        "task_params": task.get("target"),
        "adapter_version": adapter,
        "name": task["task"],
        "version": version,
        "created_from_run": trace["run_id"],
        "store_schema": task["store_schema"],
        "cell_schema": adf_cell_schema,
        "scope": task["scope"],
        # Legacy field name retained for ADF v1 compatibility. This is now an
        # OBSERVATION MANIFEST, not a behavioural trace abstraction: verification
        # consumes the literal recorded event sequence.
        "alpha": {"projection_fields": order,
                  "quotient": folds, "naming_actual": naming,
                  "initial_store": task["initial_store"]},
        "semantics": {"version": SEMANTICS_VERSION,
                      "hold_budget": DEFAULT_HOLD_BUDGET},
        "P": P,
        "external_choices": ext_records,
        "internal_choices": int_records,
        "signoff": {"status": "draft"},
        "provenance": trace.get("provenance_default", "sandbox_observed"),
        "translator_version": atf.TRANSLATOR_VERSION,
    }
    # artefact_id is a schema identity and is stable across changes to P; the
    # content hash is what witnesses that a contract admits the same runs.
    adf["content_hash"] = atf.content_hash(adf)
    # B2: a signed artefact may only contain terms the runtime can execute.
    # A richer serialized language than the engines implement lets unsupported
    # `par`, `rec` or repetition enter a scientific artefact.
    SUPPORTED = {"seq", "cell", "call", "ext", "int", "skip", "stop"}

    def _grammar_errs(n, out):
        if not isinstance(n, dict):
            return out
        op = n.get("op")
        if op not in SUPPORTED:
            out.append(f"unsupported operator '{op}' in P: the executable "
                       f"fragment is {sorted(SUPPORTED)}")
        if n.get("repeatable"):
            out.append(f"cell '{n.get('action')}' is marked repeatable; "
                       "retry is a transition property, not a term construct")
        for k in ("children", "cells", "options"):
            for c in n.get(k, []) or []:
                _grammar_errs(c, out)
        for b in n.get("branches", []) or []:
            _grammar_errs(b.get("node", b), out)
        for k in ("left", "right"):
            if n.get(k):
                _grammar_errs(n[k], out)
        return out

    gerrs = _grammar_errs(P, [])
    if gerrs:
        raise ValueError("unsupported grammar in signed artefact: "
                         + "; ".join(sorted(set(gerrs))))

    errs = validate("adf", adf)
    if errs:
        raise ValueError("ADF validation failed:\n" + "\n".join(errs))
    return adf
