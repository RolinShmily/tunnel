# client/

客户端配置模板目录，均包含 `<placeholder>` 占位符，需经 `scripts/config-batch.py` 渲染至 `dist/client/` 后使用。

## 文件一览

| 文件 | 适用场景 | 关键特性 |
| --- | --- | --- |
| `mihomo-clash.yaml` | 桌面单机（双栈） | `allow-lan: false`，双 TUN 模式（兼容独立 Tailscale 客户端） |
| `mihomo-clash-v4only.yaml` | 桌面单机（纯 IPv4） | 同上，关闭 IPv6 并拦截公网 IPv6 回退 IPv4 |
| `mihomo-clash-lan.yaml` | 局域网共享代理（双栈） | `allow-lan: true`、`auto-redirect: false`、`strict-route: false`，避免劫持桥接流量，预留 `proxy-providers` 模板位 |
| `mihomo-clash-lan-v4only.yaml` | 局域网共享代理（纯 IPv4） | 同上，纯 IPv4 变体 |
| `mihomo-clash-router.yaml` | Linux 软路由 / 透明网关（双栈） | `auto-redirect: true`（nftables）、`dns.listen: 0.0.0.0:1053`、`fake-ip-ttl: 10` |
| `mihomo-clash-router-v4only.yaml` | Linux 软路由 / 透明网关（纯 IPv4） | 同上，纯 IPv4 变体 |
| `mihomo-clash-tailscale.yaml` | 手机 / 轻客户端（单 TUN 双栈） | 内置 `type: tailscale` 原生出站，不排除 Tailscale 网段，将 `100.64.0.0/10`、`fd7a:115c:a1e0::/48`、`+.ts.net` 直送 `Tailscale` 节点 |
| `mihomo-clash-tailscale-v4only.yaml` | 手机 / 轻客户端（单 TUN 纯 IPv4） | 同上，纯 IPv4 变体 |
| `v2ray-nodes.txt` | 通用节点导入 | 输出 VLESS-Reality、Hysteria2、VLESS-WS 三条标准 URI，供 v2rayN 等客户端使用 |

## 通用约定

- **代理组**：精简为 `Proxy`（手动选择）+ `Auto`（fallback 自动切换：`Reality` → `Hysteria2` → `CF-CDN` → `Direct`）+ `Direct`，不拆分多服务分组。
- **双栈 vs `-v4only`**：`-v4only` 关闭 `ipv6` 与 `dns.ipv6`，并在私网/Tailscale 规则之后通过 `IP-CIDR6,::/0,REJECT,no-resolve` 快速拒绝公网 IPv6，避免无 IPv6 环境下直连报错或卡顿。
- **DNS 与分流**：FakeIP 模式 + `prefer-h3: true`，按 `nameserver-policy` 分流国内/海外解析；非 CN 域名拦截 `UDP 443`（QUIC 回退 HTTP/2）；全量采用 `.mrs` 二进制 `rule-providers`。
- **双 TUN 与单 TUN 边界**：
  - 官方 Tailscale 统一区分「内网数据面/P2P UDP 直连」与「官方控制面/官网/DERP TCP 代理」：`tailscale.com` / `tailscale.io` 通过代理 DNS（`8.8.8.8#Proxy`）解析真实 IP 并排除 FakeIP，TCP 连接经 `custom_proxy` 走 `Proxy`，而 `tailscaled` UDP 与 `41641` P2P / STUN 由 `RULE-SET,tailscale,Direct` 优先直连。
  - 前 6 份双 TUN 模板在 `tun.route-exclude-address` 排除 Tailnet 网段，并将 `+.ts.net` 在 `dns.nameserver-policy` 指向本地 MagicDNS（`100.100.100.100`），适配系统独立 Tailscale 客户端。
  - 后 2 份 `*-tailscale*.yaml` 用于单 VPN 槽位设备（如手机），由 Mihomo `type: tailscale` 直接承接 Tailnet 流量与 `ts://Tailscale` 解析，并支持通过 `TailscaleDialerProxy` 可选注入 `dialer-proxy` 让官方控制面/DERP 经代理建立连接。
