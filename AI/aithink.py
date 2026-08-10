"""AI 思考逻辑。

策略：
1. 进攻：向敌方根节点方向推进节点，寻找能切断敌方节点的路径
2. 防守：在敌方到己方根的路径上布置拦截节点
3. 资源：间歇强化关键树枝，优先拾取附近点数包
4. 随机性：加权随机选择动作，AI 聪明但可被击败

所有参数通过 assets/ai_default.json 配置，AI/ai.json 为运行时配置文件，
为空时自动从 ai_default.json 复制。

在 AI 回合时由 Game._ai_update() 调用。
"""

import json
import math
import os
import random
import shutil

from constant import (
    MAX_STRENGTH, MIN_STRENGTH, NODE_RADIUS,
    PLAY_MARGIN, PLAY_AREA_TOP, SCREEN_WIDTH, SCREEN_HEIGHT,
    RANGE_OPTIONS,
)


# ==================== 配置加载 ====================

def _load_config():
    """加载 AI 配置文件。若 AI/ai.json 为空则从 assets/ai_default.json 复制。"""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_dir, 'AI', 'ai.json')
    default_path = os.path.join(base_dir, 'assets', 'ai_default.json')

    # 若配置文件不存在或为空，从默认文件复制
    need_copy = True
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    json.loads(content)  # 验证 JSON 合法性
                    need_copy = False
        except (json.JSONDecodeError, IOError):
            need_copy = True

    if need_copy:
        shutil.copy2(default_path, config_path)

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


_CONFIG = _load_config()


# ==================== AI 类 ====================

