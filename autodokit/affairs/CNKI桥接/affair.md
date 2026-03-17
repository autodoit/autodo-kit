# CNKI桥接

## 事务说明

- 该事务提供 CNKI 相关技能的规划能力封装。
- 输入 `mode` 决定调用的 planner 构建方法。
- 输出统一写入 `cnki_bridge_result.json`。

## 输入约定

- `mode`: 规划模式，例如 `cnki-search`、`cnki-export`。
- 其余参数按对应模式透传。
- `output_dir`: 输出目录，必须为绝对路径。

## 输出

- `cnki_bridge_result.json`
