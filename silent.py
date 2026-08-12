"""静默 AI 对弈训练模式（独立进程 + 独立小窗口）。

由主菜单"AI 对弈"在设置中开启"静默 AI 对弈"后，经确认弹窗启动：
自动关闭主窗口并打开本窗口，进入后无法返回主菜单（关闭窗口即退出）。

- 只学习并保存 AI 参数（ai.json 权重微调 / learn.json），不保存回放；
- 仅在每局结束时播放 orb 音效，对弈过程静音；
- 无速率限制：渲染不限帧率、AI 思考 0 延迟，全速训练；
- 窗口显示：当前局数 / 当前回合数 / 当前平均速度 / 已训练时间 /
  历史总局数 / 前三局步数。
"""
import os
import random
import sys
import time

from constant import VERSION

# 静默模式：抑制 main 模块级主窗口创建与开始音效（必须在 import main 之前设置）
os.environ['BTB_SILENT'] = '1'
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402
import main    # noqa: E402
from AI import aithink4

# 静默训练不保存回放：patch 掉 ReplayRecorder 的记录与保存
main.ReplayRecorder.record = lambda self, *a, **k: None
main.ReplayRecorder.save = lambda self, *a, **k: None

# 对弈过程静音：所有音效调用全部拦截，仅切换局时由本模块主动播放 orb
_orig_play_sfx = main.play_sfx
main.play_sfx = lambda *a, **k: None

# --- 性能优化：延迟保存训练数据（内存版替换 + 批量落盘）---
# 原理：学习逻辑每局调用 save_weights/_save_stats/_save_learn 更新数据。
# 替换为内存版（只更新内存变量，不碰磁盘），每 N 局再由 _flush_saves() 批量写盘。
# 这样把磁盘 I/O 频率从"每局一次"降到"每 N 局一次"，同时保证学习结果在内存中累积不丢失。

# 保存原始函数引用
_orig_save_weights = aithink4.save_weights
_orig_save_stats = aithink4._save_stats
_orig_save_learn = aithink4._save_learn

# 内存缓存（启动时从文件加载初始值，保证与已有数据衔接）
_memory_stats = aithink4._load_stats()          # dict，初始从 ai.json 读
_memory_learn = aithink4._load_learn()          # dict，初始从 learn.json 读


def _mem_save_weights(cfg):
    """内存版：只更新 _JSON_OVERRIDE，不写文件。下一局 AIConfig() 会读到新权重。"""
    aithink4._JSON_OVERRIDE = cfg.to_dict()
    return True


def _mem_save_stats(stats):
    _memory_stats.clear()
    _memory_stats.update(stats)
    return True


def _mem_load_stats():
    return dict(_memory_stats)


def _mem_save_learn(learn):
    _memory_learn.clear()
    _memory_learn.update(learn)
    return True


def _mem_load_learn():
    return dict(_memory_learn)


# 替换模块内函数（模块内部调用 save_weights/_save_learn 等会走到这些内存版）
aithink4.save_weights = _mem_save_weights
aithink4._save_stats = _mem_save_stats
aithink4._load_stats = _mem_load_stats
aithink4._save_learn = _mem_save_learn
aithink4._load_learn = _mem_load_learn


def _flush_saves():
    """把内存中累积的学习结果批量写入磁盘。"""
    # 1. 权重：从已更新的 _JSON_OVERRIDE 重建 cfg 并写盘
    try:
        cfg = aithink4.AIConfig()
        _orig_save_weights(cfg)
    except Exception as e:
        print(f"[静默训练] 保存权重失败: {e}")
    # 2. 统计
    if _memory_stats:
        try:
            _orig_save_stats(dict(_memory_stats))
        except Exception as e:
            print(f"[静默训练] 保存统计失败: {e}")
    # 3. 学习数据
    if _memory_learn:
        try:
            _orig_save_learn(dict(_memory_learn))
        except Exception as e:
            print(f"[静默训练] 保存学习数据失败: {e}")
# -----------------------------------

W, H = 460, 380  # 统计小窗口


