import pygame
import pygame.gfxdraw
import math
import sys
import os
import shutil
import random

from constant import *

# 回放系统
from replay import ReplayRecorder

pygame.init()

_sfx_bank = {}         # {filename: Sound}
# 通用调试日志池: [(text, color, tick, duration_ms), ...]
_debug_entries = []
DEFAULT_DEBUG_DURATION = 2000  # 默认显示时长(ms)
DEBUG_MODE = os.path.isfile(os.path.join(os.path.dirname(__file__), 'debug'))
DEBUGS = []
with open('debug', 'r', encoding='utf-8') as f:
    debug_mode = f.read().splitlines()
    for line in debug_mode:
        line = line.strip()
        if line and not line.startswith('#'):
            DEBUGS.append(line)
print("[DEBUG] 已激活的调试选项: " + ", ".join(DEBUGS))


def _load_all_sfx():
    for f in TAP_SOUNDS.values():
        _load_one(f)
    for f in SHEAR_SOUNDS:
        _load_one(f)
    for files in ORB_SOUNDS.values():
        for f in files:
            _load_one(f)
    _load_one(CLICK_SOUND)
    for name in ['join_leave', 'victory', 'heavy_hit']:
        _load_one(f'{name}.ogg')


def _load_one(filename):
    path = os.path.join(SOUND_DIR, filename)
    try:
        _sfx_bank[filename] = pygame.mixer.Sound(path)
    except Exception as e:
        print(f"[SFX] 加载失败: {path} - {e}")


def _play_file(fname: str):
    snd = _sfx_bank.get(fname)
    if snd:
        snd.play()
        if DEBUG_MODE:
            fname_short = fname.rsplit('.', 1)[0]  # 去扩展名
            add_debug_log(f"[DEBUG] Sound - {fname_short}", (-1, -1, -1))


def add_debug_log(text, color=(-1, -1, -1), duration_ms=None):
    """向左下角调试日志池添加一条消息。
    - text: 显示文本
    - color: RGB 元组
    - duration_ms: 显示时长(ms)，默认 2000
    """
    if color == (-1, -1, -1):
        color = randcolor("noblack")
    if not DEBUG_MODE:
        return
    tick = pygame.time.get_ticks()
    dur = duration_ms if duration_ms is not None else DEFAULT_DEBUG_DURATION
    _debug_entries.append((text, color, tick, dur))


def draw_debug_logs(surface, font=None, padding_x=10, padding_bottom=20, gap=16,
                    filter_tags=None):
    """在 surface 左下角自底向上绘制调试日志。
    - font: 默认为 font_tiny
    - filter_tags: 可选包含标签的字符串列表，只绘制包含该标签的条目
    """
    if font is None:
        font = font_tiny  # noqa: F821 — 模块级字体，draw() 中调用时已在作用域
    now = pygame.time.get_ticks()
    # 清理过期条目
    _debug_entries[:] = [
        (t, c, tick, d) for t, c, tick, d in _debug_entries
        if now - tick < d
    ]
    # 自底向上绘制
    entries = _debug_entries
    if filter_tags:
        entries = [(t, c, tick, d) for t, c, tick, d in entries
                   if any(tag in t for tag in filter_tags)]
    for i, (text, color, _tick, _dur) in enumerate(reversed(entries)):
        txt = font.render(text, True, color)
        surface.blit(txt, (padding_x, SCREEN_HEIGHT - padding_bottom - i * gap))


def play_sfx(name, **kwargs):
    """统一音效播放入口。
    - tap:     kwargs['strength'] = 1~5 → 对应音调
    - shear:   全随机 6 变调
    - orb:     kwargs['value'] = 1~3 → 分段随机
    - click:   固定 x1.00
    - 其他:    单文件 (join_leave, victory, heavy_hit)
    """
    if "SOUNDS_DISABLED" in DEBUGS:
        return
    if name == 'tap':
        strength = kwargs.get('strength', 1)
        fname = TAP_SOUNDS.get(strength, TAP_SOUNDS[1])
    elif name == 'shear':
        fname = random.choice(SHEAR_SOUNDS)
    elif name == 'orb':
        value = kwargs.get('value', 1)
        fname = random.choice(ORB_SOUNDS.get(value, ORB_SOUNDS[1]))
    elif name == 'click':
        fname = CLICK_SOUND
    elif name == 'turn':
        fname = random.choice(IDLE_SOUNDS)
    else:
        fname = f'{name}.ogg'
    _play_file(fname)


# ===== 音效系统 =====
_load_all_sfx()
# ===== 音效系统 END =====


font_big = get_font(36, bold=True)
font_mid = get_font(22)
font_small = get_font(16)
font_tiny = get_font(13)

def randcolor(mode:str='all'):
    if mode == 'all':
        return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    elif mode == 'noblack':
        return (random.randint(32, 255), random.randint(32, 255), random.randint(32, 255))
    else:
        raise ValueError(f"未知颜色模式: {mode}")


def _draw_aa_circle(surface, color, center, radius):
    """绘制抗锯齿实心圆（填充 + AA 描边）。

    自动检测色值：RGBA（4 通道）回退到常规绘制（gfxdraw 仅支持 RGB）。
    """
    cx, cy = int(center[0]), int(center[1])
    r = int(radius)
    if r < 1:
        return
    if len(color) == 4:
        # RGBA：gfxdraw 不支持，回退
        pygame.draw.circle(surface, color, (cx, cy), r)
        return
    try:
        pygame.gfxdraw.filled_circle(surface, cx, cy, r, color)
        pygame.gfxdraw.aacircle(surface, cx, cy, r, color)
    except (ValueError, OverflowError):
        pass


def _draw_aa_circle_outline(surface, color, center, radius, width=1):
    """绘制抗锯齿圆形描边（空心圆）。

    RGBA 色值回退到常规绘制。
    """
    cx, cy = int(center[0]), int(center[1])
    r = int(radius)
    if r < 1 or width < 1:
        return
    if len(color) == 4:
        pygame.draw.circle(surface, color, (cx, cy), r, width)
        return
    try:
        if width == 1:
            pygame.gfxdraw.aacircle(surface, cx, cy, r, color)
        else:
            for w in range(width):
                pygame.gfxdraw.aacircle(surface, cx, cy, r - w, color)
    except (ValueError, OverflowError):
        pass


screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption(f"Binary Tree Battle - {VERSION}")
clock = pygame.time.Clock()
add_debug_log("[DEBUG] 调试模式已激活, 调试选项:", (-1, -1, -1), 3000)
for i in DEBUGS:
    add_debug_log(f" - {i}", (-1, -1, -1), 3000)
play_sfx('victory')


class Node:
    _next_id = 0

    def __init__(self, team, x, y, strength=1, parent=None):
        self.id = Node._next_id
        Node._next_id += 1
        self.team = team
        self.x = x
        self.y = y
        self.strength = strength
        self.parent = parent
        self.children = []

    def can_have_child(self):
        return len(self.children) < MAX_CHILDREN

    def draw(self, surface, emphasized=False):
        color = TEAM_COLORS[self.team]['main']
        cx, cy = int(self.x), int(self.y)

        # 可操作节点的脉冲强调环（幅度比点数包小 ~37%）
        if emphasized:
            pulse = 1.0 + 0.05 * math.sin(pygame.time.get_ticks() * 0.005)
            ring_r = int(NODE_RADIUS * pulse) + 5
            light = TEAM_COLORS[self.team]['light']
            ring_surf = pygame.Surface((ring_r * 2 + 4, ring_r * 2 + 4), pygame.SRCALPHA)
            _draw_aa_circle_outline(ring_surf, (*light, 80),
                                    (ring_r + 2, ring_r + 2), ring_r, 3)
            surface.blit(ring_surf, (cx - ring_r - 2, cy - ring_r - 2))

        # 节点圆形
        _draw_aa_circle(surface, color, (cx, cy), NODE_RADIUS)
        _draw_aa_circle_outline(surface, WHITE, (cx, cy), NODE_RADIUS, 2)

        # 根节点金色镶边
        if self.parent is None:
            _draw_aa_circle_outline(surface, (255, 215, 0), (cx, cy), NODE_RADIUS + 5, 3)

        # 强度数字
        txt = font_mid.render(str(self.strength), True, WHITE)
        rect = txt.get_rect(center=(cx, cy))
        surface.blit(txt, rect)

    def contains_point(self, px, py):
        dx = px - self.x
        dy = py - self.y
        return dx * dx + dy * dy <= NODE_RADIUS * NODE_RADIUS


class PointPack:
    """点数包：场上随机生成的小球，节点碰到后给队伍加分。"""

    def __init__(self, x, y, value):
        self.x = x
        self.y = y
        self.value = value
        self.radius = PICKUP_RADIUS
        self.spawn_time = pygame.time.get_ticks()
        self.pulse = 0.0

    def update(self):
        self.pulse += 0.06

    def draw(self, surface):
        now = pygame.time.get_ticks()
        age = now - self.spawn_time
        # 出生动画：缩放 0.3→1.0
        if age < PICKUP_SPAWN_ANIM_MS:
            t = age / PICKUP_SPAWN_ANIM_MS
            scale = 0.3 + 0.7 * t
        else:
            scale = 1.0
        pulse_scale = 1.0 + 0.08 * math.sin(self.pulse)
        r = max(2, int(self.radius * scale * pulse_scale))

        color = PICKUP_COLORS[self.value]
        cx, cy = int(self.x), int(self.y)

        # 光晕
        glow_r = r + 5
        glow_surf = pygame.Surface((glow_r * 2 + 2, glow_r * 2 + 2), pygame.SRCALPHA)
        _draw_aa_circle(glow_surf, (*PICKUP_GLOW, 35), (glow_r + 1, glow_r + 1), glow_r)
        _draw_aa_circle(glow_surf, (*PICKUP_GLOW, 70), (glow_r + 1, glow_r + 1), r + 2)
        surface.blit(glow_surf, (cx - glow_r - 1, cy - glow_r - 1))

        # 主体
        _draw_aa_circle(surface, color, (cx, cy), r)
        _draw_aa_circle_outline(surface, WHITE, (cx, cy), r, 2)

        # 数字标签
        txt = font_small.render(str(self.value), True, BLACK)
        surface.blit(txt, txt.get_rect(center=(cx, cy)))


class ScorePopup:
    """碰撞得分时的浮动文字反馈。"""

    def __init__(self, x, y, value, team):
        self.x = x
        self.y = y
        self.value = value
        self.team = team
        self.start_time = pygame.time.get_ticks()
        self.duration = 800

    def is_alive(self):
        return pygame.time.get_ticks() - self.start_time < self.duration

    def draw(self, surface):
        age = pygame.time.get_ticks() - self.start_time
        t = age / self.duration
        offset_y = -35 * t
        alpha = int(255 * (1 - t))
        color = TEAM_COLORS[self.team]['light']
        txt = font_mid.render(f"+{self.value}", True, color)
        txt.set_alpha(max(0, alpha))
        surface.blit(txt, txt.get_rect(center=(int(self.x), int(self.y + offset_y))))


