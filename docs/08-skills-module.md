# Skills 模块 (nanobot/skills/)

技能系统允许通过 markdown 文件 (SKILL.md) 加载代理能力。技能支持渐进式加载、依赖检查和工作区覆盖。

## 目录结构

```
nanobot/skills/
├── README.md           # 技能模块概述
├── skill-creator/      # 技能创建工具
│   ├── SKILL.md        # 创建指南
│   └── scripts/
│       ├── init_skill.py      # 初始化新技能
│       ├── package_skill.py   # 打包为 .skill 文件
│       └── quick_validate.py  # 验证技能结构
├── github/             # GitHub CLI 集成
├── weather/            # 天气查询
├── summarize/          # URL/文件摘要
├── tmux/               # 远程 tmux 控制
├── clawhub/            # 技能搜索和安装
├── memory/             # 两层内存系统
└── cron/               # 定时任务调度
```

---

## 1. 内置技能列表

| 技能 | 描述 | 有脚本 | 关键特性 |
|------|------|--------|----------|
| **github** | 使用 `gh` CLI 与 GitHub 交互 | 否 | PR 检查、工作流运行、API 查询 |
| **weather** | 通过 wttr.in/Open-Meteo 获取天气信息 | 否 | 无需 API key，紧凑格式代码 |
| **summarize** | 摘要 URL、文件和 YouTube 视频 | 否 | 触发短语、字幕提取 |
| **tmux** | 远程控制 tmux 会话 | 是 | `find-sessions.sh`, `wait-for-text.sh` |
| **clawhub** | 从注册表搜索和安装技能 | 否 | 向量搜索、安装到工作区 |
| **skill-creator** | 创建新技能 | 是 | 验证、打包、模板 |
| **memory** | 两层内存系统 | 否 | `always: true` 标志、基于 grep 的回忆 |
| **cron** | 调度提醒和周期性任务 | 否 | 时区感知、三种模式（提醒/任务/一次性） |

---

## 2. 技能格式和结构

### 核心结构

每个技能是一个包含以下内容的目录:

```
skill-name/
├── SKILL.md (必需)
├── scripts/ (可选)
├── references/ (可选)
└── assets/ (可选)
```

### SKILL.md 格式

**必需的 YAML Frontmatter:**
```yaml
---
name: skill-name (hyphen-case, 最多 64 字符)
description: 技能做什么以及何时使用 (最多 1024 字符)
homepage: https://optional-link.com (可选)
metadata: {"nanobot":{"emoji":"🔥","os":["darwin","linux"],"requires":{"bins":["gh"],"env":["API_KEY"]},"always":true}} (可选)
---
```

**正文:** Markdown 指令（触发后加载）

### Frontmatter 字段

| 字段 | 必需 | 描述 |
|------|------|------|
| `name` | ✅ | hyphen-case，最多 64 字符 |
| `description` | ✅ | 做什么 + 何时使用，最多 1024 字符 |
| `homepage` | ❌ | 文档 URL |
| `metadata.nanobot.emoji` | ❌ | 显示图标 |
| `metadata.nanobot.os` | ❌ | OS 要求（如 `["darwin", "linux"]`） |
| `metadata.nanobot.requires.bins` | ❌ | PATH 上的 CLI 工具 |
| `metadata.nanobot.requires.env` | ❌ | 环境变量 |
| `metadata.nanobot.always` | ❌ | 启动时加载 |
| `metadata.nanobot.install` | ❌ | 安装说明 |

### 可选资源目录

