"""Sequential composition of process contracts.

The process language already supports P ; Q through ``op='seq'``. This module
lifts that operator to complete ADF contracts while preserving the shared typed
store and executable semantics.

The mathematical compatibility condition is chi_1 => iota_2. The executable
checker below is intentionally conservative: it proves the common cases in the
restricted guard language (right entry is ``true`` or every literal required by
it is already required by the left exit). If it cannot establish implication it
refuses to compose rather than guessing.
"""

from . import atf, guards
from .atf import artefact_id, validate

COMPOSER_VERSION = "1.0.0"


def _guard_implies_sufficient(premise, conclusion):
    if (conclusion or "true").strip() == "true":
        return True
    p = set(guards.parse_guard(premise))
    q = set(guards.parse_guard(conclusion))
    return q.issubset(p)


def _merge_cell_schema(left, right):
    out = dict(left)
    for action, schema in right.items():
        if action in out and out[action] != schema:
            raise ValueError(
                f"cell '{action}' has incompatible schemas in the two contracts")
        out[action] = schema
    return out


def compose_sequential(left, right, name, version="1.0.0"):
    """Return the sequential composition ``left ; right`` as a draft ADF.

    Preconditions:
      * identical typed store and projection field vocabulary;
      * identical executable semantics and adapter meaning;
      * compatible cell declarations for shared action names;
      * a mechanically established sufficient form of chi_1 => iota_2.
    """
    if left["store_schema"] != right["store_schema"]:
        raise ValueError("cannot compose contracts over different store schemas")
    if left.get("adapter_version") != right.get("adapter_version"):
        raise ValueError("cannot compose contracts produced by different observation adapters")
    if left.get("semantics") != right.get("semantics"):
        raise ValueError("cannot compose contracts with different executable semantics")

    lf = left.get("alpha", {}).get("projection_fields")
    rf = right.get("alpha", {}).get("projection_fields")
    if lf != rf:
        raise ValueError("cannot compose contracts with different projection vocabularies")

    exit1 = left["scope"]["exit_guard"]
    entry2 = right["scope"]["entry"]
    if not _guard_implies_sufficient(exit1, entry2):
        raise ValueError(
            f"boundary compatibility not established mechanically: <{exit1}> "
            f"does not syntactically imply <{entry2}>. Prove/encode a stronger "
            "interface condition before composing.")

    cell_schema = _merge_cell_schema(left["cell_schema"], right["cell_schema"])
    scope = {"entry": left["scope"]["entry"],
             "exit_guard": right["scope"]["exit_guard"]}
    left_ref = f"{left['artefact_id']}@{left['version']}#{left.get('content_hash','')}"
    right_ref = f"{right['artefact_id']}@{right['version']}#{right.get('content_hash','')}"

    adf = {
        "adf_version": "1.0",
        "artefact_id": artefact_id(left["store_schema"], cell_schema, scope,
                                   task_params={"composition": [left_ref, right_ref]},
                                   adapter_version=left.get("adapter_version")),
        "task_params": {"composition": [left_ref, right_ref]},
        "adapter_version": left.get("adapter_version"),
        "name": name,
        "version": version,
        "created_from_run": f"composition:{left_ref}|{right_ref}",
        "store_schema": left["store_schema"],
        "cell_schema": cell_schema,
        "scope": scope,
        "alpha": {
            "projection_fields": list(lf or left["store_schema"].keys()),
            "quotient": [],
            "naming_actual": "sequential-contract-composition",
            "initial_store": left.get("alpha", {}).get("initial_store"),
        },
        "semantics": dict(left["semantics"]),
        "P": {"op": "seq", "children": [left["P"], right["P"]]},
        "external_choices": list(left.get("external_choices", []))
                            + list(right.get("external_choices", [])),
        "internal_choices": list(left.get("internal_choices", []))
                            + list(right.get("internal_choices", [])),
        "composition": {"operator": "seq", "version": COMPOSER_VERSION,
                        "left": left_ref, "right": right_ref},
        "signoff": {"status": "draft"},
        "provenance": "declared",
        "translator_version": atf.TRANSLATOR_VERSION,
    }
    adf["content_hash"] = atf.content_hash(adf)
    errs = validate("adf", adf)
    if errs:
        raise ValueError("composed ADF validation failed:\n" + "\n".join(errs))
    return adf
