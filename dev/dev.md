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
  - [config.json - 配置文件](#configjson---配置文件)
  - [network_protocol.py - 网络协议](#network_protocolpy---网络协议)
  - [game_server.py - 服务端](#game_serverpy---服务端)
  - [game_client.py - 客户端](#game_clientpy---客户端)
  - [anti_cheat.py - 反作弊](#anti_cheatpy---反作弊)
  - [AI/aithink4.py - AI 系统](#aiaithink4py---ai-系统)
  - [AI 自动学习](#ai-自动学习17)
  - [AI 托管](#ai-托管30)
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
- [日志系统](#日志系统)
- [CI/CD](#cicd)
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
├── constant.py              # 全局常量、颜色、音效配置、字体加载（从 config.json 读取）
├── config.json              # 游戏基础配置（显示、玩法、AI 思考时间、点数包、端口；gitignore 排除）
├── config.default.json      # 配置默认模板（提交到仓库，config.json 缺失时自动复制）
├── network_protocol.py      # 网络消息编解码、状态序列化/反序列化
├── game_server.py           # 房主端 TCP 服务器（红方，线程安全）
├── game_client.py           # 客户端 TCP 连接（蓝方，线程安全）
├── anti_cheat.py            # 服务端反作弊校验
├── replay.py                # 对局回放录制器
├── requirements.txt         # Python 依赖
├── LICENCE                  # GPLv3 许可证全文
├── .gitignore               # Git 忽略规则
├── debug                    # 调试模式配置文件（存在即开启调试）
├── logs/                    # 运行日志（按启动时间命名，如 20260810_143025a.log）
│
├── assets/
│   ├── sounds/              # OGG 音效文件（点击、切割、回合切换等）
│   └── ai_default.json      # AI 默认参数（不可修改的初始版本）
│
├── AI/
│   ├── aithink4.py          # AI 决策引擎（当前生效版本，含自动学习基础设施）
│   ├── aithink3.py          # AI 旧版（被 aithink4 小幅调参迭代而来）
│   ├── aithink2.py          # AI 旧版（早期移植版本）
│   ├── aithink.py           # AI 旧版（最早移植版本）
│   ├── ai.json              # AI 全部 30 个权重参数（运行时加载，自动学习会更新）
│   ├── learn.json           # AI 学习数据（对局统计/对手打法，gitignore 排除，运行时生成）
│   └── backup/              # ai.json 按日期自动备份（gitignore 排除）
│
├── dev/
│   ├── dev.md               # 本文档
│   └── rl_evolve.py         # AI 自对弈训练器（变异权重锦标赛，择优写回 ai.json）
│
├── .github/
│   └── workflows/
│       ├── release-cd.yml   # GitHub Actions：打 tag 自动发布 ZIP Release
│       └── issues-export.yml# GitHub Actions：Issue 变更时自动导出到 ISSUES.md
│
└── replays/                 # 对局回放文件（*.bpr, JSONL 格式）
```

### 模块职责速查

| 文件 | 职责 | 依赖 |
|------|------|------|
| `main.py` | 游戏主入口；定义 `Node`、`PointPack`、`Game` 等核心类；处理全部 UI 渲染和事件 | `constant`, `replay`, `AI.aithink4` |
| `constant.py` | 所有可配置常量、颜色、字体、音效路径；模块加载时读取 `config.json` | 标准库 `json/os` |
| `config.json` | 游戏基础参数配置（AI 决策参数除外） | 被 `constant.py` 读取 |
| `network_protocol.py` | 消息枚举、编解码、粘包处理、状态序列化 | `main`（通过 `resolve_module_class` 动态引用） |
| `game_server.py` | TCP 监听、蓝队动作接收、广播状态 | `network_protocol`, `anti_cheat` |
| `game_client.py` | TCP 连接、状态接收、操作发送 | `network_protocol` |
| `anti_cheat.py` | 服务端验证：回合、坐标、点数、频率、禁止降级 | `constant` |
| `replay.py` | JSONL 格式对局记录、保存到 `replays/` | 无（仅标准库） |
| `AI/aithink4.py` | 多策略 AI 决策引擎（当前生效） | `constant`, `assets/ai_default.json` |
| `AI/ai.json` | AI 运行时参数（可热修改） | 被 `aithink4.py` 读取 |
| `assets/ai_default.json` | AI 默认参数模板 | 被 `aithink4.py` 复制 |

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
│   ├── _ai_team: 'RED'|'BLUE'
│   ├── _ai_think_timer: int          # AI 思考计时器（帧）
│   ├── _AI_THINK_DELAY: int          # AI 思考延迟（从 config.json 读取，默认 90 帧）
│   ├── _ai_memory: dict              # AI 跨回合记忆（落点记忆/强化计数）
│   ├── _ai_post_reinforce: int       # 本回合放置后已强化次数（最多 2 次）
│   └── _ai_debug_candidates: list    # AI 候选可视化数据（已注释停用）
│
├── 交互状态
│   ├── dragging: bool        # 是否正在拖拽
│   ├── drag_node: Node|None  # 拖拽中的父节点
│   ├── temp_strength: int    # 拖拽时的临时强度
│   ├── temp_range_index: int # 拖拽时的临时范围索引
│   ├── has_created_this_turn: bool  # 本回合是否已创建节点
│   ├── hovered_branch_child: Node|None  # 鼠标悬停的树枝
│   │
│   ├── 树枝修改模式（右键进入）
│   │   ├── _branch_modify_mode: bool
│   │   ├── _branch_modify_target: Node|None
│   │   └── _branch_modify_strength: int   # UI 中暂定的新强度（只能 > 原强度）
│   └── _idle_played_key: tuple|None   # 已播放过回合 idle 音效的标识
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
| `Node` | L229-L277 | 树节点，含渲染、点击检测 |
| `PointPack` | L278-L322 | 点数包，含出生动画 |
| `ScorePopup` | L323-L347 | 拾取得分浮动文字 |
| `Game` | L348-L2815 | **核心类**，包含全部游戏逻辑 |
| `main()` | L2817+ | 程序入口，主循环 |

**`Game` 类的方法分组**：

| 分组 | 方法 | 说明 |
|------|------|------|
| 生命周期 | `reset()`, `start_game()`, `go_menu()` | 初始化/重置/返回菜单 |
| 联机 | `apply_action()`, `_broadcast()`, `_broadcast_state_changed()` | 动作同步与广播 |
| 碰撞 | `_segments_intersect()`, `_segment_intersects_circle()`, `_resolve_crossing()` | 线段相交/圆相交/切割结算 |
| 节点操作 | `_try_create_node()`, `_remove_nodes()`, `_collect_subtree()` | 创建/删除/收集子树 |
| 点数包 | `_spawn_pickup()`, `_init_pickups()`, `_check_pickup_collisions()` | 生成/初始化/碰撞检测 |
| 交互 | `_update_hovered_branch()`, `_handle_wheel()` | 树枝悬停检测/滚轮处理 |
| 树枝修改 | `_enter_branch_modify()`, `_handle_branch_modify_event()`, `_adjust_branch_modify_strength()`, `_confirm_branch_modify()`, `_draw_branch_modify_overlay()` | 右键修改模式：进入/事件/调强度/确认/绘制 |
| 音效 | `update()` 中 idle 检测 | 己方回合开始时播放随机 idle 音调（`_idle_played_key` 去重） |
| AI | `_ai_update()` | AI 回合操作（含放置后强化） |
| 渲染 | `draw_menu()`, `draw_playing()`, `draw_game_over()` 等 | 各状态界面绘制 |
| 事件 | `handle_event()`, `_handle_menu_event()`, `_handle_playing_event()` 等 | 按状态分发事件 |
| 回放 | `_start_replay()`, `_replay_step_forward()` 等 | 回放播放与控制 |

**设计要点**：
- `resolve_module_class()`（`network_protocol.py` L9-L23）：避免 `from main import Node` 导致 `main.py` 被重复执行为独立模块。通过 `sys.modules` 动态获取 `__main__` 中已加载的类。
- 所有坐标运算使用 `float`，渲染时转换为 `int`。
- 线段相交判断使用叉积方向法（`_orient`），严格排除端点重合情况。

### constant.py - 常量与配置

所有可调参数集中在此文件，开发者可以通过修改常量来调整游戏平衡。**大部分值可在模块加载时被 `config.json` 覆盖**（`_load_config()` + `_config.get(...)` 模式）：

- `_load_config()`：读取项目根目录 `config.json`，不存在则返回空 dict（全部使用默认值）
- `SCREEN_WIDTH/HEIGHT`：窗口尺寸（1300×700，可配置）
- `FPS`：帧率（60，可配置）
- `NODE_RADIUS`：节点圆形半径（18px）
- `INITIAL_POINTS`：初始点数（10，可配置）
- `MIN_STRENGTH/MAX_STRENGTH`：强度范围（1~5，可配置）
- `MAX_CHILDREN`：每个节点最大子节点数（2，可配置）
- `RANGE_OPTIONS`：可选范围半径列表 `[120, 160, 200, 240]`
- `AI_THINK_DELAY`：AI 思考延迟帧数（90，可配置）
- `PICKUP_VALUES`：点数包分值列表 `[1, 2, 3]`（可配置）
- `DEFAULT_PORT`：联机默认端口（8447，可配置）
- `FONT_CANDIDATES`：跨平台字体候选路径（Windows/macOS/Linux/Android）
- `SOUND_DIR` 和音效映射：所有音效文件的对应关系

### config.json - 配置文件

位于项目根目录，格式：

```json
{
  "display":  { "width": 1300, "height": 700, "fps": 60 },
  "gameplay": { "initial_points": 10, "min_strength": 1, "max_strength": 5, "max_children": 2 },
  "ai":       { "think_delay_frames": 90 },
  "pickup":   { "radius": 13, "min_root_distance": 160, "values": [1, 2, 3] },
  "network":  { "default_port": 8447 }
}
```

> **注意**：`config.json` 只控制**基础游戏参数**。AI 决策评分参数在 `AI/ai.json`（由 `aithink4.py` 读取），两者互不干扰。

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
| **禁止降级** | `check_modify_branch` 校验 `target_strength >= target.strength`，客户端请求降级直接拒绝 |
| 频率限制 | 每秒不超过 10 个动作 |

累计违规超过阈值可触发踢出（目前计数值保留，踢出逻辑预留）。

### AI/aithink4.py - AI 系统

**当前生效版本**：`main.py` 顶部 `from AI.aithink4 import AIThinker`。同目录的 `aithink3.py`（前身）、`aithink2.py`、`aithink.py` 是早期移植版本（结构类似，但缺少后续增强功能），仅供对比参考。

**入口**：`AIThinker(game).decide_action()` → 返回动作字典或 `None`。

**决策流程**（从高到低）：

```
1. 根危预检：敌方接近己方根时跳过拾取和扩张
2. 局面动态分析（analyze_situation）—— 根据节点/边/点数/威胁走廊/半场控制调整权重
3. 候选目标生成（gen_targets）—— 朝敌根推进、侧翼、切敌节点、切边、收集、环形扫描
4. 强制杀根检测（find_kill_move）—— 预算内一步穿过敌根 → 直接取胜
5. 多维度静态评分（score_target）+ 威胁惩罚（threat_penalty）
6. 轻量前向模拟（simulate_lookahead）—— 对 top 候选做"我落子→敌回应→我再回应"的贪心推演
7. 加权随机选择 → 执行
8. 薄弱边强化（choose_reinforce）
9. 结束回合
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

**AI 增强特性**：
- **放置后强化**：AI 放置节点后调用 `choose_reinforce()` 优先加固威胁走廊内的低强度边，每回合最多 2 次（由 `Game._ai_post_reinforce` 控制，见 `main.py _ai_update()`）
- **记忆**：上次落点被摧毁的位置不再重建（`_ai_memory`，每局 `reset()` 时清空）
- **前向模拟**：对候选做 2 层贪心推演修正静态分
- **思考延迟**：由 `config.json` 的 `ai.think_delay_frames` 控制（默认 90 帧 ≈ 1.5s），`main.py` 中 `_AI_THINK_DELAY = AI_THINK_DELAY`

**aithink4 相对 aithink3 的调优**（吸取回放局教训）：
- `max_move_cost` 从 2 → **1**：常规落子只允许 0~1 点开销，强制免费短步推进，把点数留给杀根窗口（回放 204717/205605 教训）
- 前线节点出生强度奖励：距离阈值 400 → **350**，每级奖励 60 → **120**：更贴近敌根才奖励，且出生即带强度，抵抗人类切强度 1 链

**可配置参数**：全部 **30 个权重**集中在 `AI/ai.json`（代码 `AIConfig.__init__` 只保留兜底默认值，运行时从 json 完整加载）。修改 `ai.json` 后每局初始化时自动生效。

相关文件：
- `AI/ai.json`：运行时权重（完整 30 字段，自动学习会更新，写前自动备份）
- `AI/learn.json`：学习数据（对局统计/对手打法，gitignore 排除）
- `AI/backup/`：ai.json 按日期自动备份（gitignore 排除）
- `AI/aithink.py` / `AI/aithink2.py` / `AI/aithink3.py`：早期版本（未被 main.py 引用）

### AI 自动学习（#17）

AI 有三层学习能力，全部以 `AI/ai.json`（权重）和 `AI/learn.json`（统计）为存储：

**1. 对局结果学习（每局结束自动触发）**
- 触发链：`Game.go_menu()` → `_record_ai_learn()`（[main.py](main.py)）→ `AIThinker.record_match_result()`（[aithink4.py](AI/aithink4.py)）
- 胜负判断：`winner == self._ai_team`；中途退出记为 `draw`（只统计、不调整权重）
- 调整规则（依据最近 20 局连败/连胜）：
  - **连败 ≥3** → 保守化：`risk_taker×0.90`、`spend_mid×0.95`、`hub_preference×0.95`、`threat_mul×1.06`、`collect_low×1.10`
  - **连胜 ≥3** → 小幅恢复激进：`risk_taker×1.05`、`spend_mid×1.03`、`threat_mul×0.98`
- 权重调整后经 `AIConfig._CLIP` 边界夹取（防止失控），写回 `ai.json`（tmp+rename 原子写），写前自动备份到 `AI/backup/ai_<时间戳>.json`

**2. 对手行为统计**
- `observe_opponent()`：AI 每回合统计敌方**长距离落子比例**（父距离 >160px）与**强化比例**（强度 >1）
- 对手强化比例 >50% → 自动提升 `threat_mul`（更重视防守），并随对局结果记录进 `learn.json` 的 `enemy_style`

**3. 在线自对弈训练（dev/rl_evolve.py）**
- 在 dummy 视频驱动下跑 **AI vs AI 自对弈锦标赛**：以当前权重为基准，生成随机微扰权重（`--mutation`），交替先后手打 `--games` 局
- 变异权重净胜更多 → 写回 `ai.json`（自动备份），否则保留
- 与游戏内学习互补：游戏内按真实对局结果微调，脚本批量搜索更优权重组合

```bash
python dev/rl_evolve.py --games 8 --mutation 0.12 --seed 42
```

### AI 托管（#30）

**用途**：AI 对战模式中，玩家可把自己的队伍交给 AI 控制（双 AI 对弈），常用于观战/挂机。

**开关**：游戏界面左下角按钮 `AI托管: 关/开`（仅鼠标点击，**不绑快捷键**）；结束回合按钮也位于左下角（`结束回合 (Tab)`，Tab 快捷键保留）。

**允许模式**：由 `constant.py` 的 `AI_CUSTODY_ALLOWED_MODES` 元组控制，目前仅 `'ai'`（AI 对战）允许，单人模式禁止使用。如需开放其他模式，往元组里追加对应模式标识即可。

**实现要点**（[main.py](main.py)）：
- `Game._ai_custody`：当前是否托管玩家队，`reset()` 时每局重置为 False
- `update()` / `_ai_update()`：托管后玩家队也走 AI 决策，双 AI 交替推进
- `_ai_update()` 创建 `AIThinker` 后立即 `ai.team = self.current_team` / `ai.enemy_team = ...`（按**当前回合队伍**，而非固定的 `_ai_team`）—— 否则托管玩家队时 `decide_action()` 会把己方行动当成对手行动，回合卡死
- `Game._ai_memory_by_team`：托管双 AI 时按队伍隔离记忆，避免两个 AI 互相污染
- `is_my_turn`：托管期间玩家队回合判定为 False，阻止人类输入干扰 AI 操作

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

**保存时机**：`Game.update()` 检测到 `STATE_GAME_OVER` 时调用 `replay.save()`，只保存一次（`_saved` 标志防重复）。**联机客户端（蓝队）不保存回放**——服务端是权威记录端，客户端只生成空文件。

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

1. **新增常量** → 在 `constant.py` 中添加（如需用户可调，同时在 `config.json` 中新增配置项并回退默认值）
2. **新增状态字段** → 在 `Game.__init__()` 中添加，`Game.reset()` 中重置
3. **新增渲染** → 在 `Game.draw_playing()` 中添加绘制逻辑
4. **新增事件** → 在 `Game._handle_playing_event()` 中添加处理
5. **联机同步** → 确保服务器执行后通过 `_broadcast()` 或 `_broadcast_state_changed()` 发送给客户端
6. **反作弊** → 在 `anti_cheat.py` 中添加对应的校验方法
7. **回放** → 在 `replay.py` 中使用 `game.replay.record()` 记录，在 `_apply_replay_action()` 中添加应用逻辑

### 添加可配置项（config.json）

如果新参数希望用户能调整：

1. 在 `config.json` 对应分组中添加字段
2. 在 `constant.py` 中用 `_config.get('分组', {}).get('字段', 默认值)` 读取（**必须提供默认值**，保证 config 缺失时向后兼容）
3. 游戏内通过 `from constant import *` 使用即可

### 修改 AI 行为

1. **快速调参**：直接修改 `AI/ai.json`，下次 AI 对局即生效
2. **修改思考速度**：修改 `config.json` 的 `ai.think_delay_frames`（不影响 AI 决策质量，只改变"思考"耗时）
3. **修改策略**：在 `AI/aithink4.py` 中修改 `decide_action()` 的决策优先级或添加新规则
4. **修改评分**：在 `score_target()` / `threat_penalty()` 中添加新的评分维度
5. **添加参数**：在 `assets/ai_default.json` 中添加新参数（含 `_note` 注释），在 `AIThinker.__init__()` 中读取
6. **切换 AI 版本**：把 `main.py` 顶部的 `from AI.aithink4 import AIThinker` 改为引用旧版模块（不推荐，仅回退时使用）

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

## 日志系统

`main.py` 在启动时初始化 `logging`，同时输出到控制台和文件。

### 初始化流程（main.py 顶部）

1. `logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(message)s")` → 控制台简版格式
2. 在 `logs/` 目录创建日志文件：`logs/YYYYmmdd_HHMMssa.log`（启动时间 + 后缀）
3. 重名时后缀自动递增 `b`、`c`、`d`...，直到不重名
4. `FileHandler` 使用文件格式 `[%(asctime)s %(levelname)s] %(message)s`（含完整时间戳）
5. **`print()` 被重定向**：全局 `print()` 被替换为 `log.info()`，所有原有 `print()` 调用自动写入日志

### 使用方式

```python
log.debug("详细调试信息")
log.info("常规信息")     # 等价于 print()
print("也会进入日志文件")  # print 已被重定向
```

### 日志文件

- 路径：`logs/`
- 文件名示例：`20260810_143025a.log`、`20260810_143025b.log`
- `.gitignore` 已忽略 `*.log`，日志不会进入版本库

***

## CI/CD

`.github/workflows/release-cd.yml`：打 tag 时自动构建 Release。

### 触发方式

- push 带 `v*` 前缀的 tag（如 `v1.5`）
- 手动触发（`workflow_dispatch`）

### 版本号约定

| Tag | Release 类型 |
|-----|-------------|
| `v1.5` | 正式版 |
| `v1.5-p-r` | 预发布版（pre-release） |

### 流程

1. `actions/checkout@v4` 拉取代码
2. 解析 tag → 提取版本号、判断是否 pre-release
3. 提取最后一次 commit message 作为 Release body
4. `zip` 打包源码（排除 `.git`、`.github`）→ `project-<版本>.zip`
5. `softprops/action-gh-release@v2` 创建 Release 并上传 ZIP

> 注意：打包包含 `logs/`（已被 .gitignore 忽略，不在 git 中所以不会被打包）和 `replays/`。发布前确认仓库中没有残留的临时文件。

***

## 已知限制与改进方向

| 限制 | 说明 | 改进方向 |
|------|------|----------|
| 单客户端 | 服务端仅支持一个客户端连接 | 增加房间列表，支持多房间 |
| TCP 协议 | 文本协议简单但扩展性有限 | 考虑迁移到二进制协议或使用现成的消息库 |
| 无认证 | 客户端无需认证即可连接 | 添加简易密码或 token 认证 |
| 音效硬编码 | 音效文件路径和映射全部在 constant.py 中 | 可迁移到 config.json 或独立音效配置 |
| AI 单难度 | AI 只有一套权重（支持自动学习演化） | 增加多难度等级或多套参数预设 |
| 自对弈需手动跑 | 游戏内只做结果学习，自对弈是独立脚本 | 可在空闲时自动触发有限自对弈 |

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
