#!/usr/bin/env python3
"""用 fnpack.json 重新生成 README 里的「现有应用」表格。

CI 在提交索引前跑这一步，保证 README 表格永远和索引一致 —— 加成员时
不必再手工维护这张表（曾经漏过 wildwork 和 fnmusic-ext）。

只替换 "## 现有应用" 到下一个二级标题之间的内容，其余 README 原样保留。
"""
from __future__ import annotations

import json
import os
import sys

SECTION = "## 现有应用"
NEXT_H2 = "## "


def _verkey(v: str):
    """版本号排序键：2.10.2 要排在 2.9.0 前面（字符串比较会反）。"""
    import re

    out = []
    for part in re.split(r"[.\-+]", v):
        out.append(int(part) if part.isdigit() else 0)
    return out


def _latest(releases: dict) -> str:
    if not releases:
        return "—"
    try:
        return sorted(releases, key=_verkey)[-1]
    except Exception:  # noqa: BLE001
        return sorted(releases)[-1]


def _one_line(text: str, limit: int = 52) -> str:
    t = " ".join((text or "").split())
    # 去掉会破坏表格的竖线与反引号
    t = t.replace("|", "／").replace("`", "")
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in ("。", "；", "，", ". "):
        i = cut.rfind(sep)
        if i > limit // 2:
            return cut[: i + 1]
    return cut + "…"


def build_table(doc: dict) -> str:
    apps = doc.get("apps") or {}
    lines = [
        "| 应用 | 说明 | 最新版本 | 分类 |",
        "|---|---|---|---|",
    ]
    for name in sorted(apps, key=lambda n: (apps[n].get("display_name") or n).lower()):
        a = apps[name]
        disp = (a.get("display_name") or name).replace("|", "／")
        desc = _one_line(a.get("desc"))
        ver = _latest(a.get("releases") or {})
        cats = "、".join(a.get("categories") or []) or "—"
        lines.append(f"| {disp} | {desc} | {ver} | {cats} |")
    lines.append("")
    lines.append(f"共 **{len(apps)}** 个应用。本表由 CI 从 `fnpack.json` 自动生成，**请勿手改**。")
    return "\n".join(lines)


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    idx = os.path.join(root, "fnpack.json")
    readme = os.path.join(root, "README.md")

    if not os.path.exists(idx):
        print("[readme] 没有 fnpack.json，跳过")
        return 0
    if not os.path.exists(readme):
        print("[readme] 没有 README.md，跳过")
        return 0

    doc = json.load(open(idx, encoding="utf-8"))
    text = open(readme, encoding="utf-8").read()

    if SECTION not in text:
        print(f"[readme] README 里找不到「{SECTION}」，未改动")
        return 1

    head, _, tail = text.partition(SECTION)
    # tail 从 SECTION 之后开始，找下一个二级标题
    idx_next = tail.find("\n" + NEXT_H2)
    if idx_next < 0:
        print("[readme] 「现有应用」之后没有其它二级标题，未改动")
        return 1
    rest = tail[idx_next:]

    table = build_table(doc)
    new_text = f"{head}{SECTION}\n\n{table}\n\n{rest.lstrip(chr(10))}"

    if new_text == text:
        print("[readme] 表格无变化")
        return 0

    open(readme, "w", encoding="utf-8").write(new_text)
    n = len(doc.get("apps") or {})
    print(f"[readme] 已按索引重写表格：{n} 个应用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
