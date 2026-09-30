"""Control-flow graph of a scene: basic blocks, labelled edges and a layered top-down layout.

No Tk here; graph.GraphTab draws what `build` and `layout` return.

Blocks. A block starts at the scene entry, at every branch / call / choice target, and after
every statement that jumps, calls, returns or ends the flow; it runs over consecutive
statements (pc + size) until the next such point.

Edges (source block -> target block, kind, label), from the block's last statement:
  BR_Z / BR_NZ       the taken branch and the fall-through, labelled true / false
                     (BR_Z jumps when its guard is 0, BR_NZ when it is not)
  JMP                one edge
  SWITCH             one edge per table slot (0, 1, ...) plus the fall-through "default";
                     SWITCH_CLAMP never falls through, its last slot takes every larger value
  JMP_RAND           one edge per target;  JMP_WEIGHTED  the same, labelled with the weight
  PROMPT_CHOICE(_F)  one edge per option (its text); PROMPT_CHOICE's CANCEL slot is left
                     out (never taken: the cancel key picks the last option)
  CALL               a "call" edge to the subroutine and the fall-through "return"
  RET_NZ             the fall-through "else" (the block also returns)
  RET                none (the block ends the scene or the subroutine)

Layout: the graph is split into groups -- the scene body and each CALLed subroutine (the
blocks reached from its root without following a CALL) -- and each is laid out on its own:
back edges (to a block still on the depth-first stack) are set aside, every other block goes
one layer below its lowest predecessor (longest path), the order inside a layer is improved
with barycentre sweeps, and each block sits under the median of its predecessors without
overlapping. The scene body goes on top, the subroutines in rows below it; a CALL is drawn
as a link to its subroutine's group, not as an arrow.
"""
from __future__ import annotations

from collections import OrderedDict

from rf4s_modkit import script

MAX_LINES = 14            # block text lines shown; the rest is "... N more"
MAX_CHARS = 64            # characters per line


class Block:
    __slots__ = ("start", "pcs", "edges", "returns", "layer", "order", "x", "y", "w", "h",
                 "lines", "link")

    def __init__(self, start):
        self.start = start
        self.pcs = []
        self.edges = []            # [(target block start, kind, label)]
        self.returns = False       # ends with RET / RET_NZ (leaves the scene or subroutine)
        self.layer = 0
        self.order = 0.0
        self.x = self.y = self.w = self.h = 0.0
        self.lines = []            # [(pc | None, text)]
        self.link = None           # a CALL block's subroutine (its last line links to it)


def _leaders(scene):
    st = scene.stmts
    lead = {scene.entry_pc} if scene.entry_pc in st else set()
    for pc, s in st.items():
        for t in s.code_targets:
            if t is not None and t in st:
                lead.add(t)
        if s.code_targets or not s.falls_through or s.terminator or s.mnem in ("RET_NZ",):
            nxt = pc + s.size
            if nxt in st:
                lead.add(nxt)
    return lead


def _edges(s, nxt, has, choice_text):
    """[(target, kind, label)] for a block ending with statement s (nxt = the pc after it,
    has(pc) = whether that pc is in the scene)."""
    out = []
    m = s.mnem
    tg = [t for t in s.code_targets]
    if m in ("BR_Z", "BR_NZ"):
        taken = "false" if m == "BR_Z" else "true"
        fall = "true" if m == "BR_Z" else "false"
        if tg and tg[0] is not None:
            out.append((tg[0], "yes" if taken == "true" else "no", taken))
        if s.falls_through and has(nxt):
            out.append((nxt, "yes" if fall == "true" else "no", fall))
        return out
    if m == "JMP":
        return [(t, "jmp", "") for t in tg if t is not None]
    if m in ("SWITCH", "SWITCH_CLAMP"):
        n = len(tg)
        for k, t in enumerate(tg):
            if t is not None:
                lab = ("%d+" % k) if (m == "SWITCH_CLAMP" and k == n - 1) else str(k)
                out.append((t, "case", lab))
        if s.falls_through and has(nxt):
            out.append((nxt, "case", "default"))
        return out
    if m == "JMP_RAND":
        return [(t, "case", "random %d" % k) for k, t in enumerate(tg) if t is not None]
    if m == "JMP_WEIGHTED":
        return [(t, "case", "weighted %d" % k) for k, t in enumerate(tg) if t is not None]
    if m in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
        cancel = m == "PROMPT_CHOICE"
        for k, item in enumerate(s.items or ()):
            ti = k + 1 if cancel else k
            if ti < len(tg) and tg[ti] is not None:
                txt = (choice_text(item) or "#%d" % item) if choice_text else "#%d" % item
                txt = txt.replace("\n", " ")
                out.append((tg[ti], "case", txt[:24] + ("…" if len(txt) > 24 else "")))
        return out
    if m == "CALL":
        if tg and tg[0] is not None:
            out.append((tg[0], "call", "call"))
        if has(nxt):
            out.append((nxt, "fall", "return"))
        return out
    if m == "RET_NZ":
        return [(nxt, "fall", "else")] if has(nxt) else []
    if s.falls_through and not s.terminator and has(nxt):
        return [(nxt, "fall", "")]
    return []


