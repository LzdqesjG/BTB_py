"""游戏常量与字体配置。"""
import os
import sys

VERSION = "v1.5"
AUTHOR = "Lzdqesj"

SCREEN_WIDTH, SCREEN_HEIGHT = 1300, 700
FPS = 60
NODE_RADIUS = 18
INITIAL_POINTS = 10
MIN_STRENGTH = 1
MAX_STRENGTH = 5
MAX_CHILDREN = 2
RANGE_OPTIONS = [120, 160, 200, 240]  # 可选范围半径，空格循环切换

# 点数包常量
PICKUP_RADIUS = 13
PICKUP_MIN_ROOT_DIST = 160
PICKUP_VALUES = [1, 2, 3]
PICKUP_COLORS = {
    1: (255, 215, 0),    # 金色
    2: (255, 165, 30),   # 橙色
    3: (255, 90, 30),    # 红橙
}
PICKUP_GLOW = (255, 240, 160)
PICKUP_SPAWN_ANIM_MS = 350
PLAY_AREA_TOP = 85       # HUD 下方
PLAY_MARGIN = 28

# 颜色
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
DARK_GRAY = (100, 100, 100)
RED = (220, 50, 50)
LIGHT_RED = (255, 120, 120)
BLUE = (50, 80, 220)
LIGHT_BLUE = (120, 150, 255)
GREEN = (50, 180, 50)
BG_COLOR = (30, 30, 40)
PANEL_COLOR = (50, 50, 70)

TEAM_COLORS = {
    'RED': {'main': RED, 'light': LIGHT_RED, 'name': '红方'},
    'BLUE': {'main': BLUE, 'light': LIGHT_BLUE, 'name': '蓝方'}
}

# 游戏状态
STATE_MENU = 'menu'
STATE_PLAYING = 'playing'
STATE_GAME_OVER = 'game_over'
STATE_HOST_WAIT = 'host_wait'      # 房主等待玩家加入
STATE_CLIENT_WAIT = 'client_wait'  # 客户端等待房主开始
STATE_JOIN_INPUT = 'join_input'    # 客户端输入IP
STATE_CONNECTING = 'connecting'    # 客户端连接中
STATE_REPLAY_SELECT = 'replay_select'  # 回放文件选择
STATE_REPLAY_PLAY = 'replay_play'      # 回放播放中
DEFAULT_PORT = 8447

# ===== 音效配置 =====
SOUND_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'sounds')

# 强度 → 音调 (click_stereo)
TAP_SOUNDS = {
    1: 'click_stereo_x1.05.ogg',
    2: 'click_stereo_x1.10.ogg',
    3: 'click_stereo_x1.15.ogg',
    4: 'click_stereo_x1.20.ogg',
    5: 'click_stereo_x1.25.ogg',
}

# 切割：6 个变调全随机
SHEAR_SOUNDS = [
    'shear_x0.90.ogg', 'shear_x0.95.ogg', 'shear_x1.00.ogg',
    'shear_x1.05.ogg', 'shear_x1.10.ogg', 'shear_x1.15.ogg',
]

# 轮回：6 个变调全随机
IDLE_SOUNDS = [
    'idle1_x0.90.ogg', 'idle1_x0.95.ogg', 'idle1_x1.00.ogg',
    'idle1_x1.05.ogg', 'idle1_x1.10.ogg', 'idle1_x1.15.ogg',
]


# 点数包：按分值分段，每段 2 个随机
ORB_SOUNDS = {
    1: ['orb_x0.90.ogg', 'orb_x0.95.ogg'],
    2: ['orb_x1.00.ogg', 'orb_x1.05.ogg'],
    3: ['orb_x1.10.ogg', 'orb_x1.15.ogg'],
}

# 按钮：固定 x1.00
CLICK_SOUND = 'click_stereo_x1.00.ogg'

# ===== 字体配置 =====
# 中文字体候选路径（按优先级排序，跨平台）
FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑粗体
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
    r"C:\Windows\Fonts\simkai.ttf",    # 楷体
    r"C:\Windows\Fonts\simli.ttf",     # 隶书
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    # Android (Termux)
    "/system/fonts/NotoSansCJK-Regular.ttc",
    "/system/fonts/DroidSansFallback.ttf",
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/NotoSansTC-Regular.otf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
]

# 粗体优先候选（会插在列表最前面）
FONT_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/system/fonts/NotoSansCJK-Bold.ttc",
    "/system/fonts/DroidSansFallback-Bold.ttf",
]


def get_cjk_font(size, bold=False):
    """跨平台中文字体加载。

    优先使用 FONT_CANDIDATES 中的系统字体，
    找不到则回退到 pygame 默认字体（可能缺中文）。

    Args:
        size: 字号
        bold: 是否优先粗体
    Returns:
        pygame.font.Font
    """
    import pygame.font

    candidates = list(FONT_CANDIDATES)
    if bold:
        # 粗体优先排在前面
        candidates = FONT_BOLD_CANDIDATES + candidates
    for path in candidates:
        if os.path.isfile(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                continue
    # 回退
    return pygame.font.Font(None, size)


def get_font(size, bold=False):
    """用户可直接修改此函数来自定义字体。"""
    return get_cjk_font(size, bold=bold)