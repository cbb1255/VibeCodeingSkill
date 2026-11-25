#!/usr/bin/env python3
"""vibe-code 初始化工具 —— 在项目里建好 docs/vibe/ 和所有骨架文件。

用法:
    python <skill目录>/scripts/init_vibe.py --project <项目根目录>
    python <skill目录>/scripts/init_vibe.py --project . --type web --name "我的待办应用"

做的事:
    1. 创建 docs/vibe/ 和 docs/vibe/checkpoints/
    2. 生成 state.md（当前阶段 0）、01-需求.md、02-技术栈.md、03-验收标准.md、04-任务清单.md
    3. 检测项目类型（有 package.json → web/node；有 pyproject.toml → python…）
    4. 检测项目目录是不是 git 仓库根目录

安全:
    已存在的文件绝不覆盖。只补缺失的。零依赖，不联网。
"""

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VIBE_REL = Path("docs") / "vibe"

# Windows 控制台默认 GBK，emoji 会让 print 抛 UnicodeEncodeError。
# 必须在任何输出之前把 stdout/stderr 切到 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _safe(text: str) -> str:
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except (UnicodeEncodeError, LookupError):
        return (text.replace("✅", "[OK]").replace("⚠️", "[!]").replace("💡", "[i]")
                    .replace("✓", "[v]").replace("·", "-").replace("❌", "[X]"))


_orig_print = print


def print(*args, **kwargs):  # noqa: A001 - 统一做编码兜底
    safe_args = [_safe(a) if isinstance(a, str) else a for a in args]
    kwargs.setdefault("file", sys.stdout)
    try:
        _orig_print(*safe_args, **kwargs)
    except UnicodeEncodeError:
        _orig_print(*[str(a).encode("ascii", "replace").decode("ascii") for a in safe_args],
                    file=sys.stdout)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def detect_type(root: Path) -> str:
    """按工程文件猜项目类型。"""
    if (root / "package.json").exists():
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8-sig"))
            if not isinstance(pkg, dict):
                return "web"
            deps = set()
            for field in ("dependencies", "devDependencies"):
                packages = pkg.get(field)
                if isinstance(packages, dict):
                    deps.update(packages)
            if {"electron", "tauri", "@tauri-apps/api", "@tauri-apps/cli"} & deps:
                return "desktop"
            if {"react", "vue", "svelte", "@angular/core", "next"} & deps:
                return "web"
            if "bin" in pkg:
                return "cli"
            return "web"
        except (ValueError, OSError):
            return "web"
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        text = ""
        for name in ("pyproject.toml", "setup.py"):
            p = root / name
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
                break
        if "console_scripts" in text or "scripts" in text:
            return "cli"
        return "lib"
    if (root / "requirements.txt").exists():
        return "script"
    if (root / "Cargo.toml").exists() or (root / "go.mod").exists():
        return "cli"
    return "script"


def has_git(root: Path) -> bool:
    if shutil.which("git") is None:
        return False
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == root
    except (OSError, subprocess.TimeoutExpired):
        return False


TYPE_LABEL = {
    "cli": "命令行工具（CLI）",
    "web": "Web 应用",
    "lib": "库 / SDK",
    "script": "脚本 / 自动化",
    "data": "数据处理 / 分析",
    "desktop": "桌面或移动应用",
}


def state_md(name: str, ptype: str, root: Path) -> str:
    return f"""# vibe-code 状态

- 项目名：{name}
- 项目类型：{ptype}（{TYPE_LABEL.get(ptype, ptype)}）
- 流程状态：进行中
- 流程根目录：{root}
- 当前代码根目录：{root}
- 项目规则入口：待核对
- 测试逻辑审查：未提交
- 活动排障：无
- 任务提交：未授权
- 当前阶段：0 — 意图与续接
- 阶段状态：进行中
- 及格线：90
- 更新时间：{now()}

## 阶段进度

| 阶段 | 状态 | 完成时间 | 备注 |
|---|---|---|---|
| 0 意图与续接 | 🔄 进行中 | — | — |
| 1 需求 | ⏳ 未开始 | — | — |
| 2 技术栈 | ⏳ 未开始 | — | — |
| 3 验收标准 | ⏳ 未开始 | — | — |
| 4 拆任务 | ⏳ 未开始 | — | — |
| 5 实现 | ⏳ 未开始 | — | — |
| 6 验证 | ⏳ 未开始 | — | — |
| 7 审查 | ⏳ 未开始 | — | — |
| 8 交付 | ⏳ 未开始 | — | — |

## 检查点

| 编号 | 时间 | 阶段 | git commit | 说明 | 代码根目录 |
|---|---|---|---|---|---|
| 尚未建立 | — | 0 | — | 等待创建基线检查点 | {root} |

## 自干标注

| 阶段 | 时间 | 原因 | 质量备注 |
|---|---|---|---|
| （暂无） | — | — | — |

## 关键决策

| 编号 | 决策 | 时间 | 用户原话/选择 |
|---|---|---|---|
| （暂无） | — | — | — |

## 回退记录

| 时间 | 从 | 回到 | 范围 | 回退前快照 | 备注 |
|---|---|---|---|---|---|
| （暂无） | — | — | — | — | — |

## 下一动作

完成阶段 0：核对适用的项目规则并确认可从规则文件找到 docs/vibe/state.md，记录规则入口；核验项目范围和 Git 状态，运行 checkpoint.py snap 并记下实际基线编号后进入阶段 1。
"""


