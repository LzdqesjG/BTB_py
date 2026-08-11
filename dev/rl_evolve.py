"""AI 自对弈训练器（在线自对弈演化训练）。

用法:
    python dev/rl_evolve.py                 # 默认 4 局锦标赛
    python dev/rl_evolve.py --games 12      # 自定义局数
    python dev/rl_evolve.py --mutation 0.15 # 变异幅度
    python dev/rl_evolve.py --seed 42       # 固定随机种子

原理:
    以当前 AI/ai.json 权重为基准 (baseline)，生成随机微扰权重 (mutant)，
    在 dummy 视频驱动下跑 AI vs AI 自对弈。若 mutant 净胜场更多，
    则把 mutant 写回 AI/ai.json（写前自动按日期备份旧权重到 AI/backup/）。

    这是"在线自对弈训练"：不依赖外部服务，随时可跑，与游戏内对局结果学习互补：
    - 游戏内 (main.go_menu → AIThinker.record_match_result):
      每局结束按胜负/对手打法微调关键权重。
    - 本脚本: 批量自对弈搜索更优权重组合。
"""
import argparse
import os
import random
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import main  # noqa: E402  (dummy 视频驱动，不弹窗口)
from AI.aithink4 import AIConfig, AIThinker, save_weights  # noqa: E402


def play_match(game, red_cfg, blue_cfg, max_turns=300):
    """用给定权重跑一局 AI vs AI，返回 (winner, turns)。winner=None 表示超时平局。"""
    game.reset(game_info={'mode': 'ai'})
    game.state = main.STATE_PLAYING
    turns = 0
    while game.winner is None and turns < max_turns:
        turns += 1
        cfg = red_cfg if game.current_team == 'RED' else blue_cfg
        ai = AIThinker(game, cfg=cfg)
        # 覆盖队伍标识：同一局双方都用 AI，分别控制红/蓝
        ai.team = game.current_team
        ai.enemy_team = 'BLUE' if ai.team == 'RED' else 'RED'
        action = ai.decide_action()
        if action is None:
            game._end_turn()  # 无法决策 → 强制切回合，防止死循环
            continue
        if action['type'] == 'end_turn':
            game._end_turn()
        else:
            try:
                game._execute_ai_action(action)
            except Exception:
                game._end_turn()  # 防御：执行失败强制切回合
    return game.winner, turns


def mutate(base, magnitude):
    """对基准权重做随机微扰，生成变异权重。"""
    m = AIConfig()
    for k in m.to_dict():
        v = getattr(m, k)
        if isinstance(v, (int, float)) and v != 0:
            setattr(m, k, v * (1 + random.uniform(-magnitude, magnitude)))
    m._apply_clip()
    return m


def main():
    ap = argparse.ArgumentParser(description='AI 自对弈训练器')
    ap.add_argument('--games', type=int, default=4, help='锦标赛局数 (默认 4)')
    ap.add_argument('--mutation', type=float, default=0.12, help='变异幅度 (默认 0.12)')
    ap.add_argument('--seed', type=int, default=None, help='随机种子')
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    base = AIConfig()  # 当前 ai.json 权重
    mutant = mutate(base, args.mutation)

    game = main.Game()
    win_b = win_m = draw = 0
    print(f"基准权重 vs 变异权重 (±{int(args.mutation * 100)}%), {args.games} 局")
    for i in range(args.games):
        flip = (i % 2 == 1)  # 交替先后手，消除先后手偏差
        red_cfg, blue_cfg = (mutant, base) if flip else (base, mutant)
        winner, turns = play_match(game, red_cfg, blue_cfg)
        if winner is None:
            draw += 1
            tag = '平局'
        elif (winner == 'RED') == flip:
            win_m += 1
            tag = '变异胜'
        else:
            win_b += 1
            tag = '基准胜'
        print(f"  局{i + 1}: {tag} ({turns} 回合)")

    print(f"结果: 基准 {win_b} / 变异 {win_m} / 平局 {draw}")
    if win_m > win_b:
        save_weights(mutant)
        print('[采纳] 变异权重更优，已写回 AI/ai.json（旧权重已备份到 AI/backup/）')
    else:
        print('[保留] 变异未占优，保留当前 AI/ai.json')


if __name__ == '__main__':
    main()
