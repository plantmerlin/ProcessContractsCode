> **IGNORE THIS FILE — SUPERSEDED.** Kept for history only. It describes an earlier design (a `move(from, to)` interface and an undecided contract shape) that the project no longer follows. See `README.md` and `SYSTEM.md` for the current design.

# Agent prompt — Tower of Hanoi

The base prompt, shared by all three arms. `directed` appends the contract;
`enforced` appends the contract and the gate note. Nothing else differs.

## Base prompt (undirected)

```
You are solving a Tower of Hanoi puzzle.

There are three pegs, A, B and C, and 6 disks numbered 1 to 6, where 1 is the
smallest. Every disk starts on peg A. Finish with all 6 disks on peg C.

After each move you are shown the current position, written like this:

A (top to bottom): 1 2 3 4 5 6
B (top to bottom): -
C (top to bottom): -

Each line lists that peg's disks from the top of the stack down to the bottom.
A dash means the peg is empty.

Call report when you have finished.
```

## What is deliberately absent

No statement that a larger disk may not be placed on a smaller one, and no
statement that only the top disk of a peg may move. Those are the **process**
constraints, and supplying them in the prompt is what saturated the WebArena
experiment: the undirected prompt there spelled out the whole ordered procedure,
so the contract given to the directed arm was largely redundant and all three
tiers scored alike. Whatever the contract is supposed to contribute has to be
absent from the prompt, or the comparison measures nothing.

What is present is the objective, the notation, and how to finish — the same
division applied on WebArena, where the cart URL was kept in the prompt while
*what counts as verification* was withheld. Removing the notation would produce
runs that fail because the agent could not read the display, and a perception
failure recorded as a process violation is exactly the confound this domain was
chosen to eliminate.

The mechanics of issuing a move belong to the tool description
(`move(from, to)` moves the top disk of one peg onto another), not to the
prompt. That is capability, not process: it says what the action does, not which
actions are permitted.

The agent is never shown the derived legality flags. Those are the monitor's
state, and showing them would repeat the v12.1 defect of handing the agent the
judgement the contract exists to make. The display reports **what is there**,
never **what is permitted**.

## Open question: disk count

Six disks is 63 moves at optimum. That is likely to floor the baseline — models
degrade badly on Hanoi past four or five disks, and a floor is as uninformative
as the ceiling WebArena reached. Pilot 10 undirected runs at 3, 4 and 5 disks and
choose the depth where conformance sits around 50–70%, before committing to a
grid. The prompt is parameterised on disk count, so this costs nothing to vary.
