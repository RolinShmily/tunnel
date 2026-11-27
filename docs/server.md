# server/

服务端 `sing-box` 配置模板目录，包含 `<placeholder>` 占位符，由 `scripts/config-batch.py` 渲染至 `dist/server/`。

## 文件一览

| 文件 | 适用场景 | 监听与出站差异 |
| --- | --- | --- |
| `sing-box.json` | 双栈服务器 | 入站监听 `::`，默认直出 `direct` |
| `sing-box-v4only.json` | 纯 IPv4 服务器 | 入站监听 `0.0.0.0`，路由显式拒绝 IPv6 出站（`ip_version: 6`、`action: reject`、`no_drop: true`） |

## 入站协议

两份模板包含相同的三个入站，与客户端三节点一一对应：

| Tag | 协议 | 默认端口 | 说明 |
| --- | --- | --- | --- |
| `vless-vision-reality-in` | VLESS + Vision + Reality | TCP `443` | 主力直连协议，无需域名证书 |
| `hysteria-in` | Hysteria2 + TLS | UDP `27015` | 弱网/高丢包加速通道，需配置证书与私钥路径 |
| `vless-ws-in` | VLESS + TLS + WebSocket | TCP `8443` | CDN 中转备用通道，启用 `max_early_data: 2048`（0-RTT） |
