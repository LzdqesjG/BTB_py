"""静默 AI 对弈训练模式（独立进程 + 独立小窗口）。

由主菜单"AI 对弈"在设置中开启"静默 AI 对弈"后，经确认弹窗启动：
自动关闭主窗口并打开本窗口，进入后无法返回主菜单（关闭窗口即退出）。

- 只学习并保存 AI 参数（ai.json 权重微调 / learn.json），不保存回放；
- 每结束一局播放 orb 音效；
- 窗口仅显示训练统计：当前局数 / 当前回合数 / 当前平均速度 / 已训练时间 / 历史总局数。
"""
import os
import random
import sys
import time

# 静默模式：抑制 main 模块级主窗口创建与开始音效（必须在 import main 之前设置）
os.environ['BTB_SILENT'] = '1'
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402
import main    # noqa: E402

# 静默训练不保存回放：patch 掉 ReplayRecorder 的记录与保存
main.ReplayRecorder.record = lambda self, *a, **k: None
main.ReplayRecorder.save = lambda self, *a, **k: None

W, H = 460, 320  # 统计小窗口


def _fmt_duration(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def run():
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("静默 AI 对弈训练")

    game = main.Game()
    game.start_ai_vs_ai_game()

    session_start = time.time()
    last_session_games = 0  # 用于检测"新结束一局"播放 orb 音效
    clock = pygame.time.Clock()
    running = True
    restart_menu = False  # Esc 返回主菜单：退出后重新拉起主程序

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # 静默窗口独立于主菜单运行，返回主菜单 = 重新启动主程序
                    running = False
                    restart_menu = True
                elif event.key == pygame.K_q:
                    running = False  # 直接退出，不返回主菜单

        game.update()

        # 每结束一局播放 orb 音效
        if game._ai_vs_ai_session_games != last_session_games:
            last_session_games = game._ai_vs_ai_session_games
            main.play_sfx('orb', value=random.randint(1, 3))

        # ---- 绘制统计 ----
        elapsed = time.time() - session_start
        screen.fill((25, 25, 35))
        title = main.font_mid.render("静默 AI 对弈训练", True, (160, 255, 180))
        screen.blit(title, title.get_rect(center=(W // 2, 32)))

        rows = [
            ("当前局数", f"{game._ai_vs_ai_session_games + 1}"),
            ("当前回合数", f"{game.turn_count}"),
            ("当前平均速度", f"{game._ai_speed_avg:.1f} 步/秒"),
            ("已训练时间", _fmt_duration(elapsed)),
            ("历史总局数", f"{game._ai_vs_ai_total_games}"),
        ]
        y = 78
        for name, val in rows:
            nt = main.font_small.render(name, True, (170, 170, 180))
            screen.blit(nt, (44, y))
            vt = main.font_mid.render(val, True, (255, 215, 0))
            screen.blit(vt, (W - 44 - vt.get_width(), y - 3))
            y += 42

        tip = main.font_tiny.render("Esc 返回主菜单 | Q 直接退出 | 只学习+保存参数，不保存回放",
                                    True, (110, 110, 125))
        screen.blit(tip, tip.get_rect(center=(W // 2, H - 22)))
        pygame.display.flip()
        clock.tick(max(1, int(game.fps)))

    pygame.quit()
    if restart_menu:
        # 重新启动主菜单（静默窗口是独立进程，主菜单进程此前已关闭）
        import subprocess
        subprocess.Popen([sys.executable, os.path.join(_ROOT, 'main.py')])


if __name__ == "__main__":
    run()
