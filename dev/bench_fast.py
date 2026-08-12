"""Performance benchmark: btb_geo C acceleration vs pure Python.

Runs identical self-play tournaments (same seed) with and without the C
kernel (BTB_NO_FAST=1) and reports:
  - per-game wall time
  - average decide_action() time per turn (mid-game sample)
  - total speedup

Usage:
    python dev/bench_fast.py [--games 4] [--max-turns 300]
"""

import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def run_tournament(games, max_turns, collect_sample_at=40):
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    if os.getcwd() != _ROOT:
        os.chdir(_ROOT)   # main.py reads ./debug and ./config.json by relative path
    import main as _main
    from AI.aithink4 import AIThinker, AIConfig, FAST_GEO

    game = _main.Game()
    cfg = AIConfig()
    total = 0.0
    games_info = []
    sample_dt = []
    for i in range(games):
        game.reset(game_info={'mode': 'ai'})
        game.state = _main.STATE_PLAYING
        t0 = time.perf_counter()
        turns = 0
        while game.winner is None and turns < max_turns:
            turns += 1
            ai = AIThinker(game, cfg=cfg)
            ai.team = game.current_team
            ai.enemy_team = 'BLUE' if ai.team == 'RED' else 'RED'
            t1 = time.perf_counter()
            action = ai.decide_action()
            t2 = time.perf_counter()
            if collect_sample_at and turns > collect_sample_at:
                sample_dt.append(t2 - t1)
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
        dt = time.perf_counter() - t0
        total += dt
        games_info.append((game.winner, turns, dt))
    return FAST_GEO, total, games_info, sample_dt


def main():
    ap = argparse.ArgumentParser(description='btb_geo C acceleration benchmark')
    ap.add_argument('--games', type=int, default=4)
    ap.add_argument('--max-turns', type=int, default=300)
    args = ap.parse_args()

    import random
    random.seed(20260812)

    fast, fast_total, fast_games, fast_samples = run_tournament(
        args.games, args.max_turns)
    print(f'[fast={fast}] tournament:')
    for w, t, dt in fast_games:
        print(f'  winner={w} turns={t} {dt:.2f}s')
    avg_fast_turn = (sum(fast_samples) / len(fast_samples)
                     if fast_samples else float('nan'))
    print(f'  total {fast_total:.2f}s  avg decide_action {avg_fast_turn*1000:.1f} ms/turn')

    # pure-Python run in a subprocess (BTB_NO_FAST=1)
    env = dict(os.environ)
    env['BTB_NO_FAST'] = '1'
    import subprocess
    _DEV = os.path.dirname(os.path.abspath(__file__))
    code = (
        'import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); '
        'import bench_fast; '
        'bench_fast.main2(%d, %d)' % (_ROOT, _DEV, args.games, args.max_turns)
    )
    r = subprocess.run([sys.executable, '-c', code],
                       capture_output=True, text=True, env=env, cwd=_DEV)
    if r.returncode != 0:
        print('pure-Python run failed:\n', r.stdout, r.stderr)
        return 1
    print(r.stdout.strip())
    tag = '__SLOW__'
    if tag in r.stdout:
        tail = [ln for ln in r.stdout.split(tag)[1].splitlines() if ln.strip()]
        slow_total = float(tail[0])
        slow_samples = float(tail[1])
        print(f'\n[totals] fast {fast_total:.2f}s  pure-Python {slow_total:.2f}s')
        print(f'[speedup] whole games: {slow_total / max(1e-9, fast_total):.1f}x')
        if fast_samples and slow_samples:
            print(f'[speedup] decide_action per turn: '
                  f'{slow_samples / max(1e-9, avg_fast_turn):.1f}x '
                  f'({avg_fast_turn*1000:.1f} ms -> {slow_samples*1000:.1f} ms)')
    return 0


def main2(games, max_turns):
    """Subprocess entry: pure-Python tournament, prints __SLOW__ totals."""
    import random
    random.seed(20260812)
    _fast, total, games_info, samples = run_tournament(games, max_turns)
    for w, t, dt in games_info:
        print(f'  winner={w} turns={t} {dt:.2f}s')
    avg = (sum(samples) / len(samples)) if samples else float('nan')
    print(f'  total {total:.2f}s  avg decide_action {avg*1000:.1f} ms/turn')
    print('__SLOW__')
    print(f'{total:.6f}')
    print(f'{avg:.9f}')


if __name__ == '__main__':
    sys.exit(main())
