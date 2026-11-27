#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch-replace required <placeholder> markers across client/ and server/ templates.

Outputs rendered configs to dist/ by default (gitignored), leaving tracked
templates untouched. Optional feature additions live in scripts/feature-generate.py.

Usage:
    python scripts/config-batch.py --preview
    python scripts/config-batch.py
    python scripts/config-batch.py --only client
    python scripts/config-batch.py --only server
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

# Local overrides can be placed in config.local.json (gitignored).
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

    # Client API
    "MihomoApiSecret": "<api-secret>",
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


def load_local_config(repo_root, explicit_path=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [explicit_path] if explicit_path else [
        os.path.join(repo_root, "config.local.json"),
        os.path.join(script_dir, "config.local.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Failed to load local config ({path}): {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"Local config must be a JSON object: {path}")
            for key, val in data.items():
                if key in CONFIG:
                    CONFIG[key] = val
            return path
    return None


def assert_values(values, scope):
    required = set()
    if scope in ("all", "client"):
        required |= CLIENT_REQUIRED
    if scope in ("all", "server"):
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

    if not re.fullmatch(r"^(?:[0-9a-fA-F]{2}){1,8}$", str(values["ShortId"]).strip()):
        raise ValueError("ShortId must be 2-16 even-length hex chars; aborted.")

    port_keys = ["RealityPort", "Hy2Port", "WsPort"]
    if scope in ("all", "server"):
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


def yaml_scalar(value):
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def set_yaml_field(block, field, spaces, value):
    pattern = rf'(?m)^({" " * spaces}{re.escape(field)}:[ \t]*).*$'
    if len(list(re.finditer(pattern, block))) != 1:
        raise ValueError(f"Cannot uniquely locate YAML field {field}; aborted.")
    return re.sub(pattern, lambda m: m.group(1) + yaml_scalar(value), block, count=1)


def set_yaml_proxy(text, name, fields):
    pattern = rf'(?ms)^(  - name: {re.escape(name)}[^\r\n]*\r?\n)(.*?)(?=^  - name: |^[^\s#]|\Z)'
    if len(list(re.finditer(pattern, text))) != 1:
        raise ValueError(f"Cannot uniquely locate Mihomo proxy {name}; aborted.")

    def repl(m):
        header, block = m.group(1), m.group(2)
        for field, (spaces, val) in fields.items():
            block = set_yaml_field(block, field, spaces, val)
        return header + block

    return re.sub(pattern, repl, text, count=1)


def render_client_yaml(content):
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
    return set_yaml_field(text, "secret", 0, CONFIG["MihomoApiSecret"])


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


def parse_args():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(
        description="Batch-replace required placeholders in client/ and server/ config templates."
    )
    parser.add_argument("--only", choices=("all", "client", "server"), default="all", help="Target scope (default: all)")
    parser.add_argument("-o", "--output", default=os.path.join(repo_root, "dist"), help="Output directory (default: <repo>/dist)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite templates in client/ and server/ directly")
    parser.add_argument("-l", "--local-config", default=None, help="Optional local JSON override file (default: config.local.json)")
    parser.add_argument("-p", "--preview", action="store_true", help="Dry-run scan without writing files")
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loaded = load_local_config(repo_root, args.local_config)
    assert_values(CONFIG, args.only)
    if loaded:
        print(f"Loaded local config: {os.path.abspath(loaded)}")

    rendered = {}

    if args.only in ("all", "client"):
        client_dir = os.path.join(repo_root, "client")
        for path in walk_files(client_dir, {".yaml"}):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if (re.search(r'(?m)^proxies:[ \t]*\r?$', content) and
                    re.search(r'(?m)^  - name:[ \t]*(?:Reality|Hysteria2)[ \t]*\r?$', content)):
                rendered[os.path.relpath(path, repo_root)] = render_client_yaml(content)
        nodes_path = os.path.join(client_dir, "v2ray-nodes.txt")
        if os.path.isfile(nodes_path):
            rendered[os.path.relpath(nodes_path, repo_root)] = render_v2ray_nodes()

    if args.only in ("all", "server"):
        server_dir = os.path.join(repo_root, "server")
        for path in walk_files(server_dir, {".json"}):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if re.search(r'"tag"\s*:\s*"[^"]*(?:reality-in|hysteria-in)"', content, re.IGNORECASE):
                rendered[os.path.relpath(path, repo_root)] = render_server_json(content)

    if not rendered:
        raise ValueError("No matching config templates found; aborted.")

    for rel, text in rendered.items():
        if PLACEHOLDER_RE.search(text):
            raise ValueError(f"Unresolved placeholder found in {rel}; aborted.")

    out_base = repo_root if args.in_place else os.path.abspath(args.output)
    if args.preview:
        print(f"Preview ({args.only}): {len(rendered)} files -> {out_base}")
        for rel in sorted(rendered):
            print(os.path.join(out_base, rel))
        return

    for rel in sorted(rendered):
        atomic_write(os.path.join(out_base, rel), rendered[rel])

    mode = "in-place" if args.in_place else out_base
    print(f"Rendered {len(rendered)} files ({args.only}) -> {mode}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