def _fmt_duration(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def run():
    # 关键优化：禁用 VSync (vsync=0)，让 flip() 立即返回，不等待显示器刷新
    screen = pygame.display.set_mode((W, H), vsync=0)
    pygame.display.set_caption(f"Binary Tree Battle - {VERSION}")

    game = main.Game()
    game.start_ai_vs_ai_game()

    session_start = time.time()
    # 速度统计：每真实秒统计完成的局数（局/秒），不受帧率限制影响
    last_speed_t = time.time()
    games_in_window = 0
    speed_history = []
    speed_avg = 0.0
    # 前三局步数（每局结束时的回合数）
    recent_turns = []
    prev_session = game._ai_vs_ai_session_games
    
    # 新增：延迟保存相关
    games_since_save = 0
    SAVE_INTERVAL = 20  # 每 n 局保存一次

    clock = pygame.time.Clock()
    running = True
    last_draw_t = 0.0          # 上次绘制时间：渲染降频，让 AI 全速跑
    DRAW_INTERVAL = 0.1        # 统计界面刷新间隔(秒)；AI 计算不受此限制

    while running:
        # 事件必须每帧 pump，否则系统判定无响应；但渲染降频
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        # 记录 update 前的回合数（一局结束时 update 内部会 reset turn_count）
        prev_turn = game.turn_count
        game.update()

        # 检测一局结束：session_games 增加发生在 update() 内 game over 分支
        if game._ai_vs_ai_session_games != prev_session:
            prev_session = game._ai_vs_ai_session_games
            recent_turns.append(prev_turn)
            if len(recent_turns) > 3:
                recent_turns.pop(0)
            games_in_window += 1   # 本秒窗口内完成的局数 +1
            games_since_save += 1  # 待保存局数 +1
            
            # 关键优化：累积 N 局后，在主线程进行一次批量磁盘写入
            if games_since_save >= SAVE_INTERVAL:
                _flush_saves()
                games_since_save = 0
                
            # 仅切换局时播放 orb 音效（用未被 patch 的原始引用）
            _orig_play_sfx('orb', value=random.randint(1, 3))

        # 每真实秒结算一次平均速度（局/秒）
        now = time.time()
        if now - last_speed_t >= 1.0:
            speed_history.append(games_in_window)
            if len(speed_history) > 10:
                speed_history.pop(0)
            speed_avg = sum(speed_history) / len(speed_history)
            games_in_window = 0
            last_speed_t = now

        # 渲染降频：AI 全速 update，统计界面仅按间隔刷新，去除绘制瓶颈
        if now - last_draw_t >= DRAW_INTERVAL:
            last_draw_t = now
            # ---- 绘制统计 ----
            elapsed = time.time() - session_start
            screen.fill((25, 25, 35))
            title = main.font_mid.render("静默 AI 对弈训练", True, (160, 255, 180))
            screen.blit(title, title.get_rect(center=(W // 2, 32)))

            # 前三局步数：不足 3 局用 "-" 占位
            t1 = str(recent_turns[-3]) if len(recent_turns) >= 3 else \
                 (str(recent_turns[-2]) if len(recent_turns) >= 2 else
                  (str(recent_turns[-1]) if len(recent_turns) >= 1 else "-"))
            t2 = str(recent_turns[-2]) if len(recent_turns) >= 2 else "-"
            t3 = str(recent_turns[-1]) if len(recent_turns) >= 1 else "-"

            rows = [
                ("当前局数", f"{game._ai_vs_ai_session_games + 1}"),
                ("当前回合数", f"{game.turn_count}"),
                ("当前平均速度", f"{speed_avg:.1f} 局/秒"),
                ("已训练时间", _fmt_duration(elapsed)),
                ("历史总局数", f"{game._ai_vs_ai_total_games}"),
                ("前三局步数", f"{t1} / {t2} / {t3}"),
                ("缓存数据", f"{games_since_save} / {SAVE_INTERVAL}"),
            ]
            y = 74
            for name, val in rows:
                nt = main.font_small.render(name, True, (170, 170, 180))
                screen.blit(nt, (40, y))
                vt = main.font_mid.render(val, True, (255, 215, 0))
                screen.blit(vt, (W - 40 - vt.get_width(), y - 3))
                y += 42

            tip = main.font_tiny.render(f"Binary Tree Battle {VERSION}      --by Lzdqesj",
                                        True, (110, 110, 125))
            screen.blit(tip, tip.get_rect(center=(W // 2, H - 22)))
            # flip() 不再等待 VSync，立即返回
            pygame.display.flip()

        # 不调用 clock.tick：完全不限帧，AI 全速训练（GIL 由 Python 自身处理）

    # 退出前，强制保存最后几局的学习结果
    if games_since_save > 0:
        _flush_saves()
        
    pygame.quit()


if __name__ == "__main__":
    run()
