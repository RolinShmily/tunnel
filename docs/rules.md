# rules/

自定义 Mihomo 规则集目录，均采用 `behavior: classical`、`format: text` 格式（每行省略策略目标，由客户端 `RULE-SET` 统一指定）。

## 文件一览

| 文件 | 对应 Provider | 作用 |
| --- | --- | --- |
| `tailscale.list` | `tailscale` | 官方 Tailscale 数据面与打洞直连：含 Tailnet 虚拟网段（`100.64.0.0/10`、`fd7a:115c:a1e0::/48`）、MagicDNS 域名（`ts.net`）以及 Tailscale 进程/端口的 UDP 流量（`tailscaled` / `tailscale` / `IPNExtension` UDP、`UDP 41641` 源/目的端口及 `tailscale.com` UDP `3478` STUN），保证内网互访与国内设备间 P2P 打洞直连。同时挂载于 `dns.fake-ip-filter`（仅提取其中的 `ts.net` 域名项），防止 MagicDNS 落入 FakeIP |
| `direct.list` | `custom_direct` | 自定义直连白名单，内置 `.local`、`172.32.0.0/12`、Steam 国内 CDN/CM 修复（`steamcdn-a.akamaihd.net`、`cm.steampowered.com`、`steamserver.net`）、CS2 与 TGPRO 社区服直连（`cs2.exe`、`tgpro.top`、`tgpro.net`、`tgprocs.net`）及 Google Play 国行下载修复（`services.googleapis.cn`）。优先级高于去广告与代理规则，同时挂载于国内 `dns.nameserver-policy` 与 `dns.fake-ip-filter`（仅提取其中域名项），避免自定义直连域名落入 FakeIP |
| `proxy.list` | `custom_proxy` | 自定义代理白名单，强制指定域名或 IP 走 `Proxy`（默认含 `dns.google`、`cloudflare-dns.com` 以及官方 Tailscale 控制面/官网/DERP TCP 域名 `tailscale.com`、`tailscale.io`；UDP P2P/STUN 由前置的 `tailscale.list` 优先放行直连） |

## 维护说明

- 每份文件需至少保留一条有效规则，避免 Mihomo 加载空规则集报错。
- 客户端默认从 GitHub `main` 分支拉取（每 24 小时更新），修改后需推送远端并在客户端刷新对应 rule-provider 生效。
