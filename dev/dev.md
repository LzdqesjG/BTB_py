# Binary Tree Battle - 开发者文档

> 面向接手开发者的技术文档，涵盖架构、模块、协议、扩展点。

***

## 目录

- [快速开始](#快速开始)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [核心架构](#核心架构)
  - [数据模型](#数据模型)
  - [游戏状态机](#游戏状态机)
  - [主循环](#主循环)
- [模块详解](#模块详解)
  - [main.py - 主游戏逻辑](#mainpy---主游戏逻辑)
  - [constant.py - 常量与配置](#constantpy---常量与配置)
  - [network_protocol.py - 网络协议](#network_protocolpy---网络协议)
  - [game_server.py - 服务端](#game_serverpy---服务端)
  - [game_client.py - 客户端](#game_clientpy---客户端)
  - [anti_cheat.py - 反作弊](#anti_cheatpy---反作弊)
  - [AI/aithink.py - AI 系统](#aiaithinkpy---ai-系统)
  - [replay.py - 回放系统](#replaypy---回放系统)
- [联机架构](#联机架构)
  - [网络拓扑](#网络拓扑)
  - [协议消息流](#协议消息流)
  - [状态同步策略](#状态同步策略)
- [切割与胜负结算](#切割与胜负结算)
- [扩展指南](#扩展指南)
  - [添加新游戏机制](#添加新游戏机制)
  - [修改 AI 行为](#修改-ai-行为)
  - [增加新的网络消息](#增加新的网络消息)
  - [添加新的游戏状态](#添加新的游戏状态)
- [调试模式](#调试模式)
- [已知限制与改进方向](#已知限制与改进方向)
- [许可协议](#许可协议)

***

## 快速开始

### 环境要求

- Python **3.9+**（开发使用 3.11.9）
- Pygame **2.6.1**

### 安装与运行

```bash
# 克隆项目
git clone https://github.com/LzdqesjG/BTB_py.git
cd BTB_py

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt

# 启动游戏
python main.py
```

### 单文件开发模式

整个项目是**单文件入口模式**：`python main.py` 直接启动即可。`main.py` 在运行时被 Python 加载为 `__main__` 模块，其余模块通过 `import` 引用。调试和开发时直接修改源码后重新运行即可。

***

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3 |
| 图形渲染 | Pygame (SDL2) |
| 音效 | Pygame mixer (OGG) |
| 网络 | TCP Socket（原生 `socket` 模块） |
| 序列化 | 自定义 `&` 分隔文本协议 + JSON |
| 持久化 | JSONL 文件（回放系统） |
| 字体 | 系统自带中文字体（跨平台候选） |

***

## 项目结构

```
BTB_py/
├── main.py                  # 游戏主入口、Node/Game 类、全量绘制和事件处理
├── constant.py              # 全局常量、颜色、音效配置、字体加载
├── network_protocol.py      # 网络消息编解码、状态序列化/反序列化
├── game_server.py           # 房主端 TCP 服务器（红方）
├── game_client.py           # 客户端 TCP 连接（蓝方）
├── anti_cheat.py            # 服务端反作弊校验
├── replay.py                # 对局回放录制器
├── requirements.txt         # Python 依赖
├── LICENCE                  # GPLv3 许可证全文
├── .gitignore               # Git 忽略规则
├── debug                    # 调试模式配置文件（存在即开启调试）
│
├── assets/
│   ├── sounds/              # OGG 音效文件（点击、切割、回合切换等）
│   └── ai_default.json      # AI 默认参数（不可修改的初始版本）
│
├── AI/
│   ├── aithink.py           # AI 决策引擎
│   ├── ai.json              # AI 运行时参数（为空时自动从 ai_default.json 复制）
│   └── ai.json.bak          # AI 参数备份
│
└── replays/                 # 对局回放文件（*.bpr, JSONL 格式）
```

### 模块职责速查

| 文件 | 职责 | 依赖 |
|------|------|------|
| `main.py` | 游戏主入口；定义 `Node`、`PointPack`、`Game` 等核心类；处理全部 UI 渲染和事件 | `constant`, `replay`, `AI.aithink`(运行时按需) |
| `constant.py` | 所有可配置常量、颜色、字体、音效路径 | 无（仅标准库） |
| `network_protocol.py` | 消息枚举、编解码、粘包处理、状态序列化 | `main`（通过 `resolve_module_class` 动态引用） |
| `game_server.py` | TCP 监听、蓝队动作接收、广播状态 | `network_protocol`, `anti_cheat` |
| `game_client.py` | TCP 连接、状态接收、操作发送 | `network_protocol` |
| `anti_cheat.py` | 服务端验证：回合、坐标、点数、频率 | `constant` |
| `replay.py` | JSONL 格式对局记录、保存到 `replays/` | 无（仅标准库） |
| `AI/aithink.py` | 多策略 AI 决策引擎 | `constant`, `assets/ai_default.json` |
| `AI/ai.json` | AI 运行时参数（可热修改） | 被 `aithink.py` 读取 |
| `assets/ai_default.json` | AI 默认参数模板 | 被 `aithink.py` 复制 |

***

## 核心架构

### 数据模型

```
Node (节点)
├── id: int                    # 全局自增 ID（Node._next_id）
├── team: 'RED' | 'BLUE'      # 所属队伍
├── x, y: float               # 屏幕坐标
├── strength: int (1~5)       # 节点强度
├── parent: Node | None       # 父节点（None = 根节点）
├── children: list[Node]      # 子节点列表（最多 MAX_CHILDREN=2 个）
│
├── can_have_child() -> bool  # 是否还能创建子节点
├── contains_point(px, py)    # 点击检测
└── draw(surface, emphasized) # 渲染（含脉冲强调动画）

PointPack (点数包)
├── x, y: float               # 位置
├── value: int (1|2|3)        # 分值
├── radius: int               # 碰撞半径
├── spawn_time: int           # 出生时间（用于出生缩放动画）
└── pulse: float              # 呼吸动画相位

Game (游戏主状态)
├── state: str                # 当前状态（见状态机）
├── nodes: list[Node]         # 所有节点
├── points: dict              # {'RED': int, 'BLUE': int}
├── current_team: 'RED'|'BLUE'
├── turn_count: int           # 回合计数
├── winner: str|None          # 胜者
│
├── 网络相关
│   ├── network_mode: None|'host'|'client'
│   ├── my_team: None|'RED'|'BLUE'
│   ├── net_server: GameServer|None
│   └── net_client: GameClient|None
│
├── AI 相关
│   ├── _ai_mode: bool
│   └── _ai_team: 'RED'|'BLUE'
│
├── 交互状态
│   ├── dragging: bool        # 是否正在拖拽
│   ├── drag_node: Node|None  # 拖拽中的父节点
│   ├── temp_strength: int    # 拖拽时的临时强度
│   ├── temp_range_index: int # 拖拽时的临时范围索引
│   ├── has_created_this_turn: bool  # 本回合是否已创建节点
│   └── hovered_branch_child: Node|None  # 鼠标悬停的树枝
│
└── replay: ReplayRecorder    # 回放记录器
```

### 游戏状态机

```
STATE_MENU ───────────────────────────────────────┐
    │  [单人] → STATE_PLAYING                      │
    │  [AI对战] → STATE_PLAYING (with _ai_mode)    │
    │  [创建房间] → STATE_HOST_WAIT                 │
    │        └─ [开始游戏] → STATE_PLAYING          │
    │  [加入房间] → STATE_JOIN_INPUT                │
    │        └─ Enter → STATE_CLIENT_WAIT           │
    │              └─ [房主开始信号] → STATE_PLAYING │
    │  [回放] → STATE_REPLAY_SELECT                 │
    │        └─ Enter → STATE_REPLAY_PLAY           │
    └──────────────────────────────────────────────┘

STATE_PLAYING ── [穿过对方根节点] → STATE_GAME_OVER
STATE_PLAYING ── [断线] → STATE_MENU (go_menu)
STATE_GAME_OVER ── [返回菜单] → STATE_MENU
任何非菜单状态 ── [退出按钮] → STATE_MENU
```

状态通过 `Game.state` 字符串控制，所有 `draw_*` 和 `handle_*_event` 方法由 `Game.draw()` 和 `Game.handle_event()` 分发。

### 主循环

```python
# main.py: main()
while True:
    for event in pygame.event.get():
        game.handle_event(event)    # 事件分发（按 state 路由）
    game.update()                   # 帧更新（碰撞检测、AI、网络处理）
    game.draw(screen)               # 按 state 渲染对应界面
    pygame.display.flip()
    clock.tick(60)                  # 固定 60 FPS
```

**`update()` 的执行顺序**：
1. 处理网络消息（服务端 `process_actions()` 或客户端 `process_updates()`）
2. 更新点数包动画（`pack.update()`）
3. 检测点数包碰撞（仅非客户端模式——客户端由服务端同步）
4. 更新悬停树枝检测（`_update_hovered_branch()`）
5. AI 自动操作（`_ai_update()`）

***

## 模块详解

### main.py - 主游戏逻辑

**核心类**：

| 类 | 行数 | 说明 |
|----|------|------|
| `Node` | L197-L243 | 树节点，含渲染、点击检测 |
| `PointPack` | L246-L288 | 点数包，含出生动画 |
| `ScorePopup` | L291-L313 | 拾取得分浮动文字 |
| `Game` | L316-L2594 | **核心类**，包含全部游戏逻辑 |

**`Game` 类的方法分组**：

| 分组 | 方法 | 说明 |
|------|------|------|
| 生命周期 | `reset()`, `start_game()`, `go_menu()` | 初始化/重置/返回菜单 |
| 联机 | `apply_action()`, `_broadcast()`, `_broadcast_state_changed()` | 动作同步与广播 |
| 碰撞 | `_segments_intersect()`, `_segment_intersects_circle()`, `_resolve_crossing()` | 线段相交/圆相交/切割结算 |
| 节点操作 | `_try_create_node()`, `_remove_nodes()`, `_collect_subtree()` | 创建/删除/收集子树 |
| 点数包 | `_spawn_pickup()`, `_init_pickups()`, `_check_pickup_collisions()` | 生成/初始化/碰撞检测 |
| 交互 | `_update_hovered_branch()`, `_handle_wheel()` | 树枝悬停检测/滚轮处理 |
| AI | `_ai_update()` | AI 回合操作 |
| 渲染 | `draw_menu()`, `draw_playing()`, `draw_game_over()` 等 | 各状态界面绘制 |
| 事件 | `handle_event()`, `_handle_menu_event()`, `_handle_playing_event()` 等 | 按状态分发事件 |
| 回放 | `_start_replay()`, `_replay_step_forward()` 等 | 回放播放与控制 |

**设计要点**：
- `resolve_module_class()`（`network_protocol.py` L9-L23）：避免 `from main import Node` 导致 `main.py` 被重复执行为独立模块。通过 `sys.modules` 动态获取 `__main__` 中已加载的类。
- 所有坐标运算使用 `float`，渲染时转换为 `int`。
- 线段相交判断使用叉积方向法（`_orient`），严格排除端点重合情况。

### constant.py - 常量与配置

所有可调参数集中在此文件，开发者可以通过修改常量来调整游戏平衡：

- `VERSION`：版本号字符串
- `SCREEN_WIDTH/HEIGHT`：窗口尺寸（1300×700）
- `NODE_RADIUS`：节点圆形半径（18px）
- `INITIAL_POINTS`：初始点数（10）
- `MIN_STRENGTH/MAX_STRENGTH`：强度范围（1~5）
- `MAX_CHILDREN`：每个节点最大子节点数（2）
- `RANGE_OPTIONS`：可选范围半径列表 `[120, 160, 200, 240]`
- `PICKUP_VALUES`：点数包分值列表 `[1, 2, 3]`
- `FONT_CANDIDATES`：跨平台字体候选路径（Windows/macOS/Linux/Android）
- `SOUND_DIR` 和音效映射：所有音效文件的对应关系

### network_protocol.py - 网络协议

**消息格式**：

```
<cmd>&<param1>&<param2>&...\n
```

| 方向 | 命令 | 值 | 参数 |
|------|------|----|------|
| C→S | JOIN | 100 | 无 |
| C→S | GET_MAP | 110 | 无 |
| C→S | BLUE_NEXT_TURN | 160 | 无 |
| C→S | BLUE_PLACE_NODE | 170 | `parent_x&parent_y&x&y&radius&strength` |
| C→S | BLUE_MODIFY_BRANCH | 180 | `node_x&node_y&target_strength` |
| S→C | OK | 200 | 无 |
| S→C | ERROR | 400 | 无 |
| S→C | STATE_SYNC | 300 | `json_state`（全量同步） |
| S→C | ACT_ADD_NODE | 220 | `team&x&y&strength&parent_id&node_id` |
| S→C | ACT_REMOVE_NODES | 230 | `id1&id2&...` |
| S→C | ACT_UPDATE_STRENGTH | 240 | `node_id&new_strength` |
| S→C | ACT_SYNC_TURN | 250 | `new_team&has_created&turn_count` |
| S→C | ACT_SYNC_POINTS | 260 | `red_points&blue_points` |
| S→C | ACT_SYNC_PICKUPS | 270 | `pickups_json` |
| S→C | ACT_GAME_OVER | 280 | `winner` |

**粘包处理**：`recv_line()` 使用全局字典 `_recv_buffers` 按 socket ID 缓存不完整数据，确保每次返回完整的一行。

**全量同步**：`serialize_state()` 将整个游戏状态（节点树、点数包、回合信息）序列化为 JSON，用于客户端首次连接或断线重连。

### game_server.py - 服务端

**在独立线程中运行**，通过 `threading.Thread(target=_listen_loop, daemon=True)` 启动。

工作流程：
1. `start()` → 绑定 `0.0.0.0:<port>`，启动监听线程
2. 接受单个客户端连接后，在 `_handle_client()` 中循环读取消息
3. 收到蓝队动作 → 放入 `action_queue`（线程安全队列）
4. 主线程每帧调用 `process_actions()` → 从队列取出动作，先通过 `AntiCheat` 校验，再执行游戏逻辑
5. 每个操作执行后立即广播对应的 ACT_* 消息给客户端

**关键设计**：服务端不在网络线程中直接修改游戏状态，而是通过队列解耦，确保所有游戏状态修改都在主线程中完成。

### game_client.py - 客户端

**同样在独立线程中运行**：
1. `connect()` → TCP 连接 → 发送 JOIN → 等待 OK → 发送 GET_MAP → 启动接收线程
2. 接收线程持续读取服务器消息，放入 `state_queue`
3. 主线程每帧调用 `process_updates()` → 批量处理队列中的消息 → 调用 `game.apply_action()` 同步状态
4. 用户操作时调用 `send_place_node()`, `send_modify_branch()`, `send_end_turn()` 发送请求

### anti_cheat.py - 反作弊

供服务端在收到蓝队每个动作时调用。验证内容：

| 校验项 | 说明 |
|--------|------|
| 游戏状态 | 必须是 `playing` 状态 |
| 回合 | 必须是蓝队回合，且本回合未创建过节点 |
| 参数合法性 | strength ∈ [1,5], radius ∈ RANGE_OPTIONS |
| 坐标合法性 | 新节点必须在屏幕范围内，不能与已有节点过近 |
| 父节点合法性 | 必须是蓝队节点、有子节点名额 |
| 范围限制 | 新节点必须在父节点的范围圈内 |
| 点数校验 | 总消耗必须不超过蓝队当前点数 |
| 频率限制 | 每秒不超过 10 个动作 |

累计违规超过阈值可触发踢出（目前计数值保留，踢出逻辑预留）。

### AI/aithink.py - AI 系统

**入口**：`AIThinker(game).decide_action()` → 返回动作字典或 `None`。

**决策优先级**（从高到低）：

```
1. 根危预检：敌方接近己方根时跳过拾取和扩张
2. 强制拾取点数包（不危时）
3. 尝试穿过敌方根（致命一击）
4. 主动切割附近敌方节点
5. 警戒区拦截（敌方进入预设区域）
6. 根节点紧急防御
7. 调节树枝强度（概率触发）
8. 常规候选评分 → 加权随机选择
9. 绝望模式：放宽间距限制强制放置
10. 结束回合
```

**评分系统**（`_score()`）：
```
总分 = 进攻分 × greediness
     + 防守分 × defensiveness
     + 切割分
     + 点数包引力分
     + 强度加分
     + 随机噪声
```

**可配置参数**：全部通过 `assets/ai_default.json` 配置，运行时从 `AI/ai.json` 加载。修改 `ai.json` 后无需重启游戏即可生效（每局初始化时重新读取）。

相关文件：
- `AI/ai.json`：运行时配置，为空时自动从 `ai_default.json` 复制
- `assets/ai_default.json`：出厂默认配置，含每个参数的注释说明

### replay.py - 回放系统

**格式**：JSONL（每行一个 JSON 对象），文件扩展名 `.bpr`。

**记录的操作类型**：

| type | 参数 | 说明 |
|------|------|------|
| `game_info` | `mode, role, team, ...` | 对局元数据（首行） |
| `init` | `red_points, blue_points` | 初始状态 |
| `spawn_pack` | `x, y, value` | 点数包生成 |
| `place_node` | `team, parent_id, node_id, x, y, strength, range` | 放置节点 |
| `modify_branch` | `team, node_id, old_strength, new_strength` | 修改树枝强度 |
| `remove_nodes` | `ids` | 批量删除节点 |
| `weaken_node` | `node_id, new_strength` | 节点被削弱但未删除 |
| `pickup` | `team, value, x, y` | 拾取点数包 |
| `end_turn` | `team` | 结束回合 |
| `game_over` | `winner` | 游戏结束 |

**保存时机**：`Game.update()` 检测到 `STATE_GAME_OVER` 时调用 `replay.save()`，只保存一次（`_saved` 标志防重复）。

**回放控制**：支持步进（←/→）、自动播放（空格）、进入残局（"进入游戏"按钮，可从任意步骤开始继续战斗）。

***

## 联机架构

### 网络拓扑

```
┌─────────────────────┐          ┌─────────────────────┐
│   红方 (Server)      │  TCP    │   蓝方 (Client)      │
│                     │◄────────►│                     │
│  所有逻辑计算        │  8447   │  仅渲染+发送操作      │
│  反作弊校验          │         │  接收状态同步        │
│  广播状态            │         │                     │
└─────────────────────┘          └─────────────────────┘
```

### 协议消息流

```
Client                           Server
  │                                │
  ├─── JOIN ──────────────────────►│
  │◄── OK ─────────────────────────┤
  ├─── GET_MAP ───────────────────►│
  │◄── STATE_SYNC (JSON) ──────────┤  全量初始状态
  │                                │
  │  === 房主点击"开始游戏" ===      │
  │◄── STATE_SYNC (JSON) ──────────┤
  │                                │
  │  === 蓝队回合 ===               │
  ├─── BLUE_PLACE_NODE ───────────►│  参数：parent_x/y, x/y, radius, strength
  │◄── ACT_ADD_NODE ───────────────┤
  │◄── ACT_REMOVE_NODES ───────────┤  (如有切割)
  │◄── ACT_SYNC_POINTS ────────────┤
  │◄── ACT_SYNC_TURN ──────────────┤
  │                                │
  ├─── BLUE_MODIFY_BRANCH ────────►│
  │◄── ACT_UPDATE_STRENGTH ────────┤
  │◄── ACT_SYNC_POINTS ────────────┤
  │                                │
  ├─── BLUE_NEXT_TURN ────────────►│
  │◄── ACT_SYNC_TURN ──────────────┤
  │                                │
  │  === 红队回合 ===               │
  │◄── ACT_ADD_NODE ───────────────┤  红队操作同样广播
  │◄── ACT_SYNC_* ────────────────┤
  │                                │
  │◄── ACT_GAME_OVER ──────────────┤  游戏结束
```

### 状态同步策略

1. **增量同步为主**：每个操作（放置节点、修改树枝、结束回合）产生一个或多个 ACT_* 消息
2. **全量同步兜底**：客户端连接时、房主开始游戏时发送 `STATE_SYNC` 全量 JSON
3. **点数包碰撞**：仅服务端检测，碰撞后通过 `ACT_SYNC_PICKUPS` 同步
4. **切割结算**：完全在服务端执行，通过 `ACT_REMOVE_NODES` + `ACT_UPDATE_STRENGTH` 广播结果
5. **client_wait 状态**：服务端在游戏未开始时返回 `{"state":"client_wait"}`，客户端进入等待界面

***

## 切割与胜负结算

**全部在服务端执行（`Game._resolve_crossing()`）**。

### 判断顺序

1. **穿过对方节点圆**（`_segment_intersects_circle`）
   - 是根节点 → 攻击方立即获胜，设置 `game.winner`，状态变为 `STATE_GAME_OVER`
   - 是普通节点 → 加入切割目标列表

2. **穿过对方树枝**（`_segments_intersect`）
   - 排除共享端点的情况（同一节点延伸的两个分支不算穿过）
   - 加入切割目标列表

### 结算规则

对每个被切的节点：`victim.strength -= attacker.strength`

- ≤ 0 → 该节点及其整棵子树被删除（`_collect_subtree` + `_remove_nodes`）
- > 0 → 保留，记录为 `weakened`

### 回放记录

每次切割操作记录为 `remove_nodes`（已删除）或 `weaken_node`（被削弱但存活），确保回放能精确还原每一步的棋盘状态。

---

## 扩展指南

### 添加新游戏机制

1. **新增常量** → 在 `constant.py` 中添加
2. **新增状态字段** → 在 `Game.__init__()` 中添加，`Game.reset()` 中重置
3. **新增渲染** → 在 `Game.draw_playing()` 中添加绘制逻辑
4. **新增事件** → 在 `Game._handle_playing_event()` 中添加处理
5. **联机同步** → 确保服务器执行后通过 `_broadcast()` 或 `_broadcast_state_changed()` 发送给客户端
6. **反作弊** → 在 `anti_cheat.py` 中添加对应的校验方法
7. **回放** → 在 `replay.py` 中使用 `game.replay.record()` 记录，在 `_apply_replay_action()` 中添加应用逻辑

### 修改 AI 行为

1. **快速调参**：直接修改 `AI/ai.json`，下次 AI 对局即生效
2. **修改策略**：在 `AI/aithink.py` 中修改 `decide_action()` 的决策优先级或添加新规则
3. **修改评分**：在 `_score()` 中添加新的评分维度
4. **添加参数**：在 `ai_default.json` 中添加新参数（含 `_note` 注释），在 `AIThinker.__init__()` 中读取

### 增加新的网络消息

1. 在 `network_protocol.py` 中添加命令码常量
2. 在 `game_server.py` 的 `_handle_client()` 中添加消息处理分支
3. 在 `game_client.py` 的 `process_updates()` 中添加接收处理
4. 在 `Game.apply_action()` 中添加对应的动作执行逻辑
5. 在 `anti_cheat.py` 中添加对应的校验方法（如果是客户端发起的操作）

### 添加新的游戏状态

1. 在 `constant.py` 中添加 `STATE_*` 常量
2. 在 `Game.__init__()` 中初始化相关属性
3. 在 `Game.handle_event()` 中添加 `elif` 分支
4. 在 `Game.draw()` 中添加 `elif` 分支
5. 实现对应的 `_handle_*_event()` 和 `draw_*()` 方法
6. 在 `Game.go_menu()` 中确保能正确退出到菜单

***

## 调试模式

在项目根目录创建名为 `debug` 的文件（无扩展名），游戏启动时自动激活调试模式。

### debug 文件格式

每行一个调试选项，`#` 开头为注释：

```
# 示例调试配置
SOUNDS_DISABLED
SHOW_DEBUG_INFO
your_option
```

### 调试功能

- 启动时打印 `[DEBUG] 已激活的调试选项: ...`
- 左下角显示调试日志（`add_debug_log()` 发送的消息）
- 音效播放时附带调试日志
- 回放保存时显示文件路径

### 自定义调试选项

在代码中使用：
```python
if "YOUR_FLAG" in DEBUGS:
    # 调试代码
```

***

## 已知限制与改进方向

| 限制 | 说明 | 改进方向 |
|------|------|----------|
| 单客户端 | 服务端仅支持一个客户端连接 | 增加房间列表，支持多房间 |
| TCP 协议 | 文本协议简单但扩展性有限 | 考虑迁移到二进制协议或使用现成的消息库 |
| 无认证 | 客户端无需认证即可连接 | 添加简易密码或 token 认证 |
| 音效硬编码 | 音效文件路径和映射全部在 constant.py 中 | 可使用配置文件管理 |
| AI 单模型 | AI 固定使用一套参数 | 增加多难度等级或多套参数预设 |
| 设置按钮预留 | 菜单上"设置"按钮尚无功能 | 可添加音量、全屏、键位等设置 |

***

## 许可协议

本项目基于 **GNU General Public License v3.0 (GPLv3)** 开源。

- 你可以自由使用、修改和分发本项目的源代码
- 修改后的版本必须同样以 GPLv3 协议开源
- 分发时必须包含完整的许可证文本和版权声明
- 本项目不提供任何担保

完整许可证文本见 [LICENCE](../LICENCE) 文件。

***

*Binary Tree Battle  --by Lzdqesj*
