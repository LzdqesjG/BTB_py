"""对局回放记录系统。

以 JSONL 格式记录对局中每一步操作，用于回放播放与 AI 强化学习训练。
游戏结束时自动保存到 replays/ 目录，文件名格式：YYYYmmdd_HHMMss.bpr
"""

import json
import os
from datetime import datetime


class ReplayRecorder:
    """对局操作记录器。

    记录格式（JSONL，每行一个操作）：
      {"type":"init", "red_points":10, "blue_points":10}
      {"type":"turn", "team":"RED", "turn_num":1}
      {"type":"place_node", "team":"RED", "parent_id":0, "node_id":2, "x":300, "y":200, "strength":3, "range":120}
      {"type":"modify_branch", "team":"RED", "node_id":2, "old_strength":2, "new_strength":3}
      {"type":"remove_nodes", "ids":[3,4,5]}
      {"type":"weaken_node", "node_id":6, "old_strength":3, "new_strength":1}
      {"type":"pickup", "team":"RED", "value":2, "x":500.0, "y":300.0}
      {"type":"spawn_pack", "x":600.0, "y":400.0, "value":1}
      {"type":"end_turn", "team":"RED"}
      {"type":"game_over", "winner":"RED"}
    """

    def __init__(self, subdir=''):
        self.actions = []
        self._saved = False
        self.subdir = subdir  # 子目录（如 ai_vs_ai），相对 replays/ 根目录

    def record(self, action_type, **kwargs):
        """记录一个操作。"""
        entry = {"type": action_type}
        entry.update(kwargs)
        self.actions.append(entry)

    @property
    def filepath(self):
        """生成回放文件路径。"""
        replay_dir = os.path.join(os.path.dirname(__file__), 'replays', self.subdir)
        os.makedirs(replay_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(replay_dir, f"{ts}.bpr")

    def save(self):
        """保存回放到文件（仅在未保存过时执行）。"""
        if self._saved:
            return None
        self._saved = True
        path = self.filepath
        with open(path, 'w', encoding='utf-8') as f:
            for action in self.actions:
                f.write(json.dumps(action, ensure_ascii=False) + '\n')
        print(f"[Replay] 已保存: {path}  ({len(self.actions)} 步)")
        return path

    def save_to(self, subdir):
        """把当前记录保存到 replays/<subdir>/ 时间戳.bpr（调试用额外副本）。

        不改变 _saved 状态：不影响对局结束时的正常自动保存。
        """
        replay_dir = os.path.join(os.path.dirname(__file__), 'replays', subdir)
        os.makedirs(replay_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(replay_dir, f"{ts}.bpr")
        with open(path, 'w', encoding='utf-8') as f:
            for action in self.actions:
                f.write(json.dumps(action, ensure_ascii=False) + '\n')
        print(f"[Replay] 已保存: {path}  ({len(self.actions)} 步)")
        return path
