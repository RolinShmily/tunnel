#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply optional feature overlays to Mihomo client YAML configs (idempotent).

Supported overlays:
  - Headscale control-plane & MagicDNS rules (DNS policy, fake-ip-filter, direct rules)
  - External proxy-providers subscriptions (injected into Proxy group)
  - Ruleset & dashboard download mirror prefix (RuleSetProxy)

Usage:
    python scripts/feature-generate.py --preview
    python scripts/feature-generate.py
    python scripts/feature-generate.py -t dist/client/mihomo-clash.yaml
"""

import argparse
import json
import os
import re
import sys
import uuid

IGNORED_DIRS = {"__pycache__", ".git"}
PLACEHOLDER_RE = re.compile(r"<[a-z0-9-]+>")

# Default schema; fill values in <repo>/config.json (copy from config.json.example).
FEATURES = {
    # Headscale (leave empty to remove/skip)
    "HeadscaleServer": "",
    "HeadscaleMagicDnsDomain": "",

    # External subscriptions (proxy-providers)
    "ExternalSubscribes": [],
    "EnableExternalSubscribes": False,

    # Mirror prefix for external-ui-url and rule-providers ("" for direct)
    "RuleSetProxy": "https://gh-proxy.com/",
}


def is_placeholder(val):
    return bool(PLACEHOLDER_RE.fullmatch(str(val).strip()))


def load_features(repo_root, explicit_path=None):
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
    section = data.get("feature-generate")
    if not isinstance(section, dict):
        raise ValueError(f"Missing or invalid 'feature-generate' section in {path}; aborted.")
    for key, val in section.items():
        if key in FEATURES:
            FEATURES[key] = val
    return path


def assert_features(values):
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


def resolve_ruleset_prefix():
    raw = str(FEATURES.get("RuleSetProxy", "")).strip()
    return "" if (not raw or is_placeholder(raw)) else raw


def normalize_url(url):
    text = str(url)
    cut = max(text.rfind("https://"), text.rfind("http://"))
    return text[cut:] if cut > 0 else text


def apply_ruleset_proxy(text):
    prefix = resolve_ruleset_prefix()
    text = re.sub(
        r'(?m)^(\s*external-ui-url:\s*["\']?)([^"\'\r\n]+)(["\']?)',
        lambda m: f"{m.group(1)}{prefix}{normalize_url(m.group(2).strip())}{m.group(3)}",
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
        lambda m: m.group(1) + prefix + normalize_url(m.group(2).strip()),
        text[start.end():section_end],
    )
    return text[:start.end()] + section + text[section_end:]


def apply_headscale(text):
    # Strip any previously injected headscale blocks first for idempotency.
    text = re.sub(r'(?ms)^[ \t]*# headscale:start\r?\n.*?^[ \t]*# headscale:end\r?\n', "", text)

    hs_server = str(FEATURES.get("HeadscaleServer", "")).strip()
    if is_placeholder(hs_server):
        hs_server = ""
    hs_domain = str(FEATURES.get("HeadscaleMagicDnsDomain", "")).strip()
    if is_placeholder(hs_domain):
        hs_domain = ""
    if not hs_server and not hs_domain:
        return text

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
            "      - 100.100.100.100",
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
        rule_lines.append(f"  - DOMAIN-SUFFIX,{hs_domain},Direct")
    rule_lines.append("  # headscale:end")
    text = re.sub(
        r'(?m)^(rules:[ \t]*\r?\n)',
        lambda m: m.group(1) + "\n".join(rule_lines) + "\n",
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


def collect_targets(target_path):
    if os.path.isfile(target_path):
        return [target_path]
    if not os.path.isdir(target_path):
        raise ValueError(f"Target path not found: {target_path}; aborted.")
    files = []
    for dirpath, dirnames, filenames in os.walk(target_path):
        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_DIRS]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() == ".yaml":
                files.append(os.path.join(dirpath, filename))
    files.sort()
    return files


def atomic_write(path, text):
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
    dist_client = os.path.join(repo_root, "dist", "client")
    default_target = dist_client if os.path.isdir(dist_client) else os.path.join(repo_root, "client")
    parser = argparse.ArgumentParser(
        description="Apply optional feature overlays (Headscale, proxy-providers, ruleset proxy) to Mihomo YAML configs."
    )
    parser.add_argument("-t", "--target", default=default_target, help="Target YAML file or directory (default: dist/client if present, else client/)")
    parser.add_argument("-c", "--config", default=None, help="Config JSON file (default: <repo>/config.json)")
    parser.add_argument("-p", "--preview", action="store_true", help="Dry-run scan without writing files")
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loaded = load_features(repo_root, args.config)
    assert_features(FEATURES)
    print(f"Loaded config: {os.path.abspath(loaded)}")

    files = collect_targets(os.path.abspath(args.target))
    updates = {}
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not re.search(r'(?m)^proxies:[ \t]*\r?$', content):
            continue
        text = apply_headscale(content)
        text = apply_proxy_providers(
            text,
            FEATURES.get("ExternalSubscribes", []),
            enabled=bool(FEATURES.get("EnableExternalSubscribes", False)),
            is_router=is_gateway_config(path, content),
        )
        text = apply_ruleset_proxy(text)
        updates[path] = text

    if not updates:
        raise ValueError(f"No Mihomo YAML configs matched under {args.target}; aborted.")

    active = []
    if str(FEATURES.get("HeadscaleServer", "")).strip() or str(FEATURES.get("HeadscaleMagicDnsDomain", "")).strip():
        active.append("headscale")
    if FEATURES.get("EnableExternalSubscribes") and FEATURES.get("ExternalSubscribes"):
        active.append("proxy-providers")
    active.append(f"ruleset-proxy={resolve_ruleset_prefix() or '(direct)'}")

    if args.preview:
        print(f"Preview: {len(updates)} files ({', '.join(active)})")
        for path in sorted(updates):
            print(path)
        return

    for path in sorted(updates):
        atomic_write(path, updates[path])

    print(f"Applied features to {len(updates)} files ({', '.join(active)}).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
