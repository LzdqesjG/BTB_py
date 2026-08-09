"""房主端游戏服务器（红队）。所有计算逻辑在此运行。"""

import socket
import threading
import queue

import network_protocol as proto
from anti_cheat import AntiCheat


class GameServer:
    """房主端服务器，在独立线程中运行，处理蓝队客户端的连接和消息。"""

    def __init__(self, game, port=8447):
        self.game = game
        self.port = port
        self.client_sock = None
        self.client_addr = None
        self.running = False
        self.connected = False

        # 主线程处理的动作队列
        self.action_queue = queue.Queue()

        # 反作弊
        self.anti_cheat = AntiCheat(game)

        self._listen_sock = None
        self._thread = None

    def start(self):
        """启动服务器监听线程。"""
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind(('0.0.0.0', self.port))
        self._listen_sock.listen(1)
        self._listen_sock.settimeout(1.0)
        self.running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止服务器。"""
        self.running = False
        self.connected = False
        if self.client_sock:
            try:
                self.client_sock.close()
            except Exception:
                pass
        if self._listen_sock:
            try:
                self._listen_sock.close()
            except Exception:
                pass

    def _listen_loop(self):
        """监听线程：等待客户端连接，然后处理消息。"""
        while self.running:
            try:
                self.client_sock, self.client_addr = self._listen_sock.accept()
                self.client_sock.settimeout(None)
                self.connected = True
                self._handle_client()
            except socket.timeout:
                continue
            except OSError:
                break
            if self.connected:
                break  # 只接受一个客户端

    def _handle_client(self):
        """处理客户端消息。"""
        while self.running and self.connected:
            data = proto.recv_line(self.client_sock)
            if data is None:
                self.connected = False
                break
            cmd, params = proto.decode_msg(data)
            if cmd is None:
                continue

            if cmd == proto.JOIN:
                # 加入成功
                self._send(proto.OK)
            elif cmd == proto.GET_MAP:
                # 如果游戏已开始则发送完整状态，否则发送等待状态
                if self.game.state == 'playing':
                    self.send_state()
                else:
                    # 告诉客户端等待房主开始
                    self._send(proto.STATE_SYNC, '{"state":"client_wait"}')
            elif cmd == proto.BLUE_PLACE_NODE:
                # 蓝队放节点: parent_x&parent_y&x&y&range&strength
                self.action_queue.put(('place_node', params))
            elif cmd == proto.BLUE_MODIFY_BRANCH:
                # 蓝队修改树枝: node_x&node_y&target_strength
                self.action_queue.put(('modify_branch', params))
            elif cmd == proto.BLUE_NEXT_TURN:
                # 蓝队结束回合
                self.action_queue.put(('end_turn', params))

    def process_actions(self):
        """主线程每帧调用：处理蓝队的动作请求。"""
        # 如果游戏未开始，拒绝所有操作
        if self.game.state != 'playing':
            # 清空队列中的积压请求
            while not self.action_queue.empty():
                self.action_queue.get_nowait()
            return
        while not self.action_queue.empty():
            action, params = self.action_queue.get_nowait()
            if action == 'place_node':
                self._handle_place_node(params)
            elif action == 'modify_branch':
                self._handle_modify_branch(params)
            elif action == 'end_turn':
                self._handle_end_turn()

    def _handle_place_node(self, params):
        """处理蓝队放置节点请求。"""
        try:
            px, py = float(params[0]), float(params[1])
            x, y = float(params[2]), float(params[3])
            radius = int(params[4])
            strength = int(params[5])
        except (IndexError, ValueError):
            self._send(proto.ERROR)
            return

        game = self.game

        # --- 反作弊校验 ---
        ok, reason = self.anti_cheat.check_place_node(px, py, x, y, radius, strength)
        if not ok:
            self._send(proto.ERROR)
            return

        # 安全获取 Node 类并找到父节点（反作弊已验证父节点存在）
        Node = proto.resolve_module_class('Node')
        parent = self._find_blue_node(px, py)

        # 计算消耗
        strength_cost = max(0, strength - 1)
        range_cost = 0
        for i, r in enumerate([120, 160, 200, 240]):
            if r == radius:
                range_cost = i
                break
        total = strength_cost + range_cost

        # 创建节点
        new_node = Node('BLUE', x, y, strength, parent=parent)
        parent.children.append(new_node)
        game.nodes.append(new_node)
        game.points['BLUE'] -= total
        removed_ids, winner, weakened = game._resolve_crossing(new_node)
        game.has_created_this_turn = True

        # 音效
        from main import play_sfx
        play_sfx('tap', strength=new_node.strength)
        if removed_ids or weakened:
            play_sfx('shear')
        if winner:
            # 服务器处理蓝队动作：蓝队赢 → 红队（主机）输
            play_sfx('heavy_hit')

        # 广播动作给客户端（与主机 _try_create_node 一致）
        self._send(proto.ACT_ADD_NODE, 'BLUE', new_node.x, new_node.y,
                   new_node.strength, new_node.parent.id, new_node.id)
        if removed_ids:
            self._send(proto.ACT_REMOVE_NODES, *removed_ids)
        # 广播被削弱但未删除的节点
        for nid, new_str in weakened.items():
            self._send(proto.ACT_UPDATE_STRENGTH, nid, new_str)
        self._send(proto.ACT_SYNC_POINTS, game.points['RED'], game.points['BLUE'])
        self._send(proto.ACT_SYNC_PICKUPS, proto.serialize_pickups(game.pickups))
        self._send(proto.ACT_SYNC_TURN, game.current_team, str(game.has_created_this_turn), game.turn_count)
        if game.winner:
            self._send(proto.ACT_GAME_OVER, game.winner)

    def _handle_modify_branch(self, params):
        """处理蓝队修改树枝强度请求。"""
        try:
            nx, ny = float(params[0]), float(params[1])
            target_strength = int(params[2])
        except (IndexError, ValueError):
            self._send(proto.ERROR)
            return

        game = self.game

        # --- 反作弊校验 ---
        ok, reason = self.anti_cheat.check_modify_branch(nx, ny, target_strength)
        if not ok:
            self._send(proto.ERROR)
            return

        # 找到目标节点（反作弊已验证存在）
        target = self._find_blue_node(nx, ny, require_parent=True)

        # 计算消耗/返还
        diff = target_strength - target.strength
        if diff > 0:
            game.points['BLUE'] -= diff
        else:
            game.points['BLUE'] += -diff
        target.strength = target_strength

        # 广播动作
        self._send(proto.ACT_UPDATE_STRENGTH, target.id, target.strength)
        self._send(proto.ACT_SYNC_POINTS, game.points['RED'], game.points['BLUE'])

    def _handle_end_turn(self):
        """处理蓝队结束回合。"""
        game = self.game

        # --- 反作弊校验 ---
        ok, reason = self.anti_cheat.check_end_turn()
        if not ok:
            self._send(proto.ERROR)
            return
        game._end_turn()
        # 广播回合切换
        self._send(proto.ACT_SYNC_TURN, game.current_team, str(game.has_created_this_turn), game.turn_count)

    def send_state(self):
        """发送全量游戏状态给客户端。"""
        if not self.connected or not self.client_sock:
            return
        json_str = proto.serialize_state(self.game)
        self._send(proto.STATE_SYNC, json_str)

    def _send(self, cmd, *params):
        """发送消息给客户端。"""
        if not self.client_sock:
            return
        try:
            data = proto.encode_msg(cmd, *params)
            self.client_sock.sendall(data)
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.connected = False

    def _find_blue_node(self, x: float, y: float, require_parent: bool = False):
        """按坐标查找蓝队节点，容差 < 1 像素。"""
        for n in self.game.nodes:
            if n.team != 'BLUE':
                continue
            if require_parent and n.parent is None:
                continue
            if abs(n.x - x) < 1 and abs(n.y - y) < 1:
                return n
        return None