def build(scene, line_text=None, choice_text=None):
    """OrderedDict start pc -> Block for the scene (entry first). line_text(stmt) -> str
    gives each statement's text (default: its mnemonic); choice_text(line id) -> str names
    PROMPT_CHOICE options."""
    st = scene.stmts
    if not st:
        return OrderedDict()
    lead = _leaders(scene)
    has = st.__contains__
    blocks = OrderedDict()
    cur = None
    for pc, s in st.items():
        if cur is None or pc in lead or (cur.pcs and cur.pcs[-1] + st[cur.pcs[-1]].size != pc):
            cur = Block(pc)
            blocks[pc] = cur
        cur.pcs.append(pc)
    for b in blocks.values():
        last = st[b.pcs[-1]]
        nxt = last.pc + last.size
        b.edges = [(t, k, lab) for t, k, lab in _edges(last, nxt, has, choice_text) if t in blocks]
        b.returns = last.mnem in ("RET", "RET_NZ")
        lines = []
        for pc in b.pcs:
            txt = line_text(st[pc]) if line_text else st[pc].mnem
            txt = " ".join(txt.split())
            lines.append((pc, txt[:MAX_CHARS - 1] + "…" if len(txt) > MAX_CHARS else txt))
        if len(lines) > MAX_LINES:
            more = len(lines) - (MAX_LINES - 1)
            lines = lines[:MAX_LINES - 1] + [(None, "… %d more" % more)]
        call = next((t for t, k, _l in b.edges if k == "call"), None)
        if call is not None:
            b.link = call
            lines.append((None, "→ sub @%04x" % call))
        b.lines = lines
    # the entry block first (the scene's first statement may be a CALLed body before it)
    if scene.entry_pc in blocks:
        blocks.move_to_end(scene.entry_pc, last=False)
    return blocks


class Group:
    """One function of the graph: the scene body (the entry) or a CALLed subroutine."""
    __slots__ = ("root", "starts", "callers", "x", "y", "w", "h", "title")

    def __init__(self, root, starts, callers, title):
        self.root = root
        self.starts = starts
        self.callers = callers      # number of CALL sites that reach this subroutine
        self.title = title
        self.x = self.y = self.w = self.h = 0.0


GROUP_TITLE_H = 26.0              # room above a group's blocks for its title


def groups(blocks, entry):
    """[Group]: the scene body first, then every CALLed subroutine in the order the calls
    are met. A group holds the blocks reached from its root without following a CALL; a
    block reached from two groups belongs to the first. Blocks reached no such way end up
    in a last "not reached from the entry" group."""
    calls = {}
    order = [entry] if entry in blocks else []
    for b in blocks.values():
        for t, k, _l in b.edges:
            if k == "call":
                calls[t] = calls.get(t, 0) + 1
    owner = {}
    out = []
    i = 0
    while i < len(order):
        root = order[i]
        i += 1
        if root in owner:
            continue
        mine, stack = [], [root]
        while stack:
            s = stack.pop()
            if s in owner or s not in blocks:
                continue
            owner[s] = root
            mine.append(s)
            for t, k, _l in blocks[s].edges:
                if k == "call":
                    if t not in order:
                        order.append(t)
                else:
                    stack.append(t)
        mine.sort()
        n = calls.get(root, 0)
        title = ("scene @%04x" % root) if root == entry else (
            "sub @%04x  ·  called from %d place%s" % (root, n, "" if n == 1 else "s"))
        out.append(Group(root, mine, n, title))
    rest = sorted(s for s in blocks if s not in owner)
    if rest:
        out.append(Group(rest[0], rest, 0, "not reached from the entry"))
    return out


def _group_edges(sub, mine, s):
    return [e for e in sub[s].edges if e[1] != "call" and e[0] in mine]


