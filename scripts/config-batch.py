#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch-render client/ and server/ config templates from <repo>/config.json.

Replaces required <placeholder> markers and applies optional client overlays
(Headscale, AdBlock, external proxy-providers, GitHub ruleset mirror prefix)
in a single pass. Outputs rendered configs to dist/ by default (gitignored),
leaving tracked templates untouched. When rendering client templates to an
output directory, also writes `<output>/client/url` with one rendered client
filename per line.

Usage:
    python scripts/config-batch.py --preview
    python scripts/config-batch.py
    python scripts/config-batch.py --only client
    python scripts/config-batch.py -t client/mihomo-clash.yaml
    python scripts/config-batch.py -t client/mihomo-clash-router.yaml -t server/sing-box.json
    python scripts/config-batch.py --in-place
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import uuid

IGNORED_DIRS = {"__pycache__", ".git"}
PLACEHOLDER_RE = re.compile(r"<[a-z0-9-]+>")
CONFIG_SECTIONS = ("reality", "hysteria2", "ws", "client", "tailscale")

# Default schema; fill values in <repo>/config.json (copy from config.json.example).
CONFIG = {
    # Reality
    "NodeAddress": "<node-address>",
    "RealityPort": 443,
    "Uuid": "<uuid>",
    "RealitySni": "<reality-sni>",
    "RealityPublicKey": "<reality-public-key>",
    "RealityPrivateKey": "<reality-private-key>",
    "ShortId": "<reality-short-id>",
    "HandshakeHost": "<reality-host>",
    "HandshakePort": 443,

    # Hysteria2
    "Hy2Port": 27015,
    "Hy2Sni": "<hy2-sni>",
    "Hy2Password": "<hy2-password>",
    "CertificatePath": "<cert-path>",
    "KeyPath": "<key-path>",

    # VLESS-WS (CF-CDN)
    "WsOptimizedDomain": "<cf-domain>",
    "WsPort": 8443,
    "WsSni": "<ws-sni>",
    "WsUuid": "<ws-uuid>",
    "WsPath": "<ws-path>",
    "WsCertificatePath": "<ws-cert-path>",
    "WsKeyPath": "<ws-key-path>",
    "WsMaxEarlyData": 2048,
    "WsEarlyDataHeader": "Sec-WebSocket-Protocol",

    # Client API & overlays
    "MihomoApiSecret": "<api-secret>",
    "RuleSetProxy": "https://gh-proxy.com/",
    "EnableAdBlock": False,
    "AdBlockRuleUrl": "https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/main/Filters/AWAvenue-Ads-Rule-Clash.mrs",
    "EnableExternalSubscribes": False,
    "ExternalSubscribes": [],

    # Tailscale / Headscale
    "HeadscaleServer": "",
    "HeadscaleMagicDnsDomain": "",
    "TailscaleControlUrl": "",
    "TailscaleAuthKey": "",
    "TailscaleHostname": "mihomo",
    "TailscaleEphemeral": False,
    "TailscaleAcceptRoutes": True,
}

CLIENT_REQUIRED = {
    "NodeAddress", "Uuid", "RealitySni", "RealityPublicKey", "ShortId",
    "Hy2Sni", "Hy2Password",
    "WsOptimizedDomain", "WsSni", "WsUuid", "WsPath",
    "MihomoApiSecret",
}

SERVER_REQUIRED = {
    "Uuid", "RealitySni", "RealityPrivateKey", "ShortId", "HandshakeHost",
    "Hy2Sni", "Hy2Password", "CertificatePath", "KeyPath",
    "WsSni", "WsUuid", "WsPath", "WsCertificatePath", "WsKeyPath",
}


def is_placeholder(val):
    return bool(PLACEHOLDER_RE.fullmatch(str(val).strip()))


