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
  PROMPT_CHOICE(_F)  one edge per option (its text), PROMPT_CHOICE's slot 0 = "cancel"
  CALL               a "call" edge to the subroutine and the fall-through "return"
  RET_NZ             the fall-through "else" (the block also returns)
  RET                none (the block ends the scene or the subroutine)

Layout: back edges (to a block still on the depth-first stack) are set aside; every other
block goes one layer below its lowest predecessor (longest path), the order inside a layer
is improved with barycentre sweeps, and x positions are relaxed towards the neighbours'
centres without overlapping.
"""
from __future__ import annotations

from collections import OrderedDict

from rf4s_modkit import script

MAX_LINES = 14            # block text lines shown; the rest is "... N more"
MAX_CHARS = 64            # characters per line


class Block:
    __slots__ = ("start", "pcs", "edges", "returns", "layer", "order", "x", "y", "w", "h",
                 "lines")

    def __init__(self, start):
        self.start = start
        self.pcs = []
        self.edges = []            # [(target block start, kind, label)]
        self.returns = False       # ends with RET / RET_NZ (leaves the scene or subroutine)
        self.layer = 0
        self.order = 0.0
        self.x = self.y = self.w = self.h = 0.0
        self.lines = []            # [(pc | None, text)]


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
        if cancel and tg and tg[0] is not None:
            out.append((tg[0], "case", "cancel"))
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
        b.lines = lines
    # the entry block first (the scene's first statement may be a CALLed body before it)
    if scene.entry_pc in blocks:
        blocks.move_to_end(scene.entry_pc, last=False)
    return blocks


def back_edges(blocks, entry):
    """{(src, dst)} of the edges that close a loop, found by an iterative depth-first walk
    from the entry, then from any block it did not reach."""
    back = set()
    state = {}                                  # 1 = on the stack, 2 = done
    roots = [entry] + [s for s in blocks if s != entry]
    for r in roots:
        if r not in blocks or r in state:
            continue
        stack = [(r, iter(blocks[r].edges))]
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
                stack.append((t, iter(blocks[t].edges)))
    return back


def layout(blocks, entry, size_of, hgap=40.0, vgap=56.0):
    """Place the blocks: sets b.layer, b.x, b.y (top-left), b.w, b.h. size_of(block) ->
    (w, h). Returns (set of back edges, total width, total height)."""
    if not blocks:
        return set(), 0.0, 0.0
    back = back_edges(blocks, entry)
    preds = {s: [] for s in blocks}
    succs = {s: [] for s in blocks}
    for s, b in blocks.items():
        for t, _k, _l in b.edges:
            if (s, t) not in back and t != s:
                succs[s].append(t)
                preds[t].append(s)
    # longest-path layers over the acyclic part (Kahn's order)
    indeg = {s: len(preds[s]) for s in blocks}
    queue = [s for s in blocks if indeg[s] == 0]
    queue.sort(key=lambda s: (s != entry, s))
    layer = {s: 0 for s in blocks}
    seen = 0
    while queue:
        s = queue.pop(0)
        seen += 1
        for t in succs[s]:
            layer[t] = max(layer[t], layer[s] + 1)
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    rows = {}
    for s, b in blocks.items():
        b.layer = layer[s]
        rows.setdefault(b.layer, []).append(s)
    nlayers = max(rows) + 1
    for i in range(nlayers):
        for k, s in enumerate(rows.get(i, [])):
            blocks[s].order = float(k)
    # barycentre sweeps: down by predecessors, up by successors
    for _sweep in range(6):
        for i in (range(1, nlayers) if _sweep % 2 == 0 else range(nlayers - 2, -1, -1)):
            nb = preds if _sweep % 2 == 0 else succs
            row = rows.get(i, [])
            def key(s):
                ns = [blocks[n].order for n in nb[s] if blocks[n].layer != blocks[s].layer]
                return (sum(ns) / len(ns)) if ns else blocks[s].order
            row.sort(key=key)
            for k, s in enumerate(row):
                blocks[s].order = float(k)
    for b in blocks.values():
        b.w, b.h = size_of(b)
    # x: pack each layer, then relax towards the neighbours' centres
    for i in range(nlayers):
        x = 0.0
        for s in rows.get(i, []):
            blocks[s].x = x
            x += blocks[s].w + hgap
    def centre(s):
        return blocks[s].x + blocks[s].w / 2
    for _it in range(12):
        for i in range(nlayers):
            row = rows.get(i, [])
            want = []
            for s in row:
                ns = preds[s] + succs[s]
                want.append(sum(centre(n) for n in ns) / len(ns) - blocks[s].w / 2 if ns else blocks[s].x)
            # keep order and gaps: push right, then pull left
            for k, s in enumerate(row):
                blocks[s].x = want[k]
            for k in range(1, len(row)):
                a, b = blocks[row[k - 1]], blocks[row[k]]
                if b.x < a.x + a.w + hgap:
                    b.x = a.x + a.w + hgap
            for k in range(len(row) - 2, -1, -1):
                a, b = blocks[row[k]], blocks[row[k + 1]]
                if a.x + a.w + hgap > b.x:
                    a.x = b.x - a.w - hgap
    x0 = min(b.x for b in blocks.values())
    for b in blocks.values():
        b.x -= x0
    y = 0.0
    for i in range(nlayers):
        row = rows.get(i, [])
        for s in row:
            blocks[s].y = y
        y += (max(blocks[s].h for s in row) if row else 0) + vgap
    width = max(b.x + b.w for b in blocks.values())
    return back, width, y - vgap


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
