"""反作弊模块 —— 服务端校验蓝队所有操作。"""

import math
import time

from constant import (
    SCREEN_WIDTH, SCREEN_HEIGHT, PLAY_AREA_TOP,
    MIN_STRENGTH, MAX_STRENGTH, NODE_RADIUS, RANGE_OPTIONS, MAX_CHILDREN,
    PLAY_MARGIN,
)


# 最小相邻节点间距（平方值，避免开平方）
NEAR_NODE_DIST_SQ = (NODE_RADIUS * 2 + 6) ** 2 - 200  # 42^2 = 1764


class AntiCheat:
    """服务端反作弊：在 server 收到蓝队消息时调用对应验证方法。"""

    def __init__(self, game):
        self.game = game
        # 违规计数：累计违规超过阈值则踢出
        self._violations = 0
        self._last_check_time = time.time()
        self._action_count = 0

    def _violation(self, reason: str) -> tuple:
        """记录一次违规，返回 (False, reason)。"""
        self._violations += 1
        print(f"[ANTI-CHEAT] 违规 #{self._violations}: {reason}")
        return False, reason

    # ---- 放置节点 ----
    def check_place_node(self, parent_x: float, parent_y: float,
                         x: float, y: float,
                         radius: int, strength: int) -> tuple:
        """验证蓝队放置节点请求。

        params: parent_x, parent_y, new_x, new_y, range_radius, strength
        返回: (ok: bool, reason: str | None)
        """
        game = self.game

        # 1. 游戏状态和回合
        if game.state != 'playing':
            return self._violation("游戏未开始")
        if game.current_team != 'BLUE':
            return self._violation("非蓝队回合")
        if game.has_created_this_turn:
            return self._violation("本回合已放置过节点")

        # 2. 参数合法性
        if not (isinstance(strength, int) and MIN_STRENGTH <= strength <= MAX_STRENGTH):
            return self._violation(f"强度非法: {strength}")
        if radius not in RANGE_OPTIONS:
            return self._violation(f"范围半径非法: {radius}")

        # 3. 坐标基础合法性（防止 NaN / 极端值）
        for name, val in [('parent_x', parent_x), ('parent_y', parent_y),
                           ('x', x), ('y', y)]:
            if not (isinstance(val, (int, float)) and math.isfinite(val)):
                return self._violation(f"{name} 坐标无效: {val}")

        # 4. 新节点必须在有效游戏区域内
        if not (PLAY_MARGIN <= x <= SCREEN_WIDTH - PLAY_MARGIN):
            return self._violation(f"x 超出屏幕范围: {x}")
        if not (PLAY_AREA_TOP + PLAY_MARGIN <= y <= SCREEN_HEIGHT - PLAY_MARGIN):
            return self._violation(f"y 超出屏幕范围: {y}")

        # 5. 新节点不能与已有节点过近
        for other in game.nodes:
            dx = other.x - x
            dy = other.y - y
            if dx * dx + dy * dy < NEAR_NODE_DIST_SQ:
                return self._violation(f"与节点 id={other.id} 距离过近")

        # 6. 父节点必须存在、是蓝队、且还有子节点名额
        parent = self._find_node('BLUE', parent_x, parent_y)
        if parent is None:
            return self._violation(f"父节点不存在或不是蓝队: ({parent_x},{parent_y})")
        if len(parent.children) >= MAX_CHILDREN:
            return self._violation(f"父节点 id={parent.id} 子节点已满")

        # 7. 新节点必须在父节点范围圈内（允许超出 1 像素公差）
        dx, dy = x - parent.x, y - parent.y
        dist_sq = dx * dx + dy * dy
        max_sq = radius * radius
        if dist_sq > (radius + 1) * (radius + 1):
            return self._violation(
                f"新节点超出范围: dist={math.sqrt(dist_sq):.1f} > radius={radius}")
        if dist_sq > max_sq:
            print(f"[ANTI-CHEAT] 警告：范围边缘公差，dist={math.sqrt(dist_sq):.2f} > radius={radius}，差值 < 1，放行")

        # 8. 验证分数消耗
        strength_cost = max(0, strength - 1)
        range_cost = RANGE_OPTIONS.index(radius)
        total = strength_cost + range_cost
        if game.points['BLUE'] < total:
            return self._violation(f"点数不足: 需要 {total}, 拥有 {game.points['BLUE']}")

        # 9. 频率 / 速率检查（简单防刷）
        now = time.time()
        self._action_count += 1
        if now - self._last_check_time > 1.0:
            self._last_check_time = now
            self._action_count = 1
        if self._action_count > 10:
            return self._violation("操作频率过高")

        return True, None

    # ---- 修改树枝强度 ----
    def check_modify_branch(self, node_x: float, node_y: float,
                            target_strength: int) -> tuple:
        """验证蓝队修改树枝强度请求。

        返回: (ok: bool, reason: str | None)
        """
        game = self.game

        # 1. 游戏状态和回合
        if game.state != 'playing':
            return self._violation("游戏未开始")
        if game.current_team != 'BLUE':
            return self._violation("非蓝队回合")

        # 2. 参数合法性
        if not (isinstance(target_strength, int)
                and MIN_STRENGTH <= target_strength <= MAX_STRENGTH):
            return self._violation(f"目标强度非法: {target_strength}")

        for name, val in [('node_x', node_x), ('node_y', node_y)]:
            if not (isinstance(val, (int, float)) and math.isfinite(val)):
                return self._violation(f"{name} 坐标无效: {val}")

        # 3. 目标节点必须存在、是蓝队、有父节点（树枝=非根节点的子节点）
        target = self._find_node('BLUE', node_x, node_y, require_parent=True)
        if target is None:
            return self._violation(
                f"目标节点不存在或不是蓝队子节点: ({node_x},{node_y})")

        # 4. 点数检查
        diff = target_strength - target.strength
        if diff > 0 and game.points['BLUE'] < diff:
            return self._violation(f"点数不足: 需要 {diff}, 拥有 {game.points['BLUE']}")

        return True, None

    # ---- 结束回合 ----
    def check_end_turn(self) -> tuple:
        """验证蓝队结束回合请求。"""
        game = self.game

        if game.state != 'playing':
            return self._violation("游戏未开始")
        if game.current_team != 'BLUE':
            return self._violation("非蓝队回合，不能结束")

        return True, None

    # ===== 工具 =====

    def _find_node(self, team: str, x: float, y: float,
                   require_parent: bool = False):
        """按坐标和队伍查找节点。容差 < 1 像素。

        require_parent=True 时只匹配有父节点的节点（用于树枝操作）。
        """
        for n in self.game.nodes:
            if n.team != team:
                continue
            if require_parent and n.parent is None:
                continue
            if abs(n.x - x) < 1 and abs(n.y - y) < 1:
                return n
        return None
