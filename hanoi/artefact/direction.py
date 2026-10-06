"""direction.py — render an ADF's process term P into agent instructions.

This is 'soft pre-guiding': the artefact ITSELF is shown to the agent as the
intended process (auto-generated, never hand-written), sitting between
undirected prompting and hard stepper enforcement (M5 drive mode).
"""


def render_direction_browser(adf):
    """Render P for a GENERIC-CAPABILITY browser agent: UI cells are things the
    agent DOES; API-layer cells are marked as automatic consequences of the
    preceding UI action (the agent cannot issue them directly). Auto-generated
    from the ADF."""
    layers = {a: cs.get("layer", "UI") for a, cs in adf["cell_schema"].items()}
    lines = []

    def guard_txt(g):
        return "" if g == "true" else f"   [only when: {g}]"

    def walk(n, indent):
        pad = "  " * indent
        op = n["op"]
        if op == "cell":
            if layers.get(n["action"]) == "API":
                lines.append(f"{pad}  ({n['action']} — happens automatically as a "
                             f"result of the action above)")
            else:
                lines.append(f"{pad}- {n['action']}{guard_txt(n['pre'])}")
        elif op == "seq":
            for c in n["children"]:
                walk(c, indent)
        elif op == "call":
            lines.append(f"{pad}{n['name']}:")
            for c in n["cells"]:
                walk(c, indent + 1)
        elif op == "ext":
            lines.append(f"{pad}- then, based on what the SEARCH ACTUALLY "
                         f"RETURNED (never assume in advance):")
            for b in n["branches"]:
                lines.append(f"{pad}    if {b['guard']}:")
                walk(b["node"], indent + 3)
        elif op == "int":
            opts = n["options"]
            empties = [o for o in opts if o["op"] == "seq" and not o["children"]]
            if empties and len(opts) == 2:
                real = next(o for o in opts if o not in empties)
                walk(real, indent)
            else:
                lines.append(f"{pad}- choose ONE of:")
                for i, o in enumerate(opts, 1):
                    lines.append(f"{pad}    option {i}:")
                    walk(o, indent + 3)

    walk(adf["P"], 0)
    return (
        "INTENDED PROCESS (the signed task artefact "
        f"{adf['name']} v{adf['version']}). Follow it EXACTLY, using the "
        "generic browser actions available to you:\n"
        "- work top-to-bottom; never jump ahead to a later step;\n"
        "- lines in (parentheses) are automatic — do not try to perform them;\n"
        "- never take a step whose [only when: ...] condition is not yet true;\n"
        "- call report only at the end, after actually performing the steps.\n\n"
        + "\n".join(lines)
    )


def render_direction_intent(adf, name_map=None):
    """Render P at INTENT level: one line per sub-artefact call (= one agent
    tool), with the group's entry guard and its internal cascade summarised.
    Still auto-generated from the ADF — never hand-written."""
    name_map = name_map or {}
    lines = []

    def first_guard(cells):
        for c in cells:
            if c.get("op") == "cell" and not c.get("hidden") and c["pre"] != "true":
                return c["pre"]
        return None

    def visible(cells):
        out = []
        for c in cells:
            if c.get("op") == "cell":
                out.append(c["action"])
            elif c.get("op") == "int":
                for o in c["options"]:
                    out += visible(o.get("children", []))
            elif c.get("op") == "ext":
                pass
        return out

    def call_line(node, pad=""):
        name = name_map.get(node["name"], node["name"])
        g = first_guard(node["cells"])
        req = f"   [requires: {g}]" if g else ""
        ext = next((c for c in node["cells"] if c.get("op") == "ext"), None)
        branch = ""
        if ext is not None:
            guards = " | ".join(b["guard"] for b in ext["branches"])
            branch = f"  (branches internally on its own result: {guards})"
        lines.append(f"{pad}- {name}{req}{branch}")

    def walk(node, pad=""):
        op = node["op"]
        if op == "seq":
            for c in node["children"]:
                walk(c, pad)
        elif op == "call":
            call_line(node, pad)
        elif op == "par":
            sync = ", ".join(node["sync"])
            lines.append(f"{pad}- the next two steps may be interleaved in any "
                         f"order (they share: {sync}):")
            walk(node["left"], pad + "  ")
            walk(node["right"], pad + "  ")
        # skip/stop: nothing at intent level

    walk(adf["P"])
    return (
        "INTENDED PROCESS (the signed task artefact "
        f"{adf['name']} v{adf['version']}). Follow it EXACTLY:\n"
        "- perform the listed tool actions top-to-bottom, one per turn;\n"
        "- never fire a step whose [requires: ...] condition is not yet true;\n"
        "- a step that branches internally decides by its OWN result at the "
        "moment you run it — never assume its outcome in advance;\n"
        "- call report ONLY at the end position, after actually performing the "
        "steps before it;\n"
        "- do not perform any action that is not in this process.\n\n"
        + "\n".join(lines)
    )


