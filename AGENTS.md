# 维护钩子

| 触发 | 同步动作 |
| --- | --- |
| 客户端模板（`client/`）新增、删除或核心行为变更 | 更新 `docs/client.md`；如涉及占位符或渲染规则，同步更新 `scripts/config-batch.py` 与 `config.json.example` |
| 服务端模板（`server/`）新增、删除或入站协议/路由变更 | 更新 `docs/server.md`；如涉及占位符或渲染规则，同步更新 `scripts/config-batch.py` 与 `config.json.example` |
| 自定义规则集（`rules/`）新增、删除或用途变更 | 更新 `docs/rules.md` |
| 渲染脚本（`scripts/`）或 `config.json.example` 分区/参数/叠加层变更 | 更新 `docs/scripts.md` 与 `config.json.example` |
| 第三方核心、规则源或参考配置变更 | 更新 `README.md` 的 Credits 节 |
| 根目录入口文件/目录或受控资产位置变更 | 更新本文件对应路径 |

## 备注

- `docs/` 沿用按目录拆分的四篇（`docs/client.md`、`docs/server.md`、`docs/rules.md`、`docs/scripts.md`），不迁移为 `architecture`/`design`/`development`/`reference` 四件套。
- 不维护双语 `README.zh-CN.md`，保留单语 `README.md`。
- 不设 `tests/`、`.github/`、`CHANGELOG.md`、`CONTRIBUTING.md`、`LICENSE` 与 `THIRD_PARTY_NOTICES`。
