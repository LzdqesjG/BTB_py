"""AI 决策引擎 —— 移植自 C++ BinaryTreeBattle 的 AI (src/ai.cpp)。

两者的底层架构不同, 但游戏内核相同:
  * 从己方节点拖出树枝生成新节点, 每个节点最多 2 个子节点;
  * 新树枝穿过对方节点/树枝会削减其强度, 强度归零则整棵子树被删除;
  * 新树枝穿过对方根节点 → 直接获胜;
  * 点数 = 强度消耗 (strength-1) + 范围消耗 (range_index)。

架构差异 (移植时做的适配):
  * C++ 的 Node 区分 edgeStrength(边强度) / level(节点等级) / attack(攻击力),
    攻击伤害 = 源节点 attack; 而 Python 的 Node.strength 同时充当"边强度"和
    "节点防御", 且新树枝伤害 = 新节点 strength (见 Game._resolve_crossing)。
    因此评分中攻击力 atk = 候选强度 str。
  * C++ 范围用 MAX_D=120 + EXTRA_D=40, ext 成本; Python 用 RANGE_OPTIONS=
    [120,160,200,240], range_index 即成本 —— 两者一一对应。
  * C++ 拾取得分点靠"树枝掠过"; Python 靠"节点碰触点数包" (NODE_RADIUS+
    PICKUP_RADIUS), 因此收集评分改为评估落点与点数包的距离。
  * C++ 窗口 1000x700, 中心 (500,350); Python 窗口 1300x700, 中心 (650,350)。

核心策略 (完全保留 C++ AI 的多维度评分体系):
  * 局面动态分析 (analyze_situation) —— 根据节点/边/点数/威胁走廊/半场控制/
    绕后缺口等动态调整进攻/扩张/防守/收集权重。
  * 候选目标生成 (gen_targets) —— 朝敌根推进、侧翼、切敌节点、切边、收集、
    环形扫描。
  * 多维度静态评分 (score_target) —— 节点命中+枢纽价值(子树大小)、边击杀/
    削弱、连击、朝敌根推进、中心控制、压制、扩张、防守纵深、母节点风险、
    收集经济性、僵持放大、噪声。
  * 威胁惩罚 (threat_penalty) —— 敌方可反击位置、贴近敌根非杀根落点、我方
    防线暴露时的深入重罚。
  * 强制杀根检测 (find_kill_move) —— 预算内可一步穿过敌根 → 直接取胜。
  * 薄弱边强化 (choose_reinforce) —— 威胁走廊内的低强度边优先加固。
  * 轻量前向模拟 (simulate_lookahead) —— 对 top 候选做"我落子→敌回应→我
    再回应"的贪心推演, 修正静态分。
  * 记忆 (memory) —— 上次落点被摧毁的位置不再重建 (打地鼠记忆), 连续无进
    攻时放大攻击倾向。

运行接口 (与 main.py 兼容):
  AIThinker(game).decide_action() -> None | {
      'type': 'place_node',   'parent': Node, 'x': float, 'y': float,
                              'strength': int, 'range_index': int
      'type': 'modify_branch','node': Node, 'new_strength': int
      'type': 'end_turn'
  }
"""


import json
import math
import os
import random
import shutil

from constant import (
    SCREEN_WIDTH, SCREEN_HEIGHT, PLAY_AREA_TOP, PLAY_MARGIN,
    NODE_RADIUS, MIN_STRENGTH, MAX_STRENGTH, MAX_CHILDREN, RANGE_OPTIONS,
    PICKUP_RADIUS,
)

# 运行时参数覆盖: 若存在 AI/ai.json, 加载并覆盖 AIConfig 默认值 (便于调参)。
# 该文件由 dev/rl_evolve.py 的进化式强化训练生成。
_AI_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai.json')
_LEARN_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'learn.json')
_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup')
_JSON_OVERRIDE = {}
if os.path.isfile(_AI_JSON):
    try:
        with open(_AI_JSON, 'r', encoding='utf-8') as _fh:
            _JSON_OVERRIDE = json.load(_fh)
    except Exception:
        _JSON_OVERRIDE = {}

# ---- C 扩展几何加速 (可选): AI/btb_geo.dll 存在时自动启用 ----
# 加速自对弈训练 (dev/rl_evolve.py / AI 对弈模式) 的热点几何计算。
# DLL 缺失时 FAST_GEO=False, 走纯 Python 实现, 行为逐位一致。
try:
    from AI.fast_geo import (FAST_GEO, HitStats, GeoPack,
                             pt_seg_dist_grid, dists_to)
except Exception:
    try:
        from fast_geo import (FAST_GEO, HitStats, GeoPack,
                              pt_seg_dist_grid, dists_to)
    except Exception:
        from collections import namedtuple as _nt
        HitStats = _nt('HitStats',
                       ['hit_root', 'nodes_hit', 'hub_value', 'edges_hit',
                        'edges_dead', 'spine_cut', 'pinned',
                        'collect_value', 'collect_grav'])
        FAST_GEO = False
        GeoPack = None
        pt_seg_dist_grid = None
        dists_to = None
# 环境变量可强制关闭 C 加速 (对照基准/调试用)
if os.environ.get('BTB_NO_FAST'):
    FAST_GEO = False


def _reload_override():
    """重新从 ai.json 加载运行时覆盖，使文件改动在本进程内立即生效。"""
    global _JSON_OVERRIDE
    try:
        with open(_AI_JSON, 'r', encoding='utf-8') as _fh:
            _JSON_OVERRIDE = json.load(_fh) or {}
    except Exception:
        _JSON_OVERRIDE = {}


# ===== 权重文件读写 / 备份 / 学习数据 (AI 自动学习基础设施) =====

def _now_tag():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_weights():
    """把当前 ai.json 备份到 AI/backup/ai_<日期时间戳>.json（按日期保留历史，写前自动调用）。"""
    if not os.path.isfile(_AI_JSON):
        return None
    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        dst = os.path.join(_BACKUP_DIR, f'ai_{_now_tag()}.json')
        shutil.copy2(_AI_JSON, dst)
        return dst
    except Exception:
        return None


def save_weights(cfg):
    """把 AIConfig 的全部权重写回 ai.json。写前自动备份旧文件，tmp+rename 原子写。

    保留 ai.json 中非权重字段（如 stats 统计），避免被权重覆盖丢失。
    """
    backup_weights()
    tmp = _AI_JSON + '.tmp'
    try:
        data = cfg.to_dict()
        st = _load_stats()
        if st:
            data['stats'] = st   # 保留非权重统计字段（嵌套在 stats 下，不展开）
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _AI_JSON)
        _reload_override()  # 本进程内立即生效
        return True
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


# ===== AI 对弈统计 (ai.json 的 stats 字段, 非权重数据) =====

