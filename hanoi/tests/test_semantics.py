import copy
import json
import unittest
from pathlib import Path

from artefact import verify
from artefact.compose import compose_sequential
from artefact.semantics import DEFAULT_HOLD_BUDGET
from artefact.stepper import Stepper
from world import Hanoi

ROOT = Path(__file__).resolve().parents[1]


def event(seq, action, typ, pre, post, applied=True):
    return {"seq": seq, "layer": "SYS", "type": typ, "action": action,
            "args": {}, "pre": dict(pre), "post": dict(post),
            "applied": applied, "observed_at": float(seq)}


class HanoiSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adf = json.loads((ROOT / "artefacts" / "hanoi3.adf.json").read_text())

    def build_seed_trace(self, use_stepper=False):
        w = Hanoi(3, goal="C")
        st = Stepper(self.adf, w.observe) if use_stepper else None
        events, ledger, interventions = [], [], []
        moves = [(1, "C"), (2, "B"), (1, "B"), (3, "C"),
                 (1, "A"), (2, "C"), (1, "C")]
        for disk, to in moves:
            pre = w.observe()
            cell = w.cell(disk, to)
            permit = None
            if st:
                ok, info = st.check(cell, sigma=pre)
                self.assertTrue(ok, (cell, info))
                permit = info["permit"]
            ok, _ = w.move(disk, to)
            self.assertTrue(ok)
            post = w.observe()
            if st:
                advanced, info = st.advance_transaction(
                    [cell], pre, post, discriminator="move", permit=permit)
                self.assertTrue(advanced, info)
            ledger.append({"operation_seq": len(ledger), "kind": "move",
                           "cell": cell, "executed": True, "dispatched": True,
                           "applied": True})
            events.append(event(len(events), cell, "action", pre, post))

        pre = w.observe()
        if st:
            ok, info = st.check("report", sigma=pre)
            self.assertTrue(ok, info)
            permit = info["permit"]
        else:
            permit = None
        post = w.observe()
        if st:
            advanced, info = st.advance_transaction(["report"], pre, post,
                                                     permit=permit)
            self.assertTrue(advanced, info)
            self.assertTrue(st.done())
        ledger.append({"operation_seq": len(ledger), "kind": "report",
                       "cell": "report", "executed": True, "dispatched": True,
                       "applied": True})
        events.append(event(len(events), "report", "report", pre, post))

        trace = {"run_id": "test_hanoi", "events": events,
                 "operation_ledger": ledger,
                 "unapplied_events_recorded": False,
                 "interventions": interventions}
        return trace, st

    def test_seed_execution_conforms(self):
        trace, _ = self.build_seed_trace()
        acr = verify.check(trace, self.adf)
        self.assertEqual(acr["verdict"], "conforms")
        self.assertEqual(acr["trace_integrity"], "pass")
        self.assertEqual(acr["process_conformance"], "pass")

    def test_runtime_and_posthoc_accept_same_execution(self):
        trace, st = self.build_seed_trace(use_stepper=True)
        self.assertTrue(st.done())
        acr = verify.check(trace, self.adf)
        self.assertEqual(acr["verdict"], "conforms")

    def test_pre_execution_veto_does_not_touch_world(self):
        w = Hanoi(3, goal="C")
        st = Stepper(self.adf, w.observe)
        before = w.observe()
        executed = {"value": False}

        def should_not_run():
            executed["value"] = True
            w.move(1, "B")

        ok, info = st.attempt("move_ab", should_not_run)
        self.assertFalse(ok)
        self.assertEqual(info["veto"], "STRUCTURAL")
        self.assertFalse(executed["value"])
        self.assertEqual(w.observe(), before)
        self.assertEqual(len(st.interventions), 1)
        self.assertEqual(st.log, [])

    def test_different_legal_first_move_is_structural(self):
        w = Hanoi(3, goal="C")
        pre = w.observe()
        cell = w.cell(1, "B")
        ok, _ = w.move(1, "B")
        self.assertTrue(ok)
        post = w.observe()
        tr = {"run_id": "alt", "events": [event(0, cell, "action", pre, post)],
              "operation_ledger": [{"operation_seq": 0, "kind": "move",
                                     "cell": cell, "executed": True}],
              "unapplied_events_recorded": False}
        acr = verify.check(tr, self.adf)
        self.assertEqual(acr["verdict"], "violations")
        self.assertTrue(any(m["class"] == "STRUCTURAL" for m in acr["misalignments"]))


