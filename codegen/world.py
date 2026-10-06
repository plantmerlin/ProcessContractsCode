"""world.py — a generic code-creation environment.

ONE process, any program. A task SPEC supplies three things as plain data:

    prompt           what the code should do
    test_input       a value to run it on
    expected_output  what a correct program returns for that input

The world knows nothing about sorting, strings or numbers. It creates a file,
stores whatever source the agent writes, runs it on the test input, and reduces
the result to a single boolean: did the program return the expected output.

The source itself is NOT checked. What the agent writes is the non-deterministic
part of the process — there are unboundedly many correct programs and no
feasible way to verify one against a natural-language description while the
contract is operating. So the contract governs the process around the code, and
correctness enters only as the test boolean.

Two decisions carried over from Hanoi:

**The world does not police the process.** It will run a file nobody verified
and accept a report at any time. The one thing it refuses is the impossible:
writing into a file that does not exist, running a file with nothing in it,
checking a result that was never produced.

**render() and observe() are different.** render() is what the agent sees.
observe() is sigma. The test boolean is revealed to the agent ONLY by
verify_result — executing shows the program's raw output, verifying compares it
with the expectation. So an agent that skips verification genuinely does not
know whether its program passed, which is what makes skipping it a real
departure rather than a formality.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 5
ENTRY = "solve"

# Appended at execution time. The agent writes a function; the harness feeds it
# the test input and captures the return value. Input/output plumbing is not
# what is being measured.
RUNNER_STUB = (
    "\n\nif __name__ == '__main__':\n"
    "    import json as _j, sys as _s\n"
    "    print(_j.dumps(" + ENTRY + "(_j.loads(_s.stdin.read()))))\n"
)


class CodeWorld:
    def __init__(self, spec, workdir=None):
        self.spec = spec
        self.filename = spec.get("filename", "solution.py")
        # resolved: the directory is also the subprocess cwd, so a relative path
        # would be re-resolved against itself and the script would vanish
        self.dir = Path(workdir or tempfile.mkdtemp(prefix="codegen_")).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

        self.file_created = False
        self.source = None
        self.executed = False
        self.exit_status = None
        self.stdout = ""
        self.stderr = ""
        self.output = None
        self.output_parsed = False
        self.verified = False

    @property
    def path(self):
        return self.dir / self.filename

    def _passed(self):
        return (self.executed and self.exit_status == 0 and self.output_parsed
                and self.output == self.spec["expected_output"])

    # ---- the agent's view -------------------------------------------------
    def render(self):
        lines = [f"file {self.filename}: "
                 + ("exists" if self.file_created else "does not exist")]
        if self.source is not None:
            lines.append(f"source: {len(self.source.splitlines())} lines")
        if self.executed:
            lines.append(f"last run on the test input: exit status "
                         f"{self.exit_status}")
            if self.stdout.strip():
                lines.append(f"returned: {self.stdout.strip()[:300]}")
            if self.stderr.strip():
                lines.append(f"stderr: {self.stderr.strip()[-400:]}")
        if self.verified:
            lines.append("verification: "
                         + ("PASSED - the output matches the expected result"
                            if self._passed() else
                            "FAILED - the output does not match the expected "
                            f"result {json.dumps(self.spec['expected_output'])}"))
        return "\n".join(lines)

    # ---- the monitor's projection ----------------------------------------
    def observe(self):
        return {
            "file_exists": self.file_created,
            "source_written": self.source is not None,
            "executed": self.executed,
            "exit_ok": self.exit_status == 0,
            "test_passed": bool(self._passed()),
            "verified": self.verified,
        }

    # ---- operations -------------------------------------------------------
    def create_file(self, filename):
        if filename != self.filename:
            return False, f"the file for this task is {self.filename}"
        self.path.write_text("", encoding="utf-8")
        self.file_created = True
        return True, "ok"

    def write_source(self, source):
        if not self.file_created:
            return False, "the file does not exist"
        if not isinstance(source, str) or not source.strip():
            return False, "no source given"
        self.source = source
        self.path.write_text(source, encoding="utf-8")
        # a rewrite invalidates anything learned about the previous source
        self.executed, self.exit_status = False, None
        self.stdout = self.stderr = ""
        self.output, self.output_parsed, self.verified = None, False, False
        return True, "ok"

    def execute_program(self):
        """Run the file on the test input in a subprocess with a hard timeout.
        The agent's code is never imported into this process."""
        if self.source is None:
            return False, "there is no source to run"
        runnable = self.dir / ("_run_" + self.filename)
        runnable.write_text(self.source + RUNNER_STUB, encoding="utf-8")
        try:
            p = subprocess.run(
                [sys.executable, str(runnable)],
                input=json.dumps(self.spec["test_input"]),
                capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS, cwd=str(self.dir))
            self.exit_status, self.stdout, self.stderr = (
                p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired:
            self.exit_status = 124
            self.stdout, self.stderr = "", f"timed out after {TIMEOUT_SECONDS}s"
        self.executed = True
        self.verified = False
        self.output, self.output_parsed = None, False
        if self.exit_status == 0:
            try:
                self.output = json.loads(self.stdout.strip())
                self.output_parsed = True
            except (ValueError, TypeError):
                pass
        return True, "ok"

    def verify_result(self):
        """Compare the returned value with the expected output.

        Recording that the check was DONE is separate from whether it PASSED:
        `verified` says the agent looked, `test_passed` says what it found. A
        failed verification is still a verification.
        """
        if not self.executed:
            return False, "the program has not been run"
        self.verified = True
        return True, "ok"

    # ---- classification ---------------------------------------------------
    def cell(self, kind, **kw):
        """The contract cell an operation classifies to, or None.

        Requests outside the vocabulary — the wrong filename, an empty write —
        classify to nothing and are refused fail-closed under enforcement.
        """
        if kind == "create_file":
            return "create_file" if kw.get("filename") == self.filename else None
        if kind == "write_source":
            src = kw.get("source")
            return "write_source" if isinstance(src, str) and src.strip() else None
        if kind in ("execute_program", "verify_result", "report"):
            return kind
        return None