REQ_MD = """# 01 需求文档

> 状态：⏳ 未填写　|　填写者：阶段 1（grill-me 追问后由总控成文）

## 一句话目标

[用一句话说清：给谁解决什么问题，做完之后世界有什么不同]

## 目标用户

[谁会用这个？他们的水平 / 使用频率 / 在什么设备上用]

## 核心使用场景

[3–6 条，每条写清「谁 · 在什么情况下 · 做什么 · 得到什么」]

1.
2.
3.

## 产品方案

[写从入口到可见结果的主要用户操作。交互待确认时，附最小 Demo 或原型和待验证操作。]

## 完成条件草案

[对应核心场景写可观察的成功结果；在阶段 3 定稿验收用例、判定和阈值。]

## 输入与输出

- 输入：
- 输出：

## 边界与约束

[数据量级、运行环境、必须兼容的东西、时间/成本限制]

## 明确不做的事（最重要）

[列出所有「这次不做」的范围，防止越做越大。每项写清为什么不做]

1.

## 非功能需求

[按项目类型填写相关维度，不相关的写「不涉及」]

- 性能：
- 安全：
- 并发：
- 多平台：
- 离线：
- 隐私：

## 待定项

[逐条记录待定事项及最迟决定时间。全部确定时写「无」]
"""

STACK_MD = """# 02 技术栈文档

> 状态：⏳ 未填写　|　填写者：阶段 2（先问用户倾向，不知道则总控追问 + 给建议）

## 选型总表

| 项目 | 选了什么 | 为什么选它 | 排除了哪些备选及原因 |
|---|---|---|---|
| 语言 |  |  |  |
| 框架 |  |  |  |
| 运行环境与版本 |  |  |  |
| 数据存储 |  |  |  |
| 外部服务 |  |  |  |
| 部署方式 |  |  |  |

## 依赖清单

| 依赖名 | 版本 | 用途 | 必要性（必须有 / 可选） |
|---|---|---|---|
|  |  |  |  |

## 目录结构约定

```
[简单画出目录结构，说明每个目录放什么]
```

## 沿用的现有配置

[如果项目已存在工程文件（package.json / pyproject.toml 等），在这里写清楚哪些是沿用的、哪些是新增的]

## 风险点

[这套栈最容易出问题的地方，提前写出来]

## 维护成本

[对比拟选方案和现实备选；可将沿用现有方案作对照。用相关的升级、排障、测试、部署与回滚、交接工作说明代价和取舍，记录待核实项和验证方式。]

## 技术方案

[写清核心场景的主要组件与数据流，或对外接口和边界。简单项目一段即可。]
"""

ACCEPT_MD = """# 03 验收标准文档

> 状态：⏳ 未填写　|　填写者：阶段 3
> **核心思路：验收 = 测试集打分，不是打勾清单。**

## 完成定义

- 已验收的需求版本：01-需求.md v______
- 核心场景、可观察结果与对应的用例编号：______
- 验收证据：人工审查通过的测试逻辑版本、正式评分、必过用例、各项阈值和有效例外。
- 交付条件：正式评分通过，代码审查的阻断问题处理完毕，用户或其指定的人亲自体验核心场景并确认通过。

## 测试集来源

- [ ] 上网找的公开测试集 / 业界 checklist → 出处链接：______　是否完整采用：______
- [ ] 用户提供的现成测试集 → 文件位置：______
- [ ] 总控自拟（没有任何现成来源时）→ 依据：需求文档的每个场景

## 功能一：<功能名>

| 用例编号 | 输入 / 操作 | 预期结果 | 优先级 |
|---|---|---|---|
| F1-01 |  |  | 🔴 必过 |
| F1-02 |  |  | 🟡 加分 |

## 功能二：<功能名>

| 用例编号 | 输入 / 操作 | 预期结果 | 优先级 |
|---|---|---|---|
| F2-01 |  |  | 🔴 必过 |

## 评分方式

- 每个功能得分 = 通过用例数 ÷ 该功能总用例数 × 100
- 总分 = 各功能得分的算术平均，功能等权
- 用未舍入的分数判定是否达标，报告可显示至小数点后 2 位
- 所有 🔴 必过用例须通过，且各功能得分和总分均须达到各自的确认线

## 及格线

| 范围 | 默认及格线 | 用户确认后的及格线与确认记录 |
|---|---|---|
| F1 | 90% | ______ |
| F2 | 90% | ______ |
| 总分 | 90% | ______ |

## 例外约定

[用户若说过「不达标也可以」，把原话记录在这里。没有就写「无」]
"""