class CoreSemanticsTests(unittest.TestCase):
    def simple_adf(self):
        return {
            "adf_version": "1.0", "artefact_id": "0" * 64,
            "name": "simple", "version": "1.0.0", "created_from_run": "seed",
            "store_schema": {"x": "bool"},
            "cell_schema": {"set_x": {"type": "action", "layer": "SYS", "reads": []}},
            "scope": {"entry": "true", "exit_guard": "x"},
            "alpha": {"projection_fields": ["x"], "initial_store": {"x": False},
                      "quotient": []},
            "semantics": {"version": "1.0.0", "hold_budget": DEFAULT_HOLD_BUDGET},
            "P": {"op": "cell", "action": "set_x", "type": "action",
                  "reads": [], "pre": "true", "post": "x:=true"},
            "external_choices": [], "internal_choices": [],
            "signoff": {"status": "draft"}, "provenance": "declared",
        }

    def test_precondition_is_checked_on_pre_state(self):
        adf = self.simple_adf()
        adf["P"]["pre"] = "x"
        cp = verify.Compiled()
        P = verify.compile_node(adf["P"], verify.END, cp)
        # x becomes true only after the action; that must not satisfy the precondition.
        evs = [{"seq": 0, "action": "set_x", "pre": {"x": False},
                "post": {"x": True}}]
        self.assertFalse(verify.conforms_exactly(P, evs, {"x": False}, cp, "x"))

    def test_relational_frame_violation_fails(self):
        adf = self.simple_adf()
        adf["store_schema"]["y"] = "bool"
        adf["alpha"]["projection_fields"].append("y")
        adf["alpha"]["initial_store"]["y"] = False
        cp = verify.Compiled()
        P = verify.compile_node(adf["P"], verify.END, cp)
        evs = [{"seq": 0, "action": "set_x", "pre": {"x": False, "y": False},
                "post": {"x": True, "y": True}}]
        self.assertFalse(verify.conforms_exactly(P, evs, {"x": False, "y": False}, cp, "x"))

    def test_unapplied_tau_event_holds_instead_of_advancing(self):
        adf = self.simple_adf()
        adf["P"]["post"] = "tau"
        cp = verify.Compiled()
        P = verify.compile_node(adf["P"], verify.END, cp)
        evs = [{"seq": 0, "action": "set_x", "pre": {"x": False},
                "post": {"x": False}, "applied": False}]
        # If the unapplied tau event advanced, termination would be reached; HOLD
        # correctly leaves the required cell pending, so this finite run is incomplete.
        self.assertFalse(verify.conforms_exactly(P, evs, {"x": False}, cp, "true"))

    def test_hold_budget_matches_runtime_and_audit(self):
        adf = self.simple_adf()
        state = {"x": False}
        step = Stepper(adf, lambda: dict(state))
        events = []
        # Six executed attempts may HOLD.
        for i in range(DEFAULT_HOLD_BUDGET):
            ok, info = step.check("set_x", sigma=dict(state))
            self.assertTrue(ok, info)
            advanced, out = step.advance_transaction(
                ["set_x"], dict(state), dict(state), permit=info["permit"])
            self.assertFalse(advanced)
            self.assertEqual(out["veto"], "GUARD_POST")
            events.append({"seq": i, "action": "set_x", "pre": dict(state),
                           "post": dict(state)})
        # Seventh proposal is prevented before execution.
        ok, info = step.check("set_x", sigma=dict(state))
        self.assertFalse(ok)
        self.assertTrue(info["exhausted"])

        cp = verify.Compiled()
        P = verify.compile_node(adf["P"], verify.END, cp)
        # Six HOLDs followed by a successful occurrence are accepted offline.
        success = {"seq": len(events), "action": "set_x", "pre": {"x": False},
                   "post": {"x": True}}
        self.assertTrue(verify.conforms_exactly(
            P, events + [success], {"x": False}, cp, "x",
            hold_budget=DEFAULT_HOLD_BUDGET))
        # A seventh executed HOLD is outside the language the runtime gate permits.
        seventh = {"seq": len(events), "action": "set_x", "pre": {"x": False},
                   "post": {"x": False}}
        self.assertFalse(verify.conforms_exactly(
            P, events + [seventh, success], {"x": False}, cp, "x",
            hold_budget=DEFAULT_HOLD_BUDGET))

    def test_sequential_contract_composition(self):
        left = self.simple_adf()
        left["name"] = "left"
        left["scope"] = {"entry": "true", "exit_guard": "x"}
        left["content_hash"] = "a" * 64

        right = copy.deepcopy(left)
        right["name"] = "right"
        right["artefact_id"] = "1" * 64
        right["content_hash"] = "b" * 64
        right["scope"] = {"entry": "x", "exit_guard": "x"}
        right["P"] = {"op": "skip"}

        composed = compose_sequential(left, right, "joined")
        self.assertEqual(composed["P"]["op"], "seq")
        self.assertEqual(composed["scope"]["entry"], "true")
        self.assertEqual(composed["scope"]["exit_guard"], "x")
        self.assertEqual(composed["composition"]["operator"], "seq")


if __name__ == "__main__":
    unittest.main()
