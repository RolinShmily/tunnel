# scripts/

本地渲染与可选特性注入脚本，基于 Python 标准库，无第三方依赖。

## 配置文件

将仓库根目录 [config.json.example](../config.json.example) 复制为 `config.json`（已被 `.gitignore` 忽略），按脚本名分为两个分区：

- `"config-batch"`：节点参数、服务端证书路径、API 密钥及单 TUN 模板的 Tailscale 出站参数。
- `"feature-generate"`：Headscale 域名、可选去广告、外部订阅及规则镜像前缀。

## 脚本一览

### `scripts/config-batch.py`

读取 `config.json` 的 `"config-batch"` 分区，校验必填字段格式并批量渲染 `client/`、`server/` 模板，默认原子写入 `dist/`（不修改受控模板）。

- **产物清单**：渲染包含客户端文件且非 `--in-place` 时，自动生成 `dist/url`（无扩展名，每行一个已渲染的客户端文件名）。
- **Tailscale 出站字段**：仅作用于 `client/mihomo-clash-tailscale*.yaml`；`TailscaleControlUrl` 或 `TailscaleAuthKey` 留空 `""` 时自动删除对应字段（分别回退官方 Tailscale 控制面 / 日志交互登录）。

常用命令：

```bash
python scripts/config-batch.py --preview                 # 预览输出清单（不写入）
python scripts/config-batch.py                           # 全量渲染至 dist/
python scripts/config-batch.py --only client             # 仅渲染客户端
python scripts/config-batch.py -t client/mihomo-clash.yaml -o ./out
python scripts/config-batch.py -c /path/to/config.json   # 指定配置文件
```

### `scripts/feature-generate.py`

读取 `config.json` 的 `"feature-generate"` 分区，对 Mihomo 客户端 YAML 施加**幂等**叠加层（默认目标为 `dist/client/`，不存在时回退 `client/`）。

| 特性 | 触发字段 | 行为 |
| --- | --- | --- |
| Headscale | `HeadscaleServer`、`HeadscaleMagicDnsDomain` | 注入控制面 DNS/FakeIP 绕过与直连规则；MagicDNS 根据目标模板是否含 `type: tailscale` 自动指向 `100.100.100.100`（`Direct`）或 `100.100.100.100#Tailscale`（`Tailscale`） |
| AdBlock | `EnableAdBlock`、`AdBlockRuleUrl` | 在 `custom_direct` 后插入 `RULE-SET,adblock,REJECT` 及对应 `rule-provider`，不新增策略组 |
| 外部订阅 | `EnableExternalSubscribes`、`ExternalSubscribes` | 注入 `proxy-providers` 并挂载到 `Proxy` 组的 `use:` |
| 镜像前缀 | `RuleSetProxy` | 重写 `external-ui-url` 与全部 `rule-providers` 的下载 URL 前缀；留空 `""` 则还原直连地址 |

常用命令：

```bash
python scripts/feature-generate.py --preview
python scripts/feature-generate.py
python scripts/feature-generate.py -t dist/client/mihomo-clash-v4only.yaml
```

## 标准执行顺序

```bash
python scripts/config-batch.py
python scripts/feature-generate.py
```