TASKS_MD = """# 04 任务清单

> 状态：⏳ 未填写　|　填写者：阶段 4（总控自己拆）
> 每完成一个任务，勾掉一行并更新 state.md。按已记录的用户授权决定是否提交。

| 任务编号 | 改什么文件 | 做完怎么算完（可验证） | 依赖哪个任务 | 可并行 | 状态 |
|---|---|---|---|---|---|
| T1 |  |  | — | — | ⏳ 待做 |
| T2 |  |  | T1 | — | ⏳ 待做 |

## 并行说明

[哪些任务可以同时做，需要分到不同分支 / worktree]

## 风险任务

[哪些任务最容易做不完或做偏，先标出来]
"""


def write_if_absent(path: Path, content: str, created: list[Path], skipped: list[Path]) -> None:
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError:
        if not path.is_file():
            raise
        skipped.append(path)
        return
    with handle:
        handle.write(content)
    created.append(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 vibe-code 的 docs/vibe/ 目录")
    parser.add_argument("--project", default=".", help="项目根目录（默认当前目录）")
    parser.add_argument("--type", default=None,
                        choices=["cli", "web", "lib", "script", "data", "desktop"],
                        help="项目类型（不填则自动检测）")
    parser.add_argument("--name", default=None, help="项目名（不填则用目录名）")
    args = parser.parse_args()

    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"[错误] --project 必须是现有目录：{root}", file=sys.stderr)
        return 1

    vibe = root / VIBE_REL
    ptype = args.type or detect_type(root)
    name = args.name or root.name
    git_ok = has_git(root)

    print(f"项目根：{root}")
    print(f"项目名：{name}")
    print(f"类型　：{ptype}（{TYPE_LABEL.get(ptype, ptype)}）{'（自动检测）' if not args.type else '（指定）'}")
    print(f"git　 ：{'当前目录是仓库根目录 ✓' if git_ok else '当前目录不是可用的仓库根目录，使用文件模式'}")
    print()

    state_path = vibe / "state.md"
    checkpoints = vibe / "checkpoints"
    created: list[Path] = []
    skipped: list[Path] = []
    try:
        for directory in (vibe, checkpoints):
            if not directory.resolve().is_relative_to(root):
                print(f"[错误] 流程目录位于项目根目录之外：{directory}", file=sys.stderr)
                return 1
        checkpoints.mkdir(parents=True, exist_ok=True)
        print(f"✓ 目录 {vibe}")

        documents = {
            state_path: state_md(name, ptype, root),
            vibe / "01-需求.md": REQ_MD,
            vibe / "02-技术栈.md": STACK_MD,
            vibe / "03-验收标准.md": ACCEPT_MD,
            vibe / "04-任务清单.md": TASKS_MD,
        }
        for path, content in documents.items():
            write_if_absent(path, content, created, skipped)
    except (OSError, RuntimeError) as exc:
        print(f"[错误] 初始化未完成：{exc}", file=sys.stderr)
        return 1

    for path in created:
        print(f"✓ 创建 {path.relative_to(root)}")
    for path in skipped:
        print(f"· 已存在，跳过（不覆盖） {path.relative_to(root)}")

    print()
    if state_path in created:
        checkpoint_script = Path(__file__).with_name("checkpoint.py").resolve()
        command = [sys.executable, str(checkpoint_script), "--project", str(root), "snap", "-m", "阶段 0 基线"]
        if sys.platform == "win32":
            command_text = "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in command)
        else:
            command_text = shlex.join(command)
        print("下一步：核对项目规则和 state.md 的续接入口，再在阶段 0 创建基线检查点，记录实际编号后进入阶段 1。")
        print(f"  {command_text}")
    else:
        print(f"下一步：读取现有 {state_path.relative_to(root)}，按其中的阶段和下一动作续接。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
