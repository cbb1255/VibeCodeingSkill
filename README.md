# skill-template 使用说明

这是一个「技能模板」，本身不是一个能干活儿的技能。

## 三步做成自己的技能

1. **复制整个文件夹**到目标位置并改名：

   ```
   项目级（只在该项目生效）：
   你的项目/.claude/skills/新技能名/

   全局（所有项目生效）：
   C:\Users\<你的用户名>\.claude\skills\新技能名/
   ```

2. **填 SKILL.md**：把 `{{……}}` 占位符全部替换成真实内容。
   - 重点写好 frontmatter 里的 `name` 和 `description`；
   - `description` 决定模型什么时候自动加载它，措辞要具体。

3. **按需删改资源**：
   - 不需要的文件夹直接删掉；
   - `scripts/`、`references/`、`assets/` 里的 README 和各示例文件都可以替换成真实内容。

## 目录结构

```
skill-template/
├── SKILL.md                    ← 唯一必填文件（技能本体）
├── README.md                   ← 本说明，成品技能可删
├── scripts/
│   ├── README.md               ← 放可执行辅助脚本（py/ps1/sh…）
│   └── example.py              ← 示例脚本，成品可替换
├── references/
│   ├── README.md               ← 放详细资料/规范/清单
│   └── example-reference.md    ← 示例参考文档
└── assets/
    └── README.md               ← 放模板、图片、样例数据等静态文件
```

## 生效方式

在 Claude Code 里新开会话（或重启），模型遇到匹配 `description` 的场景就会自动加载；也可以直接叫技能名或触发词。