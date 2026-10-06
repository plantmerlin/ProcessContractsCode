"""Guard grammar S4 (ARTEFACT_SPEC 3.3) — parse, evaluate, render; post-assignments;
store typechecking. ASCII rendering throughout (D16): 'true', 'not f', 'f=1',
conjunction ' /\\ ', posts 'f:=v /\\ g:=w' or 'tau'."""

OPS = ("<=", ">=", "!=", "=", "<", ">")   # longest-first for parsing


def parse_value(tok):
    tok = tok.strip()
    if tok == "true":
        return True
    if tok == "false":
        return False
    try:
        return int(tok)
    except ValueError:
        try:
            return float(tok)
        except ValueError:
            return tok                       # enum / string literal


def render_value(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


def parse_literal(s):
    """-> (field, op, value, negated). op None => bare boolean field."""
    s = s.strip()
    neg = False
    if s.startswith("not "):
        neg, s = True, s[4:].strip()
    for op in OPS:
        if op in s:
            f, k = s.split(op, 1)
            return (f.strip(), op, parse_value(k), neg)
    return (s, None, None, neg)


def parse_guard(g):
    g = (g or "true").strip()
    if g == "true":
        return []
    return [parse_literal(p) for p in g.split("/\\")]


def guard_fields(g):
    return {lit[0] for lit in parse_guard(g)}


def eval_guard(g, store):
    for f, op, k, neg in parse_guard(g):
        if f not in store:
            return False
        v = store[f]
        if op is None:
            ok = bool(v)
            if neg:
                ok = not ok
        else:
            try:
                ok = {"=": v == k, "!=": v != k, "<": v < k,
                      "<=": v <= k, ">": v > k, ">=": v >= k}[op]
            except TypeError:      # ill-typed store value: guard is simply false
                ok = False         # (the SCHEMA pass reports the typing fault)
            if neg:                            # 'not f op k' is outside grammar
                return False
        if not ok:
            return False
    return True


def _enum_members(ftype):
    if isinstance(ftype, str) and ftype.startswith("enum[") and ftype.endswith("]"):
        return [m.strip() for m in ftype[5:-1].split(",")]
    return None


def typed_constant_errors(f, op, k, ftype):
    """Is the constant well typed for the field it is compared against?

    Checking only that the FIELD is declared leaves the determinism band
    unenforced: `n=abc` on an int, `s=3` on a string, `e=c` on an enum whose
    members are {a,b}, and `b=1` on a bool were all accepted, so guards outside
    the intended language reached signed contracts.
    """
    errs = []
    members = _enum_members(ftype)
    if op is None:
        if ftype != "bool":
            errs.append(f"bare literal on non-bool field '{f}' ({ftype})")
        return errs
    if op in ("<", "<=", ">", ">="):
        if ftype not in ("int", "number"):
            errs.append(f"ordering op '{op}' on non-numeric field '{f}' ({ftype})")
        elif not isinstance(k, (int, float)) or isinstance(k, bool):
            errs.append(f"ordering op '{op}' on '{f}' needs a numeric constant, got {k!r}")
        return errs
    # equality / inequality: the constant must inhabit the field's type
    if ftype == "bool" and not isinstance(k, bool):
        errs.append(f"'{f}' is bool but constant is {k!r}")
    elif ftype == "int" and (isinstance(k, bool) or not isinstance(k, int)):
        errs.append(f"'{f}' is int but constant is {k!r}")
    elif ftype == "number" and (isinstance(k, bool) or not isinstance(k, (int, float))):
        errs.append(f"'{f}' is number but constant is {k!r}")
    elif members is not None and k not in members:
        errs.append(f"'{f}' is {ftype} but constant {k!r} is not a member")
    elif ftype == "string" and not isinstance(k, str):
        errs.append(f"'{f}' is string but constant is {k!r}")
    return errs


def band_check(g, store_schema):
    """R9 mechanical: the guard must lie inside the determinism band.

    Every field declared; ordering only on numerics; bare literals only on
    bools; every comparison constant well typed for its field; and negation only
    of a bare boolean, since `not f op k` is outside the grammar.
    """
    errs = []
    for f, op, k, neg in parse_guard(g):
        if f not in store_schema:
            errs.append(f"guard field '{f}' not in store schema")
            continue
        if neg and op is not None:
            errs.append(f"negated comparison 'not {f}{op}...' is outside the grammar")
        errs += typed_constant_errors(f, op, k, store_schema[f])
    return errs


def _sat_interval(f, op, k, ftype):
    """Satisfying set of one literal over f, as (lo, hi) inclusive bounds for
    numerics or a set of admitted values otherwise. None = unconstrained."""
    if op in ("<", "<=", ">", ">=") and isinstance(k, (int, float)):
        if op == "<":
            return (None, k - 1 if ftype == "int" else k)
        if op == "<=":
            return (None, k)
        if op == ">":
            return (k + 1 if ftype == "int" else k, None)
        return (k, None)
    return None


def branches_disjoint(guards_list, store_schema):
    """Are these external-choice branch guards pairwise disjoint?

    External choice must be resolved uniquely by the state. `offers` unions the
    transitions of EVERY branch whose guard holds, so overlapping guards make
    the choice nondeterministic — which the intended semantics forbid, and which
    translation previously accepted without comment.

    Decided over the restricted literal/conjunction language by interval and
    equality reasoning; no solver is required.
    """
    def conj(g):
        return parse_guard(g)

    def overlap(g1, g2):
        lits = conj(g1) + conj(g2)
        by_field = {}
        for f, op, k, neg in lits:
            by_field.setdefault(f, []).append((op, k, neg))
        for f, cons in by_field.items():
            ftype = store_schema.get(f, "string")
            lo, hi, eq, neq, bools = None, None, set(), set(), set()
            for op, k, neg in cons:
                if op is None:
                    bools.add(not neg)
                    continue
                if op == "=":
                    (neq if neg else eq).add(k)
                elif op == "!=":
                    neq.add(k)
                else:
                    iv = _sat_interval(f, op, k, ftype)
                    if iv:
                        l, h = iv
                        if l is not None:
                            lo = l if lo is None else max(lo, l)
                        if h is not None:
                            hi = h if hi is None else min(hi, h)
            if len(bools) > 1:
                return False                       # requires f and not f
            if len(eq) > 1:
                return False                       # two different equalities
            if eq & neq:
                return False
            if lo is not None and hi is not None and lo > hi:
                return False                       # empty interval
            for v in eq:
                if isinstance(v, (int, float)):
                    if lo is not None and v < lo:
                        return False
                    if hi is not None and v > hi:
                        return False
        return True                                # a common witness may exist

    errs = []
    for i in range(len(guards_list)):
        for j in range(i + 1, len(guards_list)):
            if overlap(guards_list[i], guards_list[j]):
                errs.append(f"branch guards <{guards_list[i]}> and "
                            f"<{guards_list[j]}> are not disjoint")
    return errs


# ---- postconditions ---------------------------------------------------------

def parse_post(p):
    """'tau' -> {}; 'f:=v /\\ g:=w' -> {f: v, g: w}."""
    p = (p or "tau").strip()
    if p == "tau":
        return {}
    d = {}
    for part in p.split("/\\"):
        f, v = part.split(":=")
        d[f.strip()] = parse_value(v)
    return d


def render_pre(reads, store, field_order):
    """R1: enabling guard = literals over the reads-set evaluated in sigma_pre,
    canonical field order (D7)."""
    lits = []
    for f in field_order:
        if f not in reads:
            continue
        v = store[f]
        if v is True:
            lits.append(f)
        elif v is False:
            lits.append(f"not {f}")
        else:
            lits.append(f"{f}={render_value(v)}")
    return " /\\ ".join(lits) if lits else "true"


def render_post(delta_fields, post_store, field_order):
    asg = [f"{f}:={render_value(post_store[f])}"
           for f in field_order if f in delta_fields]
    return " /\\ ".join(asg) if asg else "tau"


def check_post_split(post_str, pre, post, unconstrained=()):
    """As check_post, but separating the two very different ways a post fails.

    `asserted` — the cell's declared effect was not observed. The action ran and
    achieved nothing, which is a FAILED ATTEMPT: the process has not moved, and
    the agent may try again (R12).
    `frame`    — a field the cell neither asserts nor releases changed anyway.
    That is not a failed attempt but an unaccounted-for effect, and it is a
    fault however many times it happens.

    Collapsing the two made every retry look like a violation to the verifier
    while the stepper treated it as a retry, so the two engines disagreed about
    the same run.
    """
    asg = parse_post(post_str)
    asserted, frame = [], []
    for f, v in asg.items():
        if post.get(f) != v:
            asserted.append((f, render_value(v), render_value(post.get(f))))
    for f in pre:
        if f in asg or f in unconstrained:
            continue
        if pre[f] != post.get(f):
            frame.append((f, f"unchanged({render_value(pre[f])})",
                          render_value(post.get(f))))
    return asserted, frame


def check_post(post_str, pre, post, unconstrained=()):
    """Verify an event's observed post against the cell's asserted post.
    Returns list of (field, expected, got) mismatches. Fields in `unconstrained`
    (R6 released branch fields) may change freely."""
    asg = parse_post(post_str)
    bad = []
    for f, v in asg.items():
        if post.get(f) != v:
            bad.append((f, render_value(v), render_value(post.get(f))))
    for f in pre:
        if f in asg or f in unconstrained:
            continue
        if pre[f] != post.get(f):
            bad.append((f, f"unchanged({render_value(pre[f])})", render_value(post.get(f))))
    return bad


# ---- store typing (SCHEMA class support) ------------------------------------

def typecheck(store_schema, store, where=""):
    errs = []
    for f, ftype in store_schema.items():
        if f not in store:
            errs.append(f"{where}: missing field '{f}'")
            continue
        v = store[f]
        if ftype == "bool" and not isinstance(v, bool):
            errs.append(f"{where}: '{f}' expected bool, got {v!r}")
        elif ftype == "int" and (isinstance(v, bool) or not isinstance(v, int)):
            errs.append(f"{where}: '{f}' expected int, got {v!r}")
        elif ftype == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
            errs.append(f"{where}: '{f}' expected number, got {v!r}")
        elif ftype == "string" and not isinstance(v, str):
            errs.append(f"{where}: '{f}' expected string, got {v!r}")
        elif ftype.startswith("enum["):
            allowed = ftype[5:-1].split(",")
            if not isinstance(v, str) or v not in allowed:
                errs.append(f"{where}: '{f}' expected one of {allowed}, got {v!r}")
    for f in store:
        if f not in store_schema:
            errs.append(f"{where}: undeclared field '{f}'")
    return errs
