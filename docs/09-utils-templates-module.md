# Utils & Templates 模块 (nanobot/utils/, nanobot/templates/)

## Utils 模块 (nanobot/utils/)

提供支持 nanobot 系统各种操作的基础工具函数。

### 目录结构

```
nanobot/utils/
├── __init__.py    # 模块导出
├── helpers.py     # 核心工具函数
└── evaluator.py   # LLM 评估系统
```

---

### 1. helpers.py - 核心工具函数

#### 图像检测

```python
def detect_image_mime(data: bytes) -> str | None
```
- 从魔数字节检测图像 MIME 类型，忽略文件扩展名
- 支持: PNG, JPEG, GIF, WEBP
- 返回: MIME 类型字符串或 `None`

#### 文件操作

```python
def ensure_dir(path: Path) -> Path
```
- 确保目录存在，必要时创建父目录
- 返回: `Path` 对象

```python
def safe_filename(name: str) -> str
```
- 将不安全的路径字符 (`<>:"/\|?*`) 替换为下划线
- 去除前后空白
- 返回: 清理后的文件名字符串

#### 时间操作

```python
def timestamp() -> str
```
- 返回: 当前 ISO 8601 时间戳字符串

#### 消息处理

```python
def split_message(content: str, max_len: int = 2000) -> list[str]
```
- 将内容分割为 max_len 内的块，优先在换行符然后空格处分割
- 默认 max_len: 2000（Discord 兼容）
- 分割顺序: `\n` → ` ` → 在 max_len 处硬分割
- 去除后续块的前导空白

```python
def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]
```
- 构建提供者安全的助手消息，带可选推理字段
- 返回: role 为 "assistant" 的消息字典
- 支持: 标准内容、tool_calls、reasoning_content (Anthropic)、thinking_blocks

#### Token 估算

```python
def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int
```
- 使用 tiktoken (cl100k_base 编码) 估算提示 tokens
- 从消息中提取文本（处理字符串和列表内容格式）
- 将工具作为 JSON 包含在估算中
- 失败时返回: 0

```python
def estimate_message_tokens(message: dict[str, Any]) -> int
```
- 估算单个持久化消息的 tokens
- 计数: content, name, tool_call_id, tool_calls
- 处理字符串、列表和字典内容格式
- 回退: tiktoken 失败时 len(payload) // 4
- 返回: 最少 1 token

```python
def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]
```
- 链式估算: 先尝试提供者计数器，然后 tiktoken
- 提供者计数器: 如果可用，使用 `provider.estimate_prompt_tokens()`
- 返回: (token_count, source) 其中 source 是 "provider_counter", "tiktoken", 或 "none"

#### 工作区模板同步

```python
def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]
```
- 将捆绑模板从 `nanobot/templates` 同步到工作区
- 只创建缺失文件（从不覆盖）
- 创建: 根 `.md` 文件, `memory/MEMORY.md`, `memory/HISTORY.md`, `skills/` 目录
- 返回: 创建文件的相对路径列表
- 非静默时使用 Rich console 输出

---

### 2. evaluator.py - LLM 评估系统

#### 职责

用于后台任务（heartbeat & cron）的 LLM 评估系统，决定结果是否需要通知用户。

#### 设计模式

- 使用轻量级工具调用 LLM 请求（与 heartbeat `_decide()` 相同模式）
- 任何失败时回退到 `True`（通知），确保重要消息不会静默丢失

#### 常量

```python
_EVALUATE_TOOL = [{
    "type": "function",
    "function": {
        "name": "evaluate_notification",
        "description": "Decide whether the user should be notified about this background task result.",
        "parameters": {
            "type": "object",
            "properties": {
                "should_notify": {
                    "type": "boolean",
                    "description": "true = result contains actionable/important info; false = routine or empty"
                },
                "reason": {
                    "type": "string",
                    "description": "One-sentence reason for the decision"
                }
            },
            "required": ["should_notify"]
        }
    }
}]

_SYSTEM_PROMPT = """You are a notification gate for a background agent. 
Notify when the response contains actionable information, errors, completed deliverables, or anything the user explicitly asked to be reminded about.
Suppress when the response is a routine status check with nothing new, a confirmation that everything is normal, or essentially empty."""
```

#### 主函数

```python
async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
) -> bool
```
- 决定后台任务结果是否应该投递给用户
- 参数:
  - `response`: 代理的执行结果
  - `task_context`: 原始任务描述
  - `provider`: 用于评估的 LLMProvider 实例
  - `model`: 用于评估的模型名
- 返回: `True` 如果应该通知，否则 `False`
- LLM 调用设置:
  - `max_tokens`: 256
  - `temperature`: 0.0 (确定性)
  - 使用 `provider.chat_with_retry()`
- 记录带原因的决策

---

### 3. __init__.py - 模块导出

