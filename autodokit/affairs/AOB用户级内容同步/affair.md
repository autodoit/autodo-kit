# AOB用户级内容同步

调用 `autodokit.tools.aob.aob_update_user_content`，按“参与方解析 -> AOL 反编译 -> logical key / SQLite 基线判定 -> canonical 回写 -> 定向发布”的顺序执行用户级内容同步。

固定输出文件：

- `aob_update_user_content_result.json`

## 关键参数

- `target_paths`
- `home_dir`
- `engine_vendors`
- `ide_vendors`
- `include_missing`
- `backup_dir`
- `dry_run`
- `skip_backup`
- `skip_items_sync`
- `simulate_only`
- `sandbox_dir`
- `repo_root`