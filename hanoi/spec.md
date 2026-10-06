# Tower of Hanoi — executable process-contract specification

This file describes the contract that the Hanoi experiment actually induces and
executes. It distinguishes the **domain legality model** (all legal Hanoi moves)
from the **process contract** (the particular demonstrated process induced from
a seed run). The experiment uses the latter.

## 1. Observable store

Let the physical Hanoi world contain disks `D={1,2,3}` and pegs
`Π={A,B,C}`. The process contract does not reason directly over the complete
physical representation. The environment adapter exposes the typed projection

```text
observe : World -> Sigma
```

with fields

```text
sigma = (
  legal_ab, legal_ac, legal_ba, legal_bc, legal_ca, legal_cb,
  config,
  solved
)
```

where each `legal_xy` is a Boolean saying whether the disk currently on top of
peg `x` can legally be moved to peg `y`, `config` is a canonical rendering of
the physical configuration, and `solved` is true exactly when all disks are on
peg C.

For the three-disk task the initial observation is

```text
sigma_0 = {
  legal_ab=true, legal_ac=true,
  legal_ba=false, legal_bc=false,
  legal_ca=false, legal_cb=false,
  config="321|-|-",
  solved=false
}
```

The task exit predicate is

```text
chi(sigma) := solved
```

The relational Hanoi legality rule is derived by `observe()` rather than put
inside the restricted guard language. Thus a process cell needs only a Boolean
guard such as `legal_ac`.

## 2. Cells

The process vocabulary contains six move cells and one report cell:

```text
move_ab, move_ac, move_ba, move_bc, move_ca, move_cb, report
```

`move_xy` means "move the disk currently on top of x to y". Naming a disk that
is not on top of its peg does not classify to a move cell at all.

A recorded execution event is

```text
e_i = (c_i, sigma_{i-1}, sigma_i)
```

plus evidence metadata such as arguments, timestamp, and whether the environment
applied the requested state change.

## 3. Relational postconditions and frame conditions

For cell `c`, let `A_c` be the finite map of explicitly asserted assignments and
`U_c` the fields deliberately released by the cell.

```text
Assert_c(sigma') := /\_{f in dom(A_c)} sigma'(f) = A_c(f)

Frame_c(sigma,sigma') :=
  /\_{f in F \ (dom(A_c) union U_c)} sigma'(f) = sigma(f)

Post_c(sigma,sigma') := Assert_c(sigma') /\ Frame_c(sigma,sigma')
```

A rendered post of `tau` means `A_c` is empty; it does **not** mean arbitrary
state change is allowed. The frame condition still constrains every field that
is neither asserted nor released.

For Hanoi move cells the derived legality fields and `config` are released,
because their next values are determined by the environment. `solved` is not
released. Consequently the final move in the seed is the cell that explicitly
establishes `solved:=true`.

## 4. The process contract used by the experiment

The induced three-disk seed process is

```text
P_solve =
    move_ac ;
    move_ab ;
    move_cb ;
    move_ac ;
    move_ba ;
    move_bc ;
    move_ac

P_finish = report

P_H = P_solve ; P_finish ; SKIP
```

The ADF stores `P_solve` and `P_finish` as named calls, but compilation expands
those names to the same literal cells. Naming is therefore structural
factorisation, not removal of behaviour.

This contract intentionally captures one demonstrated process. A different legal
solution to Hanoi may satisfy the puzzle rules while failing the process contract.

## 5. Domain legality is not the process contract

For comparison, a general Hanoi policy could be written informally as a loop
that permits any legal move until `solved`, followed by `report`. Call that
process `P_legal`.

The experiment does **not** use `P_legal` as its contract. It uses the induced
seed process `P_H`, so

```text
L(P_H) subseteq L(P_legal)
```

for the corresponding action/state language. This distinction is deliberate:
the environment enforces puzzle legality; the process contract constrains which
legal action is permitted at each point of the demonstrated process.

## 6. Execution trace and intervention evidence

The execution trace

```text
tau = <e_1,...,e_n>
```

contains operations that crossed the runtime boundary and were presented to the
environment, including an unenforced operation that the environment processed but
did not apply.

A proposal refused by the runtime gate **before dispatch** is not an execution
event because the world was never touched. It is retained separately in the
operation/intervention ledger. Thus an enforced run has two complementary forms
of evidence:

```text
execution trace tau     -- what actually reached the world
intervention trace nu   -- proposals prevented before execution
```

The conformance judgement is over the executed history:

```text
tau |= C                (paper rendering: tau models C)
```

while `nu` reports how often enforcement prevented departure from the contract.

## 7. ADVANCE and HOLD

For an offered cell `c` with precondition `g_c`, the normal transition is

```text
ADVANCE:
  sigma |= g_c
  Assert_c(sigma')
  Frame_c(sigma,sigma')
  --------------------------------
  (P,sigma) -c-> (P',sigma')
```

where `P'` is the continuation associated with the offered cell.

If the operation executes, its asserted effect is absent, but its frame remains
intact, the event is still part of the trace and the process does not advance:

```text
HOLD:
  sigma |= g_c
  not Assert_c(sigma')
  Frame_c(sigma,sigma')
  --------------------------------
  (P,sigma) -c,HOLD-> (P,sigma')
```

HOLD is bounded by the contract's declared `semantics.hold_budget`. A successful
occurrence ends the retry episode. A frame violation is never a HOLD.

## 8. Exact finite-trace conformance

A finite execution conforms when:

1. the trace is a well-formed single history (schema, state continuity, and
   operation/event correspondence hold);
2. the declared initial state is the first event's pre-state;
3. every event can be consumed by an admitted ADVANCE or HOLD transition;
4. the residual process reaches successful termination; and
5. the final state satisfies `solved`.

The exact walk determines the Boolean verdict. Minimum-cost alignment is applied
only after exact conformance fails, to diagnose the departure.

## 9. Failure families

The implementation reports two families rather than treating instrumentation
integrity and process behaviour as one category.

### Trace-integrity findings

- `SCHEMA` — an observed state does not inhabit the declared typed store.
- `CONTINUITY` — the first pre-state is not the declared initial state or one
  event's post-state is not the next event's pre-state.
- `LEDGER_MISMATCH` — the recorded event sequence does not correspond to the
  operations that should have produced execution events.
- `UNMEDIATED` — an operation crossed the boundary without classifying to a
  declared cell.

### Process-conformance findings

- `STRUCTURAL` — the recorded cell was not offered at that point, or a required
  cell is missing.
- `GUARD_PRE` — the right structural cell occurred in a pre-state that did not
  satisfy its guard.
- `GUARD_POST` — an unaccounted-for frame change occurred, an asserted effect is
  inconsistent with the observation, or the bounded HOLD retry budget is
  exceeded.
- `COMPLETENESS` — the finite run ends without successful process termination
  and satisfaction of the exit predicate.

A run is certified only when both families are clear.

## 10. Sequential composition

For contracts over the same typed store and executable semantics,

```text
C1 = (S, iota_1, P1, chi_1)
C2 = (S, iota_2, P2, chi_2)
```

sequential composition is admitted when the boundary is compatible:

```text
forall sigma . chi_1(sigma) => iota_2(sigma)
```

and is written

```text
C1 ; C2
```

with process term `P1 ; P2`, entry predicate `iota_1`, and final exit predicate
`chi_2`. The state in which `C1` terminates is the state in which `C2` begins.

The Hanoi ADF already realizes this structurally as

```text
C_H = C_solve ; C_finish
```

where the handoff state established by the last move has `solved=true`, which is
the guard required by `report`.
