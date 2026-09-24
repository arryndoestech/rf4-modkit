"""rf4s_modkit/route.py -- the NPC town-navigation graph (`rf3route.bin`, archive 15214, magic
"TRCS") and its precomputed next-hop matrix (`rf3RouteResult.bin`, archive 15215, headerless).
Decode, JSON round trip, byte-exact rebuild, path walk, matrix regeneration.

IDB-verified 2026-09-19: loader `ScheduleMng_TaskCtor` RF4S.exe+0x230010 (accepts the file only
when +0 == 0x53435254 "TRCS" and +4 == 0x00010002, then copies the three u16 counts and three
section offsets into the schedule work buffer); consumers `Nav_FindNearestNodeInGroup`
+0x2316A0 (room group -> nearest node, octagonal distance, optional line-of-sight) and
`Nav_BuildPathFromAToB` +0x231060 (walks the next-hop matrix hop by hop, adds per-node jitter
from `jitter`, sums the edge costs, 64-hop cap).

rf3route.bin (10456 B):
    +0   "TRCS"          +4  u32 0x00010002 (version)
    +8   u16 room_count (872)   +12 u16 node_count (317)   +16 u16 edge_count (783)
         (each u16 sits in its own dword; the high halves are 0)
    +20  u32 off_rooms (32)   -> room_count x 4 B  {u8 room_lo, u8 node_count, u16 first_node}
                                 room_lo == room id & 0xFF (the table is indexed by room id)
    +24  u32 off_nodes (3520) -> node_count x 12 B {i16 x, i16 y, u16 first_edge, u16 jitter,
                                 u8 edge_count, u8 room, u16 0}   (tile units; << 12 = Q12 world)
    +28  u32 off_edges (7324) -> edge_count x 4 B  {u8 dest_room, u8 dest_node, u16 cost}
                                 dest_node = index within the destination room's node group;
                                 cost 0 = room-transition edge
    The pathfinder indexes the room table and edge destinations with 8-bit room numbers, so only
    rooms 0..255 can carry nodes (shipped: 32 rooms with nodes, highest id 159).  Nodes are
    stored grouped by room and edges grouped by node, with first_node / first_edge as running
    sums; build() regenerates the room table and both running sums from the node/edge lists.

rf3RouteResult.bin (50562 B = 318 rows x 159 B): nibble matrix `hop[dst][src]`:
    byte = data[stride*dst + (src >> 1)], even src = HIGH nibble, odd src = LOW nibble;
    the value is the index (0..14) into src's edge list of the edge that leads toward dst.
    stride = ceil(node_count / 2) = 159; the shipped file carries one spare (all-zero) row.
    Nav_BuildPathFromAToB: cur = src; while cur != dst: e = edges[cur][hop[dst][cur]];
    cur = node(e.dest_room, e.dest_node); cost += e.cost.
    compute() rebuilds the matrix from the graph (shortest total cost, first edge on the path);
    it reproduces the shipped matrix except where two routes tie (see selftest).
"""
from __future__ import annotations

import heapq
import json
import struct
from collections import namedtuple

MAGIC = b"TRCS"
VERSION = 0x00010002
HEADER_SIZE = 32
MAX_ROOMS = 872
MAX_HOPS = 64

Room = namedtuple("Room", "room_lo node_count first_node")
Node = namedtuple("Node", "x y first_edge jitter edge_count room")
Edge = namedtuple("Edge", "dest_room dest_node cost")


class RouteError(ValueError):
    pass


