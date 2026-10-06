"""Shared executable semantics for process contracts.

Keep constants that change the accepted trace language here so the runtime
stepper, post-hoc verifier, translator, and contract identity cannot drift.
"""

SEMANTICS_VERSION = "1.0.0"
DEFAULT_HOLD_BUDGET = 6

TRACE_INTEGRITY_CLASSES = frozenset({
    "SCHEMA", "CONTINUITY", "LEDGER_MISMATCH", "UNMEDIATED",
})
PROCESS_CONFORMANCE_CLASSES = frozenset({
    "STRUCTURAL", "GUARD_PRE", "GUARD_POST", "COMPLETENESS",
})


def finding_family(cls):
    if cls in TRACE_INTEGRITY_CLASSES:
        return "TRACE_INTEGRITY"
    if cls in PROCESS_CONFORMANCE_CLASSES:
        return "PROCESS_CONFORMANCE"
    # Runtime-only diagnostics can still surface in development builds without
    # silently pretending they are one of the formal paper classes.
    return "IMPLEMENTATION"
