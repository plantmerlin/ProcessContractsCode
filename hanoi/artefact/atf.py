"""ATF/ADF/ACR I/O + JSON Schema validation against spec/schemas (ARTEFACT_SPEC 2, 3.6, 3.8)."""

import json
import hashlib
import os
import secrets
from pathlib import Path
from datetime import datetime, timezone

import jsonschema
from referencing import Registry, Resource

from .semantics import SEMANTICS_VERSION, DEFAULT_HOLD_BUDGET

ROOT = Path(__file__).resolve().parent.parent

# Schemas are the FILE FORMAT and are shared by every task.
SCHEMA_DIR = ROOT / "spec" / "schemas"

# The data stores are per-task. They used to be fixed at the repo root, so a
# second task's runs landed among the first task's and the packager pooled them.
# ARTEFACT_HOME relocates them; unset, everything behaves exactly as before.
HOME = Path(os.environ.get("ARTEFACT_HOME", ROOT))
RUNS = HOME / "runs"
ARTEFACTS = HOME / "artefacts"
REPORTS = HOME / "reports"


def _load_schemas():
    schemas = {}
    for name in ("atf.trace.schema.json", "adf.artefact.schema.json", "acr.report.schema.json"):
        schemas[name] = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    resources = [(s["$id"], Resource.from_contents(s)) for s in schemas.values()]
    registry = Registry().with_resources(resources)
    return {
        "atf": jsonschema.Draft202012Validator(schemas["atf.trace.schema.json"], registry=registry),
        "adf": jsonschema.Draft202012Validator(schemas["adf.artefact.schema.json"], registry=registry),
        "acr": jsonschema.Draft202012Validator(schemas["acr.report.schema.json"], registry=registry),
    }


_VALIDATORS = None


def validate(kind, obj):
    """kind in {atf, adf, acr}. Returns list of error strings (empty = valid)."""
    global _VALIDATORS
    if _VALIDATORS is None:
        _VALIDATORS = _load_schemas()
    return [f"{'/'.join(map(str, e.path))}: {e.message}"
            for e in _VALIDATORS[kind].iter_errors(obj)]


def canonical_json(obj):
    """Spec 4.1: UTF-8, sorted keys, no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def artefact_id(store_schema, cell_schema, scope, task_params=None,
                adapter_version=None):
    """D12: SHA-256 over canonical JSON of (store_schema, cell_schema, scope).

    This is a TASK-MODEL identity, not a content identity. It answers 'do these two
    contracts speak about the same world?' and is deliberately stable while the
    process term changes, which is what lets a contract be versioned rather than
    replaced. It CANNOT witness that a contract is unchanged: two contracts with
    different P, different alpha and different seeds share this id. Use
    content_hash() for that.
    """
    payload = canonical_json({"store_schema": store_schema,
                              "cell_schema": cell_schema, "scope": scope,
                              # The same schema can mean different things. A
                              # different target product, a different price
                              # limit, or a different projection implementation
                              # changes what the contract is ABOUT while leaving
                              # its shape identical, so all three belong in the
                              # identity of the task model.
                              "task_params": task_params or {},
                              "adapter_version": adapter_version or ""})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


TRANSLATOR_VERSION = "1.3.0"


def content_hash(adf):
    """SHA-256 over everything that determines what the contract admits.

    Covers the schema identity, the process term, the abstraction, the declared
    choice structure, the translator semantics that produced it, and the seed it
    was induced from. Two contracts agreeing on this hash accept exactly the same
    runs; two disagreeing on it may not, however equal their artefact_id.
    """
    payload = canonical_json({
        "artefact_id": adf.get("artefact_id"),
        "store_schema": adf.get("store_schema"),
        "cell_schema": adf.get("cell_schema"),
        "scope": adf.get("scope"),
        "alpha": adf.get("alpha"),
        "P": adf.get("P"),
        "external_choices": adf.get("external_choices"),
        "internal_choices": adf.get("internal_choices"),
        "translator_version": adf.get("translator_version", TRANSLATOR_VERSION),
        "semantics": adf.get("semantics", {"version": SEMANTICS_VERSION,
                                             "hold_budget": DEFAULT_HOLD_BUDGET}),
        "created_from_run": adf.get("created_from_run"),
        "composition": adf.get("composition"),
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_run_id(task, when=None):
    # compact time (no colons): run_id doubles as a directory name on Windows
    # 16 bits collide in practice at this corpus size; 128 does not.
    ts = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H%M%SZ")
    return f"{ts}_{task}_{secrets.token_hex(16)}"


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_run(envelope, span_lines):
    """Write a run package runs/<run_id>/{trace.json, spans.jsonl}. Validates ATF first."""
    errs = validate("atf", envelope)
    if errs:
        raise ValueError("ATF validation failed:\n" + "\n".join(errs))
    d = RUNS / envelope["run_id"]
    write_json(d / "trace.json", envelope)
    with (d / "spans.jsonl").open("w", encoding="utf-8") as f:
        for line in span_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return d


def load_run(run_id):
    d = RUNS / run_id
    trace = json.loads((d / "trace.json").read_text(encoding="utf-8"))
    spans = [json.loads(l) for l in (d / "spans.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return trace, spans


def load_adf(name):
    return json.loads((ARTEFACTS / f"{name}.adf.json").read_text(encoding="utf-8"))
