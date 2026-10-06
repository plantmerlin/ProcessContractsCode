# Tower of Hanoi — process contracts

Self-contained. Copy this folder anywhere and it runs: the engines are in
`artefact/`, the schemas in `spec/`, and `atf.py` resolves both relative to this
directory, so runs and contracts stay inside it.

## Requirements

Python 3.11+, and:

```bash
pip install openai-agents jsonschema referencing
export OPENAI_API_KEY=...
```

## Run

```bash
python run_hanoi.py                 # 1 undirected run, 3 disks
python run_hanoi.py 5 3             # 5 runs, 3 disks
python induce.py                    # build the contract from a seed run
ENFORCE=1 python run_hanoi.py 5 3   # 5 runs with the gate active
```

Environment variables: `MODEL_SNAPSHOT` (default `gpt-4o`), `MAX_TURNS`
(default 60), `PROMPT_VARIANT` (`with_rules` | `no_rules`), `ENFORCE`.

## What is here

| | |
|---|---|
| `world.py` | the puzzle. `move()` refuses illegal and impossible moves; `render()` is what the agent sees; `observe()` is σ, what the monitor sees |
| `run_hanoi.py` | prompt, `move`/`report` tools, the gate, ATF recording |
| `induce.py` | M1 — one recorded run becomes the contract |
| `tasks/hanoi3.task.json` | store schema, cells, guards, releases, scope |
| `artefacts/hanoi3.adf.json` | the induced contract |
| `artefact/` | translator, verifier, runtime stepper, direction renderer, and sequential composer |
| `spec/schemas/` | ATF / ADF / ACR file formats |
| `runs/` | current ATF run packages, one directory each |
| `traces/` | legacy pre-ATF exploratory traces; not accepted by the current verifier |
| `spec.md` | the executable Hanoi contract and its distinction from general Hanoi legality |
| `SEMANTICS.md` | frozen finite-trace semantics and the three paper propositions |
| `tests/test_semantics.py` | regression tests for pre-state guards, frame checks, HOLD, runtime/audit consistency, Hanoi, and composition |
| `SYSTEM.md` | the architecture, layer by layer |

`artefact/` and `spec/` are **copies**. Fixes made here do not reach the parent
project, and vice versa — if you change an engine, decide deliberately which
copy is authoritative.

## The design in four points

**The environment refuses illegal moves; the contract constrains the agent.**
`move` will not place a larger disk on a smaller one. What is left for the
contract is procedural: which action comes next, and whether the run may declare
itself finished.

**`observe()` is not shown to the agent.** It carries derived legality
predicates — the judgement the contract exists to make. The agent gets
`render()`, the position and nothing else.

**The contract is a recording.** `P` is the straight-line cell sequence of the
seed run, so conformance means replicating it. It captures *one solution*, not
the rules of Hanoi: a different legal solve is rejected. That is deliberate.

**Execution events and interventions are distinct evidence.** An operation that
crosses the runtime boundary is an event even when the environment refuses its
state change (`applied: false`). A proposal refused by the gate before dispatch
never reaches the world, so it is an *intervention*, not an execution event. The
operation ledger retains both kinds of proposal.

## Reading a result

```
[00] completed  moves=7  blocked=0  refused=4  solved=Y  events=8
```

`blocked` — the world refused (unenforced runs).
`refused` — the gate refused before the world was touched (enforced runs).
`<- SEED CANDIDATE` — solved with no blocked moves, so it can be induced from.

With the gate on, structural/precondition departures are prevented before
execution, while the auditor still independently checks the literal executed
trace, post/frame obligations, trace integrity, and completeness. `refused` is
therefore evidence of how often the agent attempted to leave the recorded path;
it is not substituted for the audit verdict.

## Stale

`PLAN.md` and `prompt.md` predate the current design (they describe a
`move(from, to)` interface and an undecided contract shape). Kept for history;
do not follow them.
