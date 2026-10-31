#!/usr/bin/env python3
"""修复 hello-agents 工作记忆在中文场景下检索失效的问题。

问题
----
`hello_agents/memory/types/working.py` 的 `WorkingMemory.retrieve()` 用 sklearn
TF-IDF 计算相关度，默认分词正则 `(?u)\\b\\w\\w+\\b` 依赖空格与词边界。中文整句会被
标点切成几个大块，查询与记忆之间没有任何公共 token：

    查询「你还记得我的名字，以及我正在做什么项目吗？」
      -> {"你还记得我的名字", "以及我正在做什么项目吗"}
    记忆「玩家说：你好，我叫小林，我正在做一个赛博小镇课程项目…」
      -> {"玩家说", "你好", "我叫小林", "我正在做一个赛博小镇课程项目"}

两组交集为空 -> cosine 与关键词分数均为 0 -> 被 `if final_score > 0` 全部丢弃
-> `retrieve()` 恒返回 []，表现为「记忆组退化成了无记忆组」，而日志里
「💾 对话已保存到…」是正常的，极易误判为「记忆没生效」。

修复
----
在所有分数都为 0 时退化为「按时间倒序返回最近 limit 条」——这正是工作记忆应有的
语义（最近 N 条上下文），而不是让检索结果为空。

影响范围
--------
仅影响 MEMORY_MODE=on。无记忆模式下根本不创建 MemoryManager，因此基线数据在打补丁
前后完全等价，不需要重跑。

用法
----
    python3 patches/apply_working_memory_fix.py            # 应用
    python3 patches/apply_working_memory_fix.py --revert   # 还原（需有 .bak）
    python3 patches/apply_working_memory_fix.py --check    # 只检查状态
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import shutil
import sys

MARKER = "退化为按时间倒序返回最近记忆"
ANCHOR = "scored_memories.sort(key=lambda x: x[0], reverse=True)"

SNIPPET = (
    "{ind}# 中文无空格场景下 TF-IDF/关键词可能全为 0,退化为按时间倒序返回最近记忆\n"
    "{ind}if not scored_memories:\n"
    "{ind}    recent = sorted(filtered_memories, key=lambda m: m.timestamp, reverse=True)\n"
    "{ind}    return recent[:limit]\n"
)


def locate_working_py() -> pathlib.Path:
    spec = importlib.util.find_spec("hello_agents")
    if spec is None or not spec.origin:
        sys.exit("找不到 hello_agents，请先 pip install 'hello-agents>=0.2.4,<=0.2.9'")
    path = pathlib.Path(spec.origin).parent / "memory" / "types" / "working.py"
    if not path.is_file():
        sys.exit(f"找不到目标文件：{path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="修复中文工作记忆检索")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="只检查是否已打补丁")
    group.add_argument("--revert", action="store_true", help="从 .bak 还原")
    args = parser.parse_args()

    path = locate_working_py()
    backup = path.with_suffix(path.suffix + ".bak")
    text = path.read_text(encoding="utf-8")
    patched = MARKER in text

    if args.check:
        print(f"目标文件: {path}")
        print(f"已打补丁: {patched}")
        return 0 if patched else 1

    if args.revert:
        if not backup.is_file():
            sys.exit(f"没有备份文件，无法还原：{backup}")
        shutil.copy2(backup, path)
        print(f"已从备份还原: {backup} -> {path}")
        return 0

    if patched:
        print(f"已打过补丁，跳过: {path}")
        return 0

    lines = text.splitlines(keepends=True)
    index = None
    for i, line in enumerate(lines):
        if ANCHOR in line:
            index = i
            indent = line[: len(line) - len(line.lstrip())]
            break
    if index is None:
        sys.exit(
            f"未找到插入锚点，可能 hello-agents 版本已变化。\n"
            f"请手工在 {path} 的 `scored_memories.sort(...)` 之前插入:\n"
            f"{SNIPPET.format(ind='        ')}"
        )

    if not backup.is_file():
        shutil.copy2(path, backup)
        print(f"已备份原文件: {backup}")

    lines.insert(index, SNIPPET.format(ind=indent))
    path.write_text("".join(lines), encoding="utf-8")

    # 复核
    if MARKER not in path.read_text(encoding="utf-8"):
        sys.exit("写入后复核失败，请手工检查")
    print(f"补丁已应用: {path}")
    print("提示：需要重启后端进程才会生效（记忆管理器在启动时初始化）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
