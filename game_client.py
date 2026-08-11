"""客户端网络线程（蓝队）。连接房主服务器，同步游戏状态。"""

import socket
import threading
import queue

import network_protocol as proto


class GameClient:
    """蓝队客户端，在独立线程中接收服务器状态、发送蓝队动作。"""

    def __init__(self, game, host, port=8447):
        self.game = game
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.connected = False
        self.join_success = False

        # 主线程处理的状态更新队列
        self.state_queue = queue.Queue()

        self._thread = None

        # 发送/关闭与网络接收线程共享 sock，加锁保护
        self._lock = threading.Lock()

    def connect(self):
        """连接服务器，发送 JOIN。返回 (True, '') 或 (False, error_msg)。"""
        error_msg = ''
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self.connected = True
            self.running = True
        except ConnectionRefusedError:
            error_msg = f"连接被拒绝: {self.host}:{self.port} (服务器未启动或端口错误)"
            return False, error_msg
        except socket.timeout:
            error_msg = f"连接超时: {self.host}:{self.port} (服务器无响应)"
            return False, error_msg
        except OSError as e:
            error_msg = f"连接错误: {self.host}:{self.port} - {e}"
            return False, error_msg

        # 发送 JOIN
        self._send(proto.JOIN)
        # 等待 OK
        data = proto.recv_line(self.sock)
        if data is None:
            self.connected = False
            return False, "服务器断开连接 (未收到 OK)"
        cmd, _ = proto.decode_msg(data)
        if cmd != proto.OK:
            self.connected = False
            return False, f"服务器返回异常 (cmd={cmd})"
        self.join_success = True

        # 请求初始地图
        self._send(proto.GET_MAP)

        # 启动接收线程
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        return True, ''

    def stop(self):
        """停止客户端。"""
        self.running = False
        with self._lock:
            self.connected = False
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass

    def _recv_loop(self):
        """接收线程：循环读取服务器消息。"""
        while self.running and self.connected:
            data = proto.recv_line(self.sock)
            if data is None:
                with self._lock:
                    self.connected = False
                break
            cmd, params = proto.decode_msg(data)
            if cmd is None:
                continue
            # 将所有命令放入队列：(cmd, params) 元组
            self.state_queue.put((cmd, params))

    def process_updates(self):
        """主线程每帧调用：处理来自服务器的所有待处理动作。"""
        while not self.state_queue.empty():
            cmd, params = self.state_queue.get_nowait()
            if cmd == proto.STATE_SYNC:
                # 全量状态同步（向后兼容）
                if params:
                    proto.deserialize_state(self.game, params[0])
            elif cmd == proto.ERROR:
                # 服务器拒绝请求：提示客户端，不改变本地状态
                reason = params[0] if params else "请求被服务器拒绝"
                self.game.show_net_error(reason)
            else:
                # 增量动作
                self.game.apply_action(cmd, params)

    # ===== 发送蓝队动作 =====

    def send_place_node(self, parent_x, parent_y, x, y, radius, strength):
        """发送放置节点请求。"""
        self._send(proto.BLUE_PLACE_NODE,
                   int(parent_x), int(parent_y),
                   int(x), int(y),
                   int(radius), int(strength))

    def send_modify_branch(self, node_x, node_y, target_strength):
        """发送修改树枝强度请求。"""
        self._send(proto.BLUE_MODIFY_BRANCH,
                   int(node_x), int(node_y), int(target_strength))

    def send_end_turn(self):
        """发送结束回合请求。"""
        self._send(proto.BLUE_NEXT_TURN)

    def _send(self, cmd, *params):
        """发送消息给服务器（加锁防止与关闭操作并发导致竞态）。"""
        with self._lock:
            if not self.sock:
                return
            try:
                data = proto.encode_msg(cmd, *params)
                self.sock.sendall(data)
            except (ConnectionResetError, BrokenPipeError, OSError):
                self.connected = False
