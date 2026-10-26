#!/usr/bin/env python3
"""把 apps.txt 里各仓库的 fnpack.json 合并成集合源索引。

要点：
  * 应用仓库是元数据的唯一来源，索引只做汇总与校验
  * 相对路径（./xxx）会被改写成指向该应用仓库的绝对 raw 地址，
    否则解析方会按索引仓库去取，图标/说明全 404
  * 每个包的 download_url 做一次 HEAD 校验，取不到就丢弃该版本
  * sha256 以实测为准：与声明不符时用实测值并告警
  * 成员可以只发 Release（不带 fnpack.json）：apps.txt 里写
    `owner/repo!release [icon_url]`，脚本会直接读 .fpk 资产合成条目
  * 成员也可以在 Gitee 上：写 `gitee:owner/repo!release [icon_url]`。
    Gitee 的列表接口不回 assets，必须逐个 tag 查详情；时间字段是
    created_at 而不是 published_at。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
GITEE_TOKEN = os.environ.get("GITEE_TOKEN") or ""
BRANCHES = ("main", "master")
SOURCE_NAME = "aaiuh飞牛应用源"
SOURCE_DESC = "飞牛 fnOS 原生应用集合。免费开源，跟随各应用上游更新。"

# 本地演练用：跳过真实下载与哈希计算（CI 里不设该变量）
DRY = os.environ.get("MERGE_DRY_RUN") == "1"


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


def gitee(path: str):
    """Gitee API v5。匿名可用但限流低；有 GITEE_TOKEN 时带上。"""
    req = urllib.request.Request(f"{GITEE_API}{path}")
    req.add_header("User-Agent", "fnos-apps-index")
    if GITEE_TOKEN:
        req.add_header("Authorization", f"token {GITEE_TOKEN}")
    with urllib.request.urlopen(req, timeout=45) as r:
        # Gitee 的 changelog 里可能带裸控制字符，宽松解析
        return json.loads(r.read().decode("utf-8", "replace"), strict=False)


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


def absolutize(url: str, repo: str, branch: str, host: str = "github") -> str:
    """把 ./xxx 这类相对地址改写成应用仓库的绝对 raw 地址。"""
    if not url or url.startswith(("http://", "https://")):
        return url
    rel = url.lstrip("./")
    if host == "gitee":
        return f"https://gitee.com/{repo}/raw/{branch}/{rel}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


def head_ok(url: str) -> bool:
    if DRY:
        return url.startswith("https://")
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
    if DRY:
        return ("0" * 64, 0)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "fnos-apps-index")
    h = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(req, timeout=180) as r:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def read_fpk_manifest(url: str) -> dict:
    """下载一个 fpk（tar.gz），读出包内 manifest 的键值。仅 Release 模式用。"""
    import tarfile

    attempts = [url]
    if url.startswith("https://github.com/"):
        attempts.append("https://gh-proxy.com/" + url)  # 直连不稳时的兜底

    fd, tmp = tempfile.mkstemp(suffix=".fpk")
    os.close(fd)
    try:
        text = None
        for attempt in attempts:
            try:
                req = urllib.request.Request(attempt)
                req.add_header("User-Agent", "fnos-apps-index")
                with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as fh:
                    while chunk := r.read(1 << 20):
                        fh.write(chunk)
                with tarfile.open(tmp, "r:gz") as tf:
                    try:
                        mf = tf.extractfile("manifest")
                    except KeyError:
                        return {}
                    if not mf:
                        return {}
                    text = mf.read().decode("utf-8", "replace")
                break
            except Exception as e:  # noqa: BLE001
                log(f"    读 fpk 失败（{attempt.split('/')[2]}）：{e}")
        if text is None:
            return {}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    meta: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and k not in meta:
            meta[k] = v
    return meta


def _assets_of(rel: dict, repo: str, host: str) -> list:
    """Gitee 的 releases 列表不回 assets，得逐个 tag 查详情。"""
    assets = rel.get("assets") or []
    if assets or host != "gitee":
        return assets
    tag = rel.get("tag_name") or ""
    if not tag:
        return []
    try:
        detail = gitee(f"/repos/{repo}/releases/tags/{tag}")
        return (detail or {}).get("assets") or []
    except Exception as e:  # noqa: BLE001
        log(f"    {repo} 取 {tag} 详情失败：{e}")
        return []


def fetch_from_releases(repo: str, icon: str = "", categories: list[str] | None = None,
                        limit: int = 6, host: str = "github") -> dict | None:
    """成员只发 Release、没有 fnpack.json 时，直接读 .fpk 资产合成片段。"""
    try:
        if host == "gitee":
            # Gitee 的 releases 列表按创建时间「升序」返回，per_page=limit 会拿到最老的几个。
            # 必须全量取回再按时间降序截断，否则永远拿不到最新版。
            rels = gitee("/repos/%s/releases?per_page=100" % repo)
            if isinstance(rels, list):
                rels = sorted(
                    [r for r in rels if isinstance(r, dict)],
                    key=lambda x: str(x.get("created_at") or ""),
                    reverse=True,
                )[:limit]
        else:
            rels = gh(f"/repos/{repo}/releases?per_page={limit}")
    except Exception as e:  # noqa: BLE001
        log(f"  {repo} 读取 Releases 失败：{e}")
        return None
    if not isinstance(rels, list) or not rels:
        log(f"  {repo} 没有任何 Release")
        return None

    picked = []
    for rel in rels:
        if not isinstance(rel, dict):
            continue
        assets = _assets_of(rel, repo, host)
        fpk = next((a for a in assets if (a.get("name") or "").endswith(".fpk")
                    and a.get("browser_download_url")), None)
        if fpk:
            picked.append((rel, fpk))
    if not picked:
        log(f"  {repo} 的 Release 里没有 .fpk 资产")
        return None

    meta = read_fpk_manifest(picked[0][1]["browser_download_url"])
    if not meta.get("appname"):
        # 兜底：manifest 读不到时按资产名推断（wildwork-2.9.5-1.fpk → wildwork）
        import re

        m = re.match(r"(.+?)-\d+\.\d+\.\d+(?:-\d+)?\.fpk$", picked[0][1]["name"])
        if not m:
            log(f"  {repo} 最新包读不到 appname，资产名也无法推断，放弃")
            return None
        log(f"  {repo} manifest 不可读，按资产名推断 appname={m.group(1)}")
        meta = {"appname": m.group(1), "display_name": m.group(1)}

    name = meta["appname"]
    releases = {}
    for rel, fpk in picked:
        # 资产名比 tag 精确：wildwork-2.9.5-1.fpk → 2.9.5-1
        import re

        m = re.search(r"-(\d+\.\d+\.\d+(?:-\d+)?)\.fpk$", fpk["name"])
        ver = m.group(1) if m else (rel.get("tag_name") or "").lstrip("vV")
        if not ver:
            continue
        # Gitee 没有 published_at，退回 created_at
        ts = rel.get("published_at") or rel.get("created_at") or ""
        releases[ver] = {
            "changelog": (rel.get("body") or "").strip()[:4000],
            "updated_at": str(ts)[:10],
            "os_min_version": meta.get("os_min_version") or "1.1.0",
            "packages": {"x86": {"download_url": fpk["browser_download_url"]}},
        }
    if not releases:
        return None

    # platform=all 展开成两种架构：FnDepot 按架构匹配，[ "all" ] 匹配不上任何一边
    plats = [p.strip() for p in (meta.get("platform") or "x86").split(",") if p.strip()]
    if "all" in plats:
        plats = ["x86", "arm"]

    owner = repo.split("/")[0]
    if host == "gitee":
        readme_url = f"https://gitee.com/{repo}/raw/main/README.md"
        owner_url = f"https://gitee.com/{owner}"
        issues_url = f"https://gitee.com/{repo}/issues"
    else:
        readme_url = f"https://raw.githubusercontent.com/{repo}/main/README.md"
        owner_url = f"https://github.com/{owner}"
        issues_url = f"https://github.com/{repo}/issues"

    app = {
        "display_name": meta.get("display_name") or name,
        "desc": meta.get("desc") or "",
        # FnDepot 校验：platform 必须是字符串数组
        "platform": plats,
        # FnDepot 校验：categories 不能为空
        "categories": categories or ["系统工具"],
        "icon_url": icon,
        "preview_urls": [],
        "readme_url": readme_url,
        "bug_report_url": issues_url,
        "maintainer": meta.get("maintainer") or owner,
        "maintainer_url": owner_url,
        "distributor": meta.get("distributor") or meta.get("maintainer") or owner,
        "distributor_url": owner_url,
        "run_as": "package",
        "install_type": "",
        "is_docker": False,
        "service_port": meta.get("service_port") or "",
        "releases": releases,
    }
    log(f"    合成 {name}，版本 {sorted(releases)}，元数据取自 {picked[0][1]['name']}")
    return {"apps": {name: app}}


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apps_file = os.path.join(root, "apps.txt")
    out_file = os.path.join(root, "fnpack.json")

    members = []
    for line in open(apps_file, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        spec = parts[0]
        icon = parts[1] if len(parts) > 1 else ""
        cats = [c.strip() for c in parts[2].split(",") if c.strip()] if len(parts) > 2 else []
        members.append((spec, icon, cats))
    log(f"成员仓库 {len(members)} 个：{', '.join(m[0] for m in members)}")

    merged: dict[str, dict] = {}
    for spec, icon, cats in members:
        host = "github"
        if spec.startswith("gitee:"):
            host = "gitee"
            spec = spec[len("gitee:"):]

        if spec.endswith("!release"):
            repo = spec[: -len("!release")]
            branch = "main"  # Release 模式没有 fnpack.json，图标走绝对地址
            doc = fetch_from_releases(repo, icon, cats, host=host)
            if not doc:
                log(f"  ✗ {repo} Release 模式取不到可用版本，跳过")
                continue
            apps = doc.get("apps") or {}
            log(f"  ✓ {repo}（Release 模式，{host}）含 {len(apps)} 个应用")
        else:
            repo = spec
            if host != "github":
                log(f"  ✗ {repo} fnpack.json 模式目前只支持 GitHub，跳过")
                continue
            doc, branch = fetch_fragment(repo)
            if not doc:
                log(f"  ✗ {repo} 取不到 fnpack.json，跳过")
                continue
            branch = branch or "main"
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
                    app[key] = absolutize(app[key], repo, branch, host)
            app["preview_urls"] = [
                absolutize(u, repo, branch, host) for u in app.get("preview_urls") or []
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
