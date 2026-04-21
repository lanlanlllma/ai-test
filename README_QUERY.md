# Tetromino Solution Query Script

这是一个 Python 脚本，用于查询俄罗斯方块求解器数据库并显示最优解决方案。

## 功能

- 📊 查询数据库中基于方块数量的最优解决方案
- 🎮 打印可视化盘面（使用字符表示）
- 📈 显示过详细的计分信息
- 📍 返回每个方块的摆放位置和旋转信息
- 📄 支持 JSON 格式输出用于编程调用

## 文件说明

### `query_solution.py` - 主脚本
包含以下主要函数：

#### `query_solution(counts, db_path)`
查询数据库并返回最优解决方案的数据。

**参数：**
- `counts` (dict): 方块数量字典，键为方块名称 (I, O, S, Z, L, J, T)，值为数量
- `db_path` (Path, 可选): 数据库文件路径，默认为 `best_solutions.sqlite3`

**返回值：** 
包含以下信息的字典：
- `counts`: 输入的方块数量
- `best_score`: 最优分数
- `nodes`: 搜索过程中探索的节点数
- `elapsed_seconds`: 求解耗时
- `filled_cells`: 填充的方块数
- `grid`: 盘面数据（二维列表）
- `placements`: 摆放信息（方块、旋转、位置）
- `created_at`: 创建时间戳

#### `print_solution(solution)`
打印解决方案的完整信息，包括：
- 方块数量
- 可视化盘面
- 计分详情
- 摆放位置
- 搜索统计信息

#### `get_placements(solution)`
从解决方案中提取摆放位置和旋转信息。

**返回值：** 
元组列表，每个元组包含 (方块名, 旋转索引, 行位置, 列位置)

#### `query_solution.Grid` 类型
二维列表，其中每个格子为一个整数：
- 0: 空格
- 正整数: 表示某个方块（不同数字代表不同方块）

### `example_query.py` - 使用示例
展示如何在代码中使用 `query_solution` 模块。

## 命令行使用

### 基本用法

```bash
python3 query_solution.py '{"I": 5, "O": 5, "S": 5, "Z": 5, "L": 5, "J": 5, "T": 1}'
```

### 指定数据库路径

```bash
python3 query_solution.py '{"I": 2, "O": 1, "S": 0, "Z": 0, "L": 1, "J": 1, "T": 2}' --db best_solutions.sqlite3
```

### JSON 格式输出

```bash
python3 query_solution.py '{"I": 1, "O": 1, "S": 1, "Z": 1, "L": 1, "J": 1, "T": 1}' --json-output
```

### 查看帮助

```bash
python3 query_solution.py --help
```

## 数据库

默认使用 `best_solutions.sqlite3` 数据库。表结构：

```sql
CREATE TABLE best_solutions (
    i_count, o_count, s_count, z_count, l_count, j_count, t_count,
    best_score, nodes, elapsed_seconds, filled_cells,
    grid_json, owner_grid_json, placements_json,
    created_at,
    PRIMARY KEY (i_count, o_count, s_count, z_count, l_count, j_count, t_count)
);
```

## 方块说明

| 字符 | 方块名 | 形状   |
| ---- | ------ | ------ |
| `I`  | I形    | 直线   |
| `O`  | O形    | 正方形 |
| `S`  | S形    | Z字左  |
| `Z`  | Z形    | Z字右  |
| `L`  | L形    | L字    |
| `J`  | J形    | 反L字  |
| `T`  | T形    | T字    |

## 旋转说明

旋转索引范围为 0-3，表示方块的不同旋转状态（顺时针）。

## 位置说明

- `anchor_r` (行): 0 = 顶部，向下递增
- `anchor_c` (列): 0 = 左侧，向右递增

## Python 代码示例

```python
from query_solution import query_solution, print_solution, get_placements
from pathlib import Path

# 创建方块数量字典
counts = {
    "I": 5,
    "O": 5,
    "S": 5,
    "Z": 5,
    "L": 5,
    "J": 5,
    "T": 1,
}

# 查询解决方案
solution = query_solution(counts, Path("best_solutions.sqlite3"))

if solution:
    # 打印完整信息
    print_solution(solution)
    
    # 获取摆放位置和旋转信息
    placements = get_placements(solution)
    for piece, rotation, anchor_r, anchor_c in placements:
        print(f"放置 {piece} 方块，旋转 {rotation}，位置 ({anchor_r}, {anchor_c})")
    
    # 直接访问数据
    score = solution['best_score']
    grid = solution['grid']
    print(f"得分: {score}")
else:
    print("未找到解决方案")
```

## 输出示例

### 盘面显示
```
+-------------------+
|L I I I I I I O O J|
|L I I I I I I O O J|
|L L I O O I I T J J|
|O O I O O I I T T Z|
...
+-------------------+
```

### 计分表
```
 Row  Colours  Base  Bonus  Total
---------------------------------
   0        4    10    +10     20
   1        4    10    +10     20
...
---------------------------------
Total                          240
```

### 摆放信息
```
Placements:
  1. L - Rotation: 0, Position (r,c): (0, 0)
  2. I - Rotation: 0, Position (r,c): (0, 1)
  3. I - Rotation: 1, Position (r,c): (0, 5)
  ...
```

## 使用场景

1. **查看最优解决方案**：输入方块数量，查看最高分的摆法
2. **学习最优策略**：通过观察系统给出的解决方案学习方块摆放策略
3. **编程集成**：将查询功能集成到其他 Python 应用中
4. **数据分析**：导出 JSON 数据进行进一步的数据分析
5. **机器学习训练**：使用最优解决方案作为训练数据

## 注意事项

- 数据库中可能不存在所有可能的方块数量组合
- 如果查询不存在的组合，会返回 None
- 方块数量为 0 表示该方块不使用
- 盘面大小为 14×10（行×列）

## 扩展使用

可以将此脚本与 `solver.py` 结合使用，实现：
- 生成新的解决方案
- 比较不同方块组合的效率
- 导出为 SVG 图像
- 统计分析

## 许可证

该脚本与原始项目使用相同的许可证。