def load_config(repo_root, explicit_path=None):
    path = os.path.abspath(explicit_path) if explicit_path else os.path.join(repo_root, "config.json")
    if not os.path.isfile(path):
        raise ValueError(
            f"Config file not found: {path} "
            f"(copy config.json.example to config.json and fill in your values); aborted."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load config ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a JSON object: {path}")

    loaded_any = False
    for sec_name in CONFIG_SECTIONS:
        if sec_name not in data:
            continue
        section = data[sec_name]
        if not isinstance(section, dict):
            raise ValueError(f"Section '{sec_name}' must be a JSON object in {path}; aborted.")
        loaded_any = True
        for key, val in section.items():
            if key in CONFIG:
                CONFIG[key] = val

    if not loaded_any:
        raise ValueError(
            f"No valid config sections ({', '.join(CONFIG_SECTIONS)}) found in {path}; aborted."
        )
    return path


def assert_values(values, need_client, need_server):
    required = set()
    if need_client:
        required |= CLIENT_REQUIRED
    if need_server:
        required |= SERVER_REQUIRED

    for key in sorted(required):
        val_str = str(values.get(key, "")).strip()
        if not val_str or is_placeholder(val_str):
            raise ValueError(f"Missing required value for {key}; aborted.")

    for key in ("Uuid", "WsUuid"):
        if key in required:
            uuid_str = str(values[key]).strip()
            try:
                uuid.UUID(uuid_str)
                if not re.fullmatch(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", uuid_str):
                    raise ValueError()
            except Exception as exc:
                raise ValueError(f"{key} must be a valid UUID; aborted.") from exc

    if "ShortId" in required and not re.fullmatch(r"^(?:[0-9a-fA-F]{2}){1,8}$", str(values["ShortId"]).strip()):
        raise ValueError("ShortId must be 2-16 even-length hex chars; aborted.")

    port_keys = ["RealityPort", "Hy2Port", "WsPort"]
    if need_server:
        port_keys.append("HandshakePort")
    for key in port_keys:
        try:
            port = int(values.get(key, 0))
            if port < 1 or port > 65535:
                raise ValueError()
        except Exception as exc:
            raise ValueError(f"{key} must be between 1 and 65535; aborted.") from exc

    for key in ("RealityPublicKey", "RealityPrivateKey"):
        if key in required and not re.fullmatch(r"^[A-Za-z0-9_-]{43}$", str(values[key]).strip()):
            raise ValueError(f"{key} must be 43-char Base64URL; aborted.")

    for key in ("CertificatePath", "KeyPath", "WsCertificatePath", "WsKeyPath"):
        if key in required and not str(values[key]).strip().startswith("/"):
            raise ValueError(f"{key} must be an absolute Linux path; aborted.")

    for key in ("NodeAddress", "Hy2Sni", "RealitySni", "HandshakeHost", "WsOptimizedDomain", "WsSni"):
        if key in required and re.search(r"[\s/]", str(values[key]).strip()):
            raise ValueError(f"{key} must be a hostname or IP without scheme/path; aborted.")

    ws_path = str(values["WsPath"]).strip()
    if not ws_path.startswith("/") or re.search(r"\s", ws_path):
        raise ValueError("WsPath must start with / and contain no spaces; aborted.")

    for key in ("Hy2Password", "MihomoApiSecret"):
        if key in required:
            val = str(values[key])
            if re.search(r"[\r\n]", val) or len(val) < 16:
                raise ValueError(f"{key} must be at least 16 chars with no newlines; aborted.")

    if need_client:
        ts_url = str(values.get("TailscaleControlUrl", "")).strip()
        if ts_url:
            if is_placeholder(ts_url) or not re.fullmatch(r"https?://[^\s]+", ts_url):
                raise ValueError("TailscaleControlUrl must be empty or a valid http(s) URL; aborted.")
        ts_key = str(values.get("TailscaleAuthKey", "")).strip()
        if ts_key:
            if is_placeholder(ts_key) or re.search(r"[\r\n]", ts_key):
                raise ValueError("TailscaleAuthKey must be empty or a valid key with no newlines; aborted.")
        ts_host = str(values.get("TailscaleHostname", "mihomo")).strip()
        if not ts_host or is_placeholder(ts_host) or re.search(r"[\s'\"]", ts_host):
            raise ValueError("TailscaleHostname must be a non-empty hostname without whitespace or quotes; aborted.")
        for bkey in ("TailscaleEphemeral", "TailscaleAcceptRoutes", "EnableAdBlock", "EnableExternalSubscribes"):
            if not isinstance(values.get(bkey), bool):
                raise ValueError(f"{bkey} must be a boolean; aborted.")
        for key in ("HeadscaleServer", "HeadscaleMagicDnsDomain"):
            val = str(values.get(key, "")).strip()
            if val and not is_placeholder(val) and re.search(r"[\s/:]", val):
                raise ValueError(f"{key} must be a hostname or domain; aborted.")
        prefix = str(values.get("RuleSetProxy", "")).strip()
        if prefix and not is_placeholder(prefix):
            if not re.fullmatch(r"https?://[^\s]+/", prefix):
                raise ValueError("RuleSetProxy must match https?://.../ or be empty; aborted.")
        subs = values.get("ExternalSubscribes", [])
        if not isinstance(subs, list):
            raise ValueError("ExternalSubscribes must be a list of URLs; aborted.")
        if bool(values.get("EnableAdBlock", False)):
            ad_url = str(values.get("AdBlockRuleUrl", "")).strip()
            if not re.fullmatch(r"https?://[^\s]+", ad_url):
                raise ValueError("AdBlockRuleUrl must be a valid http(s) URL when EnableAdBlock is true; aborted.")


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def set_yaml_field(block, field, spaces, value):
    pattern = rf'(?m)^({" " * spaces}{re.escape(field)}:[ \t]*).*$'
    if len(list(re.finditer(pattern, block))) != 1:
        raise ValueError(f"Cannot uniquely locate YAML field {field}; aborted.")
    return re.sub(pattern, lambda m: m.group(1) + yaml_scalar(value), block, count=1)


def remove_yaml_field(block, field, spaces):
    pattern = rf'(?m)^{" " * spaces}{re.escape(field)}:[ \t]*[^\r\n]*\r?\n?'
    return re.sub(pattern, "", block, count=1)


def set_yaml_proxy(text, name, fields, remove_fields=()):
    pattern = rf'(?ms)^(  - name: {re.escape(name)}[^\r\n]*\r?\n)(.*?)(?=^  - name: |^[^\s#]|\Z)'
    if len(list(re.finditer(pattern, text))) != 1:
        raise ValueError(f"Cannot uniquely locate Mihomo proxy {name}; aborted.")

    def repl(m):
        header, block = m.group(1), m.group(2)
        for field, spaces in remove_fields:
            block = remove_yaml_field(block, field, spaces)
        for field, (spaces, val) in fields.items():
            block = set_yaml_field(block, field, spaces, val)
        return header + block

    return re.sub(pattern, repl, text, count=1)


def resolve_ruleset_prefix():
    raw = str(CONFIG.get("RuleSetProxy", "")).strip()
    return "" if (not raw or is_placeholder(raw)) else raw


def normalize_url(url):
    text = str(url)
    cut = max(text.rfind("https://"), text.rfind("http://"))
    return text[cut:] if cut > 0 else text


def is_github_url(url):
    return bool(re.match(r"^https?://(?:[^/]+\.)?(?:github\.com|githubusercontent\.com)/", url, re.IGNORECASE))


def apply_mirror_prefix(url, prefix):
    clean = normalize_url(url.strip())
    if prefix and is_github_url(clean):
        return prefix + clean
    return clean


def apply_ruleset_proxy(text):
    prefix = resolve_ruleset_prefix()
    text = re.sub(
        r'(?m)^(\s*external-ui-url:\s*["\']?)([^"\'\r\n]+)(["\']?)',
        lambda m: f"{m.group(1)}{apply_mirror_prefix(m.group(2), prefix)}{m.group(3)}",
        text,
    )
    start = re.search(r'(?m)^rule-providers:[ \t]*\r?$', text)
    if not start:
        return text
    tail = text[start.end():]
    stop = re.search(r'(?m)^[^\s#]', tail)
    section_end = start.end() + (stop.start() if stop else len(tail))
    section = re.sub(
        r'(?m)^(\s+url: )([^\r\n]+)',
        lambda m: m.group(1) + apply_mirror_prefix(m.group(2), prefix),
        text[start.end():section_end],
    )
    return text[:start.end()] + section + text[section_end:]


def has_tailscale_outbound(text):
    return bool(re.search(r'(?m)^    type:[ \t]*tailscale[ \t]*\r?$', text))


def apply_headscale(text):
    text = re.sub(r'(?ms)^[ \t]*# headscale:start\r?\n.*?^[ \t]*# headscale:end\r?\n', "", text)

    hs_server = str(CONFIG.get("HeadscaleServer", "")).strip()
    if is_placeholder(hs_server):
        hs_server = ""
    hs_domain = str(CONFIG.get("HeadscaleMagicDnsDomain", "")).strip()
    if is_placeholder(hs_domain):
        hs_domain = ""
    if not hs_server and not hs_domain:
        return text

    ts_outbound = has_tailscale_outbound(text)
    magic_dns_server = "ts://Tailscale" if ts_outbound else "100.100.100.100"
    magic_dns_target = "Tailscale" if ts_outbound else "Direct"

    policy_lines = ["    # headscale:start"]
    if hs_server:
        policy_lines.extend([
            f"    '{hs_server},+.{hs_server}':",
            "      - https://dns.alidns.com/dns-query#disable-qtype-65=true",
            "      - https://doh.pub/dns-query#disable-qtype-65=true",
        ])
    if hs_domain:
        policy_lines.extend([
            f"    '+.{hs_domain}':",
            f"      - {magic_dns_server}",
        ])
    policy_lines.append("    # headscale:end")
    text = re.sub(
        r'(?m)^(  nameserver-policy:[ \t]*\r?\n)',
        lambda m: m.group(1) + "\n".join(policy_lines) + "\n",
        text,
        count=1,
    )

    filter_lines = ["    # headscale:start"]
    if hs_server:
        filter_lines.extend([f"    - '{hs_server}'", f"    - '+.{hs_server}'"])
    if hs_domain:
        filter_lines.append(f"    - '+.{hs_domain}'")
    filter_lines.append("    # headscale:end")
    text = re.sub(
        r'(?m)^(  fake-ip-filter:[ \t]*\r?\n)',
        lambda m: m.group(1) + "\n".join(filter_lines) + "\n",
        text,
        count=1,
    )

    rule_lines = ["  # headscale:start"]
    if hs_server:
        rule_lines.append(f"  - DOMAIN-SUFFIX,{hs_server},Direct")
    if hs_domain:
        rule_lines.append(f"  - DOMAIN-SUFFIX,{hs_domain},{magic_dns_target}")
    rule_lines.append("  # headscale:end")
    text = re.sub(
        r'(?m)^(rules:[ \t]*\r?\n)',
        lambda m: m.group(1) + "\n".join(rule_lines) + "\n",
        text,
        count=1,
    )
    return text


def infer_ruleset_format(url):
    path = re.split(r"[?#]", url, maxsplit=1)[0].lower()
    if path.endswith(".mrs"):
        return "mrs"
    if path.endswith((".yaml", ".yml")):
        return "yaml"
    return "text"


def apply_adblock(text):
    text = re.sub(r'(?ms)^[ \t]*# adblock:start\r?\n.*?^[ \t]*# adblock:end\r?\n', "", text)

    if not bool(CONFIG.get("EnableAdBlock", False)):
        return text

    url = normalize_url(str(CONFIG.get("AdBlockRuleUrl", "")).strip())
    if not url or is_placeholder(url):
        return text

    fmt = infer_ruleset_format(url)
    rule_block = "  # adblock:start\n  - RULE-SET,adblock,REJECT\n  # adblock:end\n"
    if re.search(r'(?m)^  - RULE-SET,custom_proxy,', text):
        text = re.sub(
            r'(?m)^(  - RULE-SET,custom_proxy,)',
            lambda m: rule_block + m.group(1),
            text,
            count=1,
        )
    else:
        text = re.sub(
            r'(?m)^(rules:[ \t]*\r?\n)',
            lambda m: m.group(1) + rule_block,
            text,
            count=1,
        )

    provider_lines = [
        "  # adblock:start",
        "  adblock:",
        "    type: http",
        "    interval: 86400",
        "    behavior: domain",
        f"    format: {fmt}",
        f"    url: {url}",
        "  # adblock:end",
    ]
    text = re.sub(
        r'(?m)^(rule-providers:[ \t]*\r?\n)',
        lambda m: m.group(1) + "\n".join(provider_lines) + "\n",
        text,
        count=1,
    )
    return text


def is_gateway_config(path, content):
    name = os.path.basename(path).lower()
    return any(k in name for k in ("router", "lan")) or bool(re.search(r"(?m)^\s*auto-redirect:", content))


def apply_proxy_providers(text, subs, enabled, is_router):
    valid_subs = [s.strip() for s in (subs if enabled else []) if s and not is_placeholder(s)]
    sec0_pattern = r'(?ms)^(?:#\s*proxy-providers[^\r\n]*\r?\n|proxy-providers:\r?\n).*?(?=^proxies:)'
    sec1_pattern = r'(?m)^(proxies:)'

    if valid_subs:
        lines = ["# proxy-providers", "proxy-providers:"]
        for i, url in enumerate(valid_subs):
            escaped = str(url).replace("'", "''")
            lines.extend([
                f"  Subscribe_{i}:",
                "    type: http",
                f"    url: '{escaped}'",
                f"    path: ./proxy_providers/subscribe_{i}.yaml",
                "    interval: 86400",
                "    health-check:",
                "      enable: true",
                "      url: https://www.gstatic.com/generate_204",
                "      interval: 300",
            ])
        sec0 = "\n".join(lines) + "\n\n"
        if re.search(sec0_pattern, text):
            text = re.sub(sec0_pattern, sec0, text, count=1)
        else:
            text = re.sub(sec1_pattern, sec0 + r'\1', text, count=1)
    else:
        if is_router:
            template = (
                "# proxy-providers\n"
                "# proxy-providers:\n"
                "#   Subscribe_0:\n"
                "#     type: http\n"
                "#     url: \"https://example.com/sub\"\n"
                "#     path: ./proxy_providers/subscribe_0.yaml\n"
                "#     interval: 86400\n"
                "#     health-check:\n"
                "#       enable: true\n"
                "#       url: https://www.gstatic.com/generate_204\n"
                "#       interval: 300\n\n"
            )
            if re.search(sec0_pattern, text):
                text = re.sub(sec0_pattern, template, text, count=1)
            else:
                text = re.sub(sec1_pattern, template + r'\1', text, count=1)
        else:
            text = re.sub(sec0_pattern, "", text, count=1)

    group_pattern = r'(?ms)(^proxy-groups:\r?\n(?:\s*#[^\r\n]*\r?\n)*\s*- name: Proxy\r?\n\s+type: select\r?\n\s+proxies:\r?\n(?:      - [^\r\n]+\r?\n)+)(?:    use:\r?\n(?:      - [^\r\n]+\r?\n)+)?'

    def repl_group(m):
        if valid_subs:
            return m.group(1) + "    use:\n" + "".join(f"      - Subscribe_{i}\n" for i in range(len(valid_subs)))
        return m.group(1)

    return re.sub(group_pattern, repl_group, text, count=1)


def render_client_yaml(content, src_path):
    text = set_yaml_proxy(content, "Reality", {
        "server": (4, CONFIG["NodeAddress"]),
        "port": (4, int(CONFIG["RealityPort"])),
        "uuid": (4, CONFIG["Uuid"]),
        "servername": (4, CONFIG["RealitySni"]),
        "public-key": (6, CONFIG["RealityPublicKey"]),
        "short-id": (6, CONFIG["ShortId"]),
    })
    text = set_yaml_proxy(text, "Hysteria2", {
        "server": (4, CONFIG["NodeAddress"]),
        "port": (4, int(CONFIG["Hy2Port"])),
        "password": (4, CONFIG["Hy2Password"]),
        "sni": (4, CONFIG["Hy2Sni"]),
    })
    text = set_yaml_proxy(text, "CF-CDN", {
        "server": (4, CONFIG["WsOptimizedDomain"]),
        "port": (4, int(CONFIG["WsPort"])),
        "uuid": (4, CONFIG["WsUuid"]),
        "servername": (4, CONFIG["WsSni"]),
        "path": (6, CONFIG["WsPath"]),
        "Host": (8, CONFIG["WsSni"]),
        "max-early-data": (6, int(CONFIG["WsMaxEarlyData"])),
        "early-data-header-name": (6, CONFIG["WsEarlyDataHeader"]),
    })
    if re.search(r'(?m)^  - name:[ \t]*Tailscale[ \t]*\r?$', text):
        ts_fields = {
            "hostname": (4, str(CONFIG["TailscaleHostname"]).strip() or "mihomo"),
            "ephemeral": (4, bool(CONFIG["TailscaleEphemeral"])),
            "accept-routes": (4, bool(CONFIG["TailscaleAcceptRoutes"])),
        }
        ts_remove = []
        ts_url = str(CONFIG.get("TailscaleControlUrl", "")).strip()
        if ts_url:
            ts_fields["control-url"] = (4, ts_url)
        else:
            ts_remove.append(("control-url", 4))
        ts_key = str(CONFIG.get("TailscaleAuthKey", "")).strip()
        if ts_key:
            ts_fields["auth-key"] = (4, ts_key)
        else:
            ts_remove.append(("auth-key", 4))
        text = set_yaml_proxy(text, "Tailscale", ts_fields, remove_fields=ts_remove)
    text = set_yaml_field(text, "secret", 0, CONFIG["MihomoApiSecret"])
    text = apply_headscale(text)
    text = apply_adblock(text)
    text = apply_proxy_providers(
        text,
        CONFIG.get("ExternalSubscribes", []),
        enabled=bool(CONFIG.get("EnableExternalSubscribes", False)),
        is_router=is_gateway_config(src_path, content),
    )
    return apply_ruleset_proxy(text)


def render_v2ray_nodes():
    node = urllib.parse.quote(str(CONFIG["NodeAddress"]).strip(), safe="")
    sni = urllib.parse.quote(str(CONFIG["RealitySni"]).strip(), safe=".-_")
    hy2_sni = urllib.parse.quote(str(CONFIG["Hy2Sni"]).strip(), safe=".-_")
    hy2_pw = urllib.parse.quote(str(CONFIG["Hy2Password"]), safe="")
    ws_opt = urllib.parse.quote(str(CONFIG["WsOptimizedDomain"]).strip(), safe="")
    ws_sni = urllib.parse.quote(str(CONFIG["WsSni"]).strip(), safe=".-_")
    ws_path = urllib.parse.quote(str(CONFIG["WsPath"]).strip(), safe="/?=&")

    return "\n".join([
        (
            f"vless://{CONFIG['Uuid']}@{node}:{int(CONFIG['RealityPort'])}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni={sni}&fp=chrome&pbk={CONFIG['RealityPublicKey']}"
            f"&sid={CONFIG['ShortId']}&type=tcp&headerType=none#Reality"
        ),
        (
            f"hysteria2://{hy2_pw}@{node}:{int(CONFIG['Hy2Port'])}/"
            f"?sni={hy2_sni}&insecure=0#Hysteria2"
        ),
        (
            f"vless://{CONFIG['WsUuid']}@{ws_opt}:{int(CONFIG['WsPort'])}"
            f"?encryption=none&security=tls&sni={ws_sni}&type=ws&host={ws_sni}"
            f"&path={ws_path}&fp=chrome#CF-CDN"
        ),
    ])


def render_client_url_list(client_files):
    return "\n".join(sorted(set(client_files)))


def pick_one_inbound(inbounds, proto, tag_hint):
    matched = [
        ib for ib in inbounds
        if isinstance(ib, dict) and ib.get("type") == proto and tag_hint in str(ib.get("tag", "")).lower()
    ]
    if len(matched) != 1:
        raise ValueError(f"Expected 1 {proto}/{tag_hint} inbound, found {len(matched)}; aborted.")
    return matched[0]


def render_server_json(content):
    cfg = json.loads(content)
    inbounds = cfg.get("inbounds", [])

    vless = pick_one_inbound(inbounds, "vless", "reality")
    hy2 = pick_one_inbound(inbounds, "hysteria2", "hysteria")
    ws = pick_one_inbound(inbounds, "vless", "ws")

    vless["listen_port"] = int(CONFIG["RealityPort"])
    vless["users"][0]["uuid"] = CONFIG["Uuid"]
    vless["tls"]["server_name"] = CONFIG["RealitySni"]
    vless["tls"]["reality"]["handshake"]["server"] = CONFIG["HandshakeHost"]
    vless["tls"]["reality"]["handshake"]["server_port"] = int(CONFIG["HandshakePort"])
    vless["tls"]["reality"]["private_key"] = CONFIG["RealityPrivateKey"]
    vless["tls"]["reality"]["short_id"] = [CONFIG["ShortId"]]

    hy2["listen_port"] = int(CONFIG["Hy2Port"])
    hy2["users"][0]["password"] = CONFIG["Hy2Password"]
    hy2["tls"]["server_name"] = CONFIG["Hy2Sni"]
    hy2["tls"]["certificate_path"] = CONFIG["CertificatePath"]
    hy2["tls"]["key_path"] = CONFIG["KeyPath"]

    ws["listen_port"] = int(CONFIG["WsPort"])
    ws["users"][0]["uuid"] = CONFIG["WsUuid"]
    ws["tls"]["server_name"] = CONFIG["WsSni"]
    ws["tls"]["certificate_path"] = CONFIG["WsCertificatePath"]
    ws["tls"]["key_path"] = CONFIG["WsKeyPath"]
    ws["transport"]["path"] = CONFIG["WsPath"]
    ws["transport"].setdefault("headers", {})["Host"] = CONFIG["WsSni"]
    ws["transport"]["max_early_data"] = int(CONFIG["WsMaxEarlyData"])
    ws["transport"]["early_data_header_name"] = str(CONFIG["WsEarlyDataHeader"])

    return json.dumps(cfg, indent=2, ensure_ascii=False)


def walk_files(root, exts):
    result = []
    if not os.path.isdir(root):
        return result
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_DIRS]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in exts:
                result.append(os.path.join(dirpath, filename))
    result.sort()
    return result


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.tmp-{uuid.uuid4().hex}"
    try:
        with open(temp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.rstrip("\r\n") + "\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def classify_file(path, content):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".yaml":
        if (re.search(r'(?m)^proxies:[ \t]*\r?$', content) and
                re.search(r'(?m)^  - name:[ \t]*(?:Reality|Hysteria2)[ \t]*\r?$', content)):
            return "client_yaml"
    elif ext == ".json":
        if re.search(r'"tag"\s*:\s*"[^"]*(?:reality-in|hysteria-in)"', content, re.IGNORECASE):
            return "server_json"
    elif ext == ".txt":
        if os.path.basename(path).lower() == "v2ray-nodes.txt" or (
                "vless://" in content and "hysteria2://" in content):
            return "client_nodes"
    return None


def resolve_target_path(raw_path, repo_root):
    if os.path.isabs(raw_path):
        return os.path.abspath(raw_path)
    cwd_candidate = os.path.abspath(raw_path)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    return os.path.abspath(os.path.join(repo_root, raw_path))


def collect_jobs(repo_root, scope, targets):
    jobs = {}
    if targets:
        for raw in targets:
            resolved = resolve_target_path(raw, repo_root)
            if os.path.isfile(resolved):
                with open(resolved, "r", encoding="utf-8") as f:
                    content = f.read()
                kind = classify_file(resolved, content)
                if not kind:
                    raise ValueError(f"Unsupported config template: {resolved}; aborted.")
                jobs[resolved] = (kind, content)
            elif os.path.isdir(resolved):
                for path in walk_files(resolved, {".yaml", ".json", ".txt"}):
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    kind = classify_file(path, content)
                    if kind:
                        jobs[path] = (kind, content)
            else:
                raise ValueError(f"Target path not found: {raw}; aborted.")
        return jobs

    if scope in ("all", "client"):
        for path in walk_files(os.path.join(repo_root, "client"), {".yaml", ".txt"}):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            kind = classify_file(path, content)
            if kind in ("client_yaml", "client_nodes"):
                jobs[path] = (kind, content)

    if scope in ("all", "server"):
        for path in walk_files(os.path.join(repo_root, "server"), {".json"}):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            kind = classify_file(path, content)
            if kind == "server_json":
                jobs[path] = (kind, content)

    return jobs


def resolve_output_path(src_path, repo_root, out_base, in_place):
    if in_place:
        return src_path
    repo_abs = os.path.abspath(repo_root)
    src_abs = os.path.abspath(src_path)
    try:
        common = os.path.commonpath([repo_abs, src_abs])
    except ValueError:
        common = ""
    if common == repo_abs:
        return os.path.join(out_base, os.path.relpath(src_abs, repo_abs))
    return os.path.join(out_base, os.path.basename(src_abs))


def parse_args():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(
        description="Batch-replace required placeholders in client/ and server/ config templates."
    )
    parser.add_argument("--only", choices=("all", "client", "server"), default="all", help="Target scope when -t is not set (default: all)")
    parser.add_argument("-t", "--target", action="append", default=[], help="Specific template file or directory to render (repeatable)")
    parser.add_argument("-o", "--output", default=os.path.join(repo_root, "dist"), help="Output directory (default: <repo>/dist)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite target files directly instead of writing to dist/")
    parser.add_argument("-c", "--config", default=None, help="Config JSON file (default: <repo>/config.json)")
    parser.add_argument("-p", "--preview", action="store_true", help="Dry-run scan without writing files")
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loaded = load_config(repo_root, args.config)

    jobs = collect_jobs(repo_root, args.only, args.target)
    if not jobs:
        raise ValueError("No matching config templates found; aborted.")

    need_client = any(kind in ("client_yaml", "client_nodes") for kind, _ in jobs.values())
    need_server = any(kind == "server_json" for kind, _ in jobs.values())
    assert_values(CONFIG, need_client, need_server)
    print(f"Loaded config: {os.path.abspath(loaded)}")

    rendered = {}
    client_files_by_dir = {}
    out_base = os.path.abspath(args.output)
    for src_path in sorted(jobs):
        kind, content = jobs[src_path]
        if kind == "client_yaml":
            text = render_client_yaml(content, src_path)
        elif kind == "client_nodes":
            text = render_v2ray_nodes()
        else:
            text = render_server_json(content)
        if PLACEHOLDER_RE.search(text):
            raise ValueError(f"Unresolved placeholder found in {src_path}; aborted.")
        dst_path = resolve_output_path(src_path, repo_root, out_base, args.in_place)
        rendered[dst_path] = text
        if kind in ("client_yaml", "client_nodes"):
            client_files_by_dir.setdefault(os.path.dirname(dst_path), []).append(os.path.basename(dst_path))

    if not args.in_place:
        for client_dir, names in sorted(client_files_by_dir.items()):
            rendered[os.path.join(client_dir, "url")] = render_client_url_list(names)

    active = []
    if need_client:
        if str(CONFIG.get("HeadscaleServer", "")).strip() or str(CONFIG.get("HeadscaleMagicDnsDomain", "")).strip():
            active.append("headscale")
        if CONFIG.get("EnableAdBlock"):
            active.append("adblock")
        if CONFIG.get("EnableExternalSubscribes") and CONFIG.get("ExternalSubscribes"):
            active.append("proxy-providers")
        active.append(f"ruleset-proxy={resolve_ruleset_prefix() or '(direct)'}")
    feature_desc = f" [{', '.join(active)}]" if active else ""

    scope_desc = "target" if args.target else args.only
    if args.preview:
        print(f"Preview ({scope_desc}): {len(rendered)} files{feature_desc}")
        for dst_path in sorted(rendered):
            print(dst_path)
        return

    for dst_path in sorted(rendered):
        atomic_write(dst_path, rendered[dst_path])

    mode = "in-place" if args.in_place else out_base
    print(f"Rendered {len(rendered)} files ({scope_desc}){feature_desc} -> {mode}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
