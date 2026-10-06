"""make_specs.py — the task specs, and the ONE task definition.

A spec is data: a prompt describing the program, a test input, and the expected
output for that input. Specs are what vary. The task definition — store, cells,
guards, exit guard — is what does not, and there is exactly one of it.

The task definition deliberately carries no `target`. Contract identity
(artefact_id) folds in task parameters from that field, so leaving it empty is
what makes the SAME contract, with the same hash, govern every spec. The spec a
run used is recorded on the run's trace instead.

    python make_specs.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AND = " /\\ "


def rle(s):
    out, i = [], 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        out.append(f"{s[i]}{j - i}")
        i = j
    return "".join(out)


def fizzbuzz(n):
    return ["FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else
            "Buzz" if i % 5 == 0 else str(i) for i in range(1, n + 1)]


def balanced(s):
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


def islands(grid):
    g = [row[:] for row in grid]
    n = 0
    for r in range(len(g)):
        for c in range(len(g[0])):
            if g[r][c] == 1:
                n += 1
                todo = [(r, c)]
                while todo:
                    y, x = todo.pop()
                    if 0 <= y < len(g) and 0 <= x < len(g[0]) and g[y][x] == 1:
                        g[y][x] = 0
                        todo += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
    return n


def order_totals(orders):
    out = {}
    for o in orders:
        if o["status"] == "cancelled":
            continue
        out[o["customer"]] = out.get(o["customer"], 0) + o["qty"] * o["unit_cents"]
    return out


BRACKETS = ["()", "([]{})", "(]", "((())", "{[()()]}", "", "([)]", "}{"]
GRID = [[1, 1, 0, 0, 1, 0],
        [1, 0, 0, 1, 0, 0],
        [0, 0, 1, 1, 0, 1],
        [0, 1, 0, 0, 0, 1],
        [1, 1, 0, 1, 0, 0]]
ORDERS = [
    {"customer": "ana",  "item": "pen",   "qty": 3, "unit_cents": 150, "status": "paid"},
    {"customer": "ben",  "item": "book",  "qty": 1, "unit_cents": 1299, "status": "paid"},
    {"customer": "ana",  "item": "paper", "qty": 2, "unit_cents": 499, "status": "cancelled"},
    {"customer": "cara", "item": "pen",   "qty": 10, "unit_cents": 150, "status": "paid"},
    {"customer": "ben",  "item": "ink",   "qty": 2, "unit_cents": 725, "status": "pending"},
    {"customer": "ana",  "item": "book",  "qty": 1, "unit_cents": 1299, "status": "paid"},
    {"customer": "dev",  "item": "pen",   "qty": 5, "unit_cents": 150, "status": "cancelled"},
]


def round_half_away(xs):
    import math
    return [int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1) for x in xs]


SMALL = {"a", "an", "and", "of", "the", "in", "on"}


def title_small(phrase):
    words = phrase.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in SMALL and 0 < i < len(words) - 1:
            out.append(lw)
        else:
            out.append(lw[:1].upper() + lw[1:])
    return " ".join(out)


ROUNDING = [0.5, 1.5, 2.5, -0.5, -2.5, 3.2, -3.7]
PHRASES = ["the lord of the rings", "a tale OF two cities", "war and peace",
           "of mice and men", "what the wind blew in"]


SORT_INPUT = [5, 3, 8, 1, 9, 2, 7, 4, 6]

SPECS = {
    "bubble_sort": {
        "prompt": ("Implement bubble sort. `solve(xs)` takes a list of integers "
                   "and returns a new list containing the same integers in "
                   "ascending order, sorted using the bubble sort algorithm."),
        "test_input": SORT_INPUT,
        "expected_output": sorted(SORT_INPUT),
    },
    "binary_insertion_sort": {
        "prompt": ("Implement binary insertion sort. `solve(xs)` takes a list of "
                   "integers and returns a new list containing the same integers "
                   "in ascending order, sorted by insertion sort where each "
                   "insertion position is found by binary search."),
        "test_input": SORT_INPUT,
        "expected_output": sorted(SORT_INPUT),
    },
    "fizzbuzz": {
        "prompt": ("Implement FizzBuzz. `solve(n)` takes a positive integer n and "
                   "returns a list of strings for the numbers 1 to n: 'Fizz' for "
                   "multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for "
                   "multiples of both, and the number itself as a string "
                   "otherwise."),
        "test_input": 15,
        "expected_output": fizzbuzz(15),
    },
    "run_length_encoding": {
        "prompt": ("Implement run-length encoding. `solve(s)` takes a string and "
                   "returns a string in which each run of a repeated character is "
                   "replaced by the character followed by the length of the run. "
                   "For example 'aab' becomes 'a2b1'."),
        "test_input": "aaabccddddde",
        "expected_output": rle("aaabccddddde"),
    },
    # ---- new tasks, run against the existing contract unchanged -------------
    "balanced_brackets": {
        "prompt": ("Check bracket balance. `solve(strings)` takes a list of "
                   "strings made of the characters ()[]{} and returns a list of "
                   "booleans, one per string: true if every bracket is closed by "
                   "the matching type in the correct order, false otherwise. The "
                   "empty string is balanced."),
        "test_input": BRACKETS,
        "expected_output": [balanced(x) for x in BRACKETS],
    },
    "count_islands": {
        "prompt": ("Count islands. `solve(grid)` takes a rectangular grid (a list "
                   "of lists) of 0s and 1s and returns the number of islands. An "
                   "island is a group of 1s connected horizontally or vertically. "
                   "Cells that touch only diagonally are NOT connected."),
        "test_input": GRID,
        "expected_output": islands(GRID),
    },
    "order_totals": {
        "prompt": ("Total customer spending. `solve(orders)` takes a list of order "
                   "records, each an object with keys customer, item, qty, "
                   "unit_cents and status. Return an object mapping each customer "
                   "to the total of qty * unit_cents over their orders, ignoring "
                   "any order whose status is \"cancelled\". A customer whose "
                   "orders are all cancelled does not appear in the result."),
        "test_input": ORDERS,
        "expected_output": order_totals(ORDERS),
    },
    # ---- enforcement demonstration: specs whose OBVIOUS implementation fails ---
    # The requirement is stated plainly; only the obvious code is wrong. They exist
    # to produce a failing test so the fix loop can be observed with and without
    # the gate.
    "round_half_away": {
        "prompt": ("Round numbers. `solve(xs)` takes a list of numbers and returns "
                   "a list of integers, each number rounded to the nearest integer. "
                   "Exact halves must round AWAY FROM ZERO: 2.5 becomes 3 and -2.5 "
                   "becomes -3."),
        "test_input": ROUNDING,
        "expected_output": round_half_away(ROUNDING),
    },
    "title_case_small_words": {
        "prompt": ("Title-case phrases. `solve(phrases)` takes a list of phrases and "
                   "returns them title-cased: each word starts with a capital letter "
                   "and the rest of the word is lowercase, EXCEPT that the small words "
                   "a, an, and, of, the, in, on are entirely lowercase - unless the "
                   "small word is the first or the last word of the phrase."),
        "test_input": PHRASES,
        "expected_output": [title_small(x) for x in PHRASES],
    },
}

FIELDS = ["file_exists", "source_written", "executed", "exit_ok",
          "test_passed", "verified"]

# (guard, reads). No releases: every field is a boolean that each cell moves in
# exactly the same way whatever program is being written, so the seed's observed
# changes are the right postconditions for EVERY spec. That independence from
# the program's content is the whole reason one contract can serve them all.
CELLS = {
    "create_file":     ("true",           []),
    "write_source":    ("file_exists",    ["file_exists"]),
    "execute_program": ("source_written", ["source_written"]),
    "verify_result":   ("executed",       ["executed"]),
}


def task_definition():
    cells = {}
    for c, (pre, reads) in CELLS.items():
        e = {"type": "action", "layer": "SYS", "group": "build", "reads": reads}
        if pre != "true":
            e["pre_override"] = pre
        cells[c] = e
    cells["report"] = {"type": "report", "layer": "SYS", "group": "finish",
                       "reads": ["verified"], "pre_override": "verified"}
    return {
        "task": "codegen",
        "adapter_version": "codegen/1.0.0",
        "store_schema": {f: "bool" for f in FIELDS},
        "cell_schema": cells,
        # Step guards carry PROCESS POSITION. The exit guard carries the one
        # piece of WORLD CORRECTNESS the process can check: the test boolean.
        "scope": {"entry": "true",
                  "exit_guard": "verified" + AND + "test_passed"},
        "initial_store": {f: False for f in FIELDS},
        "note": ("ONE contract for every spec. Process: create_file -> "
                 "write_source -> execute_program -> verify_result -> report. "
                 "The program written is not checked; correctness enters only "
                 "as test_passed."),
    }


def main():
    (HERE / "specs").mkdir(exist_ok=True)
    (HERE / "tasks").mkdir(exist_ok=True)
    for old in (HERE / "tasks").glob("*.task.json"):
        old.unlink()
    for name, s in SPECS.items():
        spec = {"spec": name, "filename": "solution.py", **s}
        (HERE / "specs" / f"{name}.json").write_text(
            json.dumps(spec, indent=1), encoding="utf-8")
        print(f"spec  {name:22} input={json.dumps(s['test_input'])[:34]:36} "
              f"expected={json.dumps(s['expected_output'])[:40]}")
    (HERE / "tasks" / "codegen.task.json").write_text(
        json.dumps(task_definition(), indent=1), encoding="utf-8")
    print("\ntask  codegen (one definition for all specs)")
    for c, (pre, _) in CELLS.items():
        print(f"   <{pre:15}> {c}")
    print(f"   <{'verified':15}> report")
    print(f"   exit guard: verified{AND}test_passed")


if __name__ == "__main__":
    main()
