# Pre-writing code freeze notes — 2026-08-24

## Semantics now frozen in this package

- Primary judgement is finite-trace satisfaction (`tau models C`), not custom CSP refinement.
- Verification uses the literal execution event sequence; no behavioural hiding or quotienting is applied before audit.
- Preconditions are evaluated on the recorded pre-state.
- Postconditions are relational: explicit assignments plus a frame condition over every unreleased field.
- `applied=false` and missing asserted effects are HOLD transitions when the frame is intact; HOLD is bounded and a successful occurrence clears the retry episode.
- The HOLD budget is contract semantics (`semantics.hold_budget`), hashed into contract identity and shared by stepper/verifier.
- Exact conformance decides the verdict; minimum-cost alignment is diagnostic only.
- Runtime pre-execution vetoes are interventions, not execution events. The operation ledger retains all proposals.
- Findings are split into TRACE_INTEGRITY and PROCESS_CONFORMANCE families.
- Sequential process composition and top-level contract composition are implemented.

## Regression suite

`PYTHONPATH=. python -m unittest discover -s tests -v`

Nine tests cover:

1. seed Hanoi trace self-conformance;
2. runtime/post-hoc acceptance of the same Hanoi execution;
3. pre-execution veto leaves the world untouched;
4. a different legal Hanoi path is structurally nonconforming;
5. preconditions use the pre-state;
6. relational frame violations fail;
7. unapplied `tau` events HOLD rather than advance;
8. runtime/offline HOLD-budget agreement;
9. sequential contract composition.

## Deliberately outside the frozen v1 executable fragment

- behavioural hiding;
- behavioural quotienting;
- arbitrary recursion;
- parallel composition/synchronisation.

The ADF schema still contains legacy/superset nodes for compatibility, but the
translator refuses unsupported operators in a signed/generated artefact.

## Remaining integration work before claiming the same freeze for WebArena

The `artefact/` directory in this Hanoi package is a copy. These semantic fixes
must also be applied to whichever engine copy is authoritative for the WebArena
experiment before the paper claims the implementations are identical across
both tasks.

Hanoi does not exercise API/environment-layer gesture transactions or permeable
cells. The general environment-effect design should therefore receive one
integration regression in the WebArena codebase: one agent gesture plus its
server-side effect(s) must produce the same transaction/result under runtime and
post-hoc checking.

The directed renderer is implemented but not wired into the Hanoi runner; this
is not required if Hanoi is presented as a semantics sanity check rather than the
full three-arm evaluation.
