# Skill渲染

## 用途

该事务用于接收 `SKILL.md` 文件绝对路径与参数字典，调用引擎中的 Skill 渲染器生成最终 Prompt 文本，并输出结构化结果 JSON。

## 运行入口

- module: `autodokit.affairs.Skill渲染.affair`
- callable: `execute`
- pass_mode: `config_path`

## 业务参数

- `skill_path`：`SKILL.md` 文件绝对路径。
- `params`：渲染所需的参数字典。
- `output_dir`：结果输出目录，要求在进入事务前已预处理为绝对路径。

## 输出结果

默认输出文件为 `skill_render_result.json`，其中包含渲染后的 `prompt`、Skill 元数据 `meta`、`skill_name` 与 `skill_path`。

