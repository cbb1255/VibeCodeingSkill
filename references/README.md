# references/ 说明

放**按需读取**的详细资料：规范、清单、领域知识、长文档等。

## 为什么放这里

- 让 SKILL.md 正文保持精炼，模型只在需要时加载细节；
- 内容太长全塞进正文会稀释指令、增加 token 消耗。

## 约定

1. 用 Markdown 写，结构清晰（标题层级 + 清单/表格）。
2. SKILL.md 正文里必须写明**读取时机**，例如：
   「遇到 X 情况时，先读 `references/xxx.md`，按其中清单逐项执行。」
3. 文件名要能自解释：`coding-style.md`、`checklist.md`、`api-conventions.md`……

## 示例

见 `example-reference.md` —— 一个含背景知识 / 检查清单 / FAQ 三段的参考文档骨架。