```python
from nanobot.utils.helpers import ensure_dir

__all__ = ["ensure_dir"]
```

- 只导出 `ensure_dir` 作为公共 API
- 其他工具按需直接导入

---

## Templates 模块 (nanobot/templates/)

包含定义代理行为、个性、用户偏好和工作区结构的 markdown 模板文件。这些模板通过 `sync_workspace_templates()` 同步到用户工作区。

### 模板文件

#### 1. AGENTS.md

**目的**: nanobot 代理的核心行为指令。

**关键指南**:
```
You are a helpful AI assistant. Be concise, accurate, and friendly.
```

**定时提醒**:
- 在调度提醒前检查可用技能
- 使用内置 `cron` 工具（NOT 通过 `exec` 的 `nanobot cron`）
- 从当前会话提取 USER_ID 和 CHANNEL
- **关键**: 不要将提醒写入 MEMORY.md — 不会触发通知

**Heartbeat 任务**:
- `HEARTBEAT.md` 在配置的 heartbeat 间隔检查
- 使用文件工具管理周期性任务:
  - **添加**: `edit_file` 追加
  - **删除**: `edit_file` 删除
  - **重写**: `write_file` 替换全部

---

#### 2. TOOLS.md

**目的**: 工具使用约束和模式的文档。

**工具特定说明**:
- **exec — 安全限制**: 可配置超时、危险命令阻止、输出截断、工作区限制
- **cron — 定时提醒**: 参考 cron 技能了解用法详情

---

#### 3. SOUL.md

**目的**: 定义代理的个性、价值观和沟通风格。

**模板格式**:
```markdown
# Soul

I am nanobot 🐈, a personal AI assistant.

## Personality
- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values
- Accuracy over speed
- User privacy and safety
- Transparency in actions

## Communication Style
- Be clear and direct
- Explain reasoning when helpful
- Ask clarifying questions when needed
```

---

#### 4. USER.md

**目的**: 用于个性化交互的用户配置模板。

**模板结构**:
```markdown
# User Profile

## Basic Information
- **Name**: (your name)
- **Timezone**: (your timezone, e.g., UTC+8)
- **Language**: (preferred language)

## Preferences

### Communication Style
- [ ] Casual
- [ ] Professional
- [ ] Technical

### Response Length
- [ ] Brief and concise
- [ ] Detailed explanations
- [ ] Adaptive based on question

## Work Context
- **Primary Role**: (your role)
- **Main Projects**: (what you're working on)
- **Tools You Use**: (IDEs, languages, frameworks)

## Special Instructions
(Any specific instructions for assistant behavior)
```

**用途**: 用户编辑此文件以自定义 nanobot 的行为。

---

#### 5. HEARTBEAT.md

**目的**: 周期性任务管理模板。

**模板格式**:
```markdown
# Heartbeat Tasks

This file is checked every 30 minutes by your nanobot agent.

## Active Tasks

<!-- Add your periodic tasks below this line -->


## Completed

<!-- Move completed tasks here or delete them -->
```

**用途**:
- 每 30 分钟检查（可配置）
- 任务可以通过文件工具添加、删除或重写
- 空任务列表 = 跳过 heartbeat

---

#### 6. memory/MEMORY.md

**目的**: 长期内存存储模板。

**模板格式**:
```markdown
# Long-term Memory

## User Information
(Important facts about the user)

## Preferences
(User preferences learned over time)

## Project Context
(Information about ongoing projects)

## Important Notes
(Things to remember)
```

**用途**: 当重要信息应该被记住时由 nanobot 自动更新。

---

## 模板系统架构

### 初始化流程

1. **Onboarding** (`nanobot onboard`):
   - 调用 `sync_workspace_templates(workspace)`
   - 在用户工作区创建所有模板文件
   - 初始化 `memory/` 目录结构

2. **工作区结构**:
```
~/.nanobot/workspace/
├── AGENTS.md          # 代理指令
├── TOOLS.md           # 工具使用文档
├── SOUL.md            # 代理个性
├── USER.md            # 用户配置（可编辑）
├── HEARTBEAT.md       # 周期性任务（可编辑）
└── memory/
    ├── MEMORY.md      # 长期内存（自动更新）
    └── HISTORY.md     # 创建为空文件
```

3. **模板同步**:
   - 只创建缺失文件
   - 从不覆盖现有用户修改
   - 返回创建的文件列表用于日志

### 在代理中的使用

模板在代理的提示构建系统中加载和使用:

- **AGENTS.md** → 代理行为上下文
- **TOOLS.md** → 工具使用指南
- **SOUL.md** → 个性化和风格
- **USER.md** → 个性化偏好
- **HEARTBEAT.md** → 由 heartbeat 系统周期性读取
- **memory/MEMORY.md** → 随上下文加载，由代理写入以持久化
