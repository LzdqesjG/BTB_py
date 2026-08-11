"""控制台启动脚本：启动 n 个 main.py 游戏实例（使用 venv 的 python.exe）。

用法:
    python launch_instances.py 4        # 启动 4 个游戏实例
    python launch_instances.py          # 默认 1 个

每个实例使用独立控制台窗口；父脚本等待所有实例退出后结束。
"""
import os
import subprocess
import sys

# venv 内的 python.exe
VENV_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '.venv', 'Scripts', 'python.exe')
MAIN_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.py')

# Windows: 每个子进程使用独立控制台窗口
if sys.platform == 'win32':
    CREATE_NEW_CONSOLE = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
else:
    CREATE_NEW_CONSOLE = 0


def parse_count(argv):
    """从命令行参数解析进程数量 n。"""
    if len(argv) < 2:
        return 1
    try:
        n = int(argv[1])
    except ValueError:
        print(f"[launch] 参数无效: {argv[1]}，应为整数进程数量。", file=sys.stderr)
        sys.exit(1)
    return max(1, n)


def main():
    n = parse_count(sys.argv)
    if not os.path.isfile(VENV_PY):
        print(f"[launch] 未找到 venv Python: {VENV_PY}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(MAIN_PY):
        print(f"[launch] 未找到 main.py: {MAIN_PY}", file=sys.stderr)
        sys.exit(1)

    procs = []
    for i in range(n):
        p = subprocess.Popen(
            [VENV_PY, MAIN_PY],
            cwd=os.path.dirname(MAIN_PY),
            creationflags=CREATE_NEW_CONSOLE,
        )
        procs.append(p)
        print(f"[launch] 已启动实例 {i + 1}/{n} (pid={p.pid})")

    print(f"[launch] 共 {n} 个实例，等待全部退出... (Ctrl+C 仅退出本脚本)")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("[launch] 收到 Ctrl+C，等待子进程自行退出...")
        for p in procs:
            p.wait()
    print("[launch] 全部实例已退出")


if __name__ == '__main__':
    main()
