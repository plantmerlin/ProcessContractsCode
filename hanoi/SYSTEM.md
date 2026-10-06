# Hanoi — the pieces of the system

Target configuration: **3 disks, `gpt-4o`**, environment blocks illegal and
impossible moves. That combination solves the puzzle optimally (7 moves, 0
blocked), so it is a working baseline to build on rather than a floor.

Layers run bottom to top. Each says what it is, what software it needs, and what
it hands to the layer above.

---

## 1. Environment — the world

**`hanoi/world.py`** · pure Python, no dependencies

Owns the state and is the only thing that can change it. Applies a legal move,
refuses an illegal or impossible one. Knows nothing about contracts, agents or
traces.

Hands up: a state, and for each attempted move a `(ok, reason)` pair.

## 2. Observation — `observe : World → σ`

**`hanoi/world.py`** (`observe`, `render`) · pure Python

Two different readings of the same world, and they must stay separate:

| | Who reads it | Contains |
|---|---|---|
| `render()` | the **agent** | the position, as three lines of text |
| `observe()` | the **monitor** | σ — the typed store the contract is written over |

`observe` must derive the six legality predicates `legal_ab … legal_cb`, one per
ordered pair of pegs. This is forced, not stylistic: the rule
`top(σ, peg(σ,d)) = d ∧ (σ(p) = [] ∨ top(σ,p) > d)` is relational and contains a
disjunction, so it lies outside the guard language `true | literal | G ∧ G`. The
relational reasoning therefore lives in the observation model and the guard
reads a boolean — the same treatment `price_ok` gets in the shopping task.

**The agent must never see σ.** Showing it the legality flags hands over the
judgement the contract exists to make; that defect cost the WebArena experiment
a whole generation.

Hands up: σ before and after every action.

## 3. Agent and capability

**`hanoi/run_hanoi.py`** · `openai-agents` SDK · `gpt-4o`

The prompt, and two tools: `move(disk, to_peg)` and `report()`. The tool returns
the outcome then the position, as plain text.

**Cell vocabulary.** An operation classifies to one of six cells,
`move_ab … move_cb`, derived as `move_{peg_of(disk)}{to_peg}`. Six regardless of
disk count, which is why the classifier uses peg-to-peg rather than
disk-to-peg — the latter would grow as `3n`.

Hands up: proposed operations, some of which may be vetoed before dispatch.

## 4. Recording — the trace

**`artefact/atf.py`** + **`spec/schemas/atf.trace.schema.json`**

Each execution event is `e = (action, observe(pre), observe(post))`, plus
`applied` — did the environment accept the requested state change. A proposal
refused before dispatch is retained in the operation/intervention ledger but is
not an execution event, because the world was never touched.

`ARTEFACT_HOME=hanoi/` keeps these runs out of the WebArena store.

Hands up: an ATF trace. **Everything above this line already exists and runs.**

---

## 5. Induction (M1) — trace → contract

**`artefact/translate.py`** · `artefact/guards.py`

Takes one goal-attaining run and produces a guarded process contract written as
an ADF file. The legacy ADF field named `alpha` is now only an observation
manifest; no behavioural hiding or quotienting is applied to the trace that is
audited. The task definition declares, per cell, the `reads`-set that makes its
precondition meaningful.

For Hanoi, the induced `P` is the demonstrated seven-move seed sequence followed
by `report`, grouped structurally into named `solve` and `finish` calls. The more
general recursive "any legal Hanoi solution" model is a domain-legality model,
not the process contract used in the experiment.

Sign-off gate: the contract must accept the run it was induced from.

**Resolved postcondition design.** Move cells release the environment-derived
legality predicates and `config`, but the relational frame condition still holds
all unreleased fields fixed. The final seed move observes and asserts
`solved:=true`, so R13 establishes the exit predicate mechanically. `tau` means
"no explicit assignment", not "arbitrary state change".

## 6. Audit (M3) — does a finished run conform?

**`artefact/verify.py`**

First decides exact finite-trace conformance (`tau models C`). Minimum-cost
alignment runs only after exact conformance fails and is diagnostic. Findings
are split into TRACE_INTEGRITY (`SCHEMA`, `CONTINUITY`, `LEDGER_MISMATCH`,
`UNMEDIATED`) and PROCESS_CONFORMANCE (`STRUCTURAL`, `GUARD_PRE`, `GUARD_POST`,
`COMPLETENESS`).

Works on any stored trace, so it needs nothing running.

## 7. Enforcement (M2) — the gate

**`artefact/stepper.py`**

Sits between the `move` tool and the world. Checks the action against the
contract *before* the world sees it; on refusal the agent is told which step it
attempted and which are permitted now.

Note what this means here: the environment already blocks illegal moves, so the
gate's remaining job is **procedural** — refusing a premature `report`, refusing
actions out of order. That is the more conservative claim and the harder one to
dismiss.

## 8. Direction — the contract as prompt text

**`artefact/direction.py`**

Renders `C` for the agent, for the middle arm. Same contract object, different
role.

## 9. Experiment status

The Hanoi harness currently provides the two conditions needed for the formal
sanitary check: **undirected** execution and **runtime-enforced** execution. The
direction renderer exists in `artefact/direction.py`, but the directed arm is not
wired into `run_hanoi.py`; the full three-arm evaluation belongs to the larger
experiment harness.

Hanoi therefore serves primarily as an executable semantics test: induction from
one successful trace, exact post-hoc conformance, runtime gating over the same
contract, intervention recording, and regression tests for their consistency.
Task outcome (`solved`) and process conformance remain separate measurements.

---

## How it fits together

```
                     world.py
                   (the world)
                        │
              ┌─────────┴──────────┐
        render()                observe()
      what the agent            σ, the monitor's
        can see                     state
            │                        │
            ▼                        ▼
      run_hanoi.py  ──────────►  atf.py ──► ATF trace
      (agent + tools)                          │
            ▲                                  │
            │                    ┌─────────────┼──────────────┐
            │                    ▼             ▼              ▼
            │              translate.py    verify.py     (a stored run)
            │               induction        audit
            │                    │             │
            │                    ▼             │
            │              contract (ADF) ◄────┘
            │                    │
            │        ┌───────────┴───────────┐
            │        ▼                       ▼
            └── direction.py            stepper.py
                (directed arm)      (enforced arm — gates the
                                     tool before the world sees it)
```

Dependencies run one way: no contract without a trace, no enforcement without a
contract, no experiment without all three arms.

---

## Freeze status

| Piece | Status |
|---|---|
| world, agent tools, `render()`, `observe()` | **implemented** |
| typed task definition and cell schema | **implemented** |
| ATF execution trace + operation/intervention ledger | **implemented** |
| induction trace → ADF contract | **implemented** |
| exact verifier + diagnostic alignment | **implemented** |
| runtime stepper using the same compiled semantics | **implemented** |
| relational post/frame checking and bounded HOLD | **implemented** |
| sequential process composition (`seq`) | **implemented** |
| sequential top-level contract composer | **implemented** (`artefact/compose.py`) |
| finite-trace semantics regression suite | **implemented**, 9 tests |
| directed prompt renderer | **implemented**, not wired into Hanoi runner |
| parallel/recursive executable contract fragment | **not part of the frozen v1 semantics** |
| legacy `traces/` files | **historical pre-ATF data; not current verifier input** |

The frozen executable fragment is intentionally narrower than the older schema
superset: sequence, guarded cells, named calls, external/internal choice, SKIP,
and STOP. Hiding, behavioural quotienting, arbitrary recursion, and parallelism
are not required for the Hanoi/paper core and should not be claimed as executed
features unless they are separately implemented and tested.

