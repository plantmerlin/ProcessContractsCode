"""Tower of Hanoi. The environment rejects illegal and impossible moves."""

PEGS = ("A", "B", "C")


class Hanoi:
    def __init__(self, n=6, goal="C"):
        self.n = n
        self.goal = goal
        # each peg is a list, bottom first
        self.pegs = {"A": list(range(n, 0, -1)), "B": [], "C": []}

    def render(self):
        lines = []
        for p in PEGS:
            top_first = list(reversed(self.pegs[p]))
            lines.append(f"{p} (top to bottom): "
                         + (" ".join(str(d) for d in top_first) if top_first else "-"))
        return "\n".join(lines)

    def peg_of(self, disk):
        for p in PEGS:
            if disk in self.pegs[p]:
                return p
        return None

    def solved(self):
        return self.pegs[self.goal] == list(range(self.n, 0, -1))

    # ---- the monitor's projection -------------------------------------------
    def can_move_top(self, frm, to):
        """May the disk currently on top of `frm` be placed on `to`?

        Note this is about the TOP of a peg, not a named disk. That matches the
        cell vocabulary (`move_ab` = "move the top of A onto B") and it is why
        six predicates suffice however many disks there are.
        """
        if frm == to or frm not in self.pegs or to not in self.pegs:
            return False
        if not self.pegs[frm]:
            return False
        return not self.pegs[to] or self.pegs[to][-1] > self.pegs[frm][-1]

    def observe(self):
        """sigma — the typed store the contract is written over.

        NOT what the agent sees. `render()` gives the agent the configuration;
        this adds the derived predicates the guards need. Handing these to the
        agent would give away the judgement the contract exists to make.

        The legality rule is derived here rather than written as a guard because
        it is relational — it compares two parts of the store — and contains a
        disjunction, so it falls outside the guard language
        `true | literal | G /\\ G`. Same treatment `price_ok` gets in the
        shopping task.
        """
        st = {f"legal_{f}{t}".lower(): self.can_move_top(f, t)
              for f in PEGS for t in PEGS if f != t}
        st["config"] = "|".join(
            ("".join(str(d) for d in self.pegs[p]) or "-") for p in PEGS)
        st["solved"] = self.solved()
        return st

    def cell(self, disk, to):
        """Which contract cell does this request classify to, if any?

        `move_xy` means "move the top of X onto Y". A request naming a disk that
        is NOT on top of its peg is therefore not this cell — it is not in the
        vocabulary at all, and classifies to nothing.

        So the two rules are carried differently, which is deliberate:
          rule 1 (only the top disk moves)  -> CLASSIFICATION: what counts as a
                                               well-formed move
          rule 2 (never onto a smaller disk) -> the GUARD `legal_xy`: when a
                                               well-formed move is permitted
        """
        frm = self.peg_of(disk)
        if frm is None or to not in PEGS or frm == to:
            return None
        if self.pegs[frm][-1] != disk:
            return None
        return f"move_{frm}{to}".lower()

    def move(self, disk, to):
        """Try to move `disk` onto peg `to`. Returns (ok, reason)."""
        if to not in PEGS:
            return False, f"no such peg: {to}"
        if not isinstance(disk, int) or not 1 <= disk <= self.n:
            return False, f"no such disk: {disk}"

        frm = self.peg_of(disk)
        if frm == to:
            return False, f"disk {disk} is already on {to}"
        if self.pegs[frm][-1] != disk:
            return False, f"disk {disk} is not on top of peg {frm}"
        if self.pegs[to] and self.pegs[to][-1] < disk:
            return False, f"disk {self.pegs[to][-1]} is smaller than disk {disk}"

        self.pegs[frm].pop()
        self.pegs[to].append(disk)
        return True, "ok"
