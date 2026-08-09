"""网络协议常量与消息编解码。"""

import json
import sys


# ===== 模块解析辅助：避免 __main__ vs main 重复导入 =====

def resolve_module_class(name):
    """从正在运行的游戏主模块获取类，避免 `from main import X` 重新执行 main.py。
    
    当 `python main.py` 运行时，main.py 被加载为 `__main__` 模块。
    `from main import Node` 会导致 Python 将 main.py 重新执行为独立的 `main` 模块，
    其中 Node 类的 _next_id 从 0 重新开始，与 __main__.Node 的计数器冲突。
    """
    for mod_name in ('__main__', 'main'):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, name):
            return getattr(mod, name)
    raise RuntimeError(
        f"无法解析类 '{name}'：在 __main__ 和 main 模块中都未找到。"
        f"请确保 main.py 已将此类导入到全局作用域。"
    )

# ===== 客户端 → 服务器 (BLUE → RED) =====
JOIN = 100
GET_MAP = 110
BLUE_NEXT_TURN = 160
BLUE_PLACE_NODE = 170          # &parent_x&parent_y&x&y&radius&strength
BLUE_MODIFY_BRANCH = 180       # &node_x&node_y&target_strength

# ===== 服务器 → 客户端 (RED → BLUE) =====
OK = 200
ERROR = 400

# 动作消息（服务器广播给客户端，客户端如同本地操作一样执行）
INIT_GAME = 210                # &pickups_json —— 初始游戏状态（初始点数包）
ACT_ADD_NODE = 220             # &team&x&y&strength&parent_id&node_id
ACT_REMOVE_NODES = 230         # &id1,id2,id3...
ACT_UPDATE_STRENGTH = 240      # &node_id&new_strength
ACT_SYNC_TURN = 250            # &new_team&has_created&turn_count
ACT_SYNC_POINTS = 260          # &red_points&blue_points
ACT_SYNC_PICKUPS = 270         # &pickups_json
ACT_GAME_OVER = 280            # &winner
STATE_SYNC = 300               # &state_json —— 全量状态同步


# ===== 消息编解码 =====

def encode_msg(cmd, *params):
    parts = [str(cmd)] + [str(p) for p in params]
    return ('&'.join(parts) + '\n').encode('utf-8')


def decode_msg(data_bytes):
    text = data_bytes.decode('utf-8').strip()
    if not text:
        return None, []
    parts = text.split('&')
    try:
        cmd = int(parts[0])
    except ValueError:
        return None, []
    return cmd, parts[1:]


# 每个 socket 的残余数据缓存（防止粘包丢数据）
_recv_buffers = {}


def recv_line(sock):
    """从 socket 读取一行（以 \\n 结尾），返回 bytes。返回 None 表示连接断开。"""
    key = id(sock)
    if key not in _recv_buffers:
        _recv_buffers[key] = b''

    buf = _recv_buffers[key]
    while True:
        # 缓冲区里已有完整行 → 直接返回
        if b'\n' in buf:
            line, rest = buf.split(b'\n', 1)
            _recv_buffers[key] = rest
            return line
        # 否则继续从 socket 读
        try:
            chunk = sock.recv(4096)
        except (ConnectionResetError, OSError):
            _recv_buffers.pop(key, None)
            return None
        if not chunk:
            _recv_buffers.pop(key, None)
            return None
        buf += chunk
        if len(buf) > 65536:
            _recv_buffers[key] = b''
            return buf


# ===== 序列化辅助 =====

def serialize_pickups(pickups):
    """序列化点数包列表为 JSON。"""
    data = [{'x': p.x, 'y': p.y, 'value': p.value} for p in pickups]
    return json.dumps(data, separators=(',', ':'))


def deserialize_pickups(json_str):
    """从 JSON 反序列化点数包列表。"""
    PointPack = resolve_module_class('PointPack')
    data = json.loads(json_str)
    packs = []
    for pd in data:
        pack = PointPack(pd['x'], pd['y'], pd['value'])
        pack.spawn_time = 0
        packs.append(pack)
    return packs


def serialize_state(game):
    """序列化完整游戏状态为 JSON（供全量同步使用）。"""
    nodes_data = []
    for n in game.nodes:
        nodes_data.append({
            'id': n.id,
            'team': n.team,
            'x': n.x,
            'y': n.y,
            'strength': n.strength,
            'parent_id': n.parent.id if n.parent else None,
        })
    pickups_data = [{'x': p.x, 'y': p.y, 'value': p.value} for p in game.pickups]
    state = {
        'nodes': nodes_data,
        'pickups': pickups_data,
        'points_red': game.points['RED'],
        'points_blue': game.points['BLUE'],
        'current_team': game.current_team,
        'turn_count': game.turn_count,
        'has_created': game.has_created_this_turn,
        'winner': game.winner,
        'next_node_id': game.nodes[-1].id + 1 if game.nodes else 0,
    }
    return json.dumps(state, separators=(',', ':'))


def deserialize_state(game, json_str):
    """从 JSON 反序列化并替换游戏状态。返回 True 表示成功。"""
    Node = resolve_module_class('Node')
    PointPack = resolve_module_class('PointPack')
    data = json.loads(json_str)

    # 处理 client_wait 特殊状态
    if isinstance(data, dict) and data.get('state') == 'client_wait':
        game.state = 'client_wait'
        return True

    # 保存旧状态用于对比
    old_roots = {n.id for n in game.nodes if n.parent is None}

    # 重置节点和点数包
    game.nodes = []
    game.pickups = []

    # 重建所有节点
    nodes_by_id = {}
    for nd in data['nodes']:
        node = Node(nd['team'], nd['x'], nd['y'], nd['strength'])
        node.id = nd['id']
        nodes_by_id[node.id] = node
        game.nodes.append(node)

    # 建立父子关系
    for nd in data['nodes']:
        if nd['parent_id'] is not None:
            child = nodes_by_id[nd['id']]
            parent = nodes_by_id.get(nd['parent_id'])
            if parent is not None:
                # 安全校验：父子节点必须在同一个队伍
                if parent.team != child.team:
                    print(f"[ERROR] deserialize_state 跨队连线！child_id={child.id} team={child.team} "
                          f"parent_id={parent.id} team={parent.team}，已跳过")
                    continue
                child.parent = parent
                parent.children.append(child)

    # 恢复 Node._next_id
    existing_ids = [n.id for n in game.nodes]
    max_id = max(existing_ids) if existing_ids else 0
    Node._next_id = data.get('next_node_id', max_id + 1)

    # 重建点数包
    for pd in data['pickups']:
        pack = PointPack(pd['x'], pd['y'], pd['value'])
        pack.spawn_time = 0
        game.pickups.append(pack)

    # 恢复游戏状态
    game.points['RED'] = data['points_red']
    game.points['BLUE'] = data['points_blue']
    game.current_team = data['current_team']
    game.turn_count = data['turn_count']
    game.has_created_this_turn = data['has_created']
    game.winner = data.get('winner')

    # 清除残留交互状态
    game.dragging = False
    game.drag_node = None
    game.hovered_branch_child = None

    if game.winner:
        game.state = 'game_over'
    else:
        game.state = 'playing'

    return True
