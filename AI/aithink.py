"""AI 思考逻辑（预留）。"""

import random


class AIThinker:
    """AI 玩家逻辑。

    在 AI 回合时由 Game._ai_update() 调用，
    决定 AI 的行为（放置节点、调节强度、结束回合等）。
    """

    def __init__(self, game):
        self.game = game

    def decide_action(self):
        """返回 AI 的下一步动作。

        TODO: 实现真正的 AI 逻辑。
        当前占位：AI 仅自动结束回合。

        Returns:
            dict | None: {'type': 'place_node', 'parent': Node, 'x': float, 'y': float, 'strength': int}
                       | {'type': 'end_turn'}
                       | None（还在思考中）
        """
        # 占位：1% 概率放节点，其他时候结束回合
        if random.random() < 0.01:
            team_nodes = [n for n in self.game.nodes
                          if n.team == self.game.current_team and n.can_have_child()]
            if team_nodes:
                parent = random.choice(team_nodes)
                angle = random.uniform(0, 6.2832)
                dist = random.randint(80, 160)
                x = parent.x + dist * random.uniform(-1, 1)
                y = parent.y + dist * random.uniform(-1, 1)
                strength = random.randint(1, min(5, 1 + self.game.points[self.game.current_team]))
                return {
                    'type': 'place_node',
                    'parent': parent,
                    'x': max(40, min(x, 1260)),
                    'y': max(100, min(y, 660)),
                    'strength': strength,
                }
        return {'type': 'end_turn'}
