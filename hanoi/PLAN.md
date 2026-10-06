> **IGNORE THIS FILE — SUPERSEDED.** Kept for history only. It describes an earlier design (a `move(from, to)` interface and an undecided contract shape) that the project no longer follows. See `README.md` and `SYSTEM.md` for the current design.

# Tower of Hanoi — process contract, step by step

A second task for the process-contract framework, in a fully observable domain.

**What is isolated:** everything Hanoi-specific — harness, task definition,
contract, runs, reports, tests — lives under `hanoi/`. Nothing here touches the
WebArena files and nothing there touches these.

**What is deliberately shared:** the four engines in `artefact/`. That sharing is
the claim being tested. If Hanoi needed its own translator or verifier, the
framework would not generalise, it would just have been forked. The engines are
expected to require **no changes at all**; if they do, that is a finding and it
gets written down rather than patched around.

---

## Step 0 — keep the run stores apart

`artefact/atf.py` derives `runs/`, `reports/` and `artefacts/` from the repo
root, so Hanoi runs would land among the 2000+ WebArena runs and the packager
would mix them. Make the store location relocatable (an `ARTEFACT_HOME`
environment variable defaulting to the current root, so existing behaviour is
unchanged), and point it at `hanoi/`. Schemas stay shared — they are the file
format, not task data.

This is the one engine change, it is additive, and it benefits both tasks.

## Step 1 — the world (M0)

A pure Python Hanoi: three pegs, `n` disks, `move(from, to)` which either applies
or is rejected. No browser, no network, no timing. Deterministic.

`observe()` returns the declared projection and nothing else. Because the state
is the peg configuration, `snapshot()` is very nearly the identity and there is
no monitor memory to carry — this is the whole reason for choosing the domain.

## Step 2 — decide the store schema

**This is the step that decides everything else, and it is not obvious.**

The natural rule — *move disk d from A to B iff d is the top of A and B is empty
or its top is larger* — is **not expressible in the guard language**. Guards are
`true | literal | G ∧ G` over typed constants: they compare a field to a
constant. They cannot relate two parts of the state to each other, and they have
no disjunction. That restriction is the determinism band and exists on purpose.

So the relational reasoning has to live in the observation model, exactly as it
already does for WebArena, where `price_within_limit` and `target_in_cart` are
*derived booleans* rather than relational guards. For Hanoi that means deriving
one legality flag per move:

```
store_schema:
  config      string        # "321|.|." — the configuration, for the record
  legal_AB    bool          # derived: is A->B legal from here?
  legal_AC    bool
  legal_BA    bool
  legal_BC    bool
  legal_CA    bool
  legal_CB    bool
  solved      bool
```

A second consequence: a move's **postcondition cannot be written either**, since
the resulting configuration depends on the current one and postconditions assert
constant assignments. The move cells therefore *release* the configuration and
the legality flags — the contract states which moves are permitted **from a
state**, not what the state becomes.

That is the right division and worth stating plainly in the paper: the contract
constrains the **agent**, and the environment decides what follows. It is the
same principle that removed the `api_*` cells from the WebArena contract.

Be honest about the cost: the legality rule then lives in `derive()`, not in the
contract, so "the contract encodes the rules of the game" is **not** the claim.
The claim is that the contract encodes *which actions are permitted when*, over
an observation model that supplies the predicates.

## Step 3 — the task definition

`hanoi/tasks/hanoi3.task.json`: the schema above, the initial store, one cell per
directed move plus `report`, and `scope.exit_guard = "solved"`.

Six move cells rather than a parameterised one, because cells are unparameterised
in this framework — `move_A_B` with precondition `legal_AB`.

## Step 4 — smoke test the engines

Before any agent: drive a scripted optimal solution through the world, build a
trace by hand, and check the verifier accepts it and the stepper permits it.
This is engine validation, **not** induction — the contract must still be induced
from an agent run (M1), never from a script.

Also check the negatives fail: an illegal move must produce `GUARD_PRE`, and a
`report` before `solved` must produce `STRUCTURAL`.

## Step 5 — induce the contract (M1)

One undirected agent run that solves the puzzle becomes the seed. Translate,
then require the contract to accept the run it came from. Expect the induced `P`
to be a repetition of move cells under an external choice, closing with `report`.

## Step 6 — audit and enforce (M2/M3)

Verify stored runs; gate a live run with the stepper. Confirm the property that
must hold by construction: **no enforced run commits an illegal move.**

## Step 7 — find the difficulty that gives headroom

3 disks (7 moves) is likely trivial; 5 disks (31 moves) likely too hard. Pilot 10
undirected runs at 3, 4 and 5 disks and pick the depth where the baseline sits
around 50–70%, rather than discovering saturation after a full grid — which is
what happened on WebArena.

## Step 8 — the experiment

The usual three arms at the chosen depth. Two things Hanoi gives that WebArena
could not:

- **Failures occur naturally.** No injection or mutation needed; models make
  illegal moves unprompted.
- **A natural outcome-invisible violation.** An agent that teleports a disk can
  still reach the correct final configuration. The end state is *identical* to a
  legal solution, so no outcome metric can see it, while the audit records
  `GUARD_PRE`. This is the finding that took 180 WebArena runs to observe 14
  times, available here by construction.

---

## What this task does not demonstrate

Hanoi has no sequencing and no phases — the process is one repeatable cell under
a guard, so `;` and `⊓` go unexercised, and a reviewer will fairly ask why
process algebra is needed to check move legality. It also has no side effects on
the world, so it carries none of the motivation for constraining agents.

Which is why it is a **validation** task, not the headline: WebArena keeps the
stakes, Hanoi supplies clean measurement, headroom, and the generalisability
claim — the same engines, unchanged, across two domains.