class RouteGraph:
    """nodes[i] = Node, edges[i] = Edge; edges of node n are edges[n.first_edge : +n.edge_count]."""

    def __init__(self, nodes: list[Node], edges: list[Edge], room_count: int = MAX_ROOMS,
                 version: int = VERSION):
        self.nodes, self.edges = nodes, edges
        self.room_count, self.version = room_count, version

    # ---- parse ----------------------------------------------------------- #
    @classmethod
    def parse(cls, data: bytes) -> "RouteGraph":
        if data[:4] != MAGIC:
            raise RouteError(f"not a TRCS route file (magic={data[:4]!r})")
        version = struct.unpack_from("<I", data, 4)[0]
        n_rooms, n_nodes, n_edges = (struct.unpack_from("<H", data, o)[0] for o in (8, 12, 16))
        off_rooms, off_nodes, off_edges = struct.unpack_from("<III", data, 20)
        if off_edges + 4 * n_edges > len(data):
            raise RouteError("route file truncated")
        rooms = [Room(*struct.unpack_from("<BBH", data, off_rooms + 4 * i)) for i in range(n_rooms)]
        nodes = [Node(*struct.unpack_from("<hhHHBB", data, off_nodes + 12 * i)) for i in range(n_nodes)]
        edges = [Edge(*struct.unpack_from("<BBH", data, off_edges + 4 * i)) for i in range(n_edges)]
        g = cls(nodes, edges, n_rooms, version)
        g._stock_rooms = rooms          # for the byte-exact check (rebuilt from the nodes)
        return g

    # ---- structure ------------------------------------------------------- #
    def rooms(self) -> list[Room]:
        """Room table regenerated from the node list (nodes must be grouped by room)."""
        first = {}
        count = {}
        for i, n in enumerate(self.nodes):
            if n.room not in first:
                first[n.room] = i
            elif first[n.room] + count[n.room] != i:
                raise RouteError(f"nodes of room {n.room} are not contiguous (node {i})")
            count[n.room] = count.get(n.room, 0) + 1
        if sorted(first, key=first.get) != sorted(first):
            raise RouteError("node groups must be stored in ascending room order")
        out, pos = [], 0
        for r in range(self.room_count):      # first_node is a running sum, also for empty rooms
            c = count.get(r, 0)
            out.append(Room(r & 0xFF, c, pos))
            pos += c
        return out

    def node_index(self, room: int, k: int) -> int:
        rm = self.rooms()[room]
        if k >= rm.node_count:
            raise RouteError(f"room {room} has only {rm.node_count} nodes")
        return rm.first_node + k

    def nodes_of_room(self, room: int) -> list[int]:
        rm = self.rooms()[room]
        return list(range(rm.first_node, rm.first_node + rm.node_count))

    def edges_of(self, node: int) -> list[Edge]:
        n = self.nodes[node]
        return self.edges[n.first_edge:n.first_edge + n.edge_count]

    def edge_target(self, e: Edge) -> int:
        return self.node_index(e.dest_room, e.dest_node)

    # ---- build ----------------------------------------------------------- #
    def build(self) -> bytes:
        rooms = self.rooms()
        nodes = []
        pos = 0
        for n in self.nodes:            # regenerate first_edge as the running sum
            nodes.append(Node(n.x, n.y, pos, n.jitter, n.edge_count, n.room))
            pos += n.edge_count
        if pos != len(self.edges):
            raise RouteError(f"edge counts sum to {pos} but {len(self.edges)} edges are listed")
        if any(r > 255 for r in {n.room for n in nodes}) or any(e.dest_room > 255 for e in self.edges):
            raise RouteError("the pathfinder addresses rooms as u8: nodes only in rooms 0..255")
        off_rooms = HEADER_SIZE
        off_nodes = off_rooms + 4 * len(rooms)
        off_edges = off_nodes + 12 * len(nodes)
        out = bytearray(struct.pack("<4sIIIIIII", MAGIC, self.version, len(rooms), len(nodes),
                                    len(self.edges), off_rooms, off_nodes, off_edges))
        for r in rooms:
            out += struct.pack("<BBH", r.room_lo, r.node_count, r.first_node)
        for n in nodes:
            out += struct.pack("<hhHHBBH", n.x, n.y, n.first_edge, n.jitter, n.edge_count, n.room, 0)
        for e in self.edges:
            out += struct.pack("<BBH", e.dest_room, e.dest_node, e.cost)
        return bytes(out)

    # ---- JSON ------------------------------------------------------------ #
    def to_json(self, name_fn=None) -> dict:
        nodes = []
        for i, n in enumerate(self.nodes):
            d = {"id": i, "room": n.room, "x": n.x, "y": n.y, "jitter": n.jitter,
                 "edges": [{"room": e.dest_room, "node": e.dest_node, "cost": e.cost}
                           for e in self.edges_of(i)]}
            if name_fn:
                d["room_name"] = name_fn(n.room) or ""
            nodes.append(d)
        return {"format": "rf3route", "version": self.version, "room_count": self.room_count,
                "nodes": nodes}

    @classmethod
    def from_json(cls, d: dict) -> "RouteGraph":
        if d.get("format") != "rf3route":
            raise RouteError("not an rf3route JSON document")
        nodes, edges = [], []
        for nd in d["nodes"]:
            es = nd.get("edges", [])
            nodes.append(Node(int(nd["x"]), int(nd["y"]), len(edges), int(nd.get("jitter", 0)),
                              len(es), int(nd["room"])))
            for e in es:
                edges.append(Edge(int(e["room"]), int(e["node"]), int(e["cost"])))
        return cls(nodes, edges, int(d.get("room_count", MAX_ROOMS)), int(d.get("version", VERSION)))

    def dumps(self, **kw) -> str:
        return json.dumps(self.to_json(**kw), indent=1)