def _load_stats():
    """读取 ai.json 中的 stats 统计字段；文件缺失/解析失败返回空 dict。"""
    if not os.path.isfile(_AI_JSON):
        return {}
    try:
        with open(_AI_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        s = data.get('stats')
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def _save_stats(stats):
    """把 stats 统计字段合并写回 ai.json（保留所有权重字段），原子写。"""
    data = {}
    if os.path.isfile(_AI_JSON):
        try:
            with open(_AI_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    data['stats'] = stats
    tmp = _AI_JSON + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _AI_JSON)
        return True
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _load_learn():
    """读取 AI/learn.json（学习统计与对局记录）。"""
    if os.path.isfile(_LEARN_JSON):
        try:
            with open(_LEARN_JSON, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_learn(data):
    """原子写入 AI/learn.json。"""
    tmp = _LEARN_JSON + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _LEARN_JSON)
        return True
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def reset_weights():
    """把 AI/ai.json 恢复为 AIConfig 内置出厂默认值（去掉运行时覆盖与学习微调）。

    重置前自动备份当前 ai.json（AI/backup/）。成功后重新加载运行时覆盖，
    使重置在当前进程内立即生效。返回 True 表示成功。
    """
    saved = dict(_JSON_OVERRIDE)
    _JSON_OVERRIDE.clear()
    try:
        cfg = AIConfig()  # 无覆盖 → 得到出厂默认权重
    finally:
        _JSON_OVERRIDE.update(saved)
    return save_weights(cfg)


# ============================================================
# 常量 (由游戏常量推导, 保证与 anti_cheat / main 完全一致)
# ============================================================
# 最小相邻节点间距。
# 本地放置 (main._try_create_node) 要求新节点与所有节点 (含父节点) 距离 >= NODE_RADIUS*2+4 = 40px;
# 网络反作弊 (anti_cheat) 略宽松 (≈39.55px)。AI 取严格值 40, 保证两种路径都合法。
MIN_SPACING = NODE_RADIUS * 2 + 4          # 40
NEAR_NODE_DIST_SQ = MIN_SPACING * MIN_SPACING   # 1600

# 有效放置区域 (anti_cheat 的校验边界)
MIN_X = PLAY_MARGIN
MAX_X = SCREEN_WIDTH - PLAY_MARGIN
MIN_Y = PLAY_AREA_TOP + PLAY_MARGIN
MAX_Y = SCREEN_HEIGHT - PLAY_MARGIN

MAX_RANGE = RANGE_OPTIONS[-1]            # 240
PICKUP_COLLECT_DIST = NODE_RADIUS + PICKUP_RADIUS   # 31: 节点碰包距离
CENTER_X, CENTER_Y = SCREEN_WIDTH / 2.0, 350.0      # 地图中心

_OCCUPY_BLOCK = 24.0      # 威胁检测: 我节点阻挡敌方延伸的判定半径


# ============================================================
# 几何工具 (与 main.py 的判定保持一致)
# ============================================================
def _dist(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def _pt_seg_dist(px, py, x1, y1, x2, y2):
    """点到线段的最短距离。"""
    dx, dy = x2 - x1, y2 - y1
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / seg_sq
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_seg(a, b, c):
    return (min(a[0], b[0]) - 1e-9 <= c[0] <= max(a[0], b[0]) + 1e-9 and
            min(a[1], b[1]) - 1e-9 <= c[1] <= max(a[1], b[1]) + 1e-9)


def _seg_cross(p1, p2, p3, p4):
    """两线段严格相交 (共享端点不算穿过, 与 Game._segments_intersect 一致)。"""
    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def _seg_hits_circle(x1, y1, x2, y2, cx, cy, radius):
    """线段 p1-p2 是否穿过以 (cx,cy) 为圆心、radius 为半径的圆。"""
    return _pt_seg_dist(cx, cy, x1, y1, x2, y2) <= radius


def _sector(dx, dy):
    """把方向向量映射到 0..7 扇区 (每 45° 一格)。"""
    return int(math.floor(math.atan2(dy, dx) / math.pi * 4.0) + 8) % 8


def _range_index(dist):
    """按距离求范围档位 cost (0..3); 超出最远范围返回 None。"""
    for i, r in enumerate(RANGE_OPTIONS):
        if dist <= r + 1e-6:
            return i
    return None


# ============================================================
# AI 配置参数 (移植自 C++ AIConfig)
# ============================================================
class AIConfig:
    """所有可调权重, 与 C++ ai.h 的 AIConfig 一一对应。

    默认值经过两阶段强化训练:
      1) 从 17 局人类全胜回放中拟合特征权重 (dev/train_ai.py);
      2) 进化式自对弈搜索进一步调优 (dev/rl_evolve.py)。
    可用 AI/ai.json 覆盖任意字段 (运行时加载, 见模块顶部)。
    """

    def __init__(self):
        # 攻击 (回放学习: 人类制胜移动切割枢纽 3.3x, 进化搜索进一步放大)
        self.node_hit = 1532.97    # 命中敌方节点
        self.hub_factor = 595.02   # 枢纽价值乘数 (子树越大越值钱)
        self.edge_kill = 105.28    # 摧毁敌方边
        self.edge_hit = 69.81      # 削弱敌方边
        self.decisive2 = 207.66    # 一次打掉 >=2 目标
        self.combo = 43.81         # 命中+穿越复合
        self.str_bonus = 26.50     # 攻击时每级强度奖励
        self.advance = 9.71        # 朝敌根推进乘数 (回放: 人类推进 78%)
        # 发展
        self.collect = 393.83      # 收集得分点 (回放: 人类收集 25x)
        self.collect_low = 70.86   # 缺分时收集
        self.expand = 0.24         # 开拓版图 (人类很少散开扩张)
        self.center = 0.07         # 占领中心 (低优先)
        self.defense = 2.36        # 防守纵深
        # 资源管理
        self.reserve_base = 2.48   # 保底积分基数
        self.spend_open = 27.32    # 开局花费敏感度
        self.spend_mid = 13.98     # 中后期花费敏感度 (人类花费仅随机 38%)
        self.spend_tight = 7.90    # 积分紧张敏感度
        self.extra_thresh = 414.62  # 额外行动触发阈值
        self.threat_mul = 1.46     # 威胁惩罚系数
        # 人类策略参数
        self.reinf_budget = 0.42   # 强化预算占富余分比例
        self.reinf_threat = 22.94  # 强化威胁门槛
        self.sprint_dist = 275.78  # 冲刺区距离
        self.sprint_bonus = 1.84   # 冲刺推进加成
        self.extra_sprint = 210.82  # 额外行动冲刺触发距离
        self.deep_push = 420.00    # 中距离大步推进距离
        self.hub_preference = 1.20  # 枢纽击杀偏好
        self.risk_taker = 1.12     # 冒险度
        # ===== 回放强化训练学到的权重 (人类制胜策略: 链式冲刺 + 切割枢纽) =====
        self.chain_bonus = 8.05    # 链式推进奖励: 落点沿"父→敌根"方向加分
        # ===== 成本/推进纪律 (回放失败案例调优) =====
        self.advance_cap = 160.0   # 推进收益按此距离饱和 (0=线性), 防昂贵长跳耗点数
        self.max_move_cost = 1     # 单次落子花费上限 (0=不限); 杀根走 find_kill_move 不受限
        # 人类 83% 免费范围、85% 强度1; 单次花费上限 1 强制 AI 用免费短步推进,
        # 把点数留给杀根窗口 (回放 204717/205605 的教训: AI 开局 range-200 长跳耗点)。
        # ===== 运行时覆盖 (AI/ai.json, 由 dev/rl_evolve.py 生成) =====
        for _k, _v in _JSON_OVERRIDE.items():
            if hasattr(self, _k):
                try:
                    setattr(self, _k, float(_v))
                except (TypeError, ValueError):
                    pass
        self._apply_clip()

    # ===== 权重边界（自动学习微调后夹取，防止失控） =====
    _CLIP = {
        'node_hit': (200, 5000), 'hub_factor': (100, 2500),
        'edge_kill': (10, 400), 'edge_hit': (5, 300),
        'decisive2': (20, 800), 'combo': (5, 200),
        'str_bonus': (5, 120), 'advance': (1, 40),
        'collect': (50, 1500), 'collect_low': (10, 350),
        'expand': (0.0, 2.0), 'center': (0.0, 1.0),
        'defense': (0.0, 10.0),
        'reserve_base': (0.5, 8.0),
        'spend_open': (5, 90), 'spend_mid': (2, 55),
        'spend_tight': (1, 35), 'extra_thresh': (100, 1000),
        'threat_mul': (0.6, 3.0),
        'reinf_budget': (0.1, 0.9), 'reinf_threat': (5, 60),
        'sprint_dist': (100, 500), 'sprint_bonus': (0.5, 4.0),
        'extra_sprint': (80, 500), 'deep_push': (200, 700),
        'hub_preference': (0.5, 3.0), 'risk_taker': (0.4, 2.5),
        'chain_bonus': (1, 30), 'advance_cap': (50, 500),
        'max_move_cost': (0, 8),
    }

    def to_dict(self):
        """导出全部权重字段为 dict（用于写回 ai.json）。"""
        return {k: getattr(self, k) for k in AIConfig._CLIP}

    def _apply_clip(self):
        """把所有权重夹到合理范围内（加载或微调后调用）。"""
        for k, (lo, hi) in AIConfig._CLIP.items():
            v = getattr(self, k, None)
            if v is not None:
                setattr(self, k, max(lo, min(hi, float(v))))


# ============================================================
# 前向模拟用轻量节点 / 局面 (不依赖 pygame 的 Node 类)
# ============================================================
class _SimNode:
    __slots__ = ('x', 'y', 'team', 'strength', 'parent', 'children')

    def __init__(self, x, y, team, strength, parent=None):
        self.x = x
        self.y = y
        self.team = team
        self.strength = strength
        self.parent = parent
        self.children = []

    def subtree(self):
        cnt = 1
        for c in self.children:
            cnt += c.subtree()
        return cnt


class _SimState:
    """浅克隆局面, 用于前向模拟。不模拟点数包精确生成, 只模拟切割/胜负。"""

    def __init__(self, nodes, my_team, en_team):
        self.map = {}
        for n in nodes:
            self.map[n] = _SimNode(n.x, n.y, n.team, n.strength)
        for n in nodes:
            sn = self.map[n]
            if n.parent is not None and n.parent in self.map:
                pn = self.map[n.parent]
                sn.parent = pn
                pn.children.append(sn)
        self.all = list(self.map.values())
        self.my_team = my_team
        self.en_team = en_team
        self.my_root = None
        self.en_root = None
        for sn in self.all:
            if sn.parent is None:
                if sn.team == my_team:
                    self.my_root = sn
                else:
                    self.en_root = sn

    def _remove_subtree(self, node):
        dead = []
        stack = [node]
        while stack:
            cur = stack.pop()
            dead.append(cur)
            for c in cur.children:
                stack.append(c)
        if node.parent is not None:
            node.parent.children = [c for c in node.parent.children if c is not node]
        for d in dead:
            if d in self.all:
                self.all.remove(d)
        if node is self.my_root:
            self.my_root = None
        if node is self.en_root:
            self.en_root = None

    def apply(self, parent, tgt, str_, team):
        """在模拟局面上放置一个新节点并结算切割。"""
        if len(parent.children) >= MAX_CHILDREN:
            return False
        x, y = tgt
        nd = _SimNode(x, y, team, str_, parent)
        parent.children.append(nd)
        self.all.append(nd)
        enemy = self.en_team if team == self.my_team else self.my_team
        src = (parent.x, parent.y)
        # 穿过敌方节点
        hits = []
        for sn in self.all:
            if sn.team == enemy:
                if (sn.x == src[0] and sn.y == src[1]) or (sn.x == x and sn.y == y):
                    continue
                if _seg_hits_circle(src[0], src[1], x, y, sn.x, sn.y, NODE_RADIUS):
                    hits.append(sn)
        for sn in hits:
            if sn.parent is None:
                # 根节点被穿过 → 该方根移除 (胜负判定)
                if sn is self.en_root:
                    self.en_root = None
                if sn is self.my_root:
                    self.my_root = None
                return True
        # 穿过敌方边
        edge_hits = []
        for sn in self.all:
            if sn.team == enemy and sn.parent is not None:
                if _seg_cross(src, (x, y), (sn.parent.x, sn.parent.y), (sn.x, sn.y)):
                    edge_hits.append(sn)
        # 统一结算
        to_kill = []
        for sn in hits + edge_hits:
            if sn not in self.all:
                continue
            sn.strength -= str_
            if sn.strength <= 0:
                to_kill.append(sn)
        for sn in to_kill:
            if sn in self.all:
                self._remove_subtree(sn)
        return True


# ============================================================
# AI 主类
# ============================================================
class AIThinker:
    def __init__(self, game, cfg=None):
        self.game = game
        self.cfg = cfg if cfg is not None else AIConfig()
        self.team = getattr(game, '_ai_team', None)
        if self.team is None:
            self.team = game.current_team
        self.enemy_team = 'BLUE' if self.team == 'RED' else 'RED'
        self.my_root = None
        self.en_root = None
        self.sit = None
        self._rng = random.Random(20240810)
        self.mem = self._memory()
        # 候选可视化数据: [(parent, x, y, strength, range_index, score), ...]
        self.last_cands = []

    # ---------- 记忆 ----------
    def _memory(self):
        # 双 AI（AI 对战 + 玩家托管）时按队伍隔离记忆，避免两个 AI 互相污染
        by_team = getattr(self.game, '_ai_memory_by_team', None)
        if isinstance(by_team, dict):
            team = self.team
            if team not in by_team:
                by_team[team] = {}
            return by_team[team]
        mem = getattr(self.game, '_ai_memory', None)
        if not isinstance(mem, dict):
            mem = {}
            self.game._ai_memory = mem
        return mem

    def _update_memory(self, nodes):
        """检查己方所有历史落点, 把已被摧毁的位置记入'打地鼠'禁区。
        (修复: 旧版只记最近一次落点, 若 AI 落点A后再落点B, A被摧毁时无法记录,
         导致反复在 A 重建。现改为跟踪全部历史落点。)

        同时维护互剪僵局计数 cut_streak: 连续 N 次落点都被立刻剪掉 → 说明
        双方在互剪 (回放 20260811_185653 陷入 600+ 回合互剪循环), 后续评分
        会大幅降低剪击收益、放大推进收益来强制破局。
        """
        mem = self.mem
        placements = mem.get('my_placements', [])
        alive = []
        kt = mem.setdefault('killed_targets', [])
        for (x, y) in placements:
            found = any(n.team == self.team and abs(n.x - x) < 1.0
                        and abs(n.y - y) < 1.0 for n in nodes)
            if found:
                alive.append((x, y))
            else:
                if (x, y) not in kt:
                    kt.append((x, y))
                    if len(kt) > 10:
                        kt.pop(0)
        mem['my_placements'] = alive
        # 互剪僵局: 上一次落点 (placements[-1]) 若已被剪 → cut_streak+1, 否则清零
        prev_last = placements[-1] if placements else None
        if prev_last is not None and prev_last not in alive:
            mem['cut_streak'] = mem.get('cut_streak', 0) + 1
        else:
            mem['cut_streak'] = 0

    def _remember_placement(self, x, y):
        """记录一次己方落子位置, 供 _update_memory 追踪是否被摧毁。"""
        mem = self.mem
        mp = mem.setdefault('my_placements', [])
        mp.append((x, y))
        if len(mp) > 24:
            mp.pop(0)

    # ---------- 对手行为统计 (自动学习) ----------
    def observe_opponent(self, nodes):
        """统计对手打法偏好，写入跨回合记忆（供对局结束学习使用）。

        指标:
        - long_dist / total: 敌方非根节点中父距离 >160px 的比例（长距离落子习惯）
        - strong / total: 敌方节点强度 >1 的比例（强化习惯）
        """
        mem = self.mem
        os_ = mem.setdefault('opp_stats',
                             {'long_dist': 0, 'total': 0, 'strong': 0})
        total = 0
        long_dist = 0
        strong = 0
        for n in nodes:
            if n.team != self.enemy_team or n.parent is None:
                continue
            total += 1
            if math.hypot(n.x - n.parent.x, n.y - n.parent.y) > 160:
                long_dist += 1
            if n.strength > 1:
                strong += 1
        os_['long_dist'] = long_dist
        os_['total'] = total
        os_['strong'] = strong

    def record_match_result(self, result, reason='', turns=0):
        """对局结束自动学习：更新 learn.json，按结果微调权重并写回 ai.json。

        参数:
        - result: 'win' / 'loss' / 'draw'（draw = 中途退出未分胜负，只记录不调权重）
        触发时机: 单人 AI 对局结束返回菜单时 (main.go_menu)。
        - 连续失败 (>=3) → 保守化: 降冒险/花费/枢纽偏好, 升威胁感知与防守收集。
        - 连续胜利 (>=3) → 轻微恢复激进。
        - 权重写回前自动把旧 ai.json 按日期备份到 AI/backup/。
        """
        learn = _load_learn()
        learn['wins'] = learn.get('wins', 0) + (1 if result == 'win' else 0)
        learn['losses'] = learn.get('losses', 0) + (1 if result == 'loss' else 0)
        learn['draws'] = learn.get('draws', 0) + (1 if result == 'draw' else 0)
        learn['total_games'] = learn.get('total_games', 0) + 1

        rec = {
            't': _now_tag(),
            'result': result,
            'turns': turns,
            'reason': reason or '',
        }
        os_ = self.mem.get('opp_stats', {})
        if os_ and os_.get('total'):
            rec['enemy_style'] = {
                'long_range_ratio': round(os_['long_dist'] / os_['total'], 2),
                'reinforce_ratio': round(os_['strong'] / os_['total'], 2),
            }
        learn.setdefault('recent', []).append(rec)
        learn['recent'] = learn['recent'][-20:]

        # ---- 依据最近连败/连胜微调权重 (平局只统计不调整) ----
        cfg = self.cfg
        adjusted = False  # 权重是否实际变化（决定是否备份+写盘）
        if result in ('win', 'loss'):
            win = (result == 'win')
            streak = 0
            for r in reversed(learn['recent']):
                if (r['result'] == 'win') == win:
                    streak += 1
                else:
                    break
            if not win and streak >= 3:
                cfg.risk_taker *= 0.96          # 降低冒险度（小步微调，防权重震荡）
                cfg.spend_mid *= 0.98           # 花费更保守
                cfg.hub_preference *= 0.98      # 减少高风险枢纽击杀
                cfg.threat_mul *= 1.03          # 提升威胁感知
                cfg.collect_low *= 1.05         # 更积极收集保点数
                learn['last_adjust'] = 'conservative'
                adjusted = True
            elif win and streak >= 3:
                cfg.risk_taker *= 1.03          # 小幅恢复冒险
                cfg.spend_mid *= 1.02
                cfg.threat_mul *= 0.99
                learn['last_adjust'] = 'aggressive'
                adjusted = True

        # ---- 对手行为应对：对手爱强化 → 提高威胁感知 ----
        if os_ and os_.get('total'):
            reinf = os_['strong'] / os_['total']
            if reinf > 0.5:
                cfg.threat_mul = min(3.0, cfg.threat_mul * 1.02)
                adjusted = True

        cfg._apply_clip()
        if adjusted:
            save_weights(cfg)  # 权重有变化才备份并写回 ai.json（对弈连刷也不会堆积备份）
        _save_learn(learn)
        return learn

    # ---------- 根节点查找 ----------
    def _find_roots(self):
        self.my_root = None
        self.en_root = None
        for n in self.game.nodes:
            if n.parent is None:
                if n.team == self.team:
                    self.my_root = n
                else:
                    self.en_root = n
                if self.my_root and self.en_root:
                    return

    # ============================================================
    # 局面动态分析
    # ============================================================
    def analyze_situation(self):
        nodes = self.game.nodes
        my_root, en_root = self.my_root, self.en_root
        my_score = self.game.points[self.team]
        en_score = self.game.points[self.enemy_team]

        class S:  # 局面快照
            pass
        s = S()
        s.my_nodes = s.en_nodes = 0
        s.my_avg_edge = s.en_avg_edge = 1.0
        s.en_front_count = 0
        my_edge_sum = en_edge_sum = 0.0
        my_edge_cnt = en_edge_cnt = 0

        for n in nodes:
            if n.team == self.team:
                s.my_nodes += 1
                for c in n.children:
                    my_edge_sum += c.strength
                    my_edge_cnt += 1
            else:
                s.en_nodes += 1
                for c in n.children:
                    en_edge_sum += c.strength
                    en_edge_cnt += 1
                if len(n.children) < MAX_CHILDREN and \
                        _dist(n.x, n.y, en_root.x, en_root.y) < 300:
                    s.en_front_count += 1

        s.my_avg_edge = my_edge_sum / my_edge_cnt if my_edge_cnt else 1.0
        s.en_avg_edge = en_edge_sum / en_edge_cnt if en_edge_cnt else 1.0

        # ---- 己方根 8 扇区防护缺口 (预防绕后) ----
        sector_prot = [1e9] * 8
        for n in nodes:
            if n.team != self.team:
                continue
            d = _dist(n.x, n.y, my_root.x, my_root.y)
            if d < 5:
                continue
            sec = _sector(n.x - my_root.x, n.y - my_root.y)
            if d < sector_prot[sec]:
                sector_prot[sec] = d
        s.flank_gap = 0.0
        s.flank_gap_angle = -1
        for i, v in enumerate(sector_prot):
            if v > s.flank_gap:
                s.flank_gap = v
                s.flank_gap_angle = i
        s.flank_threat = False
        if s.flank_gap_angle >= 0:
            for n in nodes:
                if n.team == self.team:
                    continue
                d = _dist(n.x, n.y, my_root.x, my_root.y)
                if d > 280:
                    continue
                if _sector(n.x - my_root.x, n.y - my_root.y) == s.flank_gap_angle:
                    s.flank_threat = True
                    break

        # ---- 敌方根缺口 (供主动绕后攻击) ----
        en_sec_prot = [1e9] * 8
        for n in nodes:
            if n.team == self.team:
                continue
            d = _dist(n.x, n.y, en_root.x, en_root.y)
            if d < 5:
                continue
            sec = _sector(n.x - en_root.x, n.y - en_root.y)
            if d < en_sec_prot[sec]:
                en_sec_prot[sec] = d
        s.en_flank_gap = 0.0
        s.en_flank_gap_angle = -1
        for i, v in enumerate(en_sec_prot):
            if v > s.en_flank_gap:
                s.en_flank_gap = v
                s.en_flank_gap_angle = i

        # ---- 玩家行为倾向 (无在线学习数据时取中性; 可被外部写入覆盖) ----
        s.player_aggression = 0.5
        s.player_defense = 0.5
        s.player_turtle = False

        # ---- 双方是否尚未正面交锋 ----
        nearest = 1e9
        for n in nodes:
            if n.team == self.team:
                for m in nodes:
                    if m.team != self.team:
                        d = _dist(n.x, n.y, m.x, m.y)
                        if d < nearest:
                            nearest = d
        s.no_contact = nearest > 260

        # ---- 换位思考: 我方薄弱边 / 暴露节点 ----
        s.my_weak_edges = 0
        s.my_front_exposed = 0
        for n in nodes:
            if n.team != self.team:
                continue
            for c in n.children:
                if c.strength > 1:
                    continue
                for en in nodes:
                    if en.team == self.team or len(en.children) >= MAX_CHILDREN:
                        continue
                    d = _dist(en.x, en.y, c.x, c.y)
                    if 20 < d < MAX_RANGE:
                        s.my_weak_edges += 1
                        break
            for en in nodes:
                if en.team == self.team or len(en.children) >= MAX_CHILDREN:
                    continue
                d = _dist(en.x, en.y, n.x, n.y)
                if 20 < d < RANGE_OPTIONS[0]:
                    s.my_front_exposed += 1
                    break

        # ---- 全局: 黄点资源优势 ----
        s.score_pt_adv = 0.0
        for sp in self.game.pickups:
            my_best = en_best = 1e9
            for n in nodes:
                if len(n.children) >= MAX_CHILDREN:
                    continue
                d = _dist(n.x, n.y, sp.x, sp.y)
                if n.team == self.team:
                    if d < my_best:
                        my_best = d
                else:
                    if d < en_best:
                        en_best = d
            if my_best < en_best - 40:
                s.score_pt_adv += sp.value
            elif en_best < my_best - 40:
                s.score_pt_adv -= sp.value

        # ---- 全局: 威胁走廊 (敌方节点逼近我根) ----
        s.en_near_root = 0
        for n in nodes:
            if n.team == self.team:
                continue
            if _dist(n.x, n.y, my_root.x, my_root.y) < 250 and \
                    len(n.children) < MAX_CHILDREN:
                s.en_near_root += 1

        # ---- 全局: 前线对比 (距敌根 < 300) ----
        s.my_front_n = s.en_front_n = 0
        s.my_front_edge = s.en_front_edge = 0.0
        for n in nodes:
            d_en = _dist(n.x, n.y, en_root.x, en_root.y)
            if d_en < 300:
                if n.team == self.team:
                    s.my_front_n += 1
                    for c in n.children:
                        s.my_front_edge += c.strength
                else:
                    s.en_front_n += 1
                    for c in n.children:
                        s.en_front_edge += c.strength

        # ---- 全局: 半场控制 (节点深入对方半场) ----
        s.my_control = s.en_control = 0.0
        for n in nodes:
            d_my = _dist(n.x, n.y, my_root.x, my_root.y)
            d_en = _dist(n.x, n.y, en_root.x, en_root.y)
            if n.team == self.team:
                if d_en < d_my:
                    s.my_control += 1.0
            else:
                if d_my < d_en:
                    s.en_control += 1.0

        # ---- 全局: 敌方根威胁预警 / 根部盾牌 ----
        s.en_min_dist = 1e9
        s.en_probing = False
        s.my_root_shield = 0
        for n in nodes:
            if n.team != self.team:
                d = _dist(n.x, n.y, my_root.x, my_root.y)
                if d < s.en_min_dist:
                    s.en_min_dist = d
            else:
                if _dist(n.x, n.y, my_root.x, my_root.y) < 240:
                    s.my_root_shield += 1
        s.en_probing = s.en_min_dist < 260

        # ---- 实时动态模型: 敌方进攻主轴(链)检测 ----
        # 从最接近我根的敌方节点沿父链回溯, 得到敌方推进链的节点集合。
        # 切割这些节点/边 = 拦截人类的"链式冲刺", 是动态模型的核心。
        s.enemy_spine = set()
        s.spine_spear_dist = 1e9
        spine_spear = None
        for n in nodes:
            if n.team == self.team or n.parent is None:
                continue
            d = _dist(n.x, n.y, my_root.x, my_root.y)
            if d < s.spine_spear_dist:
                s.spine_spear_dist = d
                spine_spear = n
        if spine_spear is not None:
            cur = spine_spear
            seen = set()
            while cur is not None and cur.parent is not None and cur.id not in seen:
                s.enemy_spine.add(cur.id)
                seen.add(cur.id)
                cur = cur.parent

        s.en_score_ahead = en_score > my_score + 3
        s.my_score = my_score
        s.en_score = en_score
        return s

    # ============================================================
    # 资源管理
    # ============================================================
    def compute_reserve(self, my_score, total_nodes):
        """保底积分: 不能把分花光, 至少保留一次免费行动的能力。"""
        reserve = 3
        if total_nodes < 8:
            reserve = min(5, 3 + my_score // 10)
        elif my_score <= 5:
            reserve = 2
        else:
            reserve = min(5, 3 + my_score // 12)
        sit = self.sit
        if sit.en_score_ahead:
            reserve += 1
        if sit.en_near_root >= 2:
            reserve += 1
        if sit.score_pt_adv < 0 and my_score < 8:
            reserve += 1
        if sit.flank_threat:
            reserve += 1
        # 僵持时几乎不留保底, 把分花在进攻/破局上
        if self.mem.get('no_progress', 0) >= 3 and my_score >= 1:
            reserve = min(reserve, 1)
        # 杀根窗口预留: 己方可扩展节点已进入敌根 240 范围时, 保留发起杀根所需点数
        # (修复回放 20260810_154845: AI 进入杀根窗口却因点数耗尽付不起 range-240 的失败)
        en_root = self.en_root
        if en_root is not None:
            for n in self.game.nodes:
                if n.team == self.team and len(n.children) < MAX_CHILDREN:
                    d = _dist(n.x, n.y, en_root.x, en_root.y)
                    kill_dist = d + 42.0   # 需越过根至少 42px
                    if kill_dist <= MAX_RANGE:
                        need = _range_index(kill_dist) or 0
                        reserve = max(reserve, need)
                        break
        if my_score > 0:
            return min(reserve, my_score)
        return 0

    def _spend_multiplier(self, my_score, total_nodes):
        sit = self.sit
        if sit.my_nodes < 4 or total_nodes < 8:
            m = self.cfg.spend_open
        elif my_score <= 5:
            m = self.cfg.spend_tight
        else:
            m = self.cfg.spend_mid
        if sit.en_score_ahead:
            m *= 1.4
        if sit.score_pt_adv < -3:
            m *= 1.3
        if sit.en_near_root >= 2 and my_score < 8:
            m *= 1.3
        return m

    # ============================================================
    # 动态策略权重 (随局面变化)
    # ============================================================
    def _dynamic_multipliers(self):
        sit = self.sit
        atk = exp = dfn = col = 1.0
        # 僵持冲刺: 连续多回合落子但无战果 → 提高进攻倾向, 降低保守防守
        if self.mem.get('no_progress', 0) >= 3:
            atk *= 1.6
            dfn *= 0.7
            exp *= 0.8
        if sit.player_aggression > 0.55:
            dfn = 1.6
        if sit.en_score > sit.my_score + 4:
            atk = 1.3
        if sit.my_nodes < sit.en_nodes:
            exp = 1.5
        if sit.en_avg_edge > 2.2:
            atk *= 1.2
        if sit.player_turtle:
            atk *= 1.25
        if sit.en_front_count > sit.my_nodes:
            atk *= 1.1
        if sit.flank_threat:
            dfn *= 2.0
        if sit.en_score >= 8:
            dfn *= 1.7
        if sit.en_score >= 12:
            dfn *= 2.2
        if sit.en_score >= 10 and sit.my_avg_edge < sit.en_avg_edge:
            atk *= 0.8
        if sit.no_contact:
            col *= 2.5
            atk *= 0.7
        if sit.my_score < 6:
            col *= 2.2
        if sit.en_score > sit.my_score:
            col *= 1.8
        if sit.my_score < 10 and sit.en_score >= 8:
            col *= 1.5
        if sit.my_weak_edges >= 2:
            atk *= 0.85
        if sit.my_weak_edges >= 4:
            atk *= 0.7
        if sit.my_front_exposed >= 3:
            atk *= 0.85
        if sit.my_weak_edges >= 3 or sit.my_front_exposed >= 4:
            dfn *= 1.5
        if sit.score_pt_adv < 0:
            col *= 1.6
        if sit.score_pt_adv >= 4:
            col *= 1.3
        if sit.en_near_root >= 1:
            dfn *= 1.4
        if sit.en_near_root >= 3:
            dfn *= 1.8
        if sit.en_front_n > sit.my_front_n + 2:
            atk *= 0.85
        if sit.my_front_n == 0 and sit.en_front_n > 0:
            dfn *= 1.5
        if sit.en_front_edge > sit.my_front_edge * 1.5:
            dfn *= 1.3
        if sit.en_control > sit.my_control + 2:
            dfn *= 1.5
        if sit.en_score_ahead:
            col *= 1.4
        # 实时动态模型: 敌方进攻主轴逼近我根 → 强化拦截与防守
        spear = getattr(sit, 'spine_spear_dist', 1e9)
        if spear < 300:
            dfn *= 1.4
        if spear < 180:
            dfn *= 1.8
        return atk, exp, dfn, col

    # ============================================================
    # 强制杀根检测
    # ============================================================
    def find_kill_move(self, nodes, my_score):
        """强制杀根: 预算内可一步穿过敌根 → 直接取胜 (最高优先级)。

        搜索范围比早期版本更广: 除了敌根正后方轴线, 还采样根后方两侧扇区,
        避免轴线落点被占用时白白错过胜机。选最省钱的杀根 (range 档位最小)。
        """
        if self.my_root is None or self.en_root is None:
            self._find_roots()
        if self.sit is None:
            self.sit = self.analyze_situation()
        en_root = self.en_root
        best = None
        best_ri = 99
        # 己方可扩展节点按到敌根距离排序 (近的优先找到更省钱的解)
        cands_n = [n for n in nodes
                   if n.team == self.team and len(n.children) < MAX_CHILDREN]
        cands_n.sort(key=lambda n: math.hypot(en_root.x - n.x, en_root.y - n.y))
        # 根后方落点距离档位: 40 起步 (最小间距正好 40), 覆盖 range 120~240 各档
        dists = (40.0, 51.0, 62.0, 73.0, 84.0, 95.0, 106.0, 117.0,
                 128.0, 139.0, 150.0, 161.0)
        # 落点偏转角 (弧度): 0 = 根正后方, 两侧扇区采样 (穿过根圆的落点不一定在轴线上)
        angles = (0.0, -0.15, 0.15, -0.3, 0.3, -0.5, 0.5, -0.75, 0.75)
        for n in cands_n:
            dx = en_root.x - n.x
            dy = en_root.y - n.y
            L = math.hypot(dx, dy)
            if L < 18 or L >= MAX_RANGE:
                continue
            ux, uy = dx / L, dy / L
            for ang in angles:
                ca, sa = math.cos(ang), math.sin(ang)
                vx = ux * ca - uy * sa
                vy = ux * sa + uy * ca
                for extra in dists:
                    d = L + extra
                    if d > MAX_RANGE:
                        break   # dists 递增, 后续更远
                    ri = _range_index(d)
                    if ri is None or ri > my_score or ri >= best_ri:
                        continue
                    tx, ty = n.x + vx * d, n.y + vy * d
                    if not self._in_bounds(tx, ty):
                        continue
                    if self._occupied(tx, ty, nodes, n):
                        continue
                    if not _seg_hits_circle(n.x, n.y, tx, ty,
                                            en_root.x, en_root.y, NODE_RADIUS):
                        continue
                    best_ri = ri
                    best = (n, tx, ty, ri)
        if best is not None:
            n, tx, ty, ri = best
            self.last_cands = [(n, tx, ty, MIN_STRENGTH, ri, 99999.0)]
            return {'type': 'place_node', 'parent': n, 'x': tx, 'y': ty,
                    'strength': MIN_STRENGTH, 'range_index': ri}
        return None

    # ============================================================
    # 候选目标生成 (有界, 控制性能)
    # ============================================================
    def gen_targets(self, parent, nodes, en_root, pickups, light=False):
        out = []
        px, py = parent.x, parent.y

        def push(x, y):
            out.append((x, y))

        dx = en_root.x - px
        dy = en_root.y - py
        d = math.hypot(dx, dy)
        if d > 1:
            ux, uy = dx / d, dy / d
            for dist in (35, 55, 75, 95, 115, 140, 165, 195, 225):
                push(px + ux * dist, py + uy * dist)
            for ang in (-0.5, 0.5, -0.28, 0.28, -0.12, 0.12, -0.75, 0.75):
                cs, sn = math.cos(ang), math.sin(ang)
                rx = ux * cs - uy * sn
                ry = ux * sn + uy * cs
                for dist in (70, 110, 150, 190, 230):
                    push(px + rx * dist, py + ry * dist)

        # 敌方节点周边 (切节点/拦截)
        en_near = []
        for n in nodes:
            if n.team == self.team:
                continue
            ddx, ddy = n.x - px, n.y - py
            L = math.hypot(ddx, ddy)
            if L < 25 or L > MAX_RANGE + 20:
                continue
            en_near.append((L, n))
        en_near.sort(key=lambda t: t[0])
        for _, n in en_near[:6]:
            ddx, ddy = n.x - px, n.y - py
            L = math.hypot(ddx, ddy)
            if L < 1:
                continue
            ux, uy = ddx / L, ddy / L
            push(n.x, n.y)
            for off in (-30, 30, -45, 45):
                push(n.x - uy * off, n.y + ux * off)
            if len(n.children) < MAX_CHILDREN:
                push(n.x + ux * 35, n.y + uy * 35)

        # 敌方节点与敌根中点 (切入路径)
        for n in nodes:
            if n.team == self.team or n.parent is None:
                continue
            mid = ((n.x + en_root.x) * 0.5, (n.y + en_root.y) * 0.5)
            if 30 < _dist(mid[0], mid[1], px, py) < MAX_RANGE:
                push(*mid)

        # 点数包周边
        for sp in pickups:
            dsp = _dist(sp.x, sp.y, px, py)
            if dsp < 18 or dsp > MAX_RANGE:
                continue
            push(sp.x, sp.y)
            if dsp > 1:
                ux = (sp.x - px) / dsp
                uy = (sp.y - py) / dsp
                push(sp.x - uy * 18, sp.y + ux * 18)
                push(sp.x + uy * 18, sp.y - ux * 18)

        # 环形扫描 (保障覆盖)
        if not light and len(out) < 60:
            ring_n = 16
            for a in range(ring_n):
                rad = a * 6.28318 / ring_n + self._rng.uniform(-0.1, 0.1)
                for dist in (45, 75, 105, 140):
                    push(px + math.cos(rad) * dist, py + math.sin(rad) * dist)

        # 去重 + 截断 (保证单节点候选数受控)
        seen = set()
        result = []
        for t in out:
            key = (round(t[0] / 8.0), round(t[1] / 8.0))
            if key in seen:
                continue
            seen.add(key)
            result.append(t)
            if len(result) >= (40 if light else 80):
                break
        return result

    # ============================================================
    # 合法性
    # ============================================================
    @staticmethod
    def _in_bounds(x, y):
        return (MIN_X <= x <= MAX_X) and (MIN_Y <= y <= MAX_Y)

    @staticmethod
    def _occupied(x, y, nodes, exclude):
        for o in nodes:
            if o is exclude:
                continue
            if (o.x - x) ** 2 + (o.y - y) ** 2 < NEAR_NODE_DIST_SQ:
                return True
        return False

    def _valid_target(self, parent, tgt, nodes):
        tx, ty = tgt
        if not self._in_bounds(tx, ty):
            return False
        d = _dist(parent.x, parent.y, tx, ty)
        if d < MIN_SPACING or d > MAX_RANGE:
            return False
        if self._occupied(tx, ty, nodes, parent):
            return False
        return True

    # ============================================================
    # 子树规模 (用于枢纽价值)
    # ============================================================
    def subtree_size(self, n):
        cnt = 1
        for c in n.children:
            cnt += self.subtree_size(c)
        return cnt

    # ============================================================
    # 几何命中统计 (收集/节点/边/压制) — 一条移动的所有几何量一次算完
    # 纯 Python 参考实现, 与 C 扩展 btb_analyze_moves 逐位等价。
    # fast 模式 (FAST_GEO) 下由 GeoPack 批量预计算后经 st 参数传入。
    # ============================================================
    def _hit_stats(self, src, tgt, atk, en_nodes, en_edges, pickups, spine=None):
        hit_root = False
        nodes_hit = 0
        hub_value = 0
        spine_cut = 0
        for n in en_nodes:
            if (n.x == src[0] and n.y == src[1]) or (n.x == tgt[0] and n.y == tgt[1]):
                continue
            if _seg_hits_circle(src[0], src[1], tgt[0], tgt[1],
                                n.x, n.y, NODE_RADIUS):
                if n.parent is None:
                    hit_root = True
                    break
                nodes_hit += 1
                hub_value += self.subtree_size(n)
                if spine and n.id in spine:
                    spine_cut += 1
        if hit_root:
            return HitStats(1, 0, 0.0, 0, 0, 0, 0, 0.0, 0.0)
        edges_hit = 0
        edges_dead = 0
        for (ex1, ey1, ex2, ey2, est, child) in en_edges:
            if _seg_cross(src, (tgt[0], tgt[1]), (ex1, ey1), (ex2, ey2)):
                edges_hit += 1
                if est <= atk:
                    edges_dead += 1
                if spine and child.id in spine:
                    spine_cut += 1
        pinned = 0
        for n in en_nodes:
            if len(n.children) < MAX_CHILDREN:
                d = _dist(tgt[0], tgt[1], n.x, n.y)
                if 20 < d < 55:
                    pinned += 1
        collect_value = 0.0
        collect_grav = 0.0
        for sp in pickups:
            d = _dist(tgt[0], tgt[1], sp.x, sp.y)
            if d < PICKUP_COLLECT_DIST:
                collect_value += sp.value
            elif d < 130:
                collect_grav += sp.value * (1.0 - d / 130.0)
        return HitStats(0, nodes_hit, hub_value, edges_hit, edges_dead,
                        spine_cut, pinned, collect_value, collect_grav)

    # ============================================================
    # 多维度静态评分 (移植自 C++ scoreTarget)
    # ============================================================
    def score_target(self, parent, tgt, str_, range_index, spend_mult,
                     dyn, en_nodes, en_edges, pickups, st=None):
        dyn_atk, dyn_exp, dyn_dfn, dyn_col = dyn
        cfg = self.cfg
        sit = self.sit
        my_root, en_root = self.my_root, self.en_root
        src = (parent.x, parent.y)
        tx, ty = tgt
        cost = range_index + (str_ - MIN_STRENGTH)
        atk = str_                      # Python: 新树枝伤害 = 新节点强度

        s = 0.5
        # ---- 互剪僵局破局: 连续被剪 cut_streak>=2 → 剪击收益降权, 推进收益放大 ----
        # 互剪僵局里 (回放 20260811_185653: 600+ 回合互剪), 双方每回合各剪掉对方一个
        # 重建节点, 剪击收益 1532.97 始终压过推进收益, 谁都不愿推进 → 死循环。
        # cut_streak 记录"上次落点被对方立刻剪掉"的连续次数 (见 _update_memory),
        # 越高说明陷得越深: 剪击越不值钱、推进越值钱, 强制把博弈推向分胜负。
        cut = self.mem.get('cut_streak', 0)
        if cut >= 3:
            cut_atk, adv_boost = 0.25, 3.0
        elif cut >= 2:
            cut_atk, adv_boost = 0.5, 2.0
        else:
            cut_atk, adv_boost = 1.0, 1.0

        # 记忆: 朝上次落点方向轻微推进
        last = self.mem.get('last_target')
        if last:
            s += _dist(tx, ty, last[0], last[1]) * 0.02

        # ---- 重复路线破局: 连续 ≥3 回合操作与上次极度相似 → 避开原路线区域, 强制换路线 ----
        # 修复: AI 双方永远重复同一操作 (如反复剪同一区域的树枝) → 谁也推进不了。
        # 检测到"原地踏步"后, 对靠近上次落点区域的候选重罚, 并偏好更远的新路线。
        if self.mem.get('similar_turns', 0) >= 3 and last:
            d_lt = _dist(tx, ty, last[0], last[1])
            if d_lt < 120:
                s -= (120 - d_lt) * 4.0   # 重复区域附近重罚
            s += d_lt * 0.25               # 离重复区越远越优先 (鼓励换线)

        # 绕后补防: 缺口扇区方向建防线
        if sit.flank_threat and sit.flank_gap_angle >= 0:
            d_root = _dist(tx, ty, my_root.x, my_root.y)
            if 50 < d_root < 240:
                if _sector(tx - my_root.x, ty - my_root.y) == sit.flank_gap_angle:
                    s += 28.0 * dyn_dfn
        # 主动绕后: 朝敌方根缺口推进
        if sit.en_flank_gap_angle >= 0:
            d_en = _dist(tx, ty, en_root.x, en_root.y)
            if 30 < d_en < 280:
                if _sector(tx - en_root.x, ty - en_root.y) == sit.en_flank_gap_angle:
                    s += 22.0 * dyn_atk

        # ---- 几何统计 (收集/节点命中/边命中/压制) — fast 模式由 C 批量预计算 ----
        if st is None:
            st = self._hit_stats(src, (tx, ty), atk, en_nodes, en_edges,
                                 pickups, getattr(sit, 'enemy_spine', None))
        hit_root = st.hit_root
        nodes_hit = st.nodes_hit
        hub_value = st.hub_value
        edges_hit = st.edges_hit
        edges_dead = st.edges_dead
        spine_cut = st.spine_cut
        pinned = st.pinned
        collect_value = st.collect_value
        collect_grav = st.collect_grav

        # ---- 收集加分 (聚合值: 与原逐包累加最多差 1 ulp, 不影响决策) ----
        if collect_value > 0:
            s += collect_value * (cfg.collect_low if spend_mult > 3 else cfg.collect) * dyn_col
            s += collect_value * 5.0     # 黄点未来积分现值
        s += collect_grav * 2.0 * dyn_col
        # 收集经济性: 花范围延长去够黄点必须物有所值
        if range_index > 0 and collect_value > 0 and collect_value < range_index:
            s -= (range_index - collect_value) * 20.0 * spend_mult

        if hit_root:
            return 10000.0

        # 动态拦截奖励: 切断敌方进攻主轴 (链式冲刺的命门)
        if spine_cut > 0:
            s += spine_cut * 400.0 * dyn_dfn

        s += nodes_hit * cfg.node_hit * atk * dyn_atk * cut_atk
        s += hub_value * cfg.hub_factor * atk * dyn_atk * cut_atk
        s += edges_dead * cfg.edge_kill * atk * dyn_atk * cut_atk
        s += (edges_hit - edges_dead) * cfg.edge_hit * dyn_atk * cut_atk

        # 从根节点开新枝且无战果 → 惩罚 (鼓励从已有前线推进)
        if parent.parent is None and len(parent.children) >= 1:
            if nodes_hit == 0 and edges_hit == 0 and collect_value == 0:
                s -= 15.0
        elif parent.parent is not None:
            s += 4.0

        # 花范围延长却无任何战果 → 重罚
        if range_index > 0 and nodes_hit == 0 and edges_hit == 0 and collect_value == 0:
            s -= range_index * 10.0 * spend_mult

        # ---- 连击 ----
        kills = nodes_hit + edges_dead
        if kills >= 2:
            s += cfg.decisive2 * dyn_atk
        elif kills >= 1 and edges_hit >= 1:
            s += cfg.combo * dyn_atk

        if nodes_hit > 0 or edges_hit > 0:
            s += (str_ - MIN_STRENGTH) * cfg.str_bonus * dyn_atk

        if kills >= 1 or hit_root:
            s += cost * spend_mult * 0.4

        # 前线节点出生强度奖励: 深入敌半场的节点出生即应有强度, 避免被一刀切
        # (回放 20 局人类胜局: 人类强化 0.64次/落子, AI 链全是强度1被人类成片切掉)
        d_en_tgt = _dist(tx, ty, en_root.x, en_root.y)
        if str_ >= 2 and d_en_tgt < 350:
            s += (str_ - MIN_STRENGTH) * 120.0 * dyn_dfn

        # ---- 朝敌根推进 (饱和函数: 60px 内线性, 之后收益递减, 90 封顶) ----
        # 回放 20260810_161227 教训: AI 用 range-200/240 长跳推进, 每跳耗 2-4 点,
        # 动作 40 就耗光点数; 人类用 range-120 免费短步密集链, 更便宜更难切断。
        # 饱和推进让"最长免费短步(~100px)"成为最优, 长跳不再因跳得远而占优。
        d_to = _dist(tx, ty, en_root.x, en_root.y)
        d_from = _dist(src[0], src[1], en_root.x, en_root.y)
        adv_gain = max(0.0, d_from - d_to)
        if cfg.advance_cap > 0:
            # 饱和推进: 60px 内线性, 之后收益递减, 到 cap 封顶
            adv_eff = adv_gain if adv_gain < 60.0 else 60.0 + (adv_gain - 60.0) * 0.4
            adv_eff = min(adv_eff, cfg.advance_cap)
            s += adv_eff * cfg.advance * dyn_atk * adv_boost
        else:
            s += adv_gain * cfg.advance * dyn_atk
        if collect_value > 0 and d_to > d_from:
            s += (d_to - d_from) * cfg.advance * 0.6

        # ---- 链式推进奖励 (回放学习: 人类 58% 落子沿"父→敌根"直线延伸) ----
        v1x = en_root.x - src[0]
        v1y = en_root.y - src[1]
        v2x = tx - src[0]
        v2y = ty - src[1]
        l1 = math.hypot(v1x, v1y)
        l2 = math.hypot(v2x, v2y)
        if l1 > 1.0 and l2 > 1.0:
            cosang = (v1x * v2x + v1y * v2y) / (l1 * l2)
            s += cosang * cfg.chain_bonus * dyn_atk
            # 链步密度奖励: 60-135px 的对齐短步额外加分 (人类密集短步链的核心)
            if 60.0 <= l2 <= 135.0 and cosang > 0.7:
                s += 40.0 * dyn_atk

        # ---- 中心控制 ----
        d_c = _dist(tx, ty, CENTER_X, CENTER_Y)
        if d_c < 300:
            s += (300 - d_c) * cfg.center

        # ---- 压制敌方可扩展节点 (几何统计已含 pinned) ----
        s += pinned * 8.0 * dyn_atk

        # ---- 开拓版图 ----
        min_own = 1e9
        for n in self.game.nodes:
            if n.team != self.team or n is parent:
                continue
            d = _dist(tx, ty, n.x, n.y)
            if d < min_own:
                min_own = d
        if min_own > 70:
            s += (min_own - 70) * cfg.expand * dyn_exp

        # ---- 从逼近敌根的节点延伸 ----
        if _dist(src[0], src[1], en_root.x, en_root.y) < 250:
            s += (250 - _dist(src[0], src[1], en_root.x, en_root.y)) * 0.08 * dyn_atk

        # ---- 防守纵深 ----
        d_my = _dist(tx, ty, my_root.x, my_root.y)
        if d_my > 120:
            s += d_my * cfg.defense * dyn_dfn
        if sit.flank_threat and d_my < 150:
            s += 15.0 * dyn_dfn
        # 深入敌腹地且防线暴露 → 重罚
        if d_to < 200 and (sit.my_weak_edges >= 2 or sit.my_front_exposed >= 3):
            s -= (200 - d_to) * 0.12 * dyn_dfn

        # ---- 母节点风险 ----
        parent_risk = 0.0
        if parent.parent is not None:
            if parent.strength <= 1:
                parent_risk += 24.0
            elif parent.strength == 2:
                parent_risk += 8.0
            d_pe = _dist(parent.x, parent.y, en_root.x, en_root.y)
            if d_pe < 260:
                parent_risk += (260 - d_pe) * 0.08
            pval = self.subtree_size(parent)
            if pval >= 3:
                parent_risk += (pval - 2) * 4.0
        s -= parent_risk * dyn_dfn

        # ---- 记忆: 已确认被摧毁的落点不重建 (打地鼠惩罚, 权重需足够大) ----
        for kx, ky in self.mem.get('killed_targets', []):
            d = _dist(tx, ty, kx, ky)
            if d < 80:
                s -= (80 - d) * 10.0

        # ---- 僵持放大 ----
        if self.mem.get('stall_turns', 0) >= 3:
            s *= 1.25
            if nodes_hit > 0:
                s *= 1.4

        # ---- 成本 ----
        s -= cost * spend_mult
        s += (str_ - MIN_STRENGTH) * 2.5
        s += self._rng.uniform(-2.0, 2.0)
        return s

    # ============================================================
    # 威胁惩罚
    # ============================================================
    def threat_penalty(self, parent, tgt, en_expandable, en_nodes):
        cfg = self.cfg
        risk = cfg.risk_taker
        my_root, en_root = self.my_root, self.en_root
        tx, ty = tgt
        pen = 0.0

        # 贴近敌根且非杀根的落点 → 建了也会被拆
        d_en = _dist(tx, ty, en_root.x, en_root.y)
        if d_en < 90:
            pen += (90 - d_en) * 2.2
        if d_en < 45:
            pen += (45 - d_en) * 3.0

        # 敌方可扩展节点能延伸打击此落点
        if FAST_GEO:
            # fast 模式: 己方节点为点集, 敌延伸线段 (e→tgt) 为线段集, 一次 C 距离矩阵
            my_pts = [(o.x, o.y) for o in self.game.nodes
                      if o.team == self.team and o is not parent]
            valid_e = []
            for e in en_expandable:
                d = _dist(e.x, e.y, tx, ty)
                if d < 20 or d > MAX_RANGE:
                    continue
                ri = _range_index(d)
                if ri is None or ri > 2:
                    continue
                valid_e.append((e, (e.x, e.y, tx, ty)))
            if not my_pts:
                # 无己方节点可阻挡 → 全部视为未拦截 (与原 Python 循环等价)
                for e, _ in valid_e:
                    pen += 14.0 * cfg.threat_mul
            elif valid_e:
                n_seg = len(valid_e)
                ds = pt_seg_dist_grid(my_pts, [s[1] for s in valid_e])
                n_pts = len(my_pts)
                for idx, (e, _) in enumerate(valid_e):
                    if min(ds[i * n_seg + idx] for i in range(n_pts)) >= _OCCUPY_BLOCK:
                        pen += 14.0 * cfg.threat_mul
        else:
            for e in en_expandable:
                d = _dist(e.x, e.y, tx, ty)
                if d < 20 or d > MAX_RANGE:
                    continue
                ri = _range_index(d)
                if ri is None or ri > 2:
                    continue
                blocked = False
                for o in self.game.nodes:
                    if o.team == self.team and o is not parent:
                        if _pt_seg_dist(o.x, o.y, e.x, e.y, tx, ty) < _OCCUPY_BLOCK:
                            blocked = True
                            break
                if not blocked:
                    pen += 14.0 * cfg.threat_mul

        # 敌方节点本身的距离惩罚
        for e in en_nodes:
            d = _dist(e.x, e.y, tx, ty)
            if d < 35:
                pen += (35 - d) * 0.5 * cfg.threat_mul
            if d < 55 and len(e.children) < MAX_CHILDREN:
                pen += (55 - d) * 0.2 * cfg.threat_mul

        # 敌方从母节点方向延伸会切断我这条新枝
        for e in en_expandable:
            d = _dist(e.x, e.y, parent.x, parent.y)
            if d < 20 or d > MAX_RANGE:
                continue
            mid = ((parent.x + tx) * 0.5, (parent.y + ty) * 0.5)
            dx, dy = mid[0] - e.x, mid[1] - e.y
            L = math.hypot(dx, dy)
            if L < 1:
                continue
            ux, uy = dx / L, dy / L
            for dist in (60, 90, 120, 150, 180, 210, 240):
                ex = e.x + ux * dist
                ey = e.y + uy * dist
                if _seg_cross((e.x, e.y), (ex, ey), (parent.x, parent.y), (tx, ty)):
                    pen += 10.0 * cfg.threat_mul
                    break

        # 离我根过远
        d_root = _dist(tx, ty, my_root.x, my_root.y)
        if d_root > 450:
            pen += (d_root - 450) * 0.1
        # 僵持无进展 → 降低威胁惩罚, 鼓励冒险破局
        if self.mem.get('no_progress', 0) >= 3:
            pen *= 0.5
        return pen

    # ============================================================
    # 薄弱边强化
    # ============================================================
    def choose_reinforce(self, nodes, my_score, en_score):
        """返回值得加固的己方边 (子节点), 否则 None。"""
        if self.my_root is None or self.en_root is None:
            self._find_roots()
        if self.sit is None:
            self.sit = self.analyze_situation()
        cands = []
        en_root = self.en_root
        for n in nodes:
            if n.team != self.team:
                continue
            for c in n.children:
                if c.strength >= 4:
                    continue
                # 前沿链判定: 该边朝敌根推进, 或整条链已深入敌半场
                advancing = False
                near_enemy = False
                d_par = 1e9
                d_ch = 1e9
                if en_root is not None:
                    d_par = _dist(n.x, n.y, en_root.x, en_root.y)
                    d_ch = _dist(c.x, c.y, en_root.x, en_root.y)
                    advancing = d_ch < d_par - 15
                    near_enemy = d_ch < 450.0
                # 近敌节点的威胁
                min_d = 1e9
                for en in nodes:
                    if en.team == self.team:
                        continue
                    d = _pt_seg_dist(en.x, en.y, n.x, n.y, c.x, c.y)
                    if d < min_d:
                        min_d = d
                if not advancing and not near_enemy and min_d > 400:
                    continue
                val = self.subtree_size(c)
                up_factor = 1.0
                if c.parent is not None and c.parent.parent is not None and \
                        c.parent.strength <= c.strength:
                    up_factor = 0.4
                # 威胁 = 近敌程度 + 推进链偏好 (人类 0.64/落子强化, 重点照顾推进链)
                threat = 0.0
                if min_d < 300:
                    rng = 300.0 - min_d
                    threat += rng * (5 - c.strength) * (0.2 + val * 0.6) * up_factor
                if advancing:
                    threat += 60.0 + (5 - c.strength) * 20.0
                elif near_enemy:
                    threat += 20.0 + (5 - c.strength) * 10.0
                if threat > 0:
                    cands.append((threat, c))
        if not cands:
            return None
        cands.sort(key=lambda t: -t[0])

        # 强化预算: 链强化是生存关键, 允许花到只剩 1 点 (但杀根窗口需预留)
        reserve = self.compute_reserve(my_score, len(nodes))
        budget = max(0, my_score - reserve)
        threat, c = cands[0]
        if threat > 40:
            budget = max(budget, max(0, my_score - 1))   # 高威胁 → 花到只剩1点
        budget = min(budget, max(0, my_score))
        if budget <= 0:
            return None
        if c.strength >= MAX_STRENGTH:
            return None
        return c

    # ============================================================
    # 轻量前向模拟 (移植自 C++ simulateLookahead)
    # ============================================================
    def _sim_best_move(self, sim, team):
        """在模拟局面中贪心求某方最佳移动 (用简化静态分)。

        fast 模式: 候选一次性收集后交给 C 批量分析命中统计 (btb_analyze_moves),
        评分只做浮点加权, 几何循环全部在 C 侧完成。
        """
        best = None
        best_s = -1e18
        my_r = sim.my_root if team == self.team else sim.en_root
        en_r = sim.en_root if team == self.team else sim.my_root
        if my_r is None or en_r is None:
            return None
        expand = [sn for sn in sim.all if sn.team == team and len(sn.children) < MAX_CHILDREN]
        expand.sort(key=lambda sn: _dist(sn.x, sn.y, en_r.x, en_r.y))
        raw = []
        for sn in expand[:6]:
            dx = en_r.x - sn.x
            dy = en_r.y - sn.y
            L = math.hypot(dx, dy)
            targets = []
            if L > 1:
                ux, uy = dx / L, dy / L
                for dist in (45, 75, 105, 140, 175, 210):
                    targets.append((sn.x + ux * dist, sn.y + uy * dist))
                for ang in (-0.5, 0.5):
                    cs, sn2 = math.cos(ang), math.sin(ang)
                    rx = ux * cs - uy * sn2
                    ry = ux * sn2 + uy * cs
                    for dist in (60, 100, 150):
                        targets.append((sn.x + rx * dist, sn.y + ry * dist))
            # 敌方节点/敌根周边
            for on in sim.all:
                if on.team != team:
                    d = _dist(on.x, on.y, sn.x, sn.y)
                    if 25 < d < MAX_RANGE:
                        targets.append((on.x, on.y))
                        break
            for t in targets:
                if not self._in_bounds(t[0], t[1]):
                    continue
                d = _dist(sn.x, sn.y, t[0], t[1])
                ri = _range_index(d)
                if ri is None:
                    continue
                for str_ in (MIN_STRENGTH, 2, 3):
                    cost = ri + (str_ - MIN_STRENGTH)
                    if cost > 8:       # 模拟中给一个宽松预算
                        continue
                    raw.append((sn, t, str_, ri))
        if not raw:
            return None
        if FAST_GEO:
            geo = GeoPack(sim.all, team, self.game.pickups, NODE_RADIUS,
                          PICKUP_COLLECT_DIST,
                          subtree_fn=lambda sn: sn.subtree(),
                          spine_ids=None,
                          max_children=MAX_CHILDREN)
            sts = geo.analyze_moves([(sn.x, sn.y, t[0], t[1], str_)
                                     for (sn, t, str_, ri) in raw])
            # 推进距离 d_to/d_from 也批量 (en_r 固定, 两次 C 调用)
            tgt_pts = [(t[0], t[1]) for (_, t, _, _) in raw]
            src_pts = [(sn.x, sn.y) for (sn, _, _, _) in raw]
            d_tos = dists_to(en_r.x, en_r.y, tgt_pts)
            d_froms = dists_to(en_r.x, en_r.y, src_pts)
            scores = []
            for i, (sn, t, str_, ri) in enumerate(raw):
                sc = self._sim_quick_score(sn, t, str_, ri, sim, team,
                                           st=sts[i],
                                           dists=(d_froms[i], d_tos[i]))
                scores.append((sc, sn, t, str_, ri))
            scores.sort(key=lambda x: -x[0])
            # 1ulp 安全: 批量分与 Python 参考分最多差 1 ulp (hypot 实现差异)。
            # 前几名分差过近时 (<1e-6) 用 Python 精确重算, 消除排序翻转;
            # 正常情况下 top1 分差远大于 1e-6, 零重算开销。
            need = 1
            while need < min(len(scores), 16) and \
                    scores[need][0] >= scores[0][0] - 1e-6:
                need += 1
            for j in range(need):
                _, sn, t, str_, ri = scores[j]
                scores[j] = (self._sim_quick_score(sn, t, str_, ri, sim, team),
                             sn, t, str_, ri)
            scores.sort(key=lambda x: -x[0])
            best = scores[0][1:]
            best_s = scores[0][0]
        else:
            for (sn, t, str_, ri) in raw:
                sc = self._sim_quick_score(sn, t, str_, ri, sim, team)
                if sc > best_s:
                    best_s = sc
                    best = (sn, t, str_, ri)
        return best

    def _sim_quick_score(self, parent, tgt, str_, ri, sim, team, st=None,
                         dists=None):
        s = 0.5
        src = (parent.x, parent.y)
        tx, ty = tgt
        enemy = self.enemy_team if team == self.team else self.team
        en_root = sim.en_root if team == self.team else sim.my_root
        # 命中统计 (fast 模式由 _sim_best_move 批量预计算后传入 st)
        if st is None:
            en_nodes = [sn for sn in sim.all if sn.team == enemy]
            en_edges = [(sn.parent.x, sn.parent.y, sn.x, sn.y, sn.strength, sn)
                        for sn in sim.all if sn.team == enemy and sn.parent is not None]
            st = self._hit_stats(src, tgt, str_, en_nodes, en_edges,
                                 self.game.pickups, None)
        if st.hit_root:
            return 10000.0
        nodes_hit = st.nodes_hit
        hub = st.hub_value
        edges_hit = st.edges_hit
        edges_dead = st.edges_dead
        atk = str_
        s += nodes_hit * self.cfg.node_hit * atk + hub * self.cfg.hub_factor * atk
        s += edges_dead * self.cfg.edge_kill * atk + (edges_hit - edges_dead) * self.cfg.edge_hit
        # 推进 (fast 模式由 _sim_best_move 用 C 批量算好传入)
        if dists is not None:
            d_from, d_to = dists
        else:
            d_to = _dist(tx, ty, en_root.x, en_root.y)
            d_from = _dist(src[0], src[1], en_root.x, en_root.y)
        s += (d_from - d_to) * self.cfg.advance
        # 收集 (近似: 落点碰包; 聚合值与原逐包累加最多差 1 ulp)
        if st.collect_value > 0:
            s += st.collect_value * self.cfg.collect + st.collect_value * 5.0
        s -= (ri + (str_ - MIN_STRENGTH)) * 2.0
        return s

    def _sim_eval(self, sim):
        my_n = en_n = 0
        my_e = en_e = 0.0
        min_d = 1e9
        for sn in sim.all:
            if sn.team == self.team:
                my_n += 1
                for c in sn.children:
                    my_e += c.strength
                if sim.en_root:
                    d = _dist(sn.x, sn.y, sim.en_root.x, sim.en_root.y)
                    if d < min_d:
                        min_d = d
            else:
                en_n += 1
                for c in sn.children:
                    en_e += c.strength
        e = (my_n - en_n) * 18.0 + (my_e - en_e) * 1.2
        if min_d < 1e8:
            e -= min_d * 0.08
        return e

    def simulate_lookahead(self, parent, tgt, str_, ri, nodes, pickups):
        """对 top 候选做贪心 2 轮推演, 返回局面增益 delta。"""
        try:
            sim = _SimState(nodes, self.team, self.enemy_team)
            cl = sim.map.get(parent)
            if cl is None or sim.my_root is None or sim.en_root is None:
                return 0.0
            if not sim.apply(cl, tgt, str_, self.team):
                return 0.0
            if sim.en_root is None:
                return 1e9
            if sim.my_root is None:
                return -1e9
            base = self._sim_eval(sim)
            # 2 轮: 敌回应 → 我回应
            for _ in range(2):
                if sim.my_root is None or sim.en_root is None:
                    break
                em = self._sim_best_move(sim, self.enemy_team)
                if em:
                    e_parent, e_tgt, e_str, e_ri = em
                    if not sim.apply(e_parent, e_tgt, e_str, self.enemy_team):
                        pass
                if sim.my_root is None or sim.en_root is None:
                    break
                mm = self._sim_best_move(sim, self.team)
                if mm:
                    m_parent, m_tgt, m_str, m_ri = mm
                    if not sim.apply(m_parent, m_tgt, m_str, self.team):
                        pass
            if sim.en_root is None:
                return 1e9
            if sim.my_root is None:
                return -1e9
            return self._sim_eval(sim) - base
        except Exception:
            return 0.0

    # ============================================================
    # 最优落子
    # ============================================================
    def _gen_cands(self, nodes, my_score, en_score, pickups, cap=1600):
        """生成全部候选并做静态评分 + 威胁惩罚，返回排序后的列表。

        返回 [(sc, n, t, str_, ri), ...] 按 sc 降序；无候选返回 None。
        """
        team = self.team
        en_root = self.en_root
        sit = self.sit

        en_nodes = [n for n in nodes if n.team != team]
        en_edges = []
        for n in nodes:
            if n.team != team and n.parent is not None:
                # 末尾附上子节点对象, 供主轴拦截判断 (child.id in sit.enemy_spine)
                en_edges.append((n.parent.x, n.parent.y, n.x, n.y, n.strength, n))
        en_expandable = [n for n in en_nodes if len(n.children) < MAX_CHILDREN]

        expandables = [n for n in nodes if n.team == team and len(n.children) < MAX_CHILDREN]
        if not expandables:
            return None
        expandables.sort(key=lambda n: _dist(n.x, n.y, en_root.x, en_root.y))
        if len(expandables) > 8:
            expandables = expandables[:8]

        spend_mult = self._spend_multiplier(my_score, len(nodes))
        reserve = self.compute_reserve(my_score, len(nodes))
        spendable = max(0, my_score - reserve)
        dyn = self._dynamic_multipliers()

        all_cands = []
        raw = []    # (n, t, str_, ri) — 候选先收集, 评分统一走 fast/纯 Python 路径
        for n in expandables:
            targets = self.gen_targets(n, nodes, en_root, pickups)
            for t in targets:
                if not self._valid_target(n, t, nodes):
                    continue
                # 重复路线破局: 反复在同一处落子被互剪 → 硬性排除该落点。
                # (仅软惩罚压不过互剪奖励 node_hit, 曾导致 AI 双方无限互剪同一落点。
                #  过滤后 AI 被迫换路线, 路线变化时 similar_turns 自然重置。)
                if self._in_repeat_zone(t[0], t[1], n.id):
                    continue
                d = _dist(n.x, n.y, t[0], t[1])
                ri = _range_index(d)
                if ri is None:
                    continue
                max_str = min(MAX_STRENGTH, spendable - ri + MIN_STRENGTH)
                for str_ in range(MIN_STRENGTH, max_str + 1):
                    cost = ri + (str_ - MIN_STRENGTH)
                    if cost > spendable:
                        break
                    if self.cfg.max_move_cost > 0 and cost > self.cfg.max_move_cost:
                        break   # 单次落子花费上限 (防点数枯竭)
                    raw.append((n, t, str_, ri))
                    if len(raw) >= cap:
                        break
                if len(raw) >= cap:
                    break
            if len(raw) >= cap:
                break

        if not raw:
            return None

        if FAST_GEO:
            # fast 模式: 一次 C 调用算完全部候选的几何命中统计
            geo = GeoPack(nodes, self.team, pickups, NODE_RADIUS,
                          PICKUP_COLLECT_DIST,
                          subtree_fn=self.subtree_size,
                          spine_ids=getattr(self.sit, 'enemy_spine', None) or None,
                          max_children=MAX_CHILDREN)
            sts = geo.analyze_moves([(n.x, n.y, t[0], t[1], str_)
                                     for (n, t, str_, ri) in raw])
            for i, (n, t, str_, ri) in enumerate(raw):
                sc = self.score_target(n, t, str_, ri, spend_mult, dyn,
                                       en_nodes, en_edges, pickups, st=sts[i])
                all_cands.append((sc, n, t, str_, ri))
        else:
            for (n, t, str_, ri) in raw:
                sc = self.score_target(n, t, str_, ri, spend_mult, dyn,
                                       en_nodes, en_edges, pickups)
                all_cands.append((sc, n, t, str_, ri))

        # 威胁惩罚 (只对 top 候选做, 节省性能)
        all_cands.sort(key=lambda c: -c[0])
        top_n = min(len(all_cands), 25)
        for i in range(top_n):
            sc, n, t, str_, ri = all_cands[i]
            pen = self.threat_penalty(n, t, en_expandable, en_nodes)
            all_cands[i] = (sc - pen, n, t, str_, ri)
        all_cands.sort(key=lambda c: -c[0])
        return all_cands

    def begin_planning(self, nodes, my_score, en_score, pickups):
        """开始 AI 决策（迭代规划版）。

        返回 (immediate_action, need_more_time, viz_cands)
        - immediate_action: 若非 None，表示这是快速动作（杀根/捡包/强化/结束），直接执行
        - need_more_time: 常规落子时，是否建议延长思考到 5 秒上限
        - viz_cands: 常规落子的初始 top16 候选可视化数据 [(parent, x, y, strength, ri, score)]
        """
        game = self.game
        # 前置准备（与 decide_action 一致）
        self._find_roots()
        if self.my_root is None or self.en_root is None:
            return None, False, []
        self._update_memory(game.nodes)
        self.observe_opponent(game.nodes)
        key = (game.turn_count, game.current_team)
        if self.mem.get('turn_key') != key:
            # last_target 必须跨回合保留：重复路线检测 (similar_turns) 依赖上一回合落点
            for k in ('reinforce_done', 'stall_turns'):
                self.mem.pop(k, None)
            self.mem['turn_key'] = key
        self.sit = self.analyze_situation()
        last_en = self.mem.get('last_placed_en')
        if last_en is not None:
            if self.sit.en_nodes >= last_en:
                self.mem['no_progress'] = self.mem.get('no_progress', 0) + 1
            else:
                self.mem['no_progress'] = 0

        # 快速分支（无需长思考）
        if not game.has_created_this_turn:
            kill = self.find_kill_move(nodes, my_score)
            if kill:
                return kill, False, []
            if my_score < 8:
                collect_move = self._emergency_collect(nodes, my_score)
                if collect_move:
                    return collect_move, False, []
            if self.mem.get('reinforce_done', 0) < 4:
                edge = self.choose_reinforce(nodes, my_score, en_score)
                if edge is not None:
                    self.mem['reinforce_done'] = self.mem.get('reinforce_done', 0) + 1
                    return {'type': 'modify_branch', 'node': edge,
                            'new_strength': min(edge.strength + 1, MAX_STRENGTH)}, False, []

        # 常规落子 → 进入迭代规划
        self._plan_all = self._gen_cands(nodes, my_score, en_score, pickups)
        self._plan_nodes = nodes
        self._plan_pickups = pickups
        self._plan_done = 0            # 已完成前向模拟的候选数（从 top 开始）
        self._plan_round = 0
        self._plan_fallback = None
        if not self._plan_all:
            # 常规落子无解 → 绝望模式兜底
            move = self._desperate_placement(nodes, my_score)
            self._plan_fallback = move
            return None, False, []
        # top 至少精化 16 个候选（模拟后几步对局）
        self._plan_max_sim = min(len(self._plan_all), 16)
        need_more = (len(self._plan_all) > 300) or (len(nodes) > 50)
        return None, need_more, self._plan_viz()

    def _plan_viz(self, k=16):
        """把候选池转成可视化数据（取前 k 个）。"""
        out = []
        for sc, n, t, str_, ri in self._plan_all[:k]:
            out.append((n, t[0], t[1], str_, ri, sc))
        return out

    def plan_step(self, sim_per_step=2):
        """推进一轮迭代规划：对 top 尚未精化的候选做前向模拟并重排。

        所有 top 候选都精化过一轮后自动循环第二轮（继续加深）。
        返回 (finished, viz_cands)。
        """
        if not self._plan_all:
            return True, self._plan_viz()
        cands = self._plan_all
        todo = min(len(cands), self._plan_max_sim)
        count = 0
        while count < sim_per_step:
            i = self._plan_done % todo
            sc, n, t, str_, ri = cands[i]
            delta = self.simulate_lookahead(n, t, str_, ri,
                                            self._plan_nodes, self._plan_pickups)
            if delta > 0:
                cands[i] = (sc * 0.4 + delta * 0.6, n, t, str_, ri)
            self._plan_done += 1
            count += 1
        cands.sort(key=lambda c: -c[0])
        self._plan_round += 1
        # 时间由 main 控制：循环精化直到思考时长耗尽
        return False, self._plan_viz()

    def _update_similar_turns(self, tx, ty, parent_id):
        """记录本次落点并维护重复路线检测状态。

        - recent_targets: 最近 15 次落点窗口 (x, y, parent_id)，用于检测互剪循环。
        - similar_turns / last_target / last_parent_id: 兼容保留（score_target 软惩罚用）。

        similar_turns 不看父节点：互剪循环里 AI 每次被剪后从不同父节点重建同一位置
        （回放 20260811_185653），只按落点位置相近即可累计，否则永远检测不到。

        所有产生 place_node 的决策出口统一调用（planner / 绝望兜底 / 紧急拾取），
        避免死循环检测只在 planner 路径生效、其他路径无限重复同一落点。
        """
        mem = self.mem
        recent = mem.setdefault('recent_targets', [])
        recent.append((tx, ty, parent_id))
        if len(recent) > 15:
            recent.pop(0)
        prev_t = mem.get('last_target')
        if prev_t is not None and _dist(tx, ty, prev_t[0], prev_t[1]) < 60.0:
            mem['similar_turns'] = mem.get('similar_turns', 0) + 1
        else:
            mem['similar_turns'] = 1  # 路线变化则重置
        mem['last_target'] = (tx, ty)
        mem['last_parent_id'] = parent_id
        return mem['similar_turns']

    def _in_repeat_zone(self, tx, ty, parent=None):
        """目标是否落在重复落点区域内。

        检测互剪循环: 最近 15 次落点中, 落在目标附近(<40px) ≥2 次 → 判定循环。
        只按位置判定, 不看父节点: 互剪时 AI 被剪后从不同父节点重建同一位置
        （回放 20260811_185653: 红队 188→18→202→216 反复重建同一落点, 父节点一直在换），
        加同父过滤会漏掉这类循环。40px 严格阈值 < 节点最小间距(40), 不会误伤链式推进。
        """
        recent = self.mem.get('recent_targets', [])
        if len(recent) < 2:
            return False
        count = 0
        for x, y, pid in recent:
            if (tx - x) ** 2 + (ty - y) ** 2 < 40 * 40:
                count += 1
        return count >= 2

    def finish_plan(self):
        """返回最终最优动作（精化后的 top1）。"""
        if not self._plan_all:
            return self._plan_fallback
        best = self._plan_all[0]
        self.last_cands = self._plan_viz()
        self._update_similar_turns(best[2][0], best[2][1], best[1].id)
        self._remember_placement(best[2][0], best[2][1])
        self.mem['last_placed_en'] = self.sit.en_nodes
        self.mem['stall_turns'] = 0
        return {'type': 'place_node', 'parent': best[1],
                'x': best[2][0], 'y': best[2][1],
                'strength': best[3], 'range_index': best[4]}

    def best_placement(self, nodes, my_score, en_score, pickups):
        all_cands = self._gen_cands(nodes, my_score, en_score, pickups)
        if not all_cands:
            return None

        # 轻量前向模拟 (只对 top 3)
        if len(nodes) <= 60:
            top_k = min(len(all_cands), 3)
            for i in range(top_k):
                sc, n, t, str_, ri = all_cands[i]
                delta = self.simulate_lookahead(n, t, str_, ri, nodes, pickups)
                if delta > 0:
                    all_cands[i] = (sc * 0.4 + delta * 0.6, n, t, str_, ri)
            all_cands.sort(key=lambda c: -c[0])

        best = all_cands[0]
        # 换路线检测（与 finish_plan/desperate/emergency 共用统一逻辑）
        self._update_similar_turns(best[2][0], best[2][1], best[1].id)
        # 收集 top 候选用于可视化 (含威胁惩罚/模拟后的最终分数)
        self.last_cands = []
        for sc, n, t, str_, ri in all_cands[:12]:
            self.last_cands.append((n, t[0], t[1], str_, ri, sc))
        self._remember_placement(best[2][0], best[2][1])
        self.mem['last_placed_en'] = self.sit.en_nodes
        self.mem['stall_turns'] = 0
        return {'type': 'place_node', 'parent': best[1],
                'x': best[2][0], 'y': best[2][1],
                'strength': best[3], 'range_index': best[4]}

    def _desperate_placement(self, nodes, my_score):
        """绝望模式: 常规落子无解时 (点数耗尽/目标全被占), 放宽间距强制放置,
        并优先贴近点数包以便收集回血, 避免无限僵持。"""
        team = self.team
        en_root = self.en_root
        pickups = self.game.pickups
        expandables = [n for n in nodes if n.team == team and len(n.children) < MAX_CHILDREN]
        if not expandables:
            return None
        best = None
        best_score = -1e18
        # 第一遍: 绕开重复落点; 若绕开后完全无解, 第二遍允许回落到原落点,
        # 避免"所有候选都在重复区 → 无限让过回合"的停滞 (互剪至少还能推进对局)。
        for attempt in (0, 1):
            for n in expandables:
                targets = self.gen_targets(n, nodes, en_root, pickups, light=True)
                for t in targets:
                    tx, ty = t
                    if not self._in_bounds(tx, ty):
                        continue
                    d = _dist(n.x, n.y, tx, ty)
                    if d < 20 or d > MAX_RANGE:
                        continue
                    ri = _range_index(d)
                    if ri is None:
                        continue
                    if ri > my_score:          # 绝望时也尽量不超预算
                        continue
                    # 宽松间距: 允许最小 20px (节点半径 18, 几乎相切)
                    ok = True
                    for o in nodes:
                        if o is n:
                            continue
                        if (o.x - tx) ** 2 + (o.y - ty) ** 2 < 20 * 20:
                            ok = False
                            break
                    if not ok:
                        continue
                    # 重复路线破局: 第一遍绕开反复落子被互剪的落点, 强制换线
                    if attempt == 0 and self._in_repeat_zone(tx, ty, n.id):
                        continue
                    # 优先能捡到点数包的落点
                    score = -d * 0.05
                    for sp in pickups:
                        pd = _dist(tx, ty, sp.x, sp.y)
                        if pd < PICKUP_COLLECT_DIST:
                            score += 200.0 + sp.value * 60.0
                        elif pd < 130:
                            score += sp.value * 2.0 * (1.0 - pd / 130.0)
                    if score > best_score:
                        best_score = score
                        best = {'type': 'place_node', 'parent': n, 'x': tx, 'y': ty,
                                'strength': MIN_STRENGTH, 'range_index': ri}
            if best is not None or attempt == 1:
                break
        if best is not None:
            self.last_cands = [(best['parent'], best['x'], best['y'],
                                best['strength'], best['range_index'], best_score)]
            self._update_similar_turns(best['x'], best['y'], best['parent'].id)
            self._remember_placement(best['x'], best['y'])
            self.mem['last_placed_en'] = self.sit.en_nodes
        return best

    def _emergency_collect(self, nodes, my_score):
        """低点数应急: 找一处免费落子 (强度1, 范围120) 直接碰到点数包, 恢复资源。
        防止"点数耗尽 → 杀根窗口付不起费"的死亡螺旋 (回放 20260810_154845 的失败根因)。
        阈值提高到 8: 人类靠捡包资助强化, AI 也需要积极捡包维持 0.64/落子的强化强度。
        """
        if my_score >= 8:
            return None
        team = self.team
        en_root = self.en_root
        if en_root is None:
            return None
        pickups = self.game.pickups
        expandables = [n for n in nodes if n.team == team and len(n.children) < MAX_CHILDREN]
        best = None
        best_score = -1e18
        for n in expandables:
            for sp in pickups:
                # 免费范围120内能否落到包上
                tx, ty = sp.x, sp.y
                d = _dist(n.x, n.y, tx, ty)
                if d < MIN_SPACING or d > RANGE_OPTIONS[0]:
                    continue
                if not self._in_bounds(tx, ty):
                    continue
                if self._occupied(tx, ty, nodes, n):
                    continue
                # 重复路线破局: 反复捡同一落点 → 换别的包/交给常规路径
                if self._in_repeat_zone(tx, ty, n.id):
                    continue
                # 朝敌根方向加分 (避免为捡包大幅绕路)
                v1x = en_root.x - n.x
                v1y = en_root.y - n.y
                l1 = math.hypot(v1x, v1y)
                score = sp.value * 100.0
                if l1 > 1:
                    score += (v1x * (tx - n.x) + v1y * (ty - n.y)) / l1 * 0.3
                if score > best_score:
                    best_score = score
                    best = {'type': 'place_node', 'parent': n, 'x': tx, 'y': ty,
                            'strength': MIN_STRENGTH, 'range_index': 0}
        if best is not None:
            self.last_cands = [(best['parent'], best['x'], best['y'],
                                best['strength'], best['range_index'], best_score)]
            self._update_similar_turns(best['x'], best['y'], best['parent'].id)
        return best

    # ============================================================
    # 决策入口 (与 main.py 的 _ai_update 对接)
    # ============================================================
    def decide_action(self):
        game = self.game
        if getattr(game, 'state', None) != 'playing':
            return None
        if game.current_team != self.team:
            return None
        # 本回合已放置过节点 → 只能结束回合 (与 main._ai_update 的守卫一致)
        if game.has_created_this_turn:
            return {'type': 'end_turn'}

        self._find_roots()
        if self.my_root is None or self.en_root is None:
            return None

        # 检查上次落点是否被摧毁 (打地鼠记忆) — 必须在回合重置前, 否则 last_placed 会被清掉
        self._update_memory(game.nodes)
        # 统计对手打法偏好 (供对局结束自动学习)
        self.observe_opponent(game.nodes)

        # 回合级记忆重置 (last_placed 已由 _update_memory 消费; 不重置 last_placed_en/no_progress)
        # last_target 跨回合保留：重复路线检测 (similar_turns) 依赖上一回合落点
        key = (game.turn_count, game.current_team)
        if self.mem.get('turn_key') != key:
            for k in ('reinforce_done', 'stall_turns'):
                self.mem.pop(k, None)
            self.mem['turn_key'] = key

        # 分析局面 (每回合重新计算)
        self.sit = self.analyze_situation()
        nodes = game.nodes
        my_score = game.points[self.team]
        en_score = game.points[self.enemy_team]
        pickups = game.pickups

        # 进度追踪: 上次落子后敌方节点数未减少 → 无进展计数+1
        last_en = self.mem.get('last_placed_en')
        if last_en is not None:
            if self.sit.en_nodes >= last_en:
                self.mem['no_progress'] = self.mem.get('no_progress', 0) + 1
            else:
                self.mem['no_progress'] = 0

        if not game.has_created_this_turn:
            # 1) 强制杀根 (一击制胜, 可花光所有点数)
            kill = self.find_kill_move(nodes, my_score)
            if kill:
                return kill
            # 1.5) 低点数应急拾取: 防止"点数耗尽→杀根窗口付不起费"的死亡螺旋
            if my_score < 8:
                collect_move = self._emergency_collect(nodes, my_score)
                if collect_move:
                    return collect_move
            # 2) 薄弱边强化 (每回合最多 4 次, 模仿人类 0.64 次/落子的强化强度)
            if self.mem.get('reinforce_done', 0) < 4:
                edge = self.choose_reinforce(nodes, my_score, en_score)
                if edge is not None:
                    self.mem['reinforce_done'] = self.mem.get('reinforce_done', 0) + 1
                    return {'type': 'modify_branch', 'node': edge,
                            'new_strength': min(edge.strength + 1, MAX_STRENGTH)}

        # 3) 常规落子
        move = self.best_placement(nodes, my_score, en_score, pickups)
        if move is None:
            # 绝望模式: 放宽间距强制放置 (避免无限僵持)
            move = self._desperate_placement(nodes, my_score)
        if move is None:
            self.mem['stall_turns'] = self.mem.get('stall_turns', 0) + 1
            return {'type': 'end_turn'}
        self.mem['stall_turns'] = 0
        return move
