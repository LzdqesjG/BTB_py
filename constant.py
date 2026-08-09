# 常量
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
DEFAULT_PORT = 8447