class AIThinker:
    """AI 玩家逻辑。

    所有数值参数从 _CONFIG（ai.json）读取，
    自动学习时修改 ai.json 中的值即可生效。
    """

    def __init__(self, game):
        self.game = game
        self._team = game.current_team
        self._enemy = 'BLUE' if self._team == 'RED' else 'RED'
        self._points = game.points[self._team]
        self._own_root = self._find_root(self._team)
        self._enemy_root = self._find_root(self._enemy)

        # 从配置加载快捷引用
        self._cfg = _CONFIG
        self._p = _CONFIG['personality']
        self._sc = _CONFIG['scoring']
        self._cs = _CONFIG['cut_scoring']
        self._ds = _CONFIG['defense_scoring']
        self._ps = _CONFIG['pickup_scoring']
        self._pl = _CONFIG['placement']
        self._ru = _CONFIG['range_upgrade']
        self._st = _CONFIG['strength']
        self._bm = _CONFIG['branch_modify']
        self._fp = _CONFIG['force_pickup']
        self._fc = _CONFIG['force_cut_nearby']
        self._fz = _CONFIG['force_defend_zone']
        self._fd = _CONFIG['force_defend_root']
        self._fa = _CONFIG['force_attack_root']

    def _find_root(self, team):
        for n in self.game.nodes:
            if n.team == team and n.parent is None:
                return n
        return None

    # ==================== 主入口 ====================

    def decide_action(self):
        """返回 AI 的下一步动作。

        优先级：根危预检 > 穿敌方根 > 主动切割 > 警戒区拦截 > 根紧急防御 > 调枝 > 常规放置 > 绝望放置 > 结束
        """
        # 根危预检：敌方接近己方根时，跳过拾取和扩张，强制防御
        root_danger = False
        if self._own_root:
            min_enemy_dist = float('inf')
            for en in self.game.nodes:
                if en.team == self._enemy:
                    d = math.hypot(en.x - self._own_root.x, en.y - self._own_root.y)
                    if d < min_enemy_dist:
                        min_enemy_dist = d
            root_danger = min_enemy_dist < self._cfg.get('root_danger_range', 450)

        # 硬规则 1：点数包在范围内 → 优先拾取（根危时跳过）
        if not root_danger:
            pickup_action = self._force_pickup()
            if pickup_action:
                return pickup_action

        # 硬规则 2：己方节点接近敌方根 → 尝试穿过敌方根
        attack_root_action = self._force_attack_root()
        if attack_root_action:
            return attack_root_action

        # 硬规则 3：敌方节点在范围内 → 主动切割
        cut_action = self._force_cut_nearby()
        if cut_action:
            return cut_action

        # 硬规则 4：敌方进入警戒区 → 强制布拦截
        zone_action = self._force_defend_zone()
        if zone_action:
            return zone_action

        # 硬规则 5：敌方进入根节点紧急范围 → 强制切割
        threat_action = self._force_defend_root()
        if threat_action:
            return threat_action

        # 5. 尝试调节树枝强度
        if random.random() < self._bm['chance']:
            action = self._consider_modify_branch()
            if action:
                return action

        # 6. 常规候选评分放置
        candidates = self._generate_candidates()
        if candidates:
            return self._select_weighted(candidates)

        # 7. 绝望模式：无处可走时，放宽间距限制，强制找位置落脚
        desperate = self._desperate_place()
        if desperate:
            return desperate

        # 8. 结束回合
        return {'type': 'end_turn'}

    # ==================== 硬规则 ====================

    def _desperate_place(self):
        """绝望模式：无处可走时，放宽间距限制找落脚点。
        只检查 _in_bounds，降低 _too_close_to_any 到 NODE_RADIUS*2。
        放置强度=1、范围=120（消耗 0）。"""
        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]
        if not own_nodes:
            return None
        # 降低间距阈值到 NODE_RADIUS * 2 = 50px
        desperate_spacing = NODE_RADIUS * 2.0
        for node in own_nodes:
            for a_idx in range(16):
                angle = (math.tau / 16) * a_idx
                tx = node.x + 120 * math.cos(angle)
                ty = node.y + 120 * math.sin(angle)
                if not self._in_bounds(tx, ty):
                    continue
                # 宽松间距检查
                ok = True
                for n in self.game.nodes:
                    if math.hypot(tx - n.x, ty - n.y) < desperate_spacing:
                        ok = False
                        break
                if not ok:
                    continue
                return {
                    'type': 'place_node',
                    'parent': node,
                    'x': tx,
                    'y': ty,
                    'strength': 1,
                    'range_index': 0,
                }
        return None

    def _force_pickup(self):
        """点数包在范围内 → 强制放置节点拾取。"""
        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]
        if not own_nodes:
            return None
        pickup_range = self._fp['range']

        for pack in self.game.pickups:
            for node in own_nodes:
                d = math.hypot(node.x - pack.x, node.y - pack.y)
                if d > pickup_range:
                    continue
                if not self._in_bounds(pack.x, pack.y):
                    continue
                if self._too_close_to_any(pack.x, pack.y):
                    continue

                range_index = self._dist_to_range(d)
                if range_index <= self._points:
                    return {
                        'type': 'place_node',
                        'parent': node,
                        'x': pack.x,
                        'y': pack.y,
                        'strength': self._fp['strength'],
                        'range_index': range_index,
                    }
        return None

    def _force_cut_nearby(self):
        """敌方节点在范围内 → 主动画线穿过切割。"""
        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]
        if not own_nodes:
            return None
        enemy_nodes = [n for n in self.game.nodes if n.team == self._enemy]
        cut_range = self._fc['range']
        extend = NODE_RADIUS * self._fc['extend_ratio']
        min_str = self._fc['min_strength']

        for en in enemy_nodes:
            for node in own_nodes:
                d = math.hypot(node.x - en.x, node.y - en.y)
                if d > cut_range:
                    continue
                dx = en.x - node.x
                dy = en.y - node.y
                if d < 1:
                    continue

                target_x = en.x + (dx / d) * extend
                target_y = en.y + (dy / d) * extend

                if not self._in_bounds(target_x, target_y):
                    continue
                if self._too_close_to_any(target_x, target_y, exclude=[en]):
                    # 微调角度重试，避免因间距被直接跳过
                    found = False
                    for jitter_a in [0.3, -0.3, 0.6, -0.6, 0.9, -0.9]:
                        ca, sa = math.cos(jitter_a), math.sin(jitter_a)
                        rdx = dx * ca - dy * sa
                        rdy = dx * sa + dy * ca
                        rd = math.hypot(rdx, rdy)
                        if rd < 1:
                            continue
                        tjx = en.x + (rdx / rd) * extend
                        tjy = en.y + (rdy / rd) * extend
                        if self._in_bounds(tjx, tjy) and not self._too_close_to_any(tjx, tjy, exclude=[en]):
                            target_x, target_y = tjx, tjy
                            found = True
                            break
                    if not found:
                        continue

                target_dist = math.hypot(target_x - node.x, target_y - node.y)
                range_index = self._dist_to_range(target_dist)

                need_str = min(MAX_STRENGTH, en.strength + 1)
                max_afford = max(1, min(MAX_STRENGTH, 1 + self._points - range_index))
                strength = min(max(need_str, min_str), max_afford)
                if strength > max_afford:
                    strength = max_afford

                if range_index + (strength - 1) > self._points:
                    continue

                return {
                    'type': 'place_node',
                    'parent': node,
                    'x': target_x,
                    'y': target_y,
                    'strength': strength,
                    'range_index': range_index,
                }
        return None

    def _force_defend_zone(self):
        """敌方进入警戒区 → 强制布置拦截节点。"""
        if self._own_root is None:
            return None

        if self._team == 'RED':
            z = self._fz['red']
            in_zone = lambda x, y: x < z['x_max'] and y < z['y_max']
        else:
            z = self._fz['blue']
            in_zone = lambda x, y: x > z['x_min'] and y > z['y_min']

        threats = []
        for en in self.game.nodes:
            if en.team == self._enemy and in_zone(en.x, en.y):
                d = math.hypot(en.x - self._own_root.x, en.y - self._own_root.y)
                threats.append((en, d))
        if not threats:
            return None

        threats.sort(key=lambda x: x[1])
        threatening_enemy = threats[0][0]
        ratio = self._fz['offset_ratio']
        min_str = self._fz['min_strength']

        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]
        for node in own_nodes:
            ix = threatening_enemy.x + (self._own_root.x - threatening_enemy.x) * ratio
            iy = threatening_enemy.y + (self._own_root.y - threatening_enemy.y) * ratio

            if not self._in_bounds(ix, iy):
                continue
            if self._too_close_to_any(ix, iy, exclude=[threatening_enemy]):
                # 微调拦截点位置重试
                found = False
                for offset_ratio in [0.25, 0.45, 0.20, 0.50, 0.15, 0.55]:
                    ix2 = threatening_enemy.x + (self._own_root.x - threatening_enemy.x) * offset_ratio
                    iy2 = threatening_enemy.y + (self._own_root.y - threatening_enemy.y) * offset_ratio
                    if self._in_bounds(ix2, iy2) and not self._too_close_to_any(ix2, iy2, exclude=[threatening_enemy]):
                        ix, iy = ix2, iy2
                        found = True
                        break
                if not found:
                    continue

            target_dist = math.hypot(ix - node.x, iy - node.y)
            range_index = self._dist_to_range(target_dist)

            max_afford = max(1, min(MAX_STRENGTH, 1 + self._points - range_index))
            strength = max(min_str, min(MAX_STRENGTH, max_afford))
            if strength < min_str and strength < max_afford:
                strength = max_afford
            if strength < min_str:
                continue

            if range_index + (strength - 1) > self._points:
                continue

            return {
                'type': 'place_node',
                'parent': node,
                'x': ix,
                'y': iy,
                'strength': strength,
                'range_index': range_index,
            }
        return None

    def _force_defend_root(self):
        """敌方进入根紧急范围 → 强制切割。"""
        if self._own_root is None:
            return None

        defend_range = self._fd['range']
        extend = NODE_RADIUS * self._fd['extend_ratio']
        min_str = self._fd['min_strength']

        threats = []
        for en in self.game.nodes:
            if en.team == self._enemy:
                d = math.hypot(en.x - self._own_root.x, en.y - self._own_root.y)
                if d <= defend_range:
                    threats.append((en, d))
        if not threats:
            return None

        threats.sort(key=lambda x: x[1])
        threatening_enemy = threats[0][0]

        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]
        for node in own_nodes:
            dx = threatening_enemy.x - node.x
            dy = threatening_enemy.y - node.y
            d = math.hypot(dx, dy)
            if d < 1:
                continue

            target_x = threatening_enemy.x + (dx / d) * extend
            target_y = threatening_enemy.y + (dy / d) * extend

            if not self._in_bounds(target_x, target_y):
                continue
            if self._too_close_to_any(target_x, target_y, exclude=[threatening_enemy]):
                found = False
                for jitter_a in [0.3, -0.3, 0.6, -0.6, 0.9, -0.9]:
                    ca, sa = math.cos(jitter_a), math.sin(jitter_a)
                    rdx = dx * ca - dy * sa
                    rdy = dx * sa + dy * ca
                    rd = math.hypot(rdx, rdy)
                    if rd < 1:
                        continue
                    tjx = threatening_enemy.x + (rdx / rd) * extend
                    tjy = threatening_enemy.y + (rdy / rd) * extend
                    if self._in_bounds(tjx, tjy) and not self._too_close_to_any(tjx, tjy, exclude=[threatening_enemy]):
                        target_x, target_y = tjx, tjy
                        found = True
                        break
                if not found:
                    continue

            target_dist = math.hypot(target_x - node.x, target_y - node.y)
            range_index = self._dist_to_range(target_dist)

            max_afford = max(1, min(MAX_STRENGTH, 1 + self._points - range_index))
            strength = max(min_str, min(MAX_STRENGTH, max_afford))
            if strength < min_str:
                strength = min(MAX_STRENGTH, max_afford)

            if range_index + (strength - 1) > self._points:
                continue

            return {
                'type': 'place_node',
                'parent': node,
                'x': target_x,
                'y': target_y,
                'strength': strength,
                'range_index': range_index,
            }
        return None

    def _force_attack_root(self):
        """己方节点接近敌方根 → 尝试画线穿过敌方根节点（致命一击）。"""
        if self._enemy_root is None:
            return None

        attack_range = self._fa['range']
        extend = NODE_RADIUS * self._fa['extend_ratio']
        min_str = self._fa['min_strength']

        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]

        for node in own_nodes:
            d = math.hypot(node.x - self._enemy_root.x, node.y - self._enemy_root.y)
            if d > attack_range:
                continue

            # 从 node 沿 enemy_root 方向，在根后方落点
            dx = self._enemy_root.x - node.x
            dy = self._enemy_root.y - node.y
            if d < 1:
                continue

            target_x = self._enemy_root.x + (dx / d) * extend
            target_y = self._enemy_root.y + (dy / d) * extend

            if not self._in_bounds(target_x, target_y):
                continue
            if self._too_close_to_any(target_x, target_y, exclude=[self._enemy_root]):
                found = False
                for jitter_a in [0.3, -0.3, 0.6, -0.6, 0.9, -0.9]:
                    ca, sa = math.cos(jitter_a), math.sin(jitter_a)
                    rdx = dx * ca - dy * sa
                    rdy = dx * sa + dy * ca
                    rd = math.hypot(rdx, rdy)
                    if rd < 1:
                        continue
                    tjx = self._enemy_root.x + (rdx / rd) * extend
                    tjy = self._enemy_root.y + (rdy / rd) * extend
                    if self._in_bounds(tjx, tjy) and not self._too_close_to_any(tjx, tjy, exclude=[self._enemy_root]):
                        target_x, target_y = tjx, tjy
                        found = True
                        break
                if not found:
                    continue

            target_dist = math.hypot(target_x - node.x, target_y - node.y)
            range_index = self._dist_to_range(target_dist)

            max_afford = max(1, min(MAX_STRENGTH, 1 + self._points - range_index))
            strength = max(min_str, min(MAX_STRENGTH, max_afford))
            if strength < min_str:
                strength = min(MAX_STRENGTH, max_afford)

            if range_index + (strength - 1) > self._points:
                continue

            return {
                'type': 'place_node',
                'parent': node,
                'x': target_x,
                'y': target_y,
                'strength': strength,
                'range_index': range_index,
            }
        return None

    # ==================== 候选生成 ====================

    def _generate_candidates(self):
        own_nodes = [n for n in self.game.nodes
                     if n.team == self._team and n.can_have_child()]
        if not own_nodes:
            return []

        candidates = []
        enemy_nodes = [n for n in self.game.nodes if n.team == self._enemy]
        sample_dists = self._pl['sample_distances']
        n_angles = self._pl['sample_angles']
        jitter = self._pl['angle_jitter']

        for node in own_nodes:
            max_range = self._max_affordable_range()
            if max_range < RANGE_OPTIONS[0]:
                continue

            for a_idx in range(n_angles):
                base_angle = (math.tau / n_angles) * a_idx
                angle = base_angle + random.uniform(-jitter, jitter)

                for dist in sample_dists:
                    if dist > max_range:
                        break

                    x = node.x + dist * math.cos(angle)
                    y = node.y + dist * math.sin(angle)

                    if not self._in_bounds(x, y):
                        continue
                    if self._too_close_to_any(x, y):
                        continue

                    range_index, strength = self._pick_range_strength(dist)
                    if strength < MIN_STRENGTH:
                        continue

                    cost = range_index + max(0, strength - 1)
                    if cost > self._points:
                        continue

                    score = self._score(node, x, y, strength, range_index, enemy_nodes)
                    if score > 0:
                        candidates.append(({
                            'type': 'place_node',
                            'parent': node,
                            'x': x,
                            'y': y,
                            'strength': strength,
                            'range_index': range_index,
                        }, score))

        # ===== 定向切割候选：强制生成穿过敌方节点的候选 =====
        cut_search_range = 320
        cut_extend = NODE_RADIUS * 2.5
        for node in own_nodes:
            for en in enemy_nodes:
                d = math.hypot(node.x - en.x, node.y - en.y)
                if d < 1 or d > cut_search_range:
                    continue
                dx = en.x - node.x
                dy = en.y - node.y
                # 落点在敌方后方（延伸 NODE_RADIUS * 2.5）
                tx = en.x + (dx / d) * cut_extend
                ty = en.y + (dy / d) * cut_extend
                if not self._in_bounds(tx, ty):
                    # 如果后方出界，尝试落在敌方正上方 / 前方
                    tx2 = en.x - (dx / d) * cut_extend
                    ty2 = en.y - (dy / d) * cut_extend
                    if self._in_bounds(tx2, ty2):
                        tx, ty = tx2, ty2
                    else:
                        continue
                if self._too_close_to_any(tx, ty, exclude=[en]):
                    # 轻微抖动位置重试
                    for offset_angle in [0.3, -0.3, 0.6, -0.6]:
                        cos_a = math.cos(offset_angle)
                        sin_a = math.sin(offset_angle)
                        rotated_dx = dx * cos_a - dy * sin_a
                        rotated_dy = dx * sin_a + dy * cos_a
                        rd = math.hypot(rotated_dx, rotated_dy)
                        if rd < 1:
                            continue
                        tx_jitter = en.x + (rotated_dx / rd) * cut_extend
                        ty_jitter = en.y + (rotated_dy / rd) * cut_extend
                        if self._in_bounds(tx_jitter, ty_jitter) and not self._too_close_to_any(tx_jitter, ty_jitter, exclude=[en]):
                            tx, ty = tx_jitter, ty_jitter
                            break
                    else:
                        continue
                target_dist = math.hypot(tx - node.x, ty - node.y)
                range_index = self._dist_to_range(target_dist)
                if range_index == 0 and self._points >= self._ru['unconditional_points']:
                    range_index = 1
                need_str = min(MAX_STRENGTH, en.strength + 1)
                max_afford = max(1, min(MAX_STRENGTH, 1 + self._points - range_index))
                strength = max(need_str, min(MAX_STRENGTH, max_afford))
                if strength > max_afford:
                    strength = max_afford
                cost = range_index + max(0, strength - 1)
                if cost > self._points:
                    continue
                score = self._score(node, tx, ty, strength, range_index, enemy_nodes)
                if score > 0:
                    candidates.append(({
                        'type': 'place_node',
                        'parent': node,
                        'x': tx,
                        'y': ty,
                        'strength': strength,
                        'range_index': range_index,
                    }, score))

        return candidates

    def _select_weighted(self, candidates):
        # 存储候选供主游戏可视化
        self.game._ai_debug_candidates = [(a, s) for a, s in candidates]

        if len(candidates) == 1:
            return candidates[0][0]

        candidates.sort(key=lambda x: x[1], reverse=True)
        total = sum(s for _, s in candidates)
        randomness = self._p['randomness']

        r = random.uniform(0, total * (1.0 + randomness * 2))
        cumulative = 0.0
        for action, score in candidates:
            cumulative += score
            if r <= cumulative:
                return action

        return candidates[0][0]

    # ==================== 范围与强度选择 ====================

    @staticmethod
    def _dist_to_range(dist):
        for i, r in enumerate(RANGE_OPTIONS):
            if dist <= r:
                return i
        return len(RANGE_OPTIONS) - 1

    def _max_affordable_range(self):
        best = RANGE_OPTIONS[0]
        for i, r in enumerate(RANGE_OPTIONS):
            if i <= self._points:
                best = r
        return best

    def _pick_range_strength(self, dist):
        range_index = self._dist_to_range(dist)

        # range 升级策略
        if range_index == 0 and self._points >= 1:
            if self._points >= self._ru['unconditional_points']:
                range_index = 1
            elif random.random() < self._ru['chance_high']:
                range_index = 1
            elif self._points >= self._ru['points_for_chance_low']:
                if random.random() < self._ru['chance_low']:
                    range_index = 1

        remaining = self._points - range_index

        # 开局强度限制
        own_count = len([n for n in self.game.nodes if n.team == self._team])
        ceiling = self._st['early_game_ceiling'] if own_count <= self._st['early_game_node_limit'] else MAX_STRENGTH

        max_affordable = max(MIN_STRENGTH, min(ceiling, 1 + remaining))
        if max_affordable >= 4:
            weights = self._st['high_point_weights'][:max_affordable]
            strength = random.choices(range(1, max_affordable + 1), weights=weights, k=1)[0]
        elif max_affordable >= 2:
            strength = random.randint(1, max_affordable)
        else:
            strength = 1

        return range_index, strength

    # ==================== 评分系统 ====================

    def _score(self, parent, x, y, strength, range_index, enemy_nodes):
        own_root = self._own_root
        enemy_root = self._enemy_root
        if own_root is None or enemy_root is None:
            return 40.0

        score = 0.0

        # 进攻
        d_before = math.hypot(parent.x - enemy_root.x, parent.y - enemy_root.y)
        d_after = math.hypot(x - enemy_root.x, y - enemy_root.y)
        if d_before > 1:
            advance = (d_before - d_after) / d_before
            score += advance * self._sc['advance_weight'] * self._p['greediness']

        # 防守
        defense = self._defense_score(x, y, enemy_nodes, own_root)
        score += defense * self._sc['defense_weight'] * self._p['defensiveness']

        # 切割
        cut = self._cut_score(parent, x, y, strength, enemy_nodes)
        score += cut * self._sc['cut_weight']

        # 点数包
        pickup = self._pickup_score(x, y)
        score += pickup * self._sc['pickup_weight']

        # 强度
        score += (strength - 1) * self._sc['strength_per_level']

        # 噪声
        nr = self._sc['noise_range']
        score += random.uniform(-nr, nr)

        return max(0.0, score)

    def _defense_score(self, cx, cy, enemy_nodes, own_root):
        if not enemy_nodes:
            return 0.0
        line_range = self._ds['line_range']
        max_val = self._ds['max_value']
        check_limit = self._ds['check_limit']

        value = 0.0
        for en in enemy_nodes[:check_limit]:
            dist_to_line = self._point_seg_dist(cx, cy, en.x, en.y, own_root.x, own_root.y)
            if dist_to_line < line_range:
                value += (line_range - dist_to_line) / line_range
        return min(value, max_val)

    def _cut_score(self, parent, x, y, strength, enemy_nodes):
        score = 0.0
        p1 = (parent.x, parent.y)
        p2 = (x, y)

        for en in enemy_nodes:
            if self._seg_intersects_circle(p1, p2, (en.x, en.y), NODE_RADIUS):
                if en.parent is None:
                    score += 200.0
                else:
                    base = min(en.strength * self._cs['enemy_strength_multiplier'],
                              self._cs['enemy_strength_cap'])
                    if self._own_root:
                        d_to_own = math.hypot(en.x - self._own_root.x,
                                             en.y - self._own_root.y)
                        if d_to_own <= self._cs['root_proximity_near']:
                            base *= self._cs['_root_proximity_near_multiplier']
                        elif d_to_own <= self._cs['root_proximity_far']:
                            base *= self._cs['_root_proximity_far_multiplier']
                    score += base

            if en.parent is not None:
                p3 = (en.parent.x, en.parent.y)
                p4 = (en.x, en.y)
                if self._segments_cross(p1, p2, p3, p4):
                    score += min(en.strength * self._cs['branch_cut_multiplier'],
                                self._cs['branch_cut_cap'])

        return min(score, self._cs['total_cap'])

    def _pickup_score(self, cx, cy):
        pickup_range = self._ps['range']
        best = 0.0
        for p in self.game.pickups:
            d = math.hypot(cx - p.x, cy - p.y)
            if d < pickup_range:
                best = max(best, p.value * (pickup_range - d) / pickup_range)
        return best

    # ==================== 树枝调节 ====================

    def _consider_modify_branch(self):
        if self._points < 1:
            return None

        own_branches = [n for n in self.game.nodes
                        if n.team == self._team and n.parent is not None
                        and n.strength < MAX_STRENGTH]
        if not own_branches:
            return None

        bm = self._bm
        best_node = None
        best_score = 0.0

        for node in own_branches:
            score = 0.0
            if self._enemy_root:
                d_enemy = math.hypot(node.x - self._enemy_root.x,
                                    node.y - self._enemy_root.y)
                score += (max(0, bm['enemy_proximity_range'] - d_enemy)
                          / bm['enemy_proximity_range'] * bm['enemy_proximity_score'])

            score += (MAX_STRENGTH - node.strength) * bm['strength_diff_score']

            if self._own_root:
                d_own = math.hypot(node.x - self._own_root.x,
                                  node.y - self._own_root.y)
                score += d_own / bm['own_distance_range'] * bm['own_distance_score']

            if score > best_score:
                best_score = score
                best_node = node

        if best_node and best_score > bm['threshold']:
            return {
                'type': 'modify_branch',
                'node': best_node,
                'new_strength': best_node.strength + 1,
            }
        return None

    # ==================== 几何工具 ====================

    @staticmethod
    def _in_bounds(x, y):
        return (PLAY_MARGIN <= x <= SCREEN_WIDTH - PLAY_MARGIN and
                PLAY_AREA_TOP <= y <= SCREEN_HEIGHT - PLAY_MARGIN)

    def _too_close_to_any(self, x, y, exclude=None):
        """检查 (x,y) 是否离任何已有节点太近。exclude 为要排除的节点列表。"""
        min_dist = NODE_RADIUS * self._pl['min_node_spacing']
        for n in self.game.nodes:
            if exclude and n in exclude:
                continue
            if math.hypot(x - n.x, y - n.y) < min_dist:
                return True
        return False

    @staticmethod
    def _point_seg_dist(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        seg_sq = dx * dx + dy * dy
        if seg_sq < 1e-9:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0,
                ((px - x1) * dx + (py - y1) * dy) / seg_sq))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    @staticmethod
    def _seg_intersects_circle(p1, p2, center, radius):
        cx, cy = center
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        seg_sq = dx * dx + dy * dy
        if seg_sq < 1e-9:
            return (x1 - cx) ** 2 + (y1 - cy) ** 2 <= radius * radius
        t = max(0.0, min(1.0,
                ((cx - x1) * dx + (cy - y1) * dy) / seg_sq))
        near_x = x1 + t * dx
        near_y = y1 + t * dy
        return (near_x - cx) ** 2 + (near_y - cy) ** 2 <= radius * radius

    @staticmethod
    def _segments_cross(p1, p2, p3, p4):
        def _orient(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        o1 = _orient(p1, p2, p3)
        o2 = _orient(p1, p2, p4)
        o3 = _orient(p3, p4, p1)
        o4 = _orient(p3, p4, p2)

        if o1 == 0 or o2 == 0 or o3 == 0 or o4 == 0:
            return False
        return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)
