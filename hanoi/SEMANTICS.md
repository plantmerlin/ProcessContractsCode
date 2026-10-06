# Frozen executable semantics (pre-writing baseline)

This note states the semantics the current code implements. It is intentionally
narrow: finite recorded executions, deterministic typed guards, runtime gating,
post-hoc audit, bounded HOLD, and sequential composition.

## Core objects

Let `F` be the finite typed store vocabulary and `Sigma` the states admitted by
that schema. The environment adapter supplies

```text
observe : World -> Sigma
```

An execution event is

```text
e_i = (c_i, sigma_{i-1}, sigma_i)
```

and a finite execution trace is

```text
tau = <e_1,...,e_n>.
```

No behavioural hiding or quotienting is applied to `tau` before conformance.
The ADF field historically named `alpha` is retained only as a versioned
observation/projection manifest and induction metadata.

A contract is treated mathematically as

```text
C = (S, iota, P, chi)
```

where `S` is the typed state interface, `iota` the entry predicate, `P` the
guarded process term, and `chi` the exit predicate. In ADF v1 the exact initial
store is stored in the legacy observation manifest and the exit predicate in
`scope.exit_guard`.

Primary conformance judgement:

```text
tau |= C                 # paper rendering: tau models C
```

This is a custom finite-trace satisfaction relation, not CSP refinement.

## Guarded cell semantics

For a cell `c`, let `g_c` be its precondition, `A_c` its explicitly asserted
post-state assignments, and `U_c` its released fields.

```text
Assert_c(sigma') := /\_{f in dom(A_c)} sigma'(f) = A_c(f)
Frame_c(sigma,sigma') :=
  /\_{f in F \ (dom(A_c) union U_c)} sigma'(f) = sigma(f)
Post_c(sigma,sigma') := Assert_c(sigma') /\ Frame_c(sigma,sigma')
```

The precondition is evaluated on the **pre-state** `sigma`, never on `sigma'`.

ADVANCE consumes the cell and moves to its continuation when `g_c`, `Assert_c`,
and `Frame_c` hold. HOLD consumes the executed event but leaves the residual
process unchanged when the asserted effect is absent **or the environment reports
`applied=false`**, provided the frame still holds. A frame violation is never a HOLD. Consecutive HOLDs are bounded by
`semantics.hold_budget`; a successful occurrence clears that retry episode.

## Evidence boundary

The operation ledger records every proposed agent operation. The execution trace
records operations that crossed the runtime boundary. A proposal refused before
dispatch is an **intervention**, not an execution event. An operation that reaches
the environment but whose requested state change is refused is still an execution
event, with `applied=false`.

Thus the evidence may be viewed as

```text
R = (tau, nu)
```

where `tau` is the executed history and `nu` the pre-execution intervention
history. Conformance is judged over `tau`; `nu` measures attempted departures
prevented by enforcement.

## Finding families

Trace-integrity prerequisites:

```text
SCHEMA, CONTINUITY, LEDGER_MISMATCH, UNMEDIATED
```

Process-conformance findings:

```text
STRUCTURAL, GUARD_PRE, GUARD_POST, COMPLETENESS
```

`GUARD_POST` includes frame violations and exhaustion of bounded HOLD. A finite
run is certified only when trace integrity passes and the exact process walk
terminates with the exit predicate satisfied.

Minimum-cost alignment is diagnostic only. It is invoked after exact conformance
fails, so changing alignment costs cannot change the Boolean verdict.

## Sequential composition

For

```text
C1 = (S, iota_1, P1, chi_1)
C2 = (S, iota_2, P2, chi_2)
```

with a shared state/semantics interface, sequential composition requires

```text
forall sigma . chi_1(sigma) => iota_2(sigma)
```

and yields `C1 ; C2` with process `P1 ; P2`, entry `iota_1`, and final exit
`chi_2`. The state is passed unchanged across the contract boundary.

## Three propositions used by the paper

### P1 — finite-trace decidability

For a finite trace and finite executable contract, `tau |= C` is decidable when
state typing, guards, post/frame predicates, and offer computation terminate,
the offer set is finite, HOLD is bounded, and process-structure expansion cannot
perform an infinite unobservable loop. The current executable fragment satisfies
these restrictions.

### P2 — runtime/audit consistency

If runtime enforcement and post-hoc audit use the same contract, projection,
compiled process, offer function, guard/post/frame semantics, and HOLD policy,
then an execution accepted incrementally by the runtime monitor is accepted by
the post-hoc exact conformance check. The implementation regression test
`test_runtime_and_posthoc_accept_same_execution` exercises this property on the
three-disk Hanoi contract.

### P3 — sequential composition preserves conformance

If `tau_1 |= C1`, `tau_2 |= C2`, the final state of `tau_1` is the initial state
of `tau_2`, and the contract boundary is compatible, then

```text
tau_1 . tau_2 |= C1 ; C2.
```

The composer implements a conservative mechanical compatibility test; it refuses
composition when implication cannot be established rather than guessing.
