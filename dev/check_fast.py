"""Correctness verification for the btb_geo C acceleration kernel.

Three layers of checks:

  1. Scalar primitives -- C vs pure-Python reference on 100k random inputs
     (btb_dist / btb_pt_seg_dist / btb_seg_cross / btb_seg_hits_circle /
      btb_sector).
  2. Batch move analysis -- random boards, random moves:
     GeoPack.analyze_moves vs pure_hit_stats. Integer fields must match
     exactly; float fields within 1e-9.
  3. Whole self-play games -- same seed, C path vs pure-Python path
     (BTB_NO_FAST=1), comparing per-game winner / turns / action-trace
     hash. Decision behavior must be identical.

Usage:
    python dev/check_fast.py
"""

import hashlib
import json
import os
import random
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ------------------------------------------------------------------
# Layer 1: scalar parity
# ------------------------------------------------------------------

def _py_dist(x1, y1, x2, y2):
    return math_hypot(x2 - x1, y2 - y1)


def _py_pt_seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1e-9:
        return math_hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / seg_sq
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math_hypot(px - cx, py - cy)


def _py_orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _py_seg_cross(x1, y1, x2, y2, x3, y3, x4, y4):
    p1, p2, p3, p4 = (x1, y1), (x2, y2), (x3, y3), (x4, y4)
    o1 = _py_orient(p1, p2, p3)
    o2 = _py_orient(p1, p2, p4)
    o3 = _py_orient(p3, p4, p1)
    o4 = _py_orient(p3, p4, p2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def _py_seg_hits_circle(x1, y1, x2, y2, cx, cy, radius):
    return _py_pt_seg_dist(cx, cy, x1, y1, x2, y2) <= radius


def _py_sector(dx, dy):
    return int(math_floor(math_atan2(dy, dx) / math_pi * 4.0) + 8) % 8


def check_scalars(fast):
    import math as _m
    global math_hypot, math_floor, math_atan2, math_pi
    math_hypot = _m.hypot
    math_floor = _m.floor
    math_atan2 = _m.atan2
    math_pi = _m.pi
    rng = random.Random(1234)
    worst = 0.0
    worst_case = None
    n = 100000
    for _ in range(n):
        coords = [rng.uniform(-300, 1300) for _ in range(8)]
        # btb_dist
        c = fast.btb_dist(*coords[:4])
        p = _py_dist(*coords[:4])
        d = abs(c - p)
        if d > worst:
            worst, worst_case = d, ('dist', coords[:4], c, p)
        # btb_pt_seg_dist
        c = fast.btb_pt_seg_dist(*coords[:6])
        p = _py_pt_seg_dist(*coords[:6])
        d = abs(c - p)
        if d > worst:
            worst, worst_case = d, ('pt_seg', coords[:6], c, p)
        # btb_seg_cross
        c = fast.btb_seg_cross(*coords[:8])
        p = 1 if _py_seg_cross(*coords[:8]) else 0
        if c != p:
            print(f'FAIL seg_cross: {coords[:8]} C={c} PY={p}')
            return False
        # btb_seg_hits_circle
        c = fast.btb_seg_hits_circle(*coords[:6], 18.0)
        p = 1 if _py_seg_hits_circle(*coords[:6], 18.0) else 0
        if c != p:
            # borderline: compare with tiny epsilon tolerance
            dc = fast.btb_pt_seg_dist(coords[4], coords[5], *coords[:4])
            dp = _py_pt_seg_dist(coords[4], coords[5], *coords[:4])
            if abs(dc - dp) > 1e-9:
                print(f'FAIL seg_hits_circle: {coords[:6]} C={c} PY={p}')
                return False
        # btb_sector
        c = fast.btb_sector(coords[0], coords[1])
        p = _py_sector(coords[0], coords[1])
        if c != p:
            print(f'FAIL sector: ({coords[0]},{coords[1]}) C={c} PY={p}')
            return False
    print(f'[scalars] 100000 random inputs OK  (worst float diff = {worst:.3e})')
    if worst > 1e-12:
        print(f'  warning: worst case {worst_case}')
    return True


# ------------------------------------------------------------------
# Layer 2: batch move analysis parity
# ------------------------------------------------------------------

def check_batch(fast, fast_geo):
    rng = random.Random(5678)
    radius = 18.0
    collect_dist = 31.0
    for board in range(60):
        # random board: two trees + pickups.
        # rec = [x, y, team, parent_idx, strength, id, is_root]
        nodes = []
        for team, root in (('RED', (rng.uniform(40, 200), rng.uniform(40, 200))),
                           ('BLUE', (rng.uniform(1100, 1260), rng.uniform(500, 660)))):
            root_idx = len(nodes)
            nodes.append([root[0], root[1], team, -1, rng.randint(1, 5), len(nodes), 1])
            last = root_idx
            for depth in range(3):
                px, py = nodes[last][0], nodes[last][1]
                ang = rng.uniform(0, 6.28)
                d = rng.uniform(60, 200)
                nx = px + d * math_cos(ang)
                ny = py + d * math_sin(ang)
                nodes.append([nx, ny, team, last, rng.randint(1, 5), len(nodes), 0])
                last = len(nodes) - 1
                if depth == 1:  # second child of the root
                    nodes.append([px + d * math_cos(ang + 1.2),
                                  py + d * math_sin(ang + 1.2),
                                  team, root_idx, rng.randint(1, 5), len(nodes), 0])
        # subtree sizes (bottom-up)
        subtree = [1] * len(nodes)
        for i in range(len(nodes) - 1, -1, -1):
            if nodes[i][3] >= 0:
                subtree[nodes[i][3]] += subtree[i]

        class N:
            __slots__ = ('x', 'y', 'team', '_parent', 'strength', 'id',
                         'is_root', 'subtree_size', 'children')
            def __init__(self, rec, parent):
                self.x, self.y = rec[0], rec[1]
                self.team = rec[2]
                self._parent = parent
                self.strength = rec[4]
                self.id = rec[5]
                self.is_root = rec[6]
                self.subtree_size = subtree[rec[5]]
                self.children = []
            @property
            def parent(self):
                return self._parent

        obj_nodes = []
        for rec in nodes:
            p = obj_nodes[rec[3]] if rec[3] >= 0 else None
            o = N(rec, p)
            obj_nodes.append(o)
            if p is not None:
                p.children.append(o)

        class P:
            __slots__ = ('x', 'y', 'value')
            def __init__(self, x, y, v):
                self.x, self.y, self.value = x, y, v

        pickups = [P(rng.uniform(100, 1200), rng.uniform(100, 600),
                     rng.choice([1, 2, 3])) for _ in range(4)]
        pickups_py = [(p.x, p.y, p.value) for p in pickups]

        en_team = 'BLUE'
        en_nodes_py = [(o.x, o.y, 1 if o.is_root else 0, o.subtree_size,
                        o.id, 1 if len(o.children) < 2 else 0)
                       for o in obj_nodes if o.team == en_team]
        en_edges_py = [(o.parent.x, o.parent.y, o.x, o.y, o.strength, o.id)
                       for o in obj_nodes if o.team == en_team and o.parent is not None]

        geo = fast_geo.GeoPack(obj_nodes, 'RED', pickups, radius, collect_dist,
                               subtree_fn=lambda n: n.subtree_size,
                               spine_ids=None, max_children=2)

        moves = []
        for _ in range(30):
            src = rng.choice(obj_nodes)
            moves.append((src.x, src.y,
                          rng.uniform(0, 1300), rng.uniform(0, 700),
                          rng.randint(1, 5)))
        c_res = geo.analyze_moves(moves)
        for i, m in enumerate(moves):
            p_res = fast_geo.pure_hit_stats(
                (m[0], m[1]), (m[2], m[3]), int(m[4]),
                en_nodes_py, en_edges_py, pickups_py, radius, collect_dist, None)
            c = c_res[i]
            for f, (cv, pv) in enumerate(zip(c, p_res)):
                if isinstance(pv, int):
                    if int(cv) != pv:
                        print(f'FAIL board={board} move={i} field={f} C={cv} PY={pv} m={m}')
                        return False
                else:
                    if abs(cv - pv) > 1e-9:
                        print(f'FAIL board={board} move={i} field={f} C={cv} PY={pv} m={m}')
                        return False
    print('[batch] 60 random boards x 30 moves: all fields match')
    return True


# ------------------------------------------------------------------
# Layer 3: whole self-play games, C vs pure-Python (same seed)
# ------------------------------------------------------------------

def _action_key(ai, action):
    if action is None:
        return 'none'
    if action['type'] == 'end_turn':
        return 'end'
    if action['type'] == 'modify_branch':
        return f"mod:{action['node'].id}:{action['new_strength']}"
    return (f"pl:{action['parent'].id}:{round(action['x'], 3)}:"
            f"{round(action['y'], 3)}:{action['strength']}:"
            f"{action.get('range_index', 0)}")


def play_and_trace(games, max_turns=300):
    import main as _main
    from AI.aithink4 import AIThinker, AIConfig
    game = _main.Game()
    cfg = AIConfig()
    out = []
    for i in range(games):
        game.reset(game_info={'mode': 'ai'})
        game.state = _main.STATE_PLAYING
        trace = []
        turns = 0
        while game.winner is None and turns < max_turns:
            turns += 1
            cfg_i = cfg
            ai = AIThinker(game, cfg=cfg_i)
            ai.team = game.current_team
            ai.enemy_team = 'BLUE' if ai.team == 'RED' else 'RED'
            action = ai.decide_action()
            trace.append(_action_key(ai, action))
            if action is None:
                game._end_turn()
                continue
            if action['type'] == 'end_turn':
                game._end_turn()
            else:
                try:
                    game._execute_ai_action(action)
                except Exception:
                    game._end_turn()
        h = hashlib.md5('|'.join(trace).encode()).hexdigest()[:16]
        out.append({'game': i, 'winner': game.winner, 'turns': turns, 'hash': h})
        print(f'  game {i}: winner={game.winner} turns={turns} hash={h}')
    return out


def worker(games=4, seed=42):
    random.seed(seed)
    import math as _m
    global math_cos, math_sin
    math_cos = _m.cos
    math_sin = _m.sin
    res = play_and_trace(games)
    print('__RESULT__' + json.dumps(res))


def main():
    import math as _m
    global math_cos, math_sin
    math_cos = _m.cos
    math_sin = _m.sin

    if '--worker' in sys.argv:
        worker()
        return 0

    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    import AI.fast_geo as fg
    import AI.aithink4 as ai4
    fast = fg
    ok = True
    ok &= check_scalars(fast)
    ok &= check_batch(fast, fg)
    print(f'[mode] AIThinker FAST_GEO = {ai4.FAST_GEO}')
    if not ai4.FAST_GEO:
        print('ERROR: fast path not active; cannot compare.')
        return 1

    # whole-game parity: fast (this process) vs pure-Python (subprocess)
    print('[games] C-path self-play (4 games, seed=42):')
    random.seed(42)
    fast_res = play_and_trace(4)
    print('[games] pure-Python self-play (4 games, seed=42):')
    env = dict(os.environ)
    env['BTB_NO_FAST'] = '1'
    r = subprocess.run([sys.executable, os.path.abspath(__file__), '--worker'],
                       capture_output=True, text=True, env=env, cwd=_ROOT)
    if r.returncode != 0:
        print('worker failed:', r.stdout, r.stderr)
        return 1
    tag = '__RESULT__'
    body = r.stdout[r.stdout.rfind(tag) + len(tag):]
    slow_res = json.loads(body.strip())
    for a, b in zip(fast_res, slow_res):
        if (a['winner'] != b['winner'] or a['turns'] != b['turns']
                or a['hash'] != b['hash']):
            print(f'FAIL game {a["game"]}: fast={a} slow={b}')
            ok = False
    if ok:
        print('[games] 4 self-play games: identical winner/turns/trace')
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