**scripts/** - 可执行代码
- Python/Bash 脚本用于确定性操作
- 可以在不加载到上下文的情况下执行
- 示例: tmux 有 `find-sessions.sh` 和 `wait-for-text.sh`

**references/** - 用于上下文加载的文档
- API 文档、schema、工作流指南
- 仅在代理需要时加载
- 最佳实践: 保持 SKILL.md 精简，详细信息放这里

**assets/** - 用于输出的文件（非上下文）
- 模板、图像、字体、样板代码
- 在最终输出中复制/使用，不加载到 LLM

---

## 3. 如何创建新技能

### 步骤 1: 初始化技能

```bash
python nanobot/skills/skill-creator/scripts/init_skill.py my-skill --path ./workspace/skills --resources scripts,references,assets --examples
```

这会创建:
- `my-skill/SKILL.md` 带模板
- `scripts/example.py` (如果 `--examples`)
- `references/api_reference.md` (如果 `--examples`)
- `assets/example_asset.txt` (如果 `--examples`)

### 步骤 2: 编辑 SKILL.md

- 完成 frontmatter: name 和 description（触发关键）
- 使用**祈使/不定式形式**编写正文指令
- 完成后删除占位符部分

### 步骤 3: 添加资源

- 为可重复代码模式创建脚本
- 为详细文档添加引用
- 为模板/样板添加资源
- 删除未使用的资源目录

### 步骤 4: 验证

```bash
python nanobot/skills/skill-creator/scripts/quick_validate.py ./workspace/skills/my-skill
```

检查:
- YAML 格式，必需字段
- 名称匹配目录
- 描述没有 TODO 占位符
- 只有允许的目录: SKILL.md, scripts/, references/, assets/

### 步骤 5: 打包（用于分发）

```bash
python nanobot/skills/skill-creator/scripts/package_skill.py ./workspace/skills/my-skill ./dist
```

创建 `my-skill.skill`（扩展名为 .skill 的 zip 文件）:
- 拒绝符号链接
- 排除 .git, __pycache__, node_modules
- 维护目录结构

### 步骤 6: 部署

- **工作区技能**: 放置在 `<workspace>/skills/`（自动发现）
- **内置技能**: 放置在 `<nanobot>/nanobot/skills/`
- **从 ClawHub 安装**: 使用 `npx clawhub install <slug> --workdir ~/.nanobot/workspace`

---

## 4. 技能加载机制

### 发现位置（优先级顺序）

1. **工作区技能** (`<workspace>/skills/`) - 最高优先级
2. **内置技能** (`<nanobot>/nanobot/skills/`) - 回退

工作区技能覆盖同名内置技能。

### 加载类

**SkillsLoader** (`nanobot/agent/skills.py`):

```python
class SkillsLoader:
    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None)
    
    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]
    def load_skill(self, name: str) -> str | None
    def load_skills_for_context(self, skill_names: list[str]) -> str
    def build_skills_summary(self) -> str
    def get_always_skills(self) -> list[str]
    def get_skill_metadata(self, name: str) -> dict | None
```

### 要求检查

从 `metadata.nanobot.requires`:
- `bins`: 检查 CLI 工具是否在 PATH 上（使用 `shutil.which`）
- `env`: 检查环境变量是否设置

要求未满足的技能在摘要中显示 `available="false"`。

### 渐进式加载（上下文管理）

**级别 1: 元数据** (~100 tokens, 始终加载)
- 技能名称和描述
- 用于触发决策

**级别 2: SKILL.md 正文** (<5k tokens, 按需)
- 完整指令
- 技能触发时加载

**级别 3: 捆绑资源** (无限制, 按需)
- 脚本可以在不读取的情况下执行
- 引用仅在代理确定需要时加载

### 始终加载的技能

在 frontmatter 中有 `always: true` 的技能:
- 启动时自动加载到上下文
- 示例: `memory` 技能
- 必须满足所有要求才能加载

### 在代理循环中的集成

**ContextBuilder** (`nanobot/agent/context.py`):
1. 使用身份、引导文件、内存构建系统提示
2. 将 `always: true` 技能加载到 "# Active Skills" 部分
3. 添加带位置的技能摘要: "# Skills - read SKILL.md with read_file tool"

**代理使用:**
- 代理读取包含所有可用技能的技能摘要
- 需要时使用 `read_file` 工具加载完整 SKILL.md
- 可以根据需要从 `references/` 读取引用文件
- 通过 `exec` 工具从 `scripts/` 执行脚本

---

## 5. 技能设计原则

### 简洁是关键

- 上下文窗口与所有其他内容共享
- 默认假设: 代理已经足够聪明
- 只添加代理还不知道的信息
- 优先简洁示例而非冗长解释

### 自由度

- **高自由度**（文本指令）: 多种有效方法
- **中等自由度**（伪代码/脚本）: 存在首选模式
- **低自由度**（特定脚本）: 脆弱操作，一致性关键

### 渐进式披露

- 保持 SKILL.md 正文在 500 行以下
- 接近限制时拆分为引用文件
- 从 SKILL.md 到引用文件的清晰链接
- 领域特定组织（如 finance.md, sales.md）

---

## 6. 从外部来源安装技能

### ClawHub 集成

`clawhub` 技能允许从公共注册表搜索和安装技能:

**搜索:**
```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

**安装:**
```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

**更新:**
```bash
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace
```

**列出已安装:**
```bash
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

技能安装到 `<workspace>/skills/`，在那里被 nanobot 自动发现。

---

## 7. 归属

技能系统改编自 [OpenClaw](https://github.com/openclaw/openclaw) 的技能系统。格式和元数据结构遵循 OpenClaw 约定以保持兼容性。
