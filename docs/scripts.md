# scripts/

本地渲染脚本，基于 Python 标准库，无第三方依赖。

## 配置文件

将仓库根目录 [config.json.example](../config.json.example) 复制为 `config.json`（已被 `.gitignore` 忽略），按功能分为 5 个分区：

| 分区 | 内容 |
| --- | --- |
| `"reality"` | VLESS-Reality 节点地址、端口、UUID、SNI、公私钥、ShortId 与回落握手目标 |
| `"hysteria2"` | Hysteria2 端口、SNI、密码及服务端证书/私钥路径 |
| `"ws"` | VLESS-WS（CDN）优选域名、端口、SNI、UUID、路径、证书及 Early Data 参数 |
| `"client"` | Mihomo API 密钥、GitHub 规则镜像前缀（`RuleSetProxy`）、可选去广告（`EnableAdBlock`）与外部订阅（`EnableExternalSubscribes`） |
| `"tailscale"` | Headscale 域名与 MagicDNS 规则，以及单 TUN 模板的 Tailscale 原生出站参数 |

## `scripts/config-batch.py`

读取根目录 `config.json`，单次完成占位符替换与客户端可选叠加层注入，默认原子写入 `dist/`（不修改受控模板）。

### 核心行为

- **产物清单**：渲染包含客户端文件且非 `--in-place` 时，自动生成 `dist/client/url`（无扩展名，每行一个已渲染的客户端文件名）。
- **Tailscale 出站字段**：`TailscaleControlUrl` / `TailscaleAuthKey` / `TailscaleHostname` 等仅作用于 `client/mihomo-clash-tailscale*.yaml`；`TailscaleControlUrl` 或 `TailscaleAuthKey` 留空 `""` 时自动删除对应字段（分别回退官方 Tailscale 控制面 / 日志交互登录）。
- **客户端可选叠加层（幂等）**：
  - **Headscale**（`HeadscaleServer`、`HeadscaleMagicDnsDomain`）：注入控制面 DNS/FakeIP 绕过与直连规则；MagicDNS 根据目标模板是否含 `type: tailscale` 自动指向 `100.100.100.100`（`Direct`）或 `100.100.100.100#Tailscale`（`Tailscale`）。
  - **AdBlock**（`EnableAdBlock`、`AdBlockRuleUrl`）：在 `custom_direct` 后插入 `RULE-SET,adblock,REJECT` 及对应 `rule-provider`，不新增策略组。
  - **外部订阅**（`EnableExternalSubscribes`、`ExternalSubscribes`）：注入 `proxy-providers` 并挂载到 `Proxy` 组的 `use:`。
  - **镜像前缀**（`RuleSetProxy`）：仅对 `external-ui-url` 与 `rule-providers` 中的 GitHub URL 拼接镜像前缀（非 GitHub 源保持原样），留空 `""` 则全部直连。

### 常用命令

```bash
python scripts/config-batch.py --preview                 # 预览输出清单（不写入）
python scripts/config-batch.py                           # 全量渲染至 dist/
python scripts/config-batch.py --only client             # 仅渲染客户端
python scripts/config-batch.py --only server             # 仅渲染服务端
python scripts/config-batch.py -t client/mihomo-clash.yaml -o ./out
python scripts/config-batch.py -c /path/to/config.json   # 指定配置文件
```
