"""临时验证：重复路线破局（similar_turns≥3 强制换线）。用完删除。"""
import os, tempfile, shutil
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import main
from AI import aithink4 as ai_mod

tmp = tempfile.mkdtemp(prefix='route_test_')
ai_mod._AI_JSON = os.path.join(tmp, 'ai.json')
ai_mod._LEARN_JSON = os.path.join(tmp, 'learn.json')
ai_mod._BACKUP_DIR = os.path.join(tmp, 'backup')
shutil.copy2(os.path.join('AI', 'ai.json'), ai_mod._AI_JSON)
ai_mod._reload_override()

g = main.Game()
g.start_ai_vs_ai_game()

games = 0
max_turns = 0
max_sim = 0
turns_by_game = []
for _ in range(70000):
    g.update()
    if _ % 25 == 0:
        for team in ('RED', 'BLUE'):
            sim = g._ai_memory_by_team[team].get('similar_turns', 0)
            if sim > max_sim:
                max_sim = sim
    if g.winner is not None:
        games += 1
        turns_by_game.append(g.turn_count)
        max_turns = max(max_turns, g.turn_count)
        if games >= 15:
            break

print(f"1) 完成对局数: {games} (目标≥10)")
print(f"2) 回合数分布: <=15:{sum(1 for t in turns_by_game if t<=15)}局 16~30:{sum(1 for t in turns_by_game if 15<t<=30)}局 >30:{sum(1 for t in turns_by_game if t>30)}局")
print(f"3) 最长一局: {max_turns} 回合 (有限即无死循环)")
print(f"4) similar_turns 采样最高: {max_sim} (≥3 说明重复路线检测+换线已触发)")
shutil.rmtree(tmp, ignore_errors=True)
print("验证完成")
