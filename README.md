# Stateful Process Contracts for LLM Agents

Code and experimental data for *Right Step, Right State: Formalising Agent
Behaviour with Stateful Process Contracts*.

A **process contract** is induced from one recorded agent execution. It pairs
each step (a *cell*) with observable pre- and post-state obligations, so it can
tell "right step, right state" apart from "right step, wrong state". The same
contract semantics drive two mechanisms:

- a **runtime stepper**, which refuses an out-of-order or state-inadmissible
  operation before it reaches the environment, and
- a **post-hoc verifier**, which checks a recorded trace and classifies any
  failure (`STRUCTURAL`, `GUARD_PRE`, `GUARD_POST`, `COMPLETENESS`, plus
  trace-integrity classes).

Recorded executions are stored as **ATF** traces, contracts as **ADF**
artefacts, and conformance results as **ACR** reports. All three are
JSON-schema validated (`spec/schemas/`).

This repository holds two independent projects. Each folder is self-contained,
with its own copy of the engines (`artefact/`) and schemas (`spec/`).

```
process-contracts/
├── hanoi/          Tower of Hanoi: validation of the architecture (paper, Appendix B)
└── codegen/        code generation: the main evaluation in the paper
    ├── cross_task/     one contract, seven programming tasks
    └── enforcement/    targeted runtime-enforcement scenarios
```

---

## `hanoi/` — Tower of Hanoi

A small, deterministic environment for checking the whole pipeline end to end:
observation, classification, induction, runtime enforcement, intervention
recording, and post-hoc auditing. The agent (`gpt-4o`) solves a three-disk
puzzle through `move` and `report` tools. A contract is induced from one
undirected solve, then used to gate later runs and audit them.

Also included are the frozen semantics (`SEMANTICS.md`), the regression suite
(`tests/`), and a set of constructed traces covering every diagnostic class
(`failure_cases/`). See `hanoi/README.md` for details.

## `codegen/` — Code generation

The agent writes a Python `solve` function, runs it on a test input, and checks
it against an expected output, using five operations:
`create_file → write_source → execute_program → verify_result → report`.
One contract is induced from an undirected bubble-sort run (seed `…0c81`,
artefact `50bfde761acc`). It never mentions a specific program, and it is reused
unchanged for every run below. All runs use `gpt-4o` with parallel tool calls
off.

### `codegen/cross_task/` — does one contract generalise?

Seven tasks: bubble sort, binary insertion sort, FizzBuzz, run-length encoding,
balanced brackets, count islands, and order totals. Each task has 4 undirected
and 5 enforced runs (63 runs). All 63 conform and pass their test. Inducing a
contract from a successful run of each task gives the same process term
(`reports/_p_invariance.json`).

### `codegen/enforcement/` — does enforcement change behaviour?

- **Scenario A, verification shortcut.** The prompt says `verify_result` may be
  skipped. Runs are on `fizzbuzz` and `count_islands`, in three arms:
  undirected, enforced with a minimal refusal message, and enforced with a
  refusal that names the permitted next step.
- **Scenario B, natural failure cases.** Two tasks whose requirements are easy
  to miss: `round_half_away` and `title_case_small_words`. Runs are undirected
  and enforced.

### Layout

| | |
|---|---|
| `world.py` | the code environment (`observe()` is the monitor's typed state) |
| `make_specs.py` | the task specs and the single task definition |
| `run_codegen.py` | agent, tools, runtime gate, ATF recording |
| `induce_codegen.py` | contract induction plus the cross-task invariance check |
| `audit_codegen.py` | post-hoc conformance reports and summary tables |
| `<store>/runs/` | one ATF trace (plus model spans) per run |
| `<store>/artefacts/` | the contract used (identical in both stores) |
| `<store>/reports/` | ACR conformance reports and `_audit_summary.json` |

---

## Setup

Python 3.11 or later.

```bash
pip install -r codegen/requirements.txt
```

Audits, induction and the tests run offline. They only need `jsonschema` and
`referencing`. Live agent runs also need `openai-agents` and an
`OPENAI_API_KEY` set in your environment. No key is stored in this repository.

## Reproduce offline (no API key)

```bash
# Hanoi
cd hanoi
PYTHONPATH=. python -m unittest discover -s tests     # 9 tests OK
python failure_cases.py                               # 9/9 cases as expected
cd ..

# Code generation
cd codegen
ARTEFACT_HOME="$PWD/cross_task"  python audit_codegen.py        # 63 ACRs, all conform
ARTEFACT_HOME="$PWD/enforcement" python audit_codegen.py        # 43 ACRs
```

`ARTEFACT_HOME` chooses which run store a script reads from and writes to. In
PowerShell, set it first with `$env:ARTEFACT_HOME = "$PWD\cross_task"`.

`induce_codegen.py` overwrites the store's contract with a newly induced one.
To check the invariance result without changing the published contract, run it
on a copy of `cross_task/` and pass the seed suffix:
`ARTEFACT_HOME=<copy> python induce_codegen.py 0c81`.

## Live runs (needs `OPENAI_API_KEY`)

```bash
cd codegen
export PARALLEL_TOOL_CALLS=0

# cross-task
export ARTEFACT_HOME="$PWD/cross_task"
python run_codegen.py 4 count_islands                  # undirected
ENFORCE=1 python run_codegen.py 5 count_islands        # enforced

# Scenario A
export ARTEFACT_HOME="$PWD/enforcement"
PROMPT_VARIANT=shortcut_allowed python run_codegen.py 3 fizzbuzz
PROMPT_VARIANT=shortcut_allowed ENFORCE=1 python run_codegen.py 3 fizzbuzz
PROMPT_VARIANT=shortcut_allowed ENFORCE=1 REFUSAL_DETAIL=permitted python run_codegen.py 3 fizzbuzz

# Scenario B
python run_codegen.py 5 title_case_small_words
ENFORCE=1 python run_codegen.py 5 title_case_small_words
```

## Notes

- **Run with parallel tool calls off.** The runtime boundary is not
  serialised. If the model batches tool calls, two operations can interleave
  inside a single observe → execute → observe step and break trace integrity.
  All runs in this repository use `PARALLEL_TOOL_CALLS=0`.
- **Program execution is not sandboxed.** Generated code runs in a subprocess
  with a 5-second timeout and a scratch directory. There is no network,
  filesystem or resource isolation, so do not use this to run untrusted code.
- The data was produced on Python 3.14 with the package versions pinned in
  `requirements.txt`.

---

## Disclosure

Claude Code (Anthropic) was used in part to create this code base.