class Game:
    def __init__(self):
        self.state = STATE_MENU
        self.nodes = []
        self.points = {'RED': INITIAL_POINTS, 'BLUE': INITIAL_POINTS}
        self.current_team = 'RED'
        self.turn_count = 1
        self.winner = None  # 胜利队伍（穿过对方根节点时设定）

        # 拖动相关
        self.dragging = False
        self.drag_node = None
        self.mouse_x = 0
        self.mouse_y = 0
        self.temp_strength = MIN_STRENGTH
        self.temp_range_index = 0  # 默认范围半径 120

        # 一回合只能创建一个节点
        self.has_created_this_turn = False

        # 悬停的树枝（child node），用于滚轮调强度
        self.hovered_branch_child = None

        # 点数包
        self.pickups = []
        self.score_popups = []

        # 结束回合按钮
        self.end_turn_rect = pygame.Rect(SCREEN_WIDTH - 195, SCREEN_HEIGHT - 60, 175, 42)
        self.menu_btn_rect = pygame.Rect(SCREEN_WIDTH // 2 - 90, SCREEN_HEIGHT // 2 + 110, 180, 50)

        # 网络模式
        self.network_mode = None   # None, 'host', 'client'
        self.my_team = None        # None, 'RED', 'BLUE'
        self.net_server = None
        self.net_client = None
        self.ip_input = ''         # IP输入文本
        self.connect_error = None  # 连接错误信息
        self.host_port = DEFAULT_PORT

        # 联机状态追踪（用于进出提示音）
        self._last_remote_connected = False

        # AI 模式
        self._ai_mode = False
        self._ai_team = None          # AI 控制的队伍
        self._ai_think_timer = 0
        self._AI_THINK_DELAY = 90  # ~1.5 秒思考时间
        self._ai_debug_candidates = []  # AI 候选可视化数据
        self._resume_from_replay = False

        # 回放记录器
        self.replay = ReplayRecorder()

        # 回放选择
        self._replay_files = []
        self._replay_selected = 0

    def reset(self, game_info=None):
        Node._next_id = 0
        self.nodes = []
        self.points = {'RED': INITIAL_POINTS, 'BLUE': INITIAL_POINTS}
        self.current_team = 'RED'
        self.turn_count = 1
        self.winner = None
        self.dragging = False
        self.drag_node = None
        self.temp_strength = MIN_STRENGTH
        self.temp_range_index = 0
        self.has_created_this_turn = False
        self.hovered_branch_child = None
        # 创建根节点：红左上，蓝右下
        red_root = Node('RED', 120, 120, strength=1)
        blue_root = Node('BLUE', SCREEN_WIDTH - 120, SCREEN_HEIGHT - 120, strength=1)
        self.nodes.append(red_root)
        self.nodes.append(blue_root)
        # 初始化点数包
        self.pickups = []
        self.score_popups = []
        self._init_pickups()

        # 回放：记录对局信息（首行），然后是初始状态
        self.replay = ReplayRecorder()
        if game_info:
            self.replay.record('game_info', **game_info)
        self.replay.record('init',
                           red_points=self.points['RED'], blue_points=self.points['BLUE'])
        for p in self.pickups:
            self.replay.record('spawn_pack', x=p.x, y=p.y, value=p.value)

    def start_game(self):
        self.reset(game_info={'mode': 'single'})
        self.state = STATE_PLAYING

    def start_host_game(self):
        """房主开始游戏（红队）。"""
        import network_protocol as proto
        self.network_mode = 'host'
        self.my_team = 'RED'
        self.reset(game_info={'mode': 'network', 'role': 'host', 'team': 'RED'})
        self.state = STATE_PLAYING
        # 发送完整初始游戏状态给客户端（含节点、点数包、回合等）
        if self.net_server and self.net_server.connected:
            self.net_server._send(proto.STATE_SYNC, proto.serialize_state(self))

    def start_client_game(self):
        """客户端进入等待房主开始的状态。"""
        self.network_mode = 'client'
        self.my_team = 'BLUE'
        self.state = STATE_CLIENT_WAIT

    def start_ai_game(self):
        """AI对战模式：随机分配队伍，本地对局。"""
        self._ai_mode = True
        self._ai_team = random.choice(['RED', 'BLUE'])
        self.my_team = 'RED' if self._ai_team == 'BLUE' else 'BLUE'
        self.network_mode = None
        self._ai_think_timer = 0
        self.reset(game_info={
            'mode': 'ai',
            'difficulty': 'normal',
            'player_team': self.my_team,
            'ai_team': self._ai_team,
        })
        self.state = STATE_PLAYING

    def go_menu(self):
        """返回菜单，清理网络资源。"""
        if self.net_server:
            self.net_server.stop()
            self.net_server = None
        if self.net_client:
            self.net_client.stop()
            self.net_client = None
        self.network_mode = None
        self.my_team = None
        self._ai_mode = False
        self._ai_team = None
        self.ip_input = ''
        self.connect_error = None
        self.state = STATE_MENU

    # ===== 联机动作系统 =====

    def apply_action(self, cmd, params):
        """客户端/服务器执行接收到的动作（如同本地操作）。"""
        import network_protocol as proto
        if cmd == proto.INIT_GAME:
            # 初始化点数包
            self.pickups = proto.deserialize_pickups(params[0])
        elif cmd == proto.ACT_ADD_NODE:
            team = params[0]
            x = float(params[1])
            y = float(params[2])
            strength = int(params[3])
            parent_id = int(params[4])
            node_id = int(params[5])
            parent = self._node_by_id(parent_id)
            if parent is None:
                return
            # 安全校验：新节点和父节点必须在同一个队伍
            if parent.team != team:
                print(f"[ERROR] ACT_ADD_NODE 跨队连线！team={team} parent.team={parent.team} parent_id={parent_id}")
                return
            new_node = Node(team, x, y, strength, parent=parent)
            new_node.id = node_id
            parent.children.append(new_node)
            self.nodes.append(new_node)
        elif cmd == proto.ACT_REMOVE_NODES:
            ids_to_remove = {int(pid) for pid in params}
            if not ids_to_remove:
                return
            # 安全保护：过滤掉根节点 ID
            root_ids = {n.id for n in self.nodes if n.parent is None}
            ids_to_remove -= root_ids
            if not ids_to_remove:
                return
            for n in self.nodes:
                n.children = [c for c in n.children if c.id not in ids_to_remove]
            self.nodes = [n for n in self.nodes if n.id not in ids_to_remove]
            if self.drag_node is not None and self.drag_node.id in ids_to_remove:
                self.dragging = False
                self.drag_node = None
            if self.hovered_branch_child is not None and self.hovered_branch_child.id in ids_to_remove:
                self.hovered_branch_child = None
            play_sfx('shear')
        elif cmd == proto.ACT_UPDATE_STRENGTH:
            node_id = int(params[0])
            new_strength = int(params[1])
            node = self._node_by_id(node_id)
            if node is not None:
                node.strength = new_strength
        elif cmd == proto.ACT_SYNC_TURN:
            self.current_team = params[0]
            self.has_created_this_turn = params[1] == 'True'
            self.turn_count = int(params[2])
        elif cmd == proto.ACT_SYNC_POINTS:
            self.points['RED'] = int(params[0])
            self.points['BLUE'] = int(params[1])
        elif cmd == proto.ACT_SYNC_PICKUPS:
            self.pickups = proto.deserialize_pickups(params[0])
        elif cmd == proto.ACT_GAME_OVER:
            self.winner = params[0]
            self.state = STATE_GAME_OVER
            self.replay.record('game_over', winner=self.winner)
            # 按己方队伍播放胜利或失败音效
            if self.my_team and self.my_team == self.winner:
                play_sfx('victory')
            else:
                play_sfx('heavy_hit')

    def _node_by_id(self, node_id):
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def _broadcast(self, cmd, *params):
        """房主广播动作给客户端。"""
        if self.network_mode == 'host' and self.net_server and self.net_server.connected:
            self.net_server._send(cmd, *params)

    def _broadcast_state_changed(self):
        """节点/点数变化后广播必要的同步消息。"""
        if self.network_mode != 'host' or not self.net_server or not self.net_server.connected:
            return
        import network_protocol as proto
        # 同步点数
        self._broadcast(proto.ACT_SYNC_POINTS, self.points['RED'], self.points['BLUE'])
        # 同步点数包
        self._broadcast(proto.ACT_SYNC_PICKUPS, proto.serialize_pickups(self.pickups))
        # 同步回合
        self._broadcast(proto.ACT_SYNC_TURN, self.current_team, str(self.has_created_this_turn), self.turn_count)
        if self.winner:
            self._broadcast(proto.ACT_GAME_OVER, self.winner)

    def get_nodes_of_team(self, team):
        return [n for n in self.nodes if n.team == team]

    def _get_roots(self):
        return [n for n in self.nodes if n.parent is None]

    # ===== 点数包机制 =====
    def _spawn_pickup(self, half=None):
        """在指定半屏或全图生成一个点数包，与根节点距离 < 160 则重试。"""
        roots = self._get_roots()
        for _ in range(200):
            if half == 'left':
                x = random.randint(PLAY_MARGIN, SCREEN_WIDTH // 2 - PLAY_MARGIN)
            elif half == 'right':
                x = random.randint(SCREEN_WIDTH // 2 + PLAY_MARGIN, SCREEN_WIDTH - PLAY_MARGIN)
            else:
                x = random.randint(PLAY_MARGIN, SCREEN_WIDTH - PLAY_MARGIN)
            y = random.randint(PLAY_AREA_TOP + PLAY_MARGIN, SCREEN_HEIGHT - PLAY_MARGIN)
            # 检查与根节点距离
            too_close = False
            for root in roots:
                dx = root.x - x
                dy = root.y - y
                if dx * dx + dy * dy < PICKUP_MIN_ROOT_DIST * PICKUP_MIN_ROOT_DIST:
                    too_close = True
                    break
            if too_close:
                continue
            value = random.choices(PICKUP_VALUES, weights=[40, 30, 30])[0]
            return PointPack(x, y, value)
        # 兜底：放宽限制
        value = random.choices(PICKUP_VALUES, weights=[40, 30, 30])[0]
        return PointPack(x, y, value)

    def _init_pickups(self):
        """初始生成 6 个点数包（左右半屏各 3），再随机删除 2 个保留 4 个。"""
        packs = []
        for _ in range(3):
            packs.append(self._spawn_pickup(half='left'))
        for _ in range(3):
            packs.append(self._spawn_pickup(half='right'))
        # 随机删除 2 个
        for _ in range(2):
            if packs:
                packs.pop(random.randint(0, len(packs) - 1))
        self.pickups = packs

    def _check_pickup_collisions(self):
        """检测所有节点与点数包的球形碰撞（不含树枝穿过）。"""
        if not self.pickups or not self.nodes:
            return
        collected = []
        for pack in self.pickups:
            for node in self.nodes:
                dx = node.x - pack.x
                dy = node.y - pack.y
                r_sum = NODE_RADIUS + pack.radius
                if dx * dx + dy * dy < r_sum * r_sum:
                    collected.append((pack, node))
                    break
        for pack, node in collected:
            if pack not in self.pickups:
                continue
            # 删除点数包
            self.pickups.remove(pack)
            # 加分
            self.points[node.team] += pack.value
            # 回放：记录拾取
            self.replay.record('pickup', team=node.team, value=pack.value,
                               x=pack.x, y=pack.y)
            # 视觉反馈
            self.score_popups.append(ScorePopup(pack.x, pack.y, pack.value, node.team))
            play_sfx('orb', value=pack.value)
            # 全图生成新点数包
            new_pack = self._spawn_pickup(half=None)
            self.pickups.append(new_pack)
            # 回放：记录新生成的点数包
            self.replay.record('spawn_pack', x=new_pack.x, y=new_pack.y,
                               value=new_pack.value)

    def update(self):
        """每帧更新。"""
        # 网络模式：处理服务器/客户端消息
        if self.network_mode == 'host' and self.net_server:
            self.net_server.process_actions()
        elif self.network_mode == 'client' and self.net_client:
            self.net_client.process_updates()

        # 联机进出提示音（所有状态生效）
        remote_now = False
        if self.network_mode == 'host' and self.net_server:
            remote_now = self.net_server.connected
        elif self.network_mode == 'client' and self.net_client:
            remote_now = self.net_client.connected
        if remote_now != self._last_remote_connected:
            play_sfx('join_leave')
            self._last_remote_connected = remote_now

        # 客户端等待状态：检查是否收到 playing 状态
        if self.state == STATE_CLIENT_WAIT:
            # 断线检测
            if self.net_client and not self.net_client.connected:
                self.go_menu()
            return

        if self.state == STATE_GAME_OVER:
            fname = self.replay.save()
            if fname:
                add_debug_log(f"[DEBUG] Replay saved: {fname}", (-1, -1, -1), 3000)
            
            return

        if self.state == STATE_REPLAY_PLAY:
            if self._replay_playing:
                self._replay_timer += 1
                if self._replay_timer >= 60:
                    self._replay_timer = 0
                    self._replay_step_forward()
                    if self._is_replay_last_step():
                        self._replay_playing = False
            return

        if self.state != STATE_PLAYING:
            return

        # 网络断线检测
        if self.network_mode == 'host' and self.net_server and not self.net_server.connected:
            self.go_menu()
            return
        if self.network_mode == 'client' and self.net_client and not self.net_client.connected:
            self.go_menu()
            return

        # 客户端不执行碰撞检测和交叉结算（由服务器处理）
        for pack in self.pickups:
            pack.update()
        if self.network_mode != 'client':
            old_points = dict(self.points)
            self._check_pickup_collisions()
            # 房主：点数包碰撞后同步状态
            if self.network_mode == 'host' and self.points != old_points:
                self._broadcast_state_changed()
        self._update_hovered_branch()
        self.score_popups = [p for p in self.score_popups if p.is_alive()]

        # AI 模式：AI 回合自动操作
        if self._ai_mode and self.current_team == self._ai_team:
            self._ai_update()

        # 房主：游戏结束时通知客户端
        if self.network_mode == 'host' and self.state == STATE_GAME_OVER and self.winner:
            import network_protocol as proto
            self._broadcast(proto.ACT_GAME_OVER, self.winner)

    @property
    def temp_range_radius(self):
        return RANGE_OPTIONS[self.temp_range_index]

    @property
    def range_cost(self):
        """范围半径每比 120 大 40，消耗 1 点"""
        return self.temp_range_index  # index 0=120→0, 1=160→1, 2=200→2, 3=240→3

    @property
    def strength_cost(self):
        return max(0, self.temp_strength - 1)

    @property
    def total_cost(self):
        return self.strength_cost + self.range_cost

    def can_afford(self, team=None):
        team = team or self.current_team
        return self.points[team] >= self.total_cost

    # ===== 线段相交与子树操作 =====
    @staticmethod
    def _segments_intersect(p1, p2, p3, p4, include_endpoints=False):
        """判断两条线段 P1P2 与 P3P4 是否相交，严格不包含端点（除非 include_endpoints=True）。
        用于判断新树枝是否穿过对方树枝（共享端点不算穿过）。"""
        def _orient(a, b, c):
            # 叉积：>0 逆时针；=0 共线；<0 顺时针
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        def _on_seg(a, b, c):
            # c 是否在以 a、b 为对角的矩形内（用于共线时）
            return (min(a[0], b[0]) - 1e-9 <= c[0] <= max(a[0], b[0]) + 1e-9 and
                    min(a[1], b[1]) - 1e-9 <= c[1] <= max(a[1], b[1]) + 1e-9)

        o1 = _orient(p1, p2, p3)
        o2 = _orient(p1, p2, p4)
        o3 = _orient(p3, p4, p1)
        o4 = _orient(p3, p4, p2)

        # 一般情况：严格相交
        if (o1 * o2 < 0) and (o3 * o4 < 0):
            return True
        if include_endpoints:
            if o1 == 0 and _on_seg(p1, p2, p3):
                return True
            if o2 == 0 and _on_seg(p1, p2, p4):
                return True
            if o3 == 0 and _on_seg(p3, p4, p1):
                return True
            if o4 == 0 and _on_seg(p3, p4, p2):
                return True
        return False

    @staticmethod
    def _segment_intersects_circle(p1, p2, center, radius):
        """判断线段 p1-p2 是否穿过以 center 为圆心、radius 为半径的圆。
        返回 True 表示线段与圆相交（线段任意部分在圆内）。"""
        cx, cy = center
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-9:
            # 退化为点：检查该点是否在圆内
            return (x1 - cx) ** 2 + (y1 - cy) ** 2 <= radius * radius
        # 投影参数 t（限制在 [0,1] 即线段范围内）
        t = ((cx - x1) * dx + (cy - y1) * dy) / seg_len_sq
        t = max(0.0, min(1.0, t))
        # 线段上离圆心最近的点
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        dist_sq = (closest_x - cx) ** 2 + (closest_y - cy) ** 2
        return dist_sq <= radius * radius

    @staticmethod
    def _draw_dashed_line(surface, p1, p2, color, dash_len=8, gap_len=6, width=1):
        """绘制虚线。color 支持 RGBA 元组（含透明度）。"""
        x1, y1 = p1
        x2, y2 = p2
        dx, dy = x2 - x1, y2 - y1
        total = math.hypot(dx, dy)
        if total < 1:
            return
        ux, uy = dx / total, dy / total
        seg = dash_len + gap_len
        drawn = 0.0
        while drawn < total:
            start_x = x1 + ux * drawn
            start_y = y1 + uy * drawn
            end = min(dash_len, total - drawn)
            end_x = x1 + ux * (drawn + end)
            end_y = y1 + uy * (drawn + end)
            pygame.draw.line(surface, color, (int(start_x), int(start_y)),
                             (int(end_x), int(end_y)), width)
            drawn += seg

    def _collect_subtree(self, root_node):
        """收集以 root_node 为根的所有后代节点（含 root_node 自己）。"""
        out = []
        stack = [root_node]
        while stack:
            cur = stack.pop()
            out.append(cur)
            for ch in cur.children:
                stack.append(ch)
        return out

    def _remove_nodes(self, nodes_to_remove):
        """批量移除节点集合：从全局列表移除、从父节点 children 移除。"""
        if not nodes_to_remove:
            return
        # 安全检查：永远不要移除根节点（parent 为 None 的节点）
        roots_in_removal = [n for n in nodes_to_remove if n.parent is None]
        if roots_in_removal:
            for r in roots_in_removal:
                print(f"[ERROR] _remove_nodes 试图移除根节点 id={r.id} team={r.team}！已阻止。")
            nodes_to_remove = [n for n in nodes_to_remove if n.parent is not None]
            if not nodes_to_remove:
                return
        ids_to_remove = {n.id for n in nodes_to_remove}
        # 更新父节点的 children 列表
        for n in self.nodes:
            n.children = [c for c in n.children if c.id not in ids_to_remove]
        # 更新全局节点列表
        self.nodes = [n for n in self.nodes if n.id not in ids_to_remove]

    def _resolve_crossing(self, new_node):
        """
        新节点 new_node 创建完成后，检查新树枝（new_node.parent -> new_node）
        是否穿过对方队伍的树枝或节点。
        返回 (removed_ids: set[int], winner: str|None, weakened: dict[int, int])
            weakened: {节点id → 新强度}  被削弱但未删除的节点
        规则1（穿树枝）：对方树枝（child 与 parent 连线）被穿过 →
          child.strength -= new_node.strength，≤0 删除 child 及其所有后代。
        规则2（穿节点）：新树枝穿过对方某节点圆 →
          - 若该节点是根节点 → 攻击方胜利，游戏结束。
          - 否则 → 该节点 strength -= new_node.strength，≤0 删除子树。
        """
        removed_ids = set()
        weakened = {}  # {node_id: new_strength}
        if new_node.parent is None:
            return removed_ids, None, weakened
        p_new = (new_node.parent.x, new_node.parent.y)
        q_new = (new_node.x, new_node.y)
        attacker_strength = new_node.strength
        attacker_team = new_node.team

        # ===== 1. 检查穿过对方节点（优先判断根节点=胜利） =====
        hit_root = None
        node_cut_targets = []
        for node in self.nodes:
            if node.team == attacker_team:
                continue  # 只切对方的
            if node is new_node or node is new_node.parent:
                continue  # 排除自身端点
            if self._segment_intersects_circle(p_new, q_new,
                                               (node.x, node.y), NODE_RADIUS):
                if node.parent is None:
                    # 穿过根节点 → 胜利
                    hit_root = node
                    break
                else:
                    node_cut_targets.append(node)

        if hit_root is not None:
            self.winner = attacker_team
            self.state = STATE_GAME_OVER
            return removed_ids, attacker_team, weakened

        # ===== 2. 检查穿过对方树枝（跨团队连线） =====
        cut_targets = []  # list[对方子节点 child_node（被切的那条线的终点）]
        for child in self.nodes:
            if child.team == attacker_team:
                continue  # 只切对方的树枝
            if child.parent is None:
                continue  # 根节点没有"自己的那条树枝"，切不到
            parent = child.parent
            p_old = (parent.x, parent.y)
            q_old = (child.x, child.y)
            endpoints_old = {id(parent), id(child)}
            endpoints_new = {id(new_node.parent), id(new_node)}
            if endpoints_old & endpoints_new:
                continue
            pt_old = (p_old, q_old)
            pt_new = (p_new, q_new)
            share_endpoint = False
            for a in pt_old:
                for b in pt_new:
                    if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
                        share_endpoint = True
                        break
                if share_endpoint:
                    break
            if share_endpoint:
                continue
            if self._segments_intersect(p_new, q_new, p_old, q_old, include_endpoints=False):
                cut_targets.append(child)

        # ===== 3. 结算：节点切断 + 树枝切断 =====
        all_targets = node_cut_targets + cut_targets
        if not all_targets:
            return removed_ids, None, weakened

        processed = set()
        for victim in all_targets:
            if victim.id in processed:
                continue
            if victim not in self.nodes:
                continue  # 可能已在前一轮被整棵子树删除
            processed.add(victim.id)
            victim.strength -= attacker_strength
            if victim.strength <= 0:
                subtree = self._collect_subtree(victim)
                for sn in subtree:
                    removed_ids.add(sn.id)
                self._remove_nodes(subtree)
            else:
                # 节点存活但强度降低了，记录以供广播
                weakened[victim.id] = victim.strength

        return removed_ids, None, weakened

    @staticmethod
    def _point_in_range(px, py, node, radius):
        dx = px - node.x
        dy = py - node.y
        return dx * dx + dy * dy <= radius * radius

    @staticmethod
    def _point_to_segment_dist(px, py, x1, y1, x2, y2):
        """点到线段 (x1,y1)-(x2,y2) 的最短距离。"""
        dx = x2 - x1
        dy = y2 - y1
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-9:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
        t = max(0.0, min(1.0, t))
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        return math.hypot(px - closest_x, py - closest_y)

    BRANCH_HOVER_THRESHOLD = 9.0

    def _update_hovered_branch(self):
        """检测鼠标悬停在哪个己方树枝上（拖动中不检测）。"""
        if self.dragging:
            self.hovered_branch_child = None
            return
        # 先验证当前 hovered_branch_child 是否仍然有效（在 self.nodes 中）
        if self.hovered_branch_child is not None and self.hovered_branch_child not in self.nodes:
            self.hovered_branch_child = None
        mx, my = self.mouse_x, self.mouse_y
        best_dist = self.BRANCH_HOVER_THRESHOLD
        best_child = None
        for child in self.nodes:
            if child.parent is None:
                continue
            if child.team != self.current_team:
                continue
            parent = child.parent
            d = self._point_to_segment_dist(mx, my, parent.x, parent.y, child.x, child.y)
            if d < best_dist:
                best_dist = d
                best_child = child
        self.hovered_branch_child = best_child

    @staticmethod
    def _draw_dashed_circle(surface, center, radius, color, width=1, dash_len=6, gap_len=4):
        """画虚线圆"""
        circumference = 2 * math.pi * radius
        step = dash_len + gap_len
        num_dashes = int(circumference / step)
        for i in range(num_dashes):
            a1 = (i * step) / radius
            a2 = (i * step + dash_len) / radius
            x1 = center[0] + radius * math.cos(a1)
            y1 = center[1] + radius * math.sin(a1)
            x2 = center[0] + radius * math.cos(a2)
            y2 = center[1] + radius * math.sin(a2)
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), width)

    def _team_label(self, team):
        """返回队伍在 UI 上的显示名称。AI 模式下显示 你/AI。"""
        if self._ai_mode:
            return '你' if team == self.my_team else 'AI'
        return TEAM_COLORS[team]['name']

    # ===== 菜单绘制 =====
    def draw_menu(self, surface):
        surface.fill(BG_COLOR)
        # 标题
        title = font_big.render("二叉树战斗", True, WHITE)
        surface.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 80)))

        subtitle = font_mid.render("Binary Tree Battle", True, GRAY)
        surface.blit(subtitle, subtitle.get_rect(center=(SCREEN_WIDTH // 2, 125)))

        # 操作说明面板
        panel = pygame.Rect(120, 160, SCREEN_WIDTH - 240, 340)
        pygame.draw.rect(surface, PANEL_COLOR, panel, border_radius=12)
        pygame.draw.rect(surface, DARK_GRAY, panel, 2, border_radius=12)

        title2 = font_mid.render("【 操 作 说 明 】", True, WHITE)
        surface.blit(title2, title2.get_rect(center=(SCREEN_WIDTH // 2, 195)))

        instructions = [
            "• 左上【红方】  右下【蓝方】  每队初始 10 点",
            "• 回合制战斗，每回合只能创建一个节点",
            "• 按住鼠标从己方节点拖出，在范围内松开来创建新节点",
            "• 松开前滚动鼠标【滚轮】调节强度（1 ~ 5）",
            "• 强度 1 不消耗点数，强度每 +1 消耗 1 点数",
            "• 按【空格】切换创建范围半径（120 / 160 / 200 / 240）",
            "• 范围每增大 40 消耗 1 点数，新节点须在该虚线圈内",
            "• 每个节点最多有 2 个子节点（二叉树）",
            "• 新树枝穿过对方树枝/节点 → 削减对方强度，≤0 删除子树",
            "• 【胜利条件】新树枝穿过对方根节点即获胜！保护你的根节点！",
            "• 【点数包】场上随机出现金色小球（1/2/3 点），节点碰到即拾取",
            "• 悬停己方树枝可滚轮调强度：+1消耗1点，-1返还1点（最低1）",
            "• 创建节点不结束回合，需手动点【结束回合】或按 Tab 结束"
        ]
        for i, line in enumerate(instructions):
            highlight = i in (8, 9, 10, 11, 12)
            txt = font_small.render(line, True, WHITE if (i <= 3 or highlight) else GRAY)
            surface.blit(txt, (150, 225 + i * 21))

        # 四个按钮：单人 / AI对战 / 创建房间 / 加入房间
        mouse_pos = pygame.mouse.get_pos()
        btn_y = 545
        btn_w, btn_h = 170, 46
        gap = 10
        total_w = btn_w * 4 + gap * 3
        start_x = SCREEN_WIDTH // 2 - total_w // 2

        # 单人对战
        bx1 = start_x
        btn1 = pygame.Rect(bx1, btn_y, btn_w, btn_h)
        h1 = btn1.collidepoint(mouse_pos)
        pygame.draw.rect(surface, GREEN if h1 else (40, 140, 40), btn1, border_radius=8)
        pygame.draw.rect(surface, WHITE, btn1, 2, border_radius=8)
        surface.blit(font_mid.render("单人", True, WHITE),
                     font_mid.render("单人", True, WHITE).get_rect(center=btn1.center))
        self._btn_single = btn1

        # AI 对战
        bx2 = bx1 + btn_w + gap
        btn2 = pygame.Rect(bx2, btn_y, btn_w, btn_h)
        h2 = btn2.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (200, 160, 40) if h2 else (140, 110, 30), btn2, border_radius=8)
        pygame.draw.rect(surface, WHITE, btn2, 2, border_radius=8)
        surface.blit(font_mid.render("AI 对战", True, WHITE),
                     font_mid.render("AI 对战", True, WHITE).get_rect(center=btn2.center))
        self._btn_ai = btn2

        # 创建房间
        bx3 = bx2 + btn_w + gap
        btn3 = pygame.Rect(bx3, btn_y, btn_w, btn_h)
        h3 = btn3.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (180, 50, 50) if h3 else (120, 30, 30), btn3, border_radius=8)
        pygame.draw.rect(surface, WHITE, btn3, 2, border_radius=8)
        surface.blit(font_mid.render("创建房间", True, WHITE),
                     font_mid.render("创建房间", True, WHITE).get_rect(center=btn3.center))
        self._btn_host = btn3

        # 加入房间
        bx4 = bx3 + btn_w + gap
        btn4 = pygame.Rect(bx4, btn_y, btn_w, btn_h)
        h4 = btn4.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (50, 80, 200) if h4 else (30, 50, 140), btn4, border_radius=8)
        pygame.draw.rect(surface, WHITE, btn4, 2, border_radius=8)
        surface.blit(font_mid.render("加入房间", True, WHITE),
                     font_mid.render("加入房间", True, WHITE).get_rect(center=btn4.center))
        self._btn_join = btn4

        # 回放 / 设置 按钮（第二行）
        btn2_y = btn_y + btn_h + 12
        btn2_w = 130
        bx5 = SCREEN_WIDTH // 2 - btn2_w - 8

        # 回放
        self._btn_replay = pygame.Rect(bx5, btn2_y, btn2_w, btn_h)
        hr = self._btn_replay.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (60, 140, 160) if hr else (35, 90, 110), self._btn_replay, border_radius=8)
        pygame.draw.rect(surface, WHITE, self._btn_replay, 2, border_radius=8)
        surface.blit(font_mid.render("回放", True, WHITE),
                     font_mid.render("回放", True, WHITE).get_rect(center=self._btn_replay.center))

        # 设置（预留）
        self._btn_settings = pygame.Rect(SCREEN_WIDTH // 2 + 8, btn2_y, btn2_w, btn_h)
        hs = self._btn_settings.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (100, 100, 100) if hs else (60, 60, 60), self._btn_settings, border_radius=8)
        pygame.draw.rect(surface, WHITE, self._btn_settings, 2, border_radius=8)
        surface.blit(font_mid.render("设置", True, WHITE),
                     font_mid.render("设置", True, WHITE).get_rect(center=self._btn_settings.center))

        # 右下角版本号与作者
        ver_text = font_tiny.render(f"Binary Tree Battle {VERSION}  by {AUTHOR}", True, (80, 80, 100))
        surface.blit(ver_text, (SCREEN_WIDTH - ver_text.get_width() - 12, SCREEN_HEIGHT - 22))

    # ===== 游戏结束绘制 =====
    def draw_game_over(self, surface):
        surface.fill(BG_COLOR)
        red_cnt = len(self.get_nodes_of_team('RED'))
        blue_cnt = len(self.get_nodes_of_team('BLUE'))

        winner = self.winner or 'RED'
        color = TEAM_COLORS[winner]['main']
        name = self._team_label(winner)

        title = font_big.render(f"{name} 获胜！", True, color)
        surface.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 160)))

        reason = font_mid.render("树枝穿透了对方根节点！", True, WHITE)
        surface.blit(reason, reason.get_rect(center=(SCREEN_WIDTH // 2, 220)))

        info = font_mid.render(f"红方节点: {red_cnt}  蓝方节点: {blue_cnt}", True, GRAY)
        surface.blit(info, info.get_rect(center=(SCREEN_WIDTH // 2, 270)))

        info2 = font_small.render(f"红方剩余点数: {self.points['RED']}  蓝方剩余点数: {self.points['BLUE']}", True, DARK_GRAY)
        surface.blit(info2, info2.get_rect(center=(SCREEN_WIDTH // 2, 305)))

        # 返回菜单按钮
        mouse_pos = pygame.mouse.get_pos()
        hover = self.menu_btn_rect.collidepoint(mouse_pos)
        c = GREEN if hover else (40, 140, 40)
        pygame.draw.rect(surface, c, self.menu_btn_rect, border_radius=8)
        pygame.draw.rect(surface, WHITE, self.menu_btn_rect, 2, border_radius=8)
        t = font_mid.render("返回菜单", True, WHITE)
        surface.blit(t, t.get_rect(center=self.menu_btn_rect.center))

    # ===== 游戏中绘制 =====
    def draw_playing(self, surface):
        surface.fill(BG_COLOR)

        # 画连接线
        for node in self.nodes:
            if node.parent is not None:
                p = node.parent
                # 跨队连线检测（防御性检查）
                if node.parent.team != node.team:
                    print(f"[ERROR] draw_playing 发现跨队连线！child(id={node.id},team={node.team}) "
                          f"-> parent(id={p.id},team={p.team})，用红色标记")
                    width = 3
                    color = (255, 50, 50)
                else:
                    width = max(1, node.strength)
                    color = TEAM_COLORS[node.team]['light']
                pygame.draw.line(surface, color,
                                 (int(p.x), int(p.y)),
                                 (int(node.x), int(node.y)), width)

        # 悬停树枝发光描边
        if self.hovered_branch_child is not None and not self.dragging:
            hc = self.hovered_branch_child
            hp = hc.parent
            glow_w = max(1, hc.strength) + 6
            light = TEAM_COLORS[hc.team]['light']
            # 用半透明粗线模拟发光
            glow_surf = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            pygame.draw.line(glow_surf, (*light, 60),
                             (int(hp.x), int(hp.y)),
                             (int(hc.x), int(hc.y)), glow_w)
            pygame.draw.line(glow_surf, (*light, 120),
                             (int(hp.x), int(hp.y)),
                             (int(hc.x), int(hc.y)), glow_w - 3)
            surface.blit(glow_surf, (0, 0))

        # 拖动中的范围圆 + 预览连线和节点
        if self.dragging and self.drag_node is not None:
            p = self.drag_node
            # 范围限制圆
            radius = self.temp_range_radius
            # 画虚线圆来表示范围
            self._draw_dashed_circle(surface, (int(p.x), int(p.y)), radius,
                                     TEAM_COLORS[self.current_team]['light'], 1)
            # 预览线
            valid = self.can_afford()
            in_range = self._point_in_range(self.mouse_x, self.mouse_y, p, radius)
            line_color = GREEN if (valid and in_range) else (200, 50, 50)
            pygame.draw.line(surface, line_color,
                             (int(p.x), int(p.y)),
                             (int(self.mouse_x), int(self.mouse_y)), 2)
            # 预览节点（半透明）
            s = pygame.Surface((NODE_RADIUS * 2 + 4, NODE_RADIUS * 2 + 4), pygame.SRCALPHA)
            c = TEAM_COLORS[self.current_team]['main']
            alpha_c = (*c, 140)
            _draw_aa_circle(s, alpha_c, (NODE_RADIUS + 2, NODE_RADIUS + 2), NODE_RADIUS)
            _draw_aa_circle_outline(s, WHITE, (NODE_RADIUS + 2, NODE_RADIUS + 2), NODE_RADIUS, 2)
            txt = font_mid.render(str(self.temp_strength), True, WHITE)
            s.blit(txt, txt.get_rect(center=(NODE_RADIUS + 2, NODE_RADIUS + 2)))
            surface.blit(s, (int(self.mouse_x) - NODE_RADIUS - 2, int(self.mouse_y) - NODE_RADIUS - 2))

        # 画点数包
        for pack in self.pickups:
            pack.draw(surface)

        # 画节点（当前回合队伍且未满子节点的节点添加脉冲强调）
        for node in self.nodes:
            emphasized = (node.team == self.current_team
                          and node.can_have_child()
                          and not self.has_created_this_turn)
            node.draw(surface, emphasized=emphasized)

        # 画得分弹出文字
        for popup in self.score_popups:
            popup.draw(surface)

        # ===== AI 候选可视化 =====
        if self._ai_debug_candidates:
            max_score = max(s for _, s in self._ai_debug_candidates)
            max_score = max(max_score, 1.0)  # 避免除零
            for action, score in self._ai_debug_candidates:
                parent = action['parent']
                x, y = action['x'], action['y']
                strength = action['strength']
                alpha = int(80 + 100 * (score / max_score))  # 80~180 透明度
                # 连线：半透明虚线
                self._draw_dashed_line(surface, (parent.x, parent.y), (x, y),
                                       (255, 255, 120, alpha), dash_len=8, gap_len=6, width=1)
                # 候选节点小圆
                r = NODE_RADIUS * 0.5 + strength * 0.5
                color = TEAM_COLORS[self.current_team]['main']
                # 外圈
                pygame.draw.circle(surface, (*color[:3], alpha),
                                   (int(x), int(y)), int(r), 1)
                # 填充
                pygame.draw.circle(surface, (*color[:3], alpha // 3),
                                   (int(x), int(y)), int(r - 1))
                # 评分数字
                s_txt = font_tiny.render(str(int(score)), True,
                                         (255, 255, 180, alpha))
                surface.blit(s_txt, s_txt.get_rect(center=(x, y - r - 8)))

        # ===== HUD 顶部信息 =====
        # 红方信息
        hud_red = pygame.Rect(10, 8, 180, 62)
        pygame.draw.rect(surface, PANEL_COLOR, hud_red, border_radius=6)
        pygame.draw.rect(surface, RED, hud_red, 2, border_radius=6)
        red_label = self._team_label('RED')
        rt = font_mid.render(f"{red_label} (红方)", True, LIGHT_RED)
        surface.blit(rt, (hud_red.x + 10, hud_red.y + 6))
        rp = font_small.render(f"点数: {self.points['RED']}", True, WHITE)
        surface.blit(rp, (hud_red.x + 10, hud_red.y + 32))
        rc = font_small.render(f"节点: {len(self.get_nodes_of_team('RED'))}", True, GRAY)
        surface.blit(rc, (hud_red.x + 100, hud_red.y + 32))

        # 蓝方信息
        hud_blue = pygame.Rect(SCREEN_WIDTH - 190, 8, 180, 62)
        pygame.draw.rect(surface, PANEL_COLOR, hud_blue, border_radius=6)
        pygame.draw.rect(surface, BLUE, hud_blue, 2, border_radius=6)
        blue_label = self._team_label('BLUE')
        bt = font_mid.render(f"{blue_label} (蓝方)", True, LIGHT_BLUE)
        surface.blit(bt, (hud_blue.x + 10, hud_blue.y + 6))
        bp = font_small.render(f"点数: {self.points['BLUE']}", True, WHITE)
        surface.blit(bp, (hud_blue.x + 10, hud_blue.y + 32))
        bc = font_small.render(f"节点: {len(self.get_nodes_of_team('BLUE'))}", True, GRAY)
        surface.blit(bc, (hud_blue.x + 100, hud_blue.y + 32))

        # 中间回合信息
        turn_name = self._team_label(self.current_team)
        turn_color = TEAM_COLORS[self.current_team]['main']
        turn_rect_w = 220
        hud_turn = pygame.Rect((SCREEN_WIDTH - turn_rect_w) // 2, 8, turn_rect_w, 62)
        pygame.draw.rect(surface, PANEL_COLOR, hud_turn, border_radius=6)
        pygame.draw.rect(surface, turn_color, hud_turn, 2, border_radius=6)
        tt = font_mid.render(f"第 {self.turn_count} 回合", True, WHITE)
        surface.blit(tt, tt.get_rect(center=(hud_turn.centerx, hud_turn.y + 18)))
        ttt = font_small.render(f"当前: {turn_name} 行动", True, turn_color)
        surface.blit(ttt, ttt.get_rect(center=(hud_turn.centerx, hud_turn.y + 44)))

        # 退出按钮（回合面板下方）
        mouse_pos = pygame.mouse.get_pos()
        exit_btn_w, exit_btn_h = 70, 24
        self.exit_btn_rect = pygame.Rect(hud_turn.centerx - exit_btn_w // 2, 75, exit_btn_w, exit_btn_h)
        eh = self.exit_btn_rect.collidepoint(mouse_pos)
        ec = (160, 50, 50) if eh else (100, 35, 35)
        pygame.draw.rect(surface, ec, self.exit_btn_rect, border_radius=4)
        pygame.draw.rect(surface, WHITE, self.exit_btn_rect, 1, border_radius=4)
        ex = font_tiny.render("退出", True, WHITE)
        surface.blit(ex, ex.get_rect(center=self.exit_btn_rect.center))

        # 拖动时强度+范围提示
        if self.dragging:
            tip_y = 90
            afford = self.can_afford()
            in_range = self._point_in_range(self.mouse_x, self.mouse_y,
                                            self.drag_node, self.temp_range_radius)
            msg = (f"强度: {self.temp_strength}(-{self.strength_cost})  "
                   f"范围: {self.temp_range_radius}(-{self.range_cost})  "
                   f"总消耗: {self.total_cost} 点  [空格切范围|滚轮调强度]")
            c = GREEN if (afford and in_range) else (220, 80, 80)
            ts = font_small.render(msg, True, c)
            surface.blit(ts, ts.get_rect(center=(SCREEN_WIDTH // 2, tip_y)))
            warn = []
            if not afford:
                warn.append("点数不足！")
            if not in_range:
                warn.append("超出范围！")
            if warn:
                ts2 = font_tiny.render("  ".join(warn), True, (255, 100, 100))
                surface.blit(ts2, ts2.get_rect(center=(SCREEN_WIDTH // 2, tip_y + 20)))

        # 结束回合按钮
        mouse_pos = pygame.mouse.get_pos()
        hover = self.end_turn_rect.collidepoint(mouse_pos)
        bc = DARK_GRAY if not hover else (80, 80, 120)
        pygame.draw.rect(surface, bc, self.end_turn_rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, self.end_turn_rect, 2, border_radius=6)
        et = font_small.render("结束回合 (Tab)", True, WHITE)
        surface.blit(et, et.get_rect(center=self.end_turn_rect.center))

        # 底部提示
        if self._ai_mode and self.current_team == self._ai_team:
            pct = int(self._ai_think_timer / self._AI_THINK_DELAY * 100)
            progress_label = f"AI 思考中... ({pct}%)" if self._ai_think_timer > 0 else "AI 思考中..."
            hint = font_tiny.render(progress_label, True, (200, 160, 60))
        elif self.network_mode and self.current_team != self.my_team:
            hint = font_tiny.render("等待对方操作...", True, (200, 200, 100))
        elif self.dragging:
            hint = font_tiny.render("滚轮调强度 | 空格切范围 | 松开鼠标创建节点", True, DARK_GRAY)
        elif self.hovered_branch_child is not None:
            hint = font_tiny.render("滚轮上/下 调节树枝强度（+1消耗1点 / -1返还1点）", True, (160, 220, 160))
        elif self.has_created_this_turn:
            hint = font_tiny.render("本回合已创建节点，可调树枝强度 | Tab/按钮 结束回合", True, (200, 200, 100))
        else:
            hint = font_tiny.render("提示: 拖动己方节点创建分支 | 悬停树枝滚轮调强度 | 空格切范围 | Tab结束回合", True, DARK_GRAY)
        surface.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 15)))

    # ===== 事件处理 =====
    def handle_event(self, event):
        if self.state == STATE_MENU:
            self._handle_menu_event(event)
        elif self.state == STATE_HOST_WAIT:
            self._handle_host_wait_event(event)
        elif self.state == STATE_CLIENT_WAIT:
            self._handle_client_wait_event(event)
        elif self.state == STATE_JOIN_INPUT:
            self._handle_join_input_event(event)
        elif self.state == STATE_GAME_OVER:
            self._handle_game_over_event(event)
        elif self.state == STATE_REPLAY_SELECT:
            self._handle_replay_select_event(event)
        elif self.state == STATE_REPLAY_PLAY:
            self._handle_replay_play_event(event)
        elif self.state == STATE_PLAYING:
            self._handle_playing_event(event)

    def _start_host(self):
        """启动房主服务器，进入等待状态。"""
        from game_server import GameServer
        self.network_mode = 'host'
        self.net_server = GameServer(self, self.host_port)
        self.net_server.start()
        self.state = STATE_HOST_WAIT
        self.connect_error = None

    def _try_connect(self):
        """客户端尝试连接服务器。"""
        from game_client import GameClient
        ip = self.ip_input.strip()
        if not ip:
            self.connect_error = "请输入 IP 地址"
            return
        # 解析 ip:port
        if ':' in ip:
            host, port_str = ip.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                self.connect_error = "端口格式错误"
                return
        else:
            host = ip
            port = DEFAULT_PORT

        self.net_client = GameClient(self, host, port)
        success, err_msg = self.net_client.connect()
        if success:
            self.connect_error = None
            self.start_client_game()
        else:
            self.connect_error = err_msg
            self.net_client = None

    def _handle_menu_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(self, '_btn_single') and self._btn_single.collidepoint(event.pos):
                play_sfx('click')
                self.start_game()
            elif hasattr(self, '_btn_ai') and self._btn_ai.collidepoint(event.pos):
                play_sfx('click')
                self.start_ai_game()
            elif hasattr(self, '_btn_host') and self._btn_host.collidepoint(event.pos):
                play_sfx('click')
                self._start_host()
            elif hasattr(self, '_btn_join') and self._btn_join.collidepoint(event.pos):
                play_sfx('click')
                self.state = STATE_JOIN_INPUT
                self.ip_input = ''
                self.connect_error = None
            elif hasattr(self, '_btn_replay') and self._btn_replay.collidepoint(event.pos):
                play_sfx('click')
                self._enter_replay_select()
            elif hasattr(self, '_btn_settings') and self._btn_settings.collidepoint(event.pos):
                play_sfx('click')
                # 设置：预留

    def _enter_replay_select(self):
        """进入回放文件选择界面。解析每个回放的步数和胜者。"""
        replay_dir = os.path.join(os.path.dirname(__file__), 'replays')
        if os.path.isdir(replay_dir):
            files = sorted(
                [f for f in os.listdir(replay_dir) if f.endswith('.bpr')],
                reverse=True)
            self._replay_files = []
            import json
            for fname in files:
                steps, winner_label, mode_label = self._parse_replay_meta(fname)
                self._replay_files.append((fname, steps, winner_label, mode_label))
        else:
            self._replay_files = []
        self._replay_selected = 0
        self._replay_delete_mode = False
        self.state = STATE_REPLAY_SELECT

    def _parse_replay_meta(self, fname):
        """快速解析回放文件的模式、步数和胜者标签。"""
        import json
        filepath = os.path.join(os.path.dirname(__file__), 'replays', fname)
        steps = 0
        winner = None
        game_info = {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        action = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = action.get('type')
                    if t == 'game_info':
                        game_info = action
                    elif t == 'end_turn':
                        steps += 1
                    elif t == 'game_over':
                        winner = action.get('winner')
        except (IOError, OSError):
            pass

        mode = game_info.get('mode', 'unknown')
        mode_label = self._mode_label(game_info)

        # 胜者标签
        if winner is None:
            winner_label = None
        elif mode == 'ai':
            player_team = game_info.get('player_team', '')
            if winner == player_team:
                winner_label = '玩家胜'
            else:
                winner_label = 'AI胜'
        else:
            winner_label = '红队胜' if winner == 'RED' else '蓝队胜'

        return steps, winner_label, mode_label

    @staticmethod
    def _mode_label(game_info):
        """将 game_info 转为简短中文标签。"""
        mode = game_info.get('mode', 'unknown')
        if mode == 'single':
            return '单人'
        elif mode == 'ai':
            return 'AI'
        elif mode == 'network':
            role = game_info.get('role', '')
            return '联机-红' if role == 'host' else '联机-蓝'
        return '?'

    def _handle_host_wait_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 端口输入框（点击获得焦点后用键盘修改）
            if hasattr(self, '_host_port_rect') and self._host_port_rect.collidepoint(event.pos):
                self._host_port_focused = True
            else:
                self._host_port_focused = False

            # 开始游戏按钮（已连接时才有效）
            if hasattr(self, '_host_start_rect') and self._host_start_rect.collidepoint(event.pos):
                play_sfx('click')
                if self.net_server and self.net_server.connected:
                    if getattr(self, '_resume_from_replay', False):
                        self._resume_from_replay = False
                        import network_protocol as proto
                        self.state = STATE_PLAYING
                        self.net_server._send(proto.STATE_SYNC, proto.serialize_state(self))
                    else:
                        self.start_host_game()
                else:
                    # 重新启动服务器（若之前端口改过）
                    if self.net_server:
                        self.net_server.stop()
                    from game_server import GameServer
                    self.net_server = GameServer(self, self.host_port)
                    self.net_server.start()
            # 取消按钮
            if hasattr(self, '_host_cancel_rect') and self._host_cancel_rect.collidepoint(event.pos):
                play_sfx('click')
                if self.net_server:
                    self.net_server.stop()
                    self.net_server = None
                self.state = STATE_MENU

        if event.type == pygame.KEYDOWN:
            if getattr(self, '_host_port_focused', False):
                if event.key == pygame.K_BACKSPACE:
                    self.host_port = int(str(self.host_port)[:-1]) if str(self.host_port)[:-1] else 8447
                elif event.unicode and event.unicode.isdigit():
                    new_port = int(str(self.host_port) + event.unicode)
                    if 1 <= new_port <= 65535:
                        self.host_port = new_port

    def _handle_join_input_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self._try_connect()
            elif event.key == pygame.K_BACKSPACE:
                self.ip_input = self.ip_input[:-1]
            elif event.key == pygame.K_ESCAPE:
                self.state = STATE_MENU
            elif event.unicode and len(self.ip_input) < 30:
                c = event.unicode
                if c in '0123456789.:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    self.ip_input += c
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 快速填入
            if hasattr(self, '_quick_fill_rect') and self._quick_fill_rect.collidepoint(event.pos):
                play_sfx('click')
                self.ip_input = f'127.0.0.1:{DEFAULT_PORT}'
            # 返回按钮
            if hasattr(self, '_join_back_rect') and self._join_back_rect.collidepoint(event.pos):
                play_sfx('click')
                self.state = STATE_MENU

    def _handle_game_over_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.menu_btn_rect.collidepoint(event.pos):
                play_sfx('click')
                self.go_menu()

    def _handle_playing_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

        # 退出按钮：任何时候都能点
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(self, 'exit_btn_rect') and self.exit_btn_rect.collidepoint(event.pos):
                play_sfx('click')
                self.go_menu()
                return

        # 网络模式/AI模式：非己方回合时只允许鼠标移动
        if self._ai_mode:
            is_my_turn = (self.current_team != self._ai_team)
        else:
            is_my_turn = (self.network_mode is None or self.current_team == self.my_team)

        if event.type == pygame.MOUSEMOTION:
            self.mouse_x, self.mouse_y = event.pos

        if not is_my_turn:
            return  # 等待对方操作

        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos
            # 左键按下：开始拖动
            if event.button == 1:
                # 先检查是否点结束回合
                if self.end_turn_rect.collidepoint(mx, my):
                    play_sfx('click')
                    self._end_turn()
                    return
                # 本回合已创建过节点则不能再拖
                if self.has_created_this_turn:
                    return
                # 找被点击的己方节点，且还能有子节点
                for node in reversed(self.nodes):
                    if node.team == self.current_team and node.contains_point(mx, my):
                        if node.can_have_child():
                            self.dragging = True
                            self.drag_node = node
                            self.mouse_x, self.mouse_y = mx, my
                            self.temp_strength = MIN_STRENGTH
                            self.temp_range_index = 0  # 默认范围 120
                        return

        # 滚轮事件 (pygame 2 / SDL2): pygame.MOUSEWHEEL
        if event.type == pygame.MOUSEWHEEL:
            self._handle_wheel(1 if event.y > 0 else -1)
        # 方向键调节强度（无滚轮设备备选）
        if event.type == pygame.KEYDOWN and event.key == pygame.K_UP:
            self._handle_wheel(1)
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_DOWN:
            self._handle_wheel(-1)

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging and self.drag_node is not None:
                mx, my = event.pos
                self._try_create_node(mx, my)
            self.dragging = False
            self.drag_node = None
            self.temp_strength = MIN_STRENGTH
            self.temp_range_index = 0

        # 空格切换范围半径（仅拖动中有效）
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            if self.dragging:
                self.temp_range_index = (self.temp_range_index + 1) % len(RANGE_OPTIONS)

        # Tab 键结束回合（任意时机）
        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            self._end_turn()

    def _handle_wheel(self, direction):
        """滚轮事件处理。direction > 0 = 向上滚（强度+1），< 0 = 向下滚（强度-1）。"""
        if self.dragging:
            # 拖动中：调节新节点强度
            if direction > 0 and self.temp_strength < MAX_STRENGTH:
                self.temp_strength += 1
                play_sfx('tap', strength=self.temp_strength)
            elif direction < 0 and self.temp_strength > MIN_STRENGTH:
                self.temp_strength -= 1
                play_sfx('tap', strength=self.temp_strength)
        elif self.hovered_branch_child is not None:
            child = self.hovered_branch_child
            if direction > 0:
                # 滚轮上 → 强度+1，消耗1点
                if child.strength < MAX_STRENGTH and self.points[self.current_team] >= 1:
                    old_str = child.strength
                    if self.network_mode == 'client' and self.net_client:
                        self.net_client.send_modify_branch(child.x, child.y, child.strength + 1)
                    else:
                        child.strength += 1
                        self.points[self.current_team] -= 1
                        self.replay.record('modify_branch', team=self.current_team,
                                           node_id=child.id, old_strength=old_str,
                                           new_strength=child.strength)
                        if self.network_mode == 'host':
                            import network_protocol as proto
                            self._broadcast(proto.ACT_UPDATE_STRENGTH, child.id, child.strength)
                            self._broadcast_state_changed()
                    play_sfx('tap', strength=child.strength)
            elif direction < 0:
                # 滚轮下 → 强度-1（最低1），返还1点
                if child.strength > MIN_STRENGTH:
                    old_str = child.strength
                    if self.network_mode == 'client' and self.net_client:
                        self.net_client.send_modify_branch(child.x, child.y, child.strength - 1)
                    else:
                        child.strength -= 1
                        self.points[self.current_team] += 1
                        self.replay.record('modify_branch', team=self.current_team,
                                           node_id=child.id, old_strength=old_str,
                                           new_strength=child.strength)
                        if self.network_mode == 'host':
                            import network_protocol as proto
                            self._broadcast(proto.ACT_UPDATE_STRENGTH, child.id, child.strength)
                            self._broadcast_state_changed()
                    play_sfx('tap', strength=child.strength)

    def _try_create_node(self, mx, my):
        node = self.drag_node
        if node is None:
            return
        if not node.can_have_child():
            return
        if self.has_created_this_turn:
            return

        # 客户端模式：发送请求给服务器，不本地应用
        if self.network_mode == 'client' and self.net_client:
            self.net_client.send_place_node(
                node.x, node.y, mx, my,
                self.temp_range_radius, self.temp_strength)
            return

        strength = self.temp_strength
        radius = self.temp_range_radius
        total = self.total_cost
        if not self.can_afford():
            return  # 点数不足

        # 范围检查：松开位置须在父节点范围圆内
        if not self._point_in_range(mx, my, node, radius):
            return

        # 限制范围：在屏幕内
        if mx < NODE_RADIUS or mx > SCREEN_WIDTH - NODE_RADIUS:
            return
        if my < 85 or my > SCREEN_HEIGHT - NODE_RADIUS:  # 避开顶部HUD
            return

        # 不与已有节点过近
        for other in self.nodes:
            dx = other.x - mx
            dy = other.y - my
            if dx * dx + dy * dy < (NODE_RADIUS * 2 + 4) ** 2:
                return

        # 创建
        new_node = Node(self.current_team, mx, my, strength, parent=node)
        node.children.append(new_node)
        self.nodes.append(new_node)
        self.points[self.current_team] -= total
        play_sfx('tap', strength=new_node.strength)

        # 回放：记录放置节点
        self.replay.record('place_node', team=self.current_team,
                           parent_id=node.id, node_id=new_node.id,
                           x=mx, y=my, strength=strength, range=radius)

        # 结算：新树枝穿过对方树枝 → 扣强度 / 删除子树
        removed_ids, winner, weakened = self._resolve_crossing(new_node)
        if removed_ids:
            self.replay.record('remove_nodes', ids=sorted(removed_ids))
        for nid, new_str in sorted(weakened.items()):
            self.replay.record('weaken_node', node_id=nid,
                               new_strength=new_str)
        if winner:
            self.replay.record('game_over', winner=winner)
        if removed_ids or weakened:
            play_sfx('shear')
        if winner:
            if self.my_team:
                play_sfx('victory' if self.my_team == winner else 'heavy_hit')
            else:
                play_sfx('victory')
        # 一回合只能创建一个节点，但不自动结束回合
        self.has_created_this_turn = True

        # 广播给客户端
        if self.network_mode == 'host':
            import network_protocol as proto
            # 1. 广播新增节点
            self._broadcast(proto.ACT_ADD_NODE, new_node.team, new_node.x, new_node.y,
                          new_node.strength, new_node.parent.id, new_node.id)
            # 2. 广播删除的节点
            if removed_ids:
                self._broadcast(proto.ACT_REMOVE_NODES, *removed_ids)
            # 3. 广播被削弱但未删除的节点（强度变化）
            for nid, new_str in weakened.items():
                self._broadcast(proto.ACT_UPDATE_STRENGTH, nid, new_str)
            # 3. 同步回合/点数/点数包
            self._broadcast_state_changed()

    def _ai_update(self):
        """AI 回合自动操作。每帧调用，延迟后执行 AI 动作。"""
        if self._ai_think_timer < self._AI_THINK_DELAY:
            self._ai_think_timer += 1
            return

        self._ai_think_timer = 0

        # 本回合已创建过节点 → 直接结束回合
        if self.has_created_this_turn:
            self._end_turn()
            return

        from AI.aithink import AIThinker
        ai = AIThinker(self)
        action = ai.decide_action()

        if action is None:
            return

        if action['type'] == 'end_turn':
            self._end_turn()
        elif action['type'] == 'place_node':
            parent = action['parent']
            x, y = action['x'], action['y']
            strength = action['strength']
            range_index = action.get('range_index', 0)
            # 检查合法性
            if not parent.can_have_child():
                self._end_turn()
                return
            total_cost = range_index + max(0, strength - 1)
            if self.points[self.current_team] < total_cost:
                # 点数不足：尝试回退到最低消耗（强度1，范围120，消耗0）
                if self.points[self.current_team] >= 0:
                    strength = 1
                    range_index = 0
                    total_cost = 0
                else:
                    self._end_turn()
                    return
            # 创建节点
            new_node = Node(self.current_team, x, y, strength, parent=parent)
            parent.children.append(new_node)
            self.nodes.append(new_node)
            self.points[self.current_team] -= total_cost
            play_sfx('tap', strength=strength)

            # 回放：记录 AI 放置节点（含实际 range 半径）
            actual_range = RANGE_OPTIONS[range_index] if range_index < len(RANGE_OPTIONS) else RANGE_OPTIONS[-1]
            self.replay.record('place_node', team=self.current_team,
                               parent_id=parent.id, node_id=new_node.id,
                               x=x, y=y, strength=strength, range=actual_range)

            removed_ids, winner, weakened = self._resolve_crossing(new_node)
            if removed_ids:
                self.replay.record('remove_nodes', ids=sorted(removed_ids))
            for nid, new_str in sorted(weakened.items()):
                self.replay.record('weaken_node', node_id=nid,
                                   new_strength=new_str)
            if winner:
                self.replay.record('game_over', winner=winner)
            if removed_ids or weakened:
                play_sfx('shear')
            if winner:
                play_sfx('victory' if self.my_team == winner else 'heavy_hit')

            # 切割后自动降级：回收点数
            if (not winner and strength >= 3
                    and (removed_ids or weakened)):
                own_root = None
                for n in self.nodes:
                    if n.team == self.current_team and n.parent is None:
                        own_root = n
                        break
                is_defensive = (
                    own_root
                    and math.hypot(new_node.x - own_root.x,
                                   new_node.y - own_root.y) <= 240)
                target_strength = 2 if is_defensive else 1
                if new_node.strength > target_strength:
                    levels_down = new_node.strength - target_strength
                    old_str = new_node.strength
                    new_node.strength = target_strength
                    self.points[self.current_team] += levels_down
                    self.replay.record(
                        'modify_branch', team=self.current_team,
                        node_id=new_node.id,
                        old_strength=old_str,
                        new_strength=target_strength)
                    if self.network_mode == 'host':
                        import network_protocol as proto
                        self._broadcast(proto.ACT_UPDATE_STRENGTH,
                                        new_node.id, new_node.strength)
                        self._broadcast_state_changed()
                    play_sfx('tap', strength=target_strength)

            self.has_created_this_turn = True
        elif action['type'] == 'modify_branch':
            node = action['node']
            new_str = action['new_strength']
            if node.strength < MAX_STRENGTH and self.points[self.current_team] >= 1:
                old_str = node.strength
                node.strength = new_str
                self.points[self.current_team] -= 1
                self.replay.record('modify_branch', team=self.current_team,
                                   node_id=node.id, old_strength=old_str,
                                   new_strength=new_str)
                if self.network_mode == 'host':
                    import network_protocol as proto
                    self._broadcast(proto.ACT_UPDATE_STRENGTH, node.id, node.strength)
                    self._broadcast_state_changed()
                play_sfx('tap', strength=new_str)

    def _end_turn(self):
        # 客户端模式：发送结束回合请求给服务器
        if self.network_mode == 'client' and self.net_client:
            self.net_client.send_end_turn()
            self.has_created_this_turn = False
            self.dragging = False
            self.drag_node = None
            self.hovered_branch_child = None
            return

        self.has_created_this_turn = False
        self.dragging = False
        self.drag_node = None
        self.hovered_branch_child = None
        self._ai_debug_candidates = []  # 清除 AI 候选可视化

        # 回放：记录结束回合
        previous_team = self.current_team
        self.replay.record('end_turn', team=previous_team)

        if self.current_team == 'RED':
            self.current_team = 'BLUE'
        else:
            self.current_team = 'RED'
            self.turn_count += 1

        # 房主模式：广播回合切换
        if self.network_mode == 'host':
            import network_protocol as proto
            self._broadcast(proto.ACT_SYNC_TURN, self.current_team, str(self.has_created_this_turn), self.turn_count)

    def draw(self, surface):
        if self.state == STATE_MENU:
            self.draw_menu(surface)
        elif self.state == STATE_HOST_WAIT:
            self.draw_host_wait(surface)
        elif self.state == STATE_CLIENT_WAIT:
            self.draw_client_wait(surface)
        elif self.state == STATE_JOIN_INPUT:
            self.draw_join_input(surface)
        elif self.state == STATE_GAME_OVER:
            self.draw_game_over(surface)
        elif self.state == STATE_REPLAY_SELECT:
            self.draw_replay_select(surface)
        elif self.state == STATE_REPLAY_PLAY:
            self.draw_replay_play(surface)
        else:
            self.draw_playing(surface)

        # 调试模式：左下角显示调试日志
        if DEBUG_MODE:
            draw_debug_logs(surface)

    def draw_host_wait(self, surface):
        """房主等待客户端加入界面。"""
        surface.fill(BG_COLOR)
        title = font_big.render("等待玩家加入...", True, WHITE)
        surface.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 180)))

        # 端口输入
        port_label = font_small.render("端口:", True, GRAY)
        surface.blit(port_label, (SCREEN_WIDTH // 2 - 130, 248))
        port_rect = pygame.Rect(SCREEN_WIDTH // 2 - 90, 240, 80, 36)
        pygame.draw.rect(surface, PANEL_COLOR, port_rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, port_rect, 2, border_radius=6)
        port_txt = font_mid.render(str(self.host_port), True, WHITE)
        surface.blit(port_txt, port_txt.get_rect(center=port_rect.center))
        self._host_port_rect = port_rect

        info = font_small.render("服务器地址: 127.0.0.1:PORT", True, DARK_GRAY)
        info = font_small.render(f"服务器地址: 127.0.0.1:{self.host_port}", True, DARK_GRAY)
        surface.blit(info, info.get_rect(center=(SCREEN_WIDTH // 2, 295)))

        tip = font_tiny.render("提示: 若客户端无法连接，请检查防火墙是否放行", True, (180, 180, 100))
        surface.blit(tip, tip.get_rect(center=(SCREEN_WIDTH // 2, 325)))

        # 开始/等待按钮
        mouse_pos = pygame.mouse.get_pos()
        start_btn = pygame.Rect(SCREEN_WIDTH // 2 - 110, 380, 220, 46)
        hover = start_btn.collidepoint(mouse_pos)
        if self.net_server and self.net_server.connected:
            btn_text = "已连接 - 开始游戏"
            btn_color = GREEN if hover else (40, 140, 40)
        else:
            btn_text = "等待中..."
            btn_color = DARK_GRAY
        pygame.draw.rect(surface, btn_color, start_btn, border_radius=8)
        pygame.draw.rect(surface, WHITE, start_btn, 2, border_radius=8)
        surface.blit(font_mid.render(btn_text, True, WHITE),
                     font_mid.render(btn_text, True, WHITE).get_rect(center=start_btn.center))
        self._host_start_rect = start_btn

        # 取消按钮
        cancel_btn = pygame.Rect(SCREEN_WIDTH // 2 - 90, 440, 180, 42)
        hc = cancel_btn.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (160, 50, 50) if hc else (100, 30, 30), cancel_btn, border_radius=8)
        pygame.draw.rect(surface, WHITE, cancel_btn, 2, border_radius=8)
        surface.blit(font_mid.render("取消", True, WHITE),
                     font_mid.render("取消", True, WHITE).get_rect(center=cancel_btn.center))
        self._host_cancel_rect = cancel_btn

    def draw_join_input(self, surface):
        """客户端输入IP界面。"""
        surface.fill(BG_COLOR)
        title = font_big.render("加入房间", True, WHITE)
        surface.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 160)))

        hint = font_small.render(f"输入房主 IP 地址 (默认端口 {DEFAULT_PORT}, 可输入 ip:端口)", True, GRAY)
        surface.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, 210)))

        # 快速填入按钮
        quick = font_tiny.render("点击此处填入 127.0.0.1:" + str(DEFAULT_PORT), True, (160, 160, 220))
        quick_rect = quick.get_rect(center=(SCREEN_WIDTH // 2, 245))
        if quick_rect.collidepoint(pygame.mouse.get_pos()):
            quick.set_alpha(255)
        else:
            quick.set_alpha(180)
        surface.blit(quick, quick_rect)
        self._quick_fill_rect = quick_rect

        # 输入框
        input_rect = pygame.Rect(SCREEN_WIDTH // 2 - 200, 270, 400, 46)
        pygame.draw.rect(surface, PANEL_COLOR, input_rect, border_radius=8)
        pygame.draw.rect(surface, WHITE, input_rect, 2, border_radius=8)
        display_text = self.ip_input + '_'  # 光标模拟
        txt = font_mid.render(display_text, True, WHITE)
        surface.blit(txt, (input_rect.x + 12, input_rect.y + 12))

        # 连接提示
        if self.connect_error:
            err = font_small.render(self.connect_error, True, (255, 100, 100))
            surface.blit(err, err.get_rect(center=(SCREEN_WIDTH // 2, 340)))

        hint2 = font_small.render("Enter 连接 | ESC 返回", True, DARK_GRAY)
        surface.blit(hint2, hint2.get_rect(center=(SCREEN_WIDTH // 2, 390)))

        # 返回按钮
        mouse_pos = pygame.mouse.get_pos()
        btn = pygame.Rect(SCREEN_WIDTH // 2 - 90, 440, 180, 46)
        hover = btn.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (160, 50, 50) if hover else (100, 30, 30), btn, border_radius=8)
        pygame.draw.rect(surface, WHITE, btn, 2, border_radius=8)
        surface.blit(font_mid.render("返回", True, WHITE),
                     font_mid.render("返回", True, WHITE).get_rect(center=btn.center))
        self._join_back_rect = btn

    def draw_client_wait(self, surface):
        """客户端等待房主开始游戏的界面（纯等待，无输入）。"""
        surface.fill(BG_COLOR)
        title = font_big.render("已连接，等待房主开始游戏...", True, WHITE)
        surface.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 280)))

        info = font_small.render("房主开始后将自动进入游戏", True, GRAY)
        surface.blit(info, info.get_rect(center=(SCREEN_WIDTH // 2, 320)))

        # 返回按钮
        mouse_pos = pygame.mouse.get_pos()
        btn = pygame.Rect(SCREEN_WIDTH // 2 - 90, 420, 180, 46)
        hover = btn.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (160, 50, 50) if hover else (100, 30, 30), btn, border_radius=8)
        pygame.draw.rect(surface, WHITE, btn, 2, border_radius=8)
        surface.blit(font_mid.render("断开返回", True, WHITE),
                     font_mid.render("断开返回", True, WHITE).get_rect(center=btn.center))
        self._client_wait_back_rect = btn

    def _handle_client_wait_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(self, '_client_wait_back_rect') and self._client_wait_back_rect.collidepoint(event.pos):
                play_sfx('click')
                self.go_menu()

    # ===== 回放系统 =====
    def draw_replay_select(self, surface):
        """回放文件选择界面。"""
        surface.fill(BG_COLOR)
        title = font_big.render("选择回放文件", True, WHITE)
        surface.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 60)))

        if not self._replay_files:
            hint = font_mid.render("暂无回放文件", True, GRAY)
            surface.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)))
        else:
            list_start_y = 120
            visible_count = min(len(self._replay_files), 15)
            for i in range(visible_count):
                idx = i
                if idx >= len(self._replay_files):
                    break
                fname, steps, winner_label, mode_label = self._replay_files[idx]
                y = list_start_y + i * 32
                is_selected = (idx == self._replay_selected)

                # 选中高亮
                if is_selected:
                    if self._replay_delete_mode:
                        bar = pygame.Rect(SCREEN_WIDTH // 2 - 300, y - 2, 600, 28)
                        pygame.draw.rect(surface, (150, 30, 30), bar, border_radius=4)
                        pygame.draw.rect(surface, (255, 60, 60), bar, 2, border_radius=4)
                    else:
                        bar = pygame.Rect(SCREEN_WIDTH // 2 - 300, y - 2, 600, 28)
                        pygame.draw.rect(surface, (50, 80, 150), bar, border_radius=4)

                _offset = -4

                # 左侧：日期时间
                date_label = fname
                if len(fname) >= 15:
                    date_label = f"{fname[:4]}-{fname[4:6]}-{fname[6:8]}  {fname[9:11]}:{fname[11:13]}:{fname[13:15]}"
                c = WHITE if is_selected else GRAY
                date_txt = font_mid.render(date_label, True, c)
                surface.blit(date_txt, (SCREEN_WIDTH // 2 - 290, y + _offset))

                # 右侧：模式 + 步数和胜者
                meta = f"[{mode_label}]  {steps} 步"
                if winner_label:
                    meta += f"  |  {winner_label}"
                meta_txt = font_mid.render(meta, True, c)
                meta_rect = meta_txt.get_rect()
                surface.blit(meta_txt, (SCREEN_WIDTH // 2 + 290 - meta_rect.width, y + _offset))

        # 底部提示
        if self._replay_delete_mode:
            hint = font_tiny.render("↑↓ 选择   Tab 删除   Del / Esc 退出删除模式", True, (255, 80, 80))
        else:
            hint = font_tiny.render("↑↓ 选择   Enter 确认   Del 删除   Esc 返回", True, DARK_GRAY)
        surface.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 20)))

    def _handle_replay_select_event(self, event):
        """回放文件选择事件处理。"""
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.KEYDOWN:
            # 删除模式：Del 退出，Tab 确认删除
            if self._replay_delete_mode:
                if event.key == pygame.K_DELETE:
                    self._replay_delete_mode = False
                    return
                if event.key == pygame.K_TAB:
                    if self._replay_files:
                        fname = self._replay_files[self._replay_selected][0]
                        src = os.path.join(os.path.dirname(__file__), 'replays', fname)
                        del_dir = os.path.join(os.path.dirname(__file__), 'replays', 'deleted')
                        os.makedirs(del_dir, exist_ok=True)
                        dst = os.path.join(del_dir, fname)
                        shutil.move(src, dst)
                        del self._replay_files[self._replay_selected]
                        play_sfx('shear')
                        if self._replay_files:
                            self._replay_selected = min(self._replay_selected, len(self._replay_files) - 1)
                        return
                if event.key == pygame.K_ESCAPE:
                    self._replay_delete_mode = False
                    return
                if event.key in (pygame.K_UP, pygame.K_DOWN):
                    if self._replay_files:
                        n = len(self._replay_files)
                        delta = -1 if event.key == pygame.K_UP else 1
                        self._replay_selected = (self._replay_selected + delta) % n
                        play_sfx('click')
                    return
                return  # 删除模式下忽略其他按键

            if event.key == pygame.K_ESCAPE:
                self.state = STATE_MENU
            elif event.key == pygame.K_DELETE:
                if self._replay_files:
                    self._replay_delete_mode = True
            elif event.key in (pygame.K_UP, pygame.K_DOWN):
                if self._replay_files:
                    n = len(self._replay_files)
                    delta = -1 if event.key == pygame.K_UP else 1
                    self._replay_selected = (self._replay_selected + delta) % n
                    play_sfx('click')
            elif event.key == pygame.K_RETURN:
                if self._replay_files:
                    play_sfx('click')
                    self._start_replay(self._replay_files[self._replay_selected][0])
        if event.type == pygame.MOUSEWHEEL:
            if self._replay_files:
                n = len(self._replay_files)
                delta = -1 if event.y > 0 else 1  # 上滚=上移=索引减
                self._replay_selected = (self._replay_selected + delta) % n
                play_sfx('click')

    def _start_replay(self, filename):
        """加载回放文件，分组为步骤，构建初始棋盘。"""
        import json
        filepath = os.path.join(os.path.dirname(__file__), 'replays', filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            all_actions = [json.loads(line) for line in f if line.strip()]

        # 按 end_turn 分步
        self._replay_steps = []
        current = []
        for a in all_actions:
            current.append(a)
            if a['type'] == 'end_turn':
                self._replay_steps.append(current)
                current = []
        if current:  # 尾部残余（如 game_over）
            self._replay_steps.append(current)

        self._replay_step_index = -1
        self._replay_playing = False
        self._replay_timer = 0

        # 构建初始状态（只有根节点，无任何操作）
        Node._next_id = 100000
        self.nodes = []
        self.points = {'RED': INITIAL_POINTS, 'BLUE': INITIAL_POINTS}
        red_root = Node('RED', 120, 120, strength=1)
        red_root.id = 0
        blue_root = Node('BLUE', SCREEN_WIDTH - 120, SCREEN_HEIGHT - 120, strength=1)
        blue_root.id = 1
        self.nodes = [red_root, blue_root]
        self.pickups = []
        self.winner = None
        self.current_team = 'RED'
        self.turn_count = 1
        self.dragging = False
        self.drag_node = None
        self.has_created_this_turn = False
        self.hovered_branch_child = None

        self._replay_id_map = {0: red_root, 1: blue_root}
        self.state = STATE_REPLAY_PLAY

    def _rebuild_replay_state(self):
        """从零重建游戏状态，应用到当前步骤。"""
        Node._next_id = 100000
        self.nodes = []
        self.points = {'RED': INITIAL_POINTS, 'BLUE': INITIAL_POINTS}
        red_root = Node('RED', 120, 120, strength=1)
        red_root.id = 0
        blue_root = Node('BLUE', SCREEN_WIDTH - 120, SCREEN_HEIGHT - 120, strength=1)
        blue_root.id = 1
        self.nodes = [red_root, blue_root]
        self.pickups = []
        self.winner = None
        self.current_team = 'RED'
        self.turn_count = 1
        self._replay_id_map = {0: red_root, 1: blue_root}

        for step_idx in range(self._replay_step_index + 1):
            for action in self._replay_steps[step_idx]:
                self._apply_replay_action(action)

    def _apply_replay_action(self, action):
        """应用单条回放动作到当前游戏状态。"""
        t = action['type']
        if t == 'init':
            self.points['RED'] = action['red_points']
            self.points['BLUE'] = action['blue_points']
        elif t == 'spawn_pack':
            self.pickups.append(PointPack(action['x'], action['y'], action['value']))
        elif t == 'place_node':
            parent = self._replay_id_map[action['parent_id']]
            new_node = Node(action['team'], action['x'], action['y'],
                            action['strength'], parent=parent)
            new_node.id = action['node_id']
            self._replay_id_map[action['node_id']] = new_node
            parent.children.append(new_node)
            self.nodes.append(new_node)
        elif t == 'modify_branch':
            node = self._replay_id_map[action['node_id']]
            node.strength = action['new_strength']
        elif t == 'remove_nodes':
            ids_to_remove = set(action['ids'])
            for n in self.nodes:
                n.children = [c for c in n.children if c.id not in ids_to_remove]
            self.nodes = [n for n in self.nodes if n.id not in ids_to_remove]
        elif t == 'weaken_node':
            node = self._replay_id_map[action['node_id']]
            node.strength = action['new_strength']
        elif t == 'pickup':
            for p in list(self.pickups):
                if abs(p.x - action['x']) < 1 and abs(p.y - action['y']) < 1:
                    self.pickups.remove(p)
                    break
            self.points[action['team']] += action['value']
        elif t == 'end_turn':
            if self.current_team == 'RED':
                self.current_team = 'BLUE'
            else:
                self.current_team = 'RED'
                self.turn_count += 1
        elif t == 'game_over':
            self.winner = action['winner']

    def _replay_step_forward(self):
        """前进一步。"""
        if self._replay_step_index + 1 >= len(self._replay_steps):
            return False
        self._replay_step_index += 1
        for action in self._replay_steps[self._replay_step_index]:
            self._apply_replay_action(action)
        return True

    def _replay_step_back(self):
        """后退一步。"""
        if self._replay_step_index < 0:
            return False
        self._replay_step_index -= 1
        self._rebuild_replay_state()
        return True

    def _is_replay_last_step(self):
        return self._replay_step_index >= len(self._replay_steps) - 1

    def _is_replay_first_step(self):
        return self._replay_step_index < 0

    def draw_replay_play(self, surface):
        """回放播放界面。"""
        surface.fill(BG_COLOR)
        # 画连接线和节点
        for node in self.nodes:
            if node.parent is not None:
                p = node.parent
                width = max(1, node.strength)
                color = TEAM_COLORS[node.team]['light']
                pygame.draw.line(surface, color, (int(p.x), int(p.y)),
                                 (int(node.x), int(node.y)), width)
            node.draw(surface)
        # 画点数包
        for pack in self.pickups:
            pack.draw(surface)

        # ===== 顶部 HUD：红方/步骤/蓝方 =====
        # 红方信息面板（左侧）
        hud_red = pygame.Rect(10, 8, 180, 62)
        pygame.draw.rect(surface, PANEL_COLOR, hud_red, border_radius=6)
        pygame.draw.rect(surface, RED, hud_red, 2, border_radius=6)
        red_label = self._team_label('RED')
        rt = font_mid.render(f"{red_label} (红方)", True, LIGHT_RED)
        surface.blit(rt, (hud_red.x + 10, hud_red.y + 6))
        rp = font_small.render(f"点数: {self.points['RED']}", True, WHITE)
        surface.blit(rp, (hud_red.x + 10, hud_red.y + 32))
        rc = font_small.render(f"节点: {len(self.get_nodes_of_team('RED'))}", True, GRAY)
        surface.blit(rc, (hud_red.x + 100, hud_red.y + 32))

        # 蓝方信息面板（右侧）
        hud_blue = pygame.Rect(SCREEN_WIDTH - 190, 8, 180, 62)
        pygame.draw.rect(surface, PANEL_COLOR, hud_blue, border_radius=6)
        pygame.draw.rect(surface, BLUE, hud_blue, 2, border_radius=6)
        blue_label = self._team_label('BLUE')
        bt = font_mid.render(f"{blue_label} (蓝方)", True, LIGHT_BLUE)
        surface.blit(bt, (hud_blue.x + 10, hud_blue.y + 6))
        bp = font_small.render(f"点数: {self.points['BLUE']}", True, WHITE)
        surface.blit(bp, (hud_blue.x + 10, hud_blue.y + 32))
        bc = font_small.render(f"节点: {len(self.get_nodes_of_team('BLUE'))}", True, GRAY)
        surface.blit(bc, (hud_blue.x + 100, hud_blue.y + 32))

        # 中间步骤信息
        hud = pygame.Rect((SCREEN_WIDTH - 300) // 2, 8, 300, 62)
        pygame.draw.rect(surface, PANEL_COLOR, hud, border_radius=6)
        total_steps = len(self._replay_steps)
        step_label = f"回放模式"
        txt = font_mid.render(step_label, True, WHITE)
        surface.blit(txt, txt.get_rect(center=(hud.centerx, hud.y + 16)))
        step_label2 = f"步骤 {self._replay_step_index + 1}/{total_steps}"
        txt2 = font_small.render(step_label2, True, GRAY)
        surface.blit(txt2, txt2.get_rect(center=(hud.centerx, hud.y + 42)))

        # 控制按钮（顶部 HUD 下方）
        mouse_pos = pygame.mouse.get_pos()
        btn_w, btn_h = 90, 30
        btn_y = hud.bottom + 8
        total_w = btn_w * 4 + 12 * 3
        start_x = SCREEN_WIDTH // 2 - total_w // 2

        def _draw_btn(x, label, enabled, hover_color):
            rect = pygame.Rect(x, btn_y, btn_w, btn_h)
            h = rect.collidepoint(mouse_pos) and enabled
            c = hover_color if h else ((120, 120, 120) if not enabled else (60, 60, 80))
            pygame.draw.rect(surface, c, rect, border_radius=5)
            pygame.draw.rect(surface, WHITE, rect, 1, border_radius=5)
            tc = WHITE if enabled else DARK_GRAY
            t = font_small.render(label, True, tc)
            surface.blit(t, t.get_rect(center=rect.center))
            return rect

        bx1 = start_x
        self._replay_prev_rect = _draw_btn(bx1, "上一步",
                                           not self._is_replay_first_step(),
                                           (50, 80, 150))
        bx2 = bx1 + btn_w + 12
        play_label = "暂停" if self._replay_playing else "播放"
        self._replay_play_rect = _draw_btn(bx2, play_label, True,
                                           (180, 140, 40) if self._replay_playing else (50, 160, 50))
        bx3 = bx2 + btn_w + 12
        self._replay_next_rect = _draw_btn(bx3, "下一步",
                                           not self._is_replay_last_step(),
                                           (50, 80, 150))
        # 进入残局按钮
        bx4 = bx3 + btn_w + 12
        can_enter = self.winner is None
        self._replay_enter_rect = _draw_btn(bx4, "进入游戏",
                                            can_enter,
                                            (160, 120, 20))

        # 胜利提示（按钮下方，避免遮挡）
        if self.winner:
            wcolor = TEAM_COLORS[self.winner]['main']
            winner_name = self._team_label(self.winner)
            wtxt = font_mid.render(f"{winner_name} 获胜", True, wcolor)
            surface.blit(wtxt, wtxt.get_rect(center=(SCREEN_WIDTH // 2, btn_y + btn_h + 18)))

        # 返回按钮
        back_rect = pygame.Rect(SCREEN_WIDTH - 120, SCREEN_HEIGHT - 50, 100, 34)
        h = back_rect.collidepoint(mouse_pos)
        pygame.draw.rect(surface, GREEN if h else (40, 140, 40), back_rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, back_rect, 2, border_radius=6)
        t = font_small.render("返回", True, WHITE)
        surface.blit(t, t.get_rect(center=back_rect.center))
        self._replay_back_rect = back_rect

        # 残局模式选择子菜单
        if getattr(self, '_resume_menu', False):
            self._draw_resume_menu(surface)

    def _draw_resume_menu(self, surface):
        """绘制残局模式选择覆盖层。"""
        # 半透明暗色背景
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))

        # 标题
        t = font_big.render("选择残局模式", True, WHITE)
        surface.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 80)))

        # 三个按钮
        btn_w, btn_h = 180, 44
        btn_gap = 16
        start_y = SCREEN_HEIGHT // 2 - 20
        start_x = SCREEN_WIDTH // 2 - btn_w // 2

        labels = [
            ("本地对战",  "single"),
            ("AI 对战",   "ai"),
            ("创建房间",  "host"),
        ]

        mouse_pos = pygame.mouse.get_pos()
        self._resume_buttons = labels
        self._resume_rects = {}

        for i, (label, mode) in enumerate(labels):
            rect = pygame.Rect(start_x, start_y + i * (btn_h + btn_gap), btn_w, btn_h)
            h = rect.collidepoint(mouse_pos)
            color = (60, 120, 200) if h else (40, 80, 140)
            pygame.draw.rect(surface, color, rect, border_radius=8)
            pygame.draw.rect(surface, WHITE, rect, 2, border_radius=8)
            t = font_mid.render(label, True, WHITE)
            surface.blit(t, t.get_rect(center=rect.center))
            self._resume_rects[label] = rect

        # 提示
        hint = font_small.render("ESC 返回", True, (180, 180, 180))
        surface.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, start_y + 3 * (btn_h + btn_gap) + 20)))

    def _handle_replay_play_event(self, event):
        """回放播放事件处理。"""
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mp = event.pos
            if hasattr(self, '_replay_back_rect') and self._replay_back_rect.collidepoint(mp):
                play_sfx('click')
                self.go_menu()
            elif hasattr(self, '_replay_play_rect') and self._replay_play_rect.collidepoint(mp):
                play_sfx('click')
                self._replay_playing = not self._replay_playing
                self._replay_timer = 0
            elif hasattr(self, '_replay_prev_rect') and self._replay_prev_rect.collidepoint(mp):
                if not self._is_replay_first_step():
                    play_sfx('click')
                    self._replay_step_back()
            elif hasattr(self, '_replay_next_rect') and self._replay_next_rect.collidepoint(mp):
                if not self._is_replay_last_step():
                    play_sfx('click')
                    self._replay_step_forward()
            elif hasattr(self, '_replay_enter_rect') and self._replay_enter_rect.collidepoint(mp):
                if self.winner is None:
                    play_sfx('click')
                    self._resume_menu = True
                    self._resume_buttons = []
                    self._resume_rects = {}
        # 残局模式子菜单
        if getattr(self, '_resume_menu', False) and event.type == pygame.MOUSEBUTTONDOWN:
            mp = pygame.mouse.get_pos()
            for label, mode in getattr(self, '_resume_buttons', []):
                rect = getattr(self, '_resume_rects', {}).get(label)
                if rect and rect.collidepoint(mp):
                    play_sfx('click')
                    self._resume_menu = False
                    if mode == 'single':
                        self._enter_game_from_replay('single')
                    elif mode == 'ai':
                        self._enter_game_from_replay('ai')
                    elif mode == 'host':
                        self._enter_game_from_replay('host')
                    return
        if event.type == pygame.KEYDOWN:
            if getattr(self, '_resume_menu', False):
                if event.key == pygame.K_ESCAPE:
                    self._resume_menu = False
                    return
            if event.key == pygame.K_ESCAPE:
                self.go_menu()
            elif event.key == pygame.K_LEFT:
                if not self._is_replay_first_step():
                    self._replay_step_back()
            elif event.key == pygame.K_RIGHT:
                if not self._is_replay_last_step():
                    self._replay_step_forward()
            elif event.key == pygame.K_SPACE:
                self._replay_playing = not self._replay_playing
                self._replay_timer = 0

    def _enter_game_from_replay(self, mode='single'):
        """从当前回放步骤进入残局模式。
        mode: 'single' 本地对战 | 'ai' AI对战 | 'host' 创建房间"""
        import network_protocol as proto

        # 修正 Node ID 计数器
        max_id = max(n.id for n in self.nodes) if self.nodes else 1
        Node._next_id = max_id + 1

        # 初始化新回放记录器
        self.replay = ReplayRecorder()

        if mode == 'ai':
            self._ai_mode = True
            self._ai_team = random.choice(['RED', 'BLUE'])
            self.my_team = 'RED' if self._ai_team == 'BLUE' else 'BLUE'
            self.network_mode = None
            self._ai_think_timer = 0
            self.replay.record('game_info', mode='ai', difficulty='normal',
                               player_team=self.my_team, ai_team=self._ai_team)
        elif mode == 'host':
            self.network_mode = 'host'
            self.my_team = 'RED'
            self._ai_mode = False
            self._ai_team = None
            self._resume_from_replay = True
            self.replay.record('game_info', mode='network', role='host', team='RED')
        else:  # single
            self._ai_mode = False
            self._ai_team = None
            self.network_mode = None
            self.replay.record('game_info', mode='single')

        self.replay.record('init',
                           red_points=self.points['RED'],
                           blue_points=self.points['BLUE'])
        for p in self.pickups:
            self.replay.record('spawn_pack', x=p.x, y=p.y, value=p.value)

        # 记录当前所有节点（BFS，根的 children 先于 grandchildren）
        from collections import deque
        queue = deque()
        for n in self.nodes:
            if n.parent is None:
                queue.append(n)
        while queue:
            node = queue.popleft()
            for child in node.children:
                self.replay.record('place_node', team=child.team,
                                   parent_id=node.id, node_id=child.id,
                                   x=child.x, y=child.y,
                                   strength=child.strength, range=120)
                queue.append(child)

        # 清除回放播放相关状态
        self._replay_steps = []
        self._replay_id_map = {}
        self._replay_playing = False
        self._replay_step_index = -1
        self._replay_timer = 0

        self.winner = None

        if mode == 'host':
            from game_server import GameServer
            self.net_server = GameServer(self, self.host_port)
            self.net_server.start()
            self.state = STATE_HOST_WAIT
            print(f"[残局] 从回放进入游戏 (创建房间) | 红: {self.points['RED']}点 | "
                  f"蓝: {self.points['BLUE']}点 | 回合: {self.current_team} T{self.turn_count}")
        else:
            self.state = STATE_PLAYING
            mode_name = '单人' if mode == 'single' else 'AI'
            print(f"[残局] 从回放进入游戏 ({mode_name}) | 红: {self.points['RED']}点 | "
                  f"蓝: {self.points['BLUE']}点 | 回合: {self.current_team} T{self.turn_count}")


def main():
    game = Game()
    while True:
        for event in pygame.event.get():
            game.handle_event(event)
        game.update()
        game.draw(screen)
        pygame.display.flip()
        clock.tick(FPS)


if __name__ == "__main__":
    main()
