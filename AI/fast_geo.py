"""ctypes wrapper for the btb_geo C acceleration kernel.

Loads AI/btb_geo.dll (built by AI/build_geo.py) and exposes:
  - FAST_GEO       True/False: whether the DLL is loaded and usable
  - btb_*          scalar primitives (bit-equivalent to aithink4.py)
  - GeoPack        batch geometry context for AIThinker hot loops
  - pt_seg_dist_many  one point vs n segments in one C call

If the DLL is missing or cannot be loaded, FAST_GEO is False and every
function here raises NotImplementedError -- the AI then falls back to the
pure-Python implementations with identical behavior.
"""

import ctypes
import math
import os
from collections import namedtuple

_HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# Pure-Python reference geometry (independent of the DLL; used by the
# parity checker dev/check_fast.py and by AIThinker fallback logic).
# Bit-equivalent to aithink4.py.
# ------------------------------------------------------------------

def _pure_dist(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def _pure_pt_seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / seg_sq
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)


def _pure_orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _pure_seg_cross(x1, y1, x2, y2, x3, y3, x4, y4):
    p1 = (x1, y1)
    p2 = (x2, y2)
    p3 = (x3, y3)
    p4 = (x4, y4)
    o1 = _pure_orient(p1, p2, p3)
    o2 = _pure_orient(p1, p2, p4)
    o3 = _pure_orient(p3, p4, p1)
    o4 = _pure_orient(p3, p4, p2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def _pure_seg_hits_circle(x1, y1, x2, y2, cx, cy, radius):
    return _pure_pt_seg_dist(cx, cy, x1, y1, x2, y2) <= radius


def pure_hit_stats(src, tgt, atk, en_nodes, en_edges, pickups,
                   radius, collect_dist, spine=None):
    """Reference Python implementation of the move statistics.

    Semantics match score_target exactly. en_nodes entries are
    (x, y, is_root, subtree_size, id, childspace); en_edges entries are
    (x1, y1, x2, y2, strength, child_id); pickups are (x, y, value).
    """
    hit_root = False
    nodes_hit = 0
    hub_value = 0
    spine_cut = 0
    for n in en_nodes:
        if (n[0] == src[0] and n[1] == src[1]) or (n[0] == tgt[0] and n[1] == tgt[1]):
            continue
        if _pure_seg_hits_circle(src[0], src[1], tgt[0], tgt[1],
                                 n[0], n[1], radius):
            if n[2]:  # is_root
                hit_root = True
                break
            nodes_hit += 1
            hub_value += n[3]
            if spine and n[4] in spine:
                spine_cut += 1
    if hit_root:
        return HitStats(1, 0, 0.0, 0, 0, 0, 0, 0.0, 0.0)
    edges_hit = 0
    edges_dead = 0
    for (ex1, ey1, ex2, ey2, est, child_id) in en_edges:
        if _pure_seg_cross(src[0], src[1], tgt[0], tgt[1],
                           ex1, ey1, ex2, ey2):
            edges_hit += 1
            if est <= atk:
                edges_dead += 1
            if spine and child_id in spine:
                spine_cut += 1
    pinned = 0
    for n in en_nodes:
        if n[5]:  # childspace
            d = _pure_dist(tgt[0], tgt[1], n[0], n[1])
            if 20 < d < 55:
                pinned += 1
    collect_value = 0.0
    collect_grav = 0.0
    for (px_, py_, pv) in pickups:
        d = _pure_dist(tgt[0], tgt[1], px_, py_)
        if d < collect_dist:
            collect_value += pv
        elif d < 130.0:
            collect_grav += pv * (1.0 - d / 130.0)
    return HitStats(0, nodes_hit, hub_value, edges_hit, edges_dead,
                    spine_cut, pinned, collect_value, collect_grav)

# ------------------------------------------------------------------
# Result of one move analysis (geometry part of score_target /
# _sim_quick_score). Fields map to btb_analyze_moves output layout.
# ------------------------------------------------------------------
HitStats = namedtuple('HitStats', [
    'hit_root',       # 0/1 new branch pierces enemy root
    'nodes_hit',      # enemy nodes pierced
    'hub_value',      # sum of subtree sizes of pierced nodes
    'edges_hit',      # enemy edges crossed
    'edges_dead',     # crossed edges with strength <= atk
    'spine_cut',      # pierced nodes/edges on enemy spine
    'pinned',         # enemy expandable nodes in 20 < d < 55
    'collect_value',  # pickup value within collect radius
    'collect_grav',   # sum value*(1-d/130) for 130 > d >= collect radius
])

_OUT0 = HitStats(0, 0, 0.0, 0, 0, 0, 0, 0.0, 0.0)

# ------------------------------------------------------------------
# DLL loading
# ------------------------------------------------------------------
_lib = None
FAST_GEO = False

_candidates = [
    os.path.join(_HERE, 'btb_geo.dll'),
    os.path.join(_HERE, 'AI', 'btb_geo.dll'),
    os.path.join(_HERE, 'dev', 'btb_geo.dll'),
    'btb_geo.dll',                      # current working dir fallback
]

for _p in _candidates:
    try:
        _lib = ctypes.CDLL(_p)
        FAST_GEO = True
        break
    except OSError:
        _lib = None

if FAST_GEO:
    _cd = ctypes.c_double
    _ci = ctypes.c_int
    _pd = ctypes.POINTER(_cd)
    _pi = ctypes.POINTER(_ci)

    _lib.btb_dist.restype = _cd
    _lib.btb_dist.argtypes = [_cd, _cd, _cd, _cd]
    _lib.btb_pt_seg_dist.restype = _cd
    _lib.btb_pt_seg_dist.argtypes = [_cd, _cd, _cd, _cd, _cd, _cd]
    _lib.btb_seg_cross.restype = _ci
    _lib.btb_seg_cross.argtypes = [_cd] * 8
    _lib.btb_seg_hits_circle.restype = _ci
    _lib.btb_seg_hits_circle.argtypes = [_cd] * 7
    _lib.btb_sector.restype = _ci
    _lib.btb_sector.argtypes = [_cd, _cd]
    _lib.btb_analyze_moves.restype = None
    _lib.btb_analyze_moves.argtypes = [
        _ci, _pd,                       # k, mv (k*5)
        _ci, _pd, _pd, _pi, _pi, _pi, _pi,   # n_en, en_x/y, is_root/subtree/childspace/spine
        _ci, _pd, _pd, _pd, _pd, _pi, _pi,   # n_eg, eg_x1/y1/x2/y2, eg_st, eg_spine
        _ci, _pd, _pd, _pd,             # n_pk, pk_x/y/val
        _cd, _cd,                       # node_radius, collect_dist
        _pd,                            # out (k*9)
    ]
    _lib.btb_pt_seg_dist_many.restype = None
    _lib.btb_pt_seg_dist_many.argtypes = [
        _cd, _cd, _ci, _pd, _pd, _pd, _pd, _pd,
    ]
    _lib.btb_pt_seg_dist_grid.restype = None
    _lib.btb_pt_seg_dist_grid.argtypes = [
        _ci, _pd, _pd, _ci, _pd, _pd, _pd, _pd, _pd,
    ]
    _lib.btb_dists_to.restype = None
    _lib.btb_dists_to.argtypes = [_cd, _cd, _ci, _pd, _pd, _pd]


def _need_lib():
    if not FAST_GEO:
        raise NotImplementedError(
            'btb_geo.dll not loaded; pure-Python fallback in effect')


# ------------------------------------------------------------------
# Scalar wrappers (rarely used directly; kept for parity testing)
# ------------------------------------------------------------------

def btb_dist(x1, y1, x2, y2):
    _need_lib()
    return _lib.btb_dist(x1, y1, x2, y2)


def btb_pt_seg_dist(px, py, x1, y1, x2, y2):
    _need_lib()
    return _lib.btb_pt_seg_dist(px, py, x1, y1, x2, y2)


def btb_seg_cross(x1, y1, x2, y2, x3, y3, x4, y4):
    _need_lib()
    return _lib.btb_seg_cross(x1, y1, x2, y2, x3, y3, x4, y4)


def btb_seg_hits_circle(x1, y1, x2, y2, cx, cy, radius):
    _need_lib()
    return _lib.btb_seg_hits_circle(x1, y1, x2, y2, cx, cy, radius)


def btb_sector(dx, dy):
    _need_lib()
    return _lib.btb_sector(dx, dy)


# ------------------------------------------------------------------
# Batch helpers
# ------------------------------------------------------------------

def pt_seg_dist_many(px, py, segs):
    """Distances from point (px,py) to each segment in segs.

    segs: list of (x1, y1, x2, y2). Returns list of floats.
    """
    _need_lib()
    n = len(segs)
    if n == 0:
        return []
    a1 = (_cd * n)()
    a2 = (_cd * n)()
    a3 = (_cd * n)()
    a4 = (_cd * n)()
    out = (_cd * n)()
    for i, s in enumerate(segs):
        a1[i] = s[0]
        a2[i] = s[1]
        a3[i] = s[2]
        a4[i] = s[3]
    _lib.btb_pt_seg_dist_many(px, py, n,
                              ctypes.cast(a1, _pd), ctypes.cast(a2, _pd),
                              ctypes.cast(a3, _pd), ctypes.cast(a4, _pd),
                              ctypes.cast(out, _pd))
    return list(out)


def dists_to(px, py, pts):
    """Distances from point (px,py) to every point in pts (one C call)."""
    _need_lib()
    n = len(pts)
    if n == 0:
        return []
    xs = (_cd * n)()
    ys = (_cd * n)()
    for i, p in enumerate(pts):
        xs[i] = p[0]
        ys[i] = p[1]
    out = (_cd * n)()
    _lib.btb_dists_to(px, py, n, ctypes.cast(xs, _pd), ctypes.cast(ys, _pd),
                      ctypes.cast(out, _pd))
    return list(out)


def pt_seg_dist_grid(pts, segs):
    """Distance matrix: every point in pts against every segment in segs.

    pts:  list of (x, y). segs: list of (x1, y1, x2, y2).
    Returns flat list of len(pts)*len(segs), row-major
    (out[i*len(segs) + j] = dist(pts[i], segs[j])).
    """
    _need_lib()
    n_pts = len(pts)
    n_seg = len(segs)
    if n_pts == 0 or n_seg == 0:
        return []
    px = (_cd * n_pts)()
    py = (_cd * n_pts)()
    for i, p in enumerate(pts):
        px[i] = p[0]
        py[i] = p[1]
    sx1 = (_cd * n_seg)()
    sy1 = (_cd * n_seg)()
    sx2 = (_cd * n_seg)()
    sy2 = (_cd * n_seg)()
    for j, s in enumerate(segs):
        sx1[j] = s[0]
        sy1[j] = s[1]
        sx2[j] = s[2]
        sy2[j] = s[3]
    out = (_cd * (n_pts * n_seg))()
    _lib.btb_pt_seg_dist_grid(n_pts, ctypes.cast(px, _pd), ctypes.cast(py, _pd),
                              n_seg, ctypes.cast(sx1, _pd), ctypes.cast(sy1, _pd),
                              ctypes.cast(sx2, _pd), ctypes.cast(sy2, _pd),
                              ctypes.cast(out, _pd))
    return list(out)


class GeoPack:
    """Packed geometry context: enemy nodes / edges / pickups arrays.

    Build once per decision phase (real board or one simulated layer),
    then call analyze_moves() once for any number of candidate moves.
    Used by AIThinker._gen_cands and _sim_best_move fast paths.

    nodes:      list of Node-like objects (x, y, team, parent, children,
                strength, id). Enemy filtering is done by `team`.
    my_team:    team of the mover (enemy = the other team).
    pickups:    list of PointPack-like objects (x, y, value).
    radius:     NODE_RADIUS.
    collect_dist: PICKUP_COLLECT_DIST.
    subtree_fn: callable(node) -> subtree size (default: count via children).
    spine_ids:  set of node ids on the enemy spine, or None.
    """
    __slots__ = ('_lib', '_n_en', '_en_x', '_en_y', '_en_is_root',
                 '_en_subtree', '_en_childspace', '_en_spine',
                 '_n_eg', '_eg_x1', '_eg_y1', '_eg_x2', '_eg_y2',
                 '_eg_st', '_eg_spine',
                 '_n_pk', '_pk_x', '_pk_y', '_pk_val',
                 '_radius', '_collect_dist', '_hits', '_hits_len',
                 '_mv', '_mv_len',                 # reusable move buffer
                 '_pe', '_pd', '_pi')              # pre-cast pointer types

    def __init__(self, nodes, my_team, pickups, radius, collect_dist,
                 subtree_fn=None, spine_ids=None, max_children=2):
        _need_lib()
        enemy = [n for n in nodes if n.team != my_team]
        n_en = len(enemy)
        en_x = (_cd * max(1, n_en))()
        en_y = (_cd * max(1, n_en))()
        en_is_root = (_ci * max(1, n_en))()
        en_subtree = (_ci * max(1, n_en))()
        en_childspace = (_ci * max(1, n_en))()
        en_spine = (_ci * max(1, n_en))()
        for i, n in enumerate(enemy):
            en_x[i] = n.x
            en_y[i] = n.y
            en_is_root[i] = 1 if n.parent is None else 0
            if subtree_fn is not None:
                en_subtree[i] = subtree_fn(n)
            else:
                cnt = 1
                stack = list(n.children)
                while stack:
                    cur = stack.pop()
                    cnt += 1
                    stack.extend(cur.children)
                en_subtree[i] = cnt
            en_childspace[i] = 1 if len(n.children) < max_children else 0
            en_spine[i] = 1 if (spine_ids and n.id in spine_ids) else 0

        edges = []
        for n in nodes:
            if n.team != my_team and n.parent is not None:
                edges.append((n.parent.x, n.parent.y, n.x, n.y,
                              n.strength, 1 if (spine_ids and n.id in spine_ids) else 0))
        n_eg = len(edges)
        eg_x1 = (_cd * max(1, n_eg))()
        eg_y1 = (_cd * max(1, n_eg))()
        eg_x2 = (_cd * max(1, n_eg))()
        eg_y2 = (_cd * max(1, n_eg))()
        eg_st = (_ci * max(1, n_eg))()
        eg_spine = (_ci * max(1, n_eg))()
        for i, e in enumerate(edges):
            eg_x1[i] = e[0]
            eg_y1[i] = e[1]
            eg_x2[i] = e[2]
            eg_y2[i] = e[3]
            eg_st[i] = e[4]
            eg_spine[i] = e[5]

        pk = list(pickups)
        n_pk = len(pk)
        pk_x = (_cd * max(1, n_pk))()
        pk_y = (_cd * max(1, n_pk))()
        pk_val = (_cd * max(1, n_pk))()
        for i, p in enumerate(pk):
            pk_x[i] = p.x
            pk_y[i] = p.y
            pk_val[i] = p.value

        self._lib = _lib
        self._n_en = n_en
        self._en_x = en_x
        self._en_y = en_y
        self._en_is_root = en_is_root
        self._en_subtree = en_subtree
        self._en_childspace = en_childspace
        self._en_spine = en_spine
        self._n_eg = n_eg
        self._eg_x1 = eg_x1
        self._eg_y1 = eg_y1
        self._eg_x2 = eg_x2
        self._eg_y2 = eg_y2
        self._eg_st = eg_st
        self._eg_spine = eg_spine
        self._n_pk = n_pk
        self._pk_x = pk_x
        self._pk_y = pk_y
        self._pk_val = pk_val
        self._radius = radius
        self._collect_dist = collect_dist
        self._hits = None
        self._hits_len = 0
        self._mv = None
        self._mv_len = 0
        self._pe = ctypes.cast  # local alias for speed
        self._pd = _pd
        self._pi = _pi

    def analyze_moves(self, moves):
        """moves: list of (x1, y1, x2, y2, atk). Returns list of HitStats."""
        k = len(moves)
        if k == 0:
            return []
        if self._mv is None or self._mv_len < k * 5:
            self._mv = (_cd * (k * 5))()
            self._mv_len = k * 5
        mv = self._mv
        for i, m in enumerate(moves):
            base = i * 5
            mv[base] = m[0]
            mv[base + 1] = m[1]
            mv[base + 2] = m[2]
            mv[base + 3] = m[3]
            mv[base + 4] = m[4]
        if self._hits is None or self._hits_len < k * 9:
            self._hits = (_cd * (k * 9))()
            self._hits_len = k * 9
        out = self._hits
        c = self._pe
        self._lib.btb_analyze_moves(
            k, c(mv, self._pd),
            self._n_en,
            c(self._en_x, self._pd), c(self._en_y, self._pd),
            c(self._en_is_root, self._pi),
            c(self._en_subtree, self._pi),
            c(self._en_childspace, self._pi),
            c(self._en_spine, self._pi),
            self._n_eg,
            c(self._eg_x1, self._pd), c(self._eg_y1, self._pd),
            c(self._eg_x2, self._pd), c(self._eg_y2, self._pd),
            c(self._eg_st, self._pi), c(self._eg_spine, self._pi),
            self._n_pk,
            c(self._pk_x, self._pd), c(self._pk_y, self._pd),
            c(self._pk_val, self._pd),
            self._radius, self._collect_dist,
            c(out, self._pd),
        )
        res = []
        for i in range(k):
            b = i * 9
            res.append(HitStats(
                int(out[b]), int(out[b + 1]), out[b + 2],
                int(out[b + 3]), int(out[b + 4]), int(out[b + 5]),
                int(out[b + 6]), out[b + 7], out[b + 8],
            ))
        return res

    def analyze_one(self, x1, y1, x2, y2, atk):
        """Single-move convenience (returns HitStats)."""
        return self.analyze_moves([(x1, y1, x2, y2, atk)])[0]
