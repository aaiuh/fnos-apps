#!/usr/bin/env python3
"""把 apps.txt 里各仓库的 fnpack.json 合并成集合源索引。

要点：
  * 应用仓库是元数据的唯一来源，索引只做汇总与校验
  * 相对路径（./xxx）会被改写成指向该应用仓库的绝对 raw 地址，
    否则解析方会按索引仓库去取，图标/说明全 404
  * 每个包的 download_url 做一次 HEAD 校验，取不到就丢弃该版本
  * sha256 以实测为准：与声明不符时用实测值并告警
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
BRANCHES = ("main", "master")
SOURCE_NAME = "aaiuh飞牛应用源"
SOURCE_DESC = "飞牛 fnOS 原生应用集合。免费开源，跟随各应用上游更新。"


def log(msg: str) -> None:
    print(f"[merge] {msg}", flush=True)


def gh(path: str) -> dict:
    req = urllib.request.Request(f"{API}{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "fnos-apps-index")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def fetch_fragment(repo: str) -> tuple[dict, str] | tuple[None, None]:
    """取某个应用仓库的 fnpack.json，返回 (内容, 分支名)。"""
    for br in BRANCHES:
        try:
            data = gh(f"/repos/{repo}/contents/fnpack.json?ref={br}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            log(f"  {repo}@{br} API 错误 {e.code}")
            continue
        except Exception as e:  # noqa: BLE001
            log(f"  {repo}@{br} 请求失败：{e}")
            continue
        raw = data.get("content")
        if not raw:
            continue
        import base64

        try:
            doc = json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"  {repo}@{br} fnpack.json 解析失败：{e}")
            continue
        return doc, br
    return None, None


def absolutize(url: str, repo: str, branch: str) -> str:
    """把 ./xxx 这类相对地址改写成应用仓库的绝对 raw 地址。"""
    if not url or url.startswith(("http://", "https://")):
        return url
    rel = url.lstrip("./")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


def head_ok(url: str) -> bool:
    if not url.startswith("https://"):
        return False
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "fnos-apps-index")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return 200 <= r.status < 400
    except Exception:  # noqa: BLE001
        return False


def sha256_of(url: str) -> tuple[str, int]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "fnos-apps-index")
    h = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(req, timeout=180) as r:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apps_file = os.path.join(root, "apps.txt")
    out_file = os.path.join(root, "fnpack.json")

    members = []
    for line in open(apps_file, encoding="utf-8"):
        s = line.strip()
        if s and not s.startswith("#"):
            members.append(s)
    log(f"成员仓库 {len(members)} 个：{', '.join(members)}")

    merged: dict[str, dict] = {}
    for repo in members:
        doc, branch = fetch_fragment(repo)
        if not doc:
            log(f"  ✗ {repo} 取不到 fnpack.json，跳过")
            continue
        apps = doc.get("apps") or {}
        log(f"  ✓ {repo}@{branch} 含 {len(apps)} 个应用")

        for name, app in apps.items():
            if name in merged:
                log(f"    ! 应用名 {name} 与前面的成员重复，保留先出现的那个")
                continue
            app = dict(app)
            # 相对地址改成指向该应用仓库
            for key in ("icon_url", "readme_url"):
                if key in app:
                    app[key] = absolutize(app[key], repo, branch)
            app["preview_urls"] = [
                absolutize(u, repo, branch) for u in app.get("preview_urls") or []
            ]

            kept = {}
            for ver, rel in (app.get("releases") or {}).items():
                pkg = (rel.get("packages") or {}).get("x86")
                if not pkg or not pkg.get("download_url"):
                    log(f"    - {name} {ver} 没有 x86 包，丢弃")
                    continue
                url = pkg["download_url"]
                if not head_ok(url):
                    log(f"    - {name} {ver} 下载地址不可达，丢弃")
                    continue
                try:
                    actual_sha, actual_size = sha256_of(url)
                except Exception as e:  # noqa: BLE001
                    log(f"    - {name} {ver} 下载失败（{e}），丢弃")
                    continue
                if pkg.get("sha256") and pkg["sha256"] != actual_sha:
                    log(f"    ! {name} {ver} 声明 sha256 与实测不符，改用实测值")
                rel = dict(rel)
                rel["packages"] = dict(rel["packages"])
                rel["packages"]["x86"] = {
                    "download_url": url,
                    "sha256": actual_sha,
                    "size": actual_size,
                }
                kept[ver] = rel
                log(f"    + {name} {ver} {actual_size} 字节 {actual_sha[:12]}…")

            if not kept:
                log(f"    ! {name} 没有可用版本，跳过该应用")
                continue
            app["releases"] = kept
            merged[name] = app

    if not merged:
        log("没有任何可用应用，保持原索引不变")
        return 1

    index = {
        "schema_version": "2",
        "source_info": {
            "name": SOURCE_NAME,
            "author": "aaiuh",
            "homepage": "https://github.com/aaiuh/fnos-apps",
            "description": SOURCE_DESC,
        },
        "apps": dict(sorted(merged.items())),
    }
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    log(f"写入 {out_file}：{len(merged)} 个应用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
