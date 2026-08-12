# AI C 扩展加速 (btb_geo) — 构建 / 验证 / 基准 / 集成

为**自动 AI 训练**（`dev/rl_evolve.py` 自对弈锦标赛 + 游戏内 AI 对弈模式）编写的
C 几何加速内核。把 AI 决策中最热的几何循环（节点/边命中检测、批量距离计算）移到
C 侧批处理，单回合决策约 **3.2 倍**加速，整局自对弈约 **2.3~3.0 倍**加速，
且与纯 Python 路径**行为逐位等价**（同种子下对局轨迹哈希完全一致）。

## 文件清单

| 文件 | 说明 |
|------|------|
| `AI/btb_geo.c` | C 内核源码（纯 C11，无第三方依赖，无 Python.h） |
| `AI/build_geo.py` | 编译脚本：自动探测 g++ → `AI/btb_geo.dll` → ctypes 加载验证 |
| `AI/fast_geo.py` | ctypes 包装：DLL 加载、`GeoPack` 批量上下文、标量原语、参考实现 |
| `AI/btb_geo.dll` | 编译产物（本机生成，已加入 .gitignore，不提交） |
| `dev/check_fast.py` | 正确性验证：标量 10 万随机对拍 + 批量局面逐字段对拍 + 整局对拍 |
| `dev/bench_fast.py` | 性能基准：fast vs 纯 Python（`BTB_NO_FAST=1`） |
| `dev/rl_evolve.py` | 训练器（修复了 `import main` 与 `def main()` 重名的既有 bug） |

## 构建

```bash
python AI/build_geo.py
```

脚本会按顺序探测：环境变量 `GXX` → 常见 TDM-GCC/MinGW 路径 → `PATH` 中的 g++，
编译命令等价于：

```bash
g++ -O2 -shared -static-libgcc -static-libstdc++ -o AI/btb_geo.dll AI/btb_geo.c
```

编译成功后自动验证 ctypes 可加载。**不要加 `-ffast-math`**（会破坏与 Python
参考实现的浮点等价性）。

## 集成与自动回退

`AI/aithink4.py` 顶部自动导入 `fast_geo`：

- `AI/btb_geo.dll` 存在 → `FAST_GEO = True`，以下热点自动走 C 批量：
  - `_gen_cands`：全部候选的节点/边命中、枢纽值、压制、收集统计（一次 C 调用）
  - `_sim_best_move`：模拟层候选命中统计 + 推进距离批量
  - `threat_penalty`：敌方延伸阻挡检测（距离矩阵一次 C 调用）
- DLL 缺失 / 无法加载 → `FAST_GEO = False`，走原纯 Python 实现，行为逐位一致
- 环境变量 `BTB_NO_FAST=1` 可强制关闭（对照基准 / 调试）

游戏本体、联机、回放等路径**不受任何影响**（只在 AIThinker 决策内启用）。

## 验证

```bash
python dev/check_fast.py
```

三层验证：

1. **标量原语**：`btb_dist` / `btb_pt_seg_dist` / `btb_seg_cross` /
   `btb_seg_hits_circle` / `btb_sector` 与 Python 参考在 10 万随机输入上对拍
   （浮点容差 1e-12，命中判定逐位一致）。
2. **批量命中分析**：60 个随机局面 × 30 条移动，`GeoPack.analyze_moves` 与
   Python 参考逐字段对比（整数严格相等，浮点容差 1e-9）。
3. **整局对拍**：同种子（42）跑 4 局 AI vs AI，C 路径与纯 Python 路径的
   winner / turns / 动作轨迹哈希必须完全一致。

> 若整局对拍出现分歧，重点检查是否又引入了 hypot 实现的 1 ulp 差异导致的
> 排序翻转（`_sim_best_move` 已有"分差过近重算"保护，见源码注释）。

## 基准

```bash
python dev/bench_fast.py --games 4
```

同种子分别跑 fast / 纯 Python 锦标赛，输出每局耗时、单回合决策耗时与加速比。

参考值（TDM-GCC 9.2, Python 3.13）：

| 指标 | 纯 Python | fast | 加速 |
|------|-----------|------|------|
| 单回合 decide_action | ~31 ms | ~10 ms | 3.2x |
| 整局自对弈（4 局） | ~10.2 s | ~4.4 s | 2.3x |

## 训练

```bash
python dev/rl_evolve.py --games 12 --mutation 0.12 --seed 42
```

DLL 存在时自动加速，**无需任何参数改动**。变异权重净胜更多会写回
`AI/ai.json`（旧权重自动备份到 `AI/backup/`）。

## 实现要点

- **批量优先**：ctypes 单函数调用有 ~1-2µs 开销，小于 Python 单次 `math.hypot`
  的场景（如 `choose_reinforce` 的小循环）刻意**不做** C 化。收益来自
  `btb_analyze_moves` 一次调用分析全部候选（每回合 1 次调用替代 ~16 万次
  Python 几何调用）。
- **端点排除**：`gen_targets` 会生成与敌方节点重合的落点（切节点），命中检测
  必须排除 src/tgt 坐标恰与敌方节点重合的情况，否则切节点落点会被误判命中根。
- **1 ulp 决胜保护**：C 的 `hypot`（MinGW CRT）与 `math.hypot`（MSVC CRT）在
  最后 1 ulp 上有差异。`score_target` 有 ±2 噪声掩护风险≈0；但 `_sim_quick_score`
  无噪声，两个候选分差落在 1 ulp 内时排序可能翻转 —— `_sim_best_move` 对
  批量排序后"分差 < 1e-6 的前几名"用 Python 精确重算，正常情况零开销。
- **`main.py` 依赖相对路径**（`./debug`、`./config.json`）：bench/check 脚本
  运行时自动 chdir 到项目根。