def render_direction(adf, renderer="v1"):
    lines = []
    last_cell = {"name": None}

    def guard_txt(g):
        return "" if g == "true" else f"   [requires: {g}]"

    def walk(n, indent, optional=False):
        pad = "  " * indent
        op = n["op"]
        if op == "cell":
            opt = " (optional)" if optional else ""
            lines.append(f"{pad}- {n['action']}{opt}{guard_txt(n['pre'])}")
            last_cell["name"] = n["action"]
        elif op == "seq":
            for c in n["children"]:
                walk(c, indent, optional)
        elif op == "call":
            lines.append(f"{pad}{n['name']}:")
            for c in n["cells"]:
                walk(c, indent + 1)
        elif op == "ext":
            if renderer == "v2" and last_cell["name"]:
                lines.append(f"{pad}- ONLY IMMEDIATELY AFTER performing "
                             f"'{last_cell['name']}', branch on the result it "
                             f"just returned (do NOT evaluate these branches "
                             f"before that step has run):")
            else:
                lines.append(f"{pad}- then branch on the observed state:")
            for b in n["branches"]:
                lines.append(f"{pad}    if {b['guard']}:")
                walk(b["node"], indent + 3)
        elif op == "int":
            opts = n["options"]
            empties = [o for o in opts if o["op"] == "seq" and not o["children"]]
            if empties and len(opts) == 2:
                real = next(o for o in opts if o not in empties)
                walk(real, indent, optional=True)
            else:
                lines.append(f"{pad}- choose ONE of the following:")
                for i, o in enumerate(opts, 1):
                    lines.append(f"{pad}    option {i}:")
                    walk(o, indent + 3)
        elif op == "par":
            sync = ", ".join(n["sync"])
            lines.append(f"{pad}- the next two groups may be interleaved in any "
                         f"order (they share: {sync}):")
            walk(n["left"], indent + 1)
            walk(n["right"], indent + 1)
        elif op == "stop":
            lines.append(f"{pad}- STOP here (task is partial); do nothing further")
        # skip: nothing to render

    walk(adf["P"], 0)
    extra = ""
    if renderer == "v2":
        extra = ("- start at the TOP and work strictly downward; never jump ahead "
                 "to a later step or branch;\n"
                 "- a branch belongs to the step directly above it and is decided "
                 "by that step's actual result, never by assumption;\n"
                 "- call report ONLY at a position where it appears in the "
                 "process, after actually performing the steps before it.\n")
    return (
        "INTENDED PROCESS (the signed task artefact "
        f"{adf['name']} v{adf['version']}). Follow it EXACTLY:\n"
        "- perform the listed tool actions top-to-bottom, one per turn;\n"
        "- steps marked (optional) may be skipped, all other steps are required;\n"
        "- never fire a step whose [requires: ...] condition is not yet true;\n"
        "- do not perform any action that is not in this process.\n"
        + extra + "\n"
        + "\n".join(lines)
    )