class RouteResult:
    """The next-hop nibble matrix. hop(src, dst) -> edge index within src's edge list."""

    def __init__(self, cells: bytearray, stride: int, rows: int):
        self.cells, self.stride, self.rows = cells, stride, rows

    @classmethod
    def parse(cls, data: bytes, node_count: int | None = None) -> "RouteResult":
        if node_count is None:
            # stride s = ceil(n/2) and rows in {2s-1, 2s}: len is s*(2s-1) or 2*s*s
            s0 = int(round((len(data) / 2) ** 0.5))
            stride = next((s for s in (s0, s0 - 1, s0 + 1)
                           if s > 0 and len(data) in (s * (2 * s - 1), 2 * s * s)), 0)
            if not stride:
                raise RouteError(f"{len(data)} bytes is not an n x ceil(n/2) nibble matrix; "
                                 f"pass node_count")
        else:
            stride = (node_count + 1) // 2
        if stride == 0 or len(data) % stride:
            raise RouteError(f"{len(data)} bytes is not a whole number of {stride}-byte rows")
        return cls(bytearray(data), stride, len(data) // stride)

    def hop(self, src: int, dst: int) -> int:
        if not (0 <= dst < self.rows) or not (0 <= src < 2 * self.stride):
            raise RouteError("node index out of range")
        b = self.cells[self.stride * dst + (src >> 1)]
        return (b >> 4) if (src & 1) == 0 else (b & 15)

    def set_hop(self, src: int, dst: int, value: int) -> None:
        if not (0 <= value <= 15):
            raise RouteError("hop values are nibbles (0..15)")
        i = self.stride * dst + (src >> 1)
        b = self.cells[i]
        self.cells[i] = (value << 4) | (b & 15) if (src & 1) == 0 else (b & 0xF0) | value

    def build(self) -> bytes:
        return bytes(self.cells)

    def path(self, graph: RouteGraph, src: int, dst: int, max_hops: int = MAX_HOPS):
        """Mirror Nav_BuildPathFromAToB: [(node, edge_cost_to_reach_it)], total cost. Raises
        RouteError when the matrix leads nowhere (bad hop index) or the hop cap is hit."""
        cur, total, out = src, 0, [(src, 0)]
        for _ in range(max_hops):
            if cur == dst:
                return out, total
            h = self.hop(cur, dst)
            n = graph.nodes[cur]
            if h >= n.edge_count:
                raise RouteError(f"node {cur} -> {dst}: hop {h} but only {n.edge_count} edges")
            e = graph.edges[n.first_edge + h]
            cur = graph.edge_target(e)
            total += e.cost
            out.append((cur, e.cost))
        raise RouteError(f"no path from {src} to {dst} within {max_hops} hops")

    @classmethod
    def compute(cls, graph: RouteGraph, rows: int | None = None) -> "RouteResult":
        """Regenerate the matrix from the graph: for every dst, run Dijkstra on the REVERSED
        graph so each src learns the cheapest total cost, then record the first edge of a
        cheapest route (lowest edge index on ties). Unreachable pairs keep hop 0."""
        n = len(graph.nodes)
        targets = [[graph.edge_target(e) for e in graph.edges_of(i)] for i in range(n)]
        rev = [[] for _ in range(n)]              # rev[v] = [(u, edge_idx_in_u, cost)]
        for u in range(n):
            for k, e in enumerate(graph.edges_of(u)):
                rev[targets[u][k]].append((u, k, e.cost))
        stride = (n + 1) // 2
        rows = rows if rows is not None else n
        res = cls(bytearray(stride * rows), stride, rows)
        # distance = (total cost, hop count): the hop count breaks cost ties so that a pair of
        # zero-cost transition edges (A<->B, both cost 0) can never be chosen as a cycle.
        INF = (float("inf"), 0)
        for dst in range(n):
            dist = [INF] * n
            dist[dst] = (0, 0)
            heap = [((0, 0), dst)]
            while heap:
                d, v = heapq.heappop(heap)
                if d > dist[v]:
                    continue
                for u, _k, c in rev[v]:
                    nd = (d[0] + c, d[1] + 1)
                    if nd < dist[u]:
                        dist[u] = nd
                        heapq.heappush(heap, (nd, u))
            for src in range(n):
                if src == dst or dist[src] == INF:
                    continue
                best = None
                for k, e in enumerate(graph.edges_of(src)):
                    t = targets[src][k]
                    if (e.cost + dist[t][0], 1 + dist[t][1]) == dist[src]:
                        best = k
                        break
                if best is not None and best <= 15:
                    res.set_hop(src, dst, best)
        return res


def describe(graph: RouteGraph, name_fn=None) -> str:
    rooms = graph.rooms()
    used = [r for r in range(graph.room_count) if rooms[r].node_count]
    lines = [f"# rf3route (TRCS v{graph.version:#x}): {graph.room_count} rooms, "
             f"{len(graph.nodes)} nodes, {len(graph.edges)} edges; {len(used)} rooms have nodes"]
    for r in used:
        nm = (name_fn(r) if name_fn else "") or ""
        rm = rooms[r]
        lines.append(f"room {r:>3} {nm:<28} nodes {rm.first_node}..{rm.first_node + rm.node_count - 1}")
        for i in range(rm.first_node, rm.first_node + rm.node_count):
            n = graph.nodes[i]
            es = ", ".join(f"->{graph.edge_target(e)}(r{e.dest_room} c{e.cost})" for e in graph.edges_of(i))
            lines.append(f"    node {i:>3} @{n.x},{n.y} jitter {n.jitter}: {es}")
    return "\n".join(lines)
