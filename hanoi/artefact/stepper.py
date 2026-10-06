"""stepper.py — the pre-guide / runtime-enforcement engine (ARTEFACT_SPEC M5 drive mode).

From (P, sigma) it computes the OFFER-SET of permitted next cells (ext resolved
by guards against the live store, int left to the agent) and gates every
attempted action: off-offer actions and guard-failing attempts are VETOED and
recorded as interventions; permitted actions execute and advance only when the
postcondition is observed. Drives at the LITERAL level: every declared cell
is a step that must occur, so every discrete operation is gated.
"""

import time
from . import guards
from .verify import Compiled, compile_node, offers, terminated, END
from .semantics import DEFAULT_HOLD_BUDGET


class Stepper:
    def __init__(self, adf, observe, permeable_layers=(), hold_budget=None):
        self.adf = adf
        self.observe = observe                  # read-only projector (D2)
        self.cp = Compiled()
        # DETERMINISATION. The residual process is a SET of candidates, not one.
        # Where two options of an internal choice share a prefix action, a single
        # residual would have to commit at the shared prefix and could then be
        # stranded, while the offline verifier — which searches and backtracks —
        # accepts the run. Carrying every candidate consistent with what has been
        # observed keeps the gate as expressive as the search, so the two engines
        # decide the same language rather than merely sharing code.
        self.procs = [compile_node(adf["P"], END, self.cp)]
        self.interventions = []   # proposals refused BEFORE execution
        self.runtime_findings = [] # faults discovered after an operation executed
        self.log = []
        # Consecutive HOLDs per action. A successful occurrence clears the count,
        # so the budget applies to one retry episode rather than accumulating
        # across later occurrences of the same action.
        self.holds = {}
        contract_budget = int(adf.get("semantics", {}).get("hold_budget",
                                                           DEFAULT_HOLD_BUDGET))
        if hold_budget is not None and int(hold_budget) != contract_budget:
            raise ValueError(
                f"runtime hold_budget={hold_budget} disagrees with contract "
                f"hold_budget={contract_budget}; runtime and audit must share semantics")
        self.hold_budget = contract_budget
        self.transactions = []
        self.attempts = []          # executed, did not advance the residual
        self.transitions = []       # advanced the residual
        self._permits = []
        # Cells the AGENT cannot perform directly (e.g. API-layer cells, which
        # are server-side consequences of a UI action). They advance when
        # observed, but must not BLOCK an otherwise-permitted agent action —
        # otherwise the process deadlocks on traffic the agent cannot emit.
        self.permeable = set(permeable_layers)

    def _typecheck_state(self, sigma, where):
        """Closed-world check on the observation boundary.

        The JSON schema alone will accept a state carrying an undeclared field,
        so the runtime must reject one before it is used: a projection the
        contract does not speak about cannot be reasoned over, and silently
        ignoring it would let the world differ from the model in a way no guard
        could see.
        """
        declared = set(self.adf["store_schema"])
        extra = sorted(set(sigma) - declared)
        missing = sorted(declared - set(sigma))
        errs = guards.typecheck(self.adf["store_schema"], sigma, where)
        if extra:
            errs.append(f"{where}: undeclared field(s) {extra}")
        if missing:
            errs.append(f"{where}: missing declared field(s) {missing}")
        return errs

    def _layer(self, action):
        return self.adf["cell_schema"].get(action, {}).get("layer", "UI")

    def _offers(self, sigma, max_skip=4, _procs=None):
        """Offers over EVERY candidate residual, plus those reachable by
        skipping over permeable cells. Returns (cell_idx, continuation, skipped)."""
        seen, out = set(), []
        frontier = [(p, ()) for p in (self.procs if _procs is None else _procs)]
        for _ in range(max_skip + 1):
            nxt = []
            for proc, skipped in frontier:
                for ci, cont in offers(proc, sigma, self.cp):
                    action = self.cp.cells[ci]["action"]
                    key = (action, len(skipped), id(cont))
                    if key not in seen:
                        seen.add(key)
                        out.append((ci, cont, skipped))
                    if self._layer(action) in self.permeable:
                        nxt.append((cont, skipped + (action,)))
            if not nxt:
                break
            frontier = nxt
        return out

    def reachable(self, action):
        """Can `action` still occur on SOME continuation of the residual
        process? Branch guards are ignored deliberately: a branch not enabled
        in the current state may become enabled once the state changes, so
        reachability is structural rather than state-dependent.

        Used to tell a refused agent 'not yet' rather than 'not ever'. An
        ordering refusal that carries no such distinction reads as a ban on the
        gesture, and the agent abandons an action it should merely defer.
        """
        seen, stack = set(), list(self.procs)
        while stack:
            p = stack.pop()
            if not isinstance(p, tuple) or p in seen:
                continue
            seen.add(p)
            tag = p[0]
            if tag in ("cell", "rep"):
                if self.cp.cells[p[1]]["action"] == action:
                    return True
                stack.append(p[2])
            elif tag == "ext":
                stack.extend(br for _g, br in p[1])
            elif tag == "int":
                stack.extend(p[1])
            elif tag == "par":
                stack.extend((p[2], p[3], p[4]))
        return False

    def offer_set(self):
        """Actions the agent may perform now (permeable cells excluded — the
        agent cannot issue them directly)."""
        sigma = self.observe()
        return sorted({self.cp.cells[ci]["action"]
                       for ci, _, _ in self._offers(sigma)
                       if self._layer(self.cp.cells[ci]["action"]) not in self.permeable})

    def attempt(self, action, execute, args=None):
        """Gate one attempted action, executing it if permitted.

        The pre-execution half is `check`; the post-execution half is the
        transaction advance, so this shares the candidate-set semantics rather
        than walking a single residual of its own.
        """
        ok, info = self.check(action)
        if not ok:
            self._veto(action, info.get("veto", "STRUCTURAL"),
                       info.get("guard", "not offered"))
            return False, info
        pre = dict(self.observe())
        execute()
        post = self.observe()
        return self.advance_transaction([action], pre, post, args=args)

    def check(self, action, sigma=None):
        """Check-only gate (no execution): may `action` fire now?

        `sigma` is the caller's ALREADY-TAKEN pre-state snapshot. Taking a
        second one here meant the decision could be made against a different
        world than the one recorded with the event — two snapshots for one
        decision, and the "what was gated is what was recorded" property then
        cannot be stated. On permit, `info["permit"]` carries a token binding
        the decision to that exact state; `advance_transaction` refuses a token
        whose state does not match what it is given.
        """
        sigma = self.observe() if sigma is None else sigma
        if self.holds.get(action, 0) >= self.hold_budget:
            return False, {"veto": "GUARD_POST",
                           "guard": "retry budget exhausted",
                           "attempts": self.holds[action],
                           "exhausted": True,
                           "permitted": []}
        offs = self._offers(sigma)
        # Derive the reported offer-set from the SAME snapshot used for gating.
        # Calling offer_set() here would observe the world a second time.
        offered = sorted({self.cp.cells[ci]["action"]
                          for ci, _, _ in offs
                          if self._layer(self.cp.cells[ci]["action"]) not in self.permeable})
        match = [(ci, cont, sk) for ci, cont, sk in offs
                 if self.cp.cells[ci]["action"] == action]
        if not match:
            return False, {"veto": "STRUCTURAL", "permitted": offered,
                           "not_yet": self.reachable(action)}
        match.sort(key=lambda m: len(m[2]))          # prefer fewest skips
        cell = self.cp.cells[match[0][0]]
        if not guards.eval_guard(cell["pre"], sigma):
            return False, {"veto": "GUARD_PRE", "guard": cell["pre"],
                           "permitted": offered}
        tok = {"action": action, "pre": dict(sigma), "issued": len(self.log)}
        self._permits.append(tok)
        return True, {"permitted": offered, "permit": tok}

    def advance(self, action, pre, post, args=None, discriminator=None, applied=True):
        """Advance one already-executed cell. Kept for single-cell callers; the
        transaction form is the general one. Operates over the candidate set."""
        return self.advance_transaction([action], pre, post, args=args,
                                        discriminator=discriminator, applied=applied)

    def advance_transaction(self, cells, pre, post, args=None, discriminator=None,
                            permit=None, applied=True):
        """Advance through one GESTURE TRANSACTION, atomically.

        One agent gesture produces a UI cell together with whatever server-side
        cells it triggers, and the instrument can observe state only either side
        of the whole cascade. The transaction is therefore the unit that is
        checked and the unit that advances:

          * some candidate residual must admit the cell sequence;
          * the FIRST cell's precondition must hold at the observed pre-state,
            being the only cell whose precondition is evaluable at an observed
            state;
          * the cells' asserted effects must be mutually CONSISTENT and their
            conjunction must hold at the observed post-state, with the frame
            condition applied once over the union;
          * all cells advance, or none do; an environment-declared
            `applied=False` occurrence is a HOLD even when the cell has no
            explicit asserted assignments.

        Candidate residuals that cannot explain the transaction are discarded;
        those that can are carried forward, so a choice whose options share a
        prefix is not resolved before the run distinguishes them.
        """
        cs_all = self.adf["cell_schema"]
        txn = {"cells": list(cells), "pre": pre, "post": post,
               "discriminator": discriminator, "applied": bool(applied),
               "observed_at": time.time()}

        # The state that justified the permit must be the state recorded with
        # the event. If they differ, the world moved between the decision and
        # the record, and neither the gate's verdict nor the audit's would be
        # about the same transition.
        if permit is not None and permit.get("pre") != pre:
            txn["outcome"] = "STALE_PERMIT"
            self.transactions.append(txn)
            self._finding(cells[0] if cells else "<none>", "STALE_PERMIT",
                          "pre-state changed between the gate decision and the record")
            return False, {"veto": "STALE_PERMIT"}

        schema_errs = (self._typecheck_state(pre, "pre")
                       + self._typecheck_state(post, "post"))
        if schema_errs:
            txn["outcome"] = "SCHEMA"
            self.transactions.append(txn)
            self._finding(cells[0] if cells else "<none>", "SCHEMA", "; ".join(schema_errs))
            return False, {"veto": "SCHEMA", "detail": schema_errs}

        if not cells:
            txn["outcome"] = "EMPTY"
            self.transactions.append(txn)
            self._finding("<empty>", "EMPTY", "transaction contained no classified cell")
            return False, {"veto": "EMPTY",
                           "detail": "a transaction must contain at least one cell"}

        # 1. every path through the candidate set that admits the sequence
        paths = [([], p, p) for p in self.procs]  # (cell indices, residual, origin)
        for action in cells:
            nxt = []
            for idxs, proc, origin in paths:
                for ci, cont, _sk in self._offers(pre, _procs=[proc]):
                    if self.cp.cells[ci]["action"] == action:
                        nxt.append((idxs + [ci], cont, origin))
            if not nxt:
                self._log_txn(txn, cells, pre, post, cs_all, False)
                self._finding(action, "STRUCTURAL",
                              f"not offered within transaction {list(cells)}")
                txn["outcome"] = "STRUCTURAL"
                self.transactions.append(txn)
                return False, {"veto": "STRUCTURAL",
                               "not_yet": self.reachable(action)}
            paths = nxt

        # 2. precondition of the first cell, at the only observed pre-state
        ok_pre = [(i, p, o) for i, p, o in paths
                  if guards.eval_guard(self.cp.cells[i[0]]["pre"], pre)]
        if not ok_pre:
            g = self.cp.cells[paths[0][0][0]]["pre"]
            self._log_txn(txn, cells, pre, post, cs_all, False)
            self._finding(cells[0], "GUARD_PRE", f"guard <{g}> false")
            txn["outcome"] = "GUARD_PRE"
            self.transactions.append(txn)
            return False, {"veto": "GUARD_PRE", "guard": g}

        # 3. consistency, then the relational postcondition at the observed post.
        # Keep HOLD-compatible ORIGINS separately: after a failed applied effect,
        # the process stays before the cell but branches that could not explain
        # the event must not be resurrected.
        survivors, hold_origins, bad, frame_bad, conflict = [], [], None, None, None
        for idxs, proc, origin in ok_pre:
            asg, unc, clash = {}, set(), None
            for ci in idxs:
                c = self.cp.cells[ci]
                for f, v in guards.parse_post(c["post"]).items():
                    if f in asg and asg[f] != v:
                        clash = (f, guards.render_value(asg[f]), guards.render_value(v))
                    asg[f] = v
                unc.update(c.get("unconstrained", ()))
            if clash:
                conflict = conflict or clash
                continue
            asserted_miss = []
            for f, v in asg.items():
                if post.get(f) != v:
                    asserted_miss.append((f, guards.render_value(v),
                                          guards.render_value(post.get(f))))
            frame_miss = []
            for f in pre:
                if f in asg or f in unc:
                    continue
                if pre[f] != post.get(f):
                    frame_miss.append((f, f"unchanged({guards.render_value(pre[f])})",
                                       guards.render_value(post.get(f))))
            if frame_miss:
                frame_bad = frame_bad if frame_bad is not None else frame_miss
                continue
            if (not applied) or asserted_miss:
                bad = bad if bad is not None else (asserted_miss or [("applied", "true", "false")])
                hold_origins.append(origin)
            else:
                survivors.append((asg, proc))

        if conflict and not survivors and not hold_origins:
            self._log_txn(txn, cells, pre, post, cs_all, False)
            self._finding(cells[-1], "INCONSISTENT",
                          f"cells of one transaction assign {conflict[0]} both "
                          f"{conflict[1]} and {conflict[2]}")
            txn["outcome"] = "INCONSISTENT"
            self.transactions.append(txn)
            return False, {"veto": "INCONSISTENT", "field": conflict[0]}

        if not survivors and frame_bad:
            self._log_txn(txn, cells, pre, post, cs_all, False)
            self._finding(cells[-1], "GUARD_POST",
                          f"frame condition violated: {frame_bad}")
            txn["outcome"] = "GUARD_POST"
            self.transactions.append(txn)
            return False, {"finding": "GUARD_POST", "frame": frame_bad,
                           "advanced": False}

        if not survivors:
            # HOLD: retain only origins that admitted this executed transaction.
            if hold_origins:
                self.procs = list(set(hold_origins))
            key = cells[-1]
            self.holds[key] = self.holds.get(key, 0) + 1
            n = self.holds[key]
            self._log_txn(txn, cells, pre, post, cs_all, False)
            self._finding(cells[-1], "GUARD_POST",
                          f"had no effect (attempt {n} via {discriminator}): {bad}")
            txn["outcome"] = "GUARD_POST"
            self.transactions.append(txn)
            return False, {"finding": "GUARD_POST", "veto": "GUARD_POST",
                           "advanced": False, "unmet": bad,
                           "required": ", ".join(f"{f}:={v}" for f, v in
                                                 (survivors[0][0] if survivors else {}).items())
                                        or "the asserted effect",
                           "attempts": n, "via": discriminator,
                           "exhausted": n >= self.hold_budget}

        # 4. commit: keep EVERY candidate that explains the transaction. A
        # successful occurrence ends any retry episode for its final cell.
        self.holds.pop(cells[-1], None)
        self._log_txn(txn, cells, pre, post, cs_all, True)
        # Compiled residuals are immutable tuples, so dedup STRUCTURALLY.
        # Keying on id() lets structurally identical candidates accumulate,
        # and the set then grows without bound on a longer contract.
        self.procs = list({p for _a, p in survivors})
        txn["outcome"] = "advanced"
        txn["candidates"] = len(self.procs)
        self.transactions.append(txn)
        return True, {"advanced": True, "candidates": len(self.procs)}

    def _log_txn(self, txn, cells, pre, post, cs_all, advanced):
        """Record a transaction in the four registers the audit needs.

        `self.log` is the EVENT history: every executed, classified operation,
        whether or not it advanced the process. `self.transitions` holds those
        that advanced; `self.attempts` those that did not.

        Previously a permitted action that executed and then failed its
        postcondition was written only to `attempts`, so the verifier never saw
        it. That made recovery look like a clean run and contradicted the claim
        that the audit is literal and that audit and enforcement work over the same
        history. An attempt is evidence — but evidence must not mean absence
        from the audit. The monitor still holds its residual and invites
        recovery; it no longer rewrites what happened.

        Per-cell pre/post inside a transaction is an ATTRIBUTION, not an
        observation: only the transaction's own pre and post were measured, and
        they are recorded on the transaction itself.
        """
        txn["id"] = len(self.transactions)
        rec = {"txn": txn["id"], "cells": list(cells), "pre": pre,
               "post": post, "observed_at": time.time()}
        (self.transitions if advanced else self.attempts).append(rec)
        for i, c in enumerate(cells):
            cs = cs_all.get(c, {})
            last = (i == len(cells) - 1)
            self.log.append({"action": c, "args": txn.get("args") or {},
                             "pre": pre, "post": post if last else pre,
                             "layer": cs.get("layer", "SYS"),
                             "type": cs.get("type", "action"),
                             "txn": txn["id"], "txn_position": i,
                             "advanced": advanced,
                             "observed_at": time.time()})

    def done(self):
        """Terminal if ANY surviving candidate is terminal and the exit guard
        holds: the run need only be explicable by one admitted path."""
        return any(terminated(p) for p in self.procs) and guards.eval_guard(
            self.adf["scope"]["exit_guard"], self.observe())

    def _finding(self, action, kind, detail):
        """Record a fault discovered AFTER execution; not an intervention.

        An intervention is a proposal refused before the world is touched. Once
        an operation has executed, the monitor can diagnose or HOLD it but cannot
        retroactively veto it. Keeping the registers distinct preserves that
        semantic boundary in the evidence.
        """
        self.runtime_findings.append({"action": action, "kind": kind,
                                      "detail": detail, "observed_at": time.time()})

    def _veto(self, action, kind, detail):
        """Record a proposal refused BEFORE execution."""
        self.interventions.append({"action": action, "kind": kind,
                                   "detail": detail, "observed_at": time.time()})
