#!/usr/bin/env python3
"""示例辅助脚本 —— 换成技能真正要做的逻辑。

用法:
    python scripts/example.py --name <项目名>

说明:
    零依赖；只读操作；不写文件、不联网。
    在 SKILL.md 正文里引用本脚本时，写清楚运行命令和参数含义。
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="skill-template 示例脚本")
    parser.add_argument("--name", required=True, help="输入一个名字")
    args = parser.parse_args()

    # ↓↓↓ 把下面这一行换成技能真正的核心逻辑 ↓↓↓
    print(f"hello, {args.name} — 这是模板占位输出，请替换为实际逻辑")


if __name__ == "__main__":
    main()