def _layout_group(blocks, starts, root, hgap, vgap):
    """Layered layout of one group in its own coordinates (top-left 0, 0); CALL edges and
    edges leaving the group are ignored. Returns (back edges, width, height)."""
    mine = set(starts)
    sub = OrderedDict((s, blocks[s]) for s in starts)
    back = set()
    state = {}
    for r in [root] + [s for s in starts if s != root]:
        if r in state:
            continue
        stack = [(r, iter(_group_edges(sub, mine, r)))]
        state[r] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                continue
            t = nxt[0]
            if state.get(t) == 1:
                back.add((node, t))
            elif t not in state:
                state[t] = 1
                stack.append((t, iter(_group_edges(sub, mine, t))))
    preds = {s: [] for s in sub}
    succs = {s: [] for s in sub}
    for s in sub:
        for t, _k, _l in _group_edges(sub, mine, s):
            if (s, t) not in back and t != s and t not in succs[s]:
                succs[s].append(t)
                preds[t].append(s)
    # longest-path layers over the acyclic part (Kahn's order)
    indeg = {s: len(preds[s]) for s in sub}
    queue = [s for s in sub if indeg[s] == 0]
    queue.sort(key=lambda s: (s != root, s))
    layer = {s: 0 for s in sub}
    while queue:
        s = queue.pop(0)
        for t in succs[s]:
            layer[t] = max(layer[t], layer[s] + 1)
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    rows = {}
    for s, b in sub.items():
        b.layer = layer[s]
        rows.setdefault(b.layer, []).append(s)
    nlayers = max(rows) + 1
    for i in range(nlayers):
        for k, s in enumerate(rows.get(i, [])):
            sub[s].order = float(k)
    # barycentre sweeps: down by predecessors, up by successors
    for sweep in range(8):
        down = sweep % 2 == 0
        nb = preds if down else succs
        for i in (range(1, nlayers) if down else range(nlayers - 2, -1, -1)):
            row = rows.get(i, [])

            def key(s, nb=nb):
                ns = [sub[n].order for n in nb[s]]
                return (sum(ns) / len(ns)) if ns else sub[s].order
            row.sort(key=key)
            for k, s in enumerate(row):
                sub[s].order = float(k)
    # x: each layer goes under its predecessors (the median of their centres), keeping the
    # order and the gaps, then shifts as a whole so its blocks sit, on the median, where they
    # want to be -- nothing drifts sideways layer after layer
    def centre(s):
        return sub[s].x + sub[s].w / 2
    for i in range(nlayers):
        row = rows.get(i, [])
        want = []
        for s in row:
            ns = sorted(centre(n) for n in preds[s] if sub[n].layer < i)
            want.append(ns[len(ns) // 2] - sub[s].w / 2 if ns else None)
        x = None
        for k, s in enumerate(row):
            w = want[k]
            if x is None:
                x = w if w is not None else 0.0
            elif w is not None:
                x = max(x, w)
            sub[s].x = x
            x += sub[s].w + hgap
        offs = sorted(want[k] - sub[s].x for k, s in enumerate(row) if want[k] is not None)
        if offs:
            shift = offs[len(offs) // 2]
            for s in row:
                sub[s].x += shift
    x0 = min(b.x for b in sub.values())
    for b in sub.values():
        b.x -= x0
    y = 0.0
    for i in range(nlayers):
        row = rows.get(i, [])
        for s in row:
            sub[s].y = y
        y += (max(sub[s].h for s in row) if row else 0) + vgap
    return back, max(b.x + b.w for b in sub.values()), y - vgap


def layout(blocks, entry, size_of, hgap=40.0, vgap=56.0, row_width=None):
    """Place the blocks: sets b.layer, b.x, b.y (top-left), b.w, b.h, and lays the groups
    (the scene body, then its subroutines) out in rows under one another. size_of(block) ->
    (w, h). Returns (set of back edges, total width, total height, [Group])."""
    if not blocks:
        return set(), 0.0, 0.0, []
    for b in blocks.values():
        b.w, b.h = size_of(b)
    gs = groups(blocks, entry)
    back = set()
    for g in gs:
        gb, g.w, g.h = _layout_group(blocks, g.starts, g.root, hgap, vgap)
        back |= gb
        g.h += GROUP_TITLE_H
    # the scene body on top; the subroutines in rows below it, wrapped at row_width
    limit = row_width or max(2400.0, gs[0].w)
    gap = 3 * hgap
    x = y = row_h = 0.0
    for n, g in enumerate(gs):
        if n == 1 or (n > 1 and x > 0 and x + g.w > limit):
            y += row_h + 2 * vgap
            x = row_h = 0.0
        g.x, g.y = x, y
        x += g.w + gap
        row_h = max(row_h, g.h)
        for s in g.starts:
            blocks[s].x += g.x
            blocks[s].y += g.y + GROUP_TITLE_H
    width = max(g.x + g.w for g in gs)
    height = max(g.y + g.h for g in gs)
    return back, width, height, gs


def block_of(blocks, pc):
    """The start of the block holding statement pc, or None."""
    for s, b in blocks.items():
        if pc in b.pcs:
            return s
    return None


def scene_graph(scene, line_text=None, choice_text=None):
    """build() for a scene straight from rf4s_modkit.script (tests, the CLI)."""
    return build(scene, line_text or (lambda s: script.opcode_mnemonic(s.op) if s.op < 0xFFF0
                                       else s.mnem), choice_text)
