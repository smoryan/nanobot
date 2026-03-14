# Channels 模块 (nanobot/channels/)

通道模块提供了一个**基于插件的架构**，用于将 nanobot 连接到各种聊天平台。它抽象了平台特定的差异，同时保持消息处理的一致接口。

## 目录结构

```
nanobot/channels/
├── __init__.py        # 模块导出
├── base.py            # 基础通道抽象类
├── registry.py        # 自动发现系统
├── manager.py         # 通道生命周期和消息路由
├── telegram.py        # Telegram 机器人
├── discord.py         # Discord Gateway
├── feishu.py          # 飞书 WebSocket
├── slack.py           # Slack Socket Mode
├── email.py           # IMAP 轮询 + SMTP
├── qq.py              # QQ 机器人
├── dingtalk.py        # 钉钉 Stream Mode
├── matrix.py          # Matrix Element
├── mochat.py          # Mochat Socket.IO
├── wecom.py           # 企业微信
└── whatsapp.py        # WhatsApp (通过 Node.js 桥接)
```

---

## 1. base.py - 基础通道抽象

### 职责

`BaseChannel` 是所有通道实现必须遵循的抽象基类。

### 类签名

```python
class BaseChannel(ABC):
    """聊天通道实现的抽象基类"""
    
    name: str = "base"
    display_name: str = "Base"
    transcription_api_key: str = ""
    
    def __init__(self, config: Any, bus: MessageBus)
    
    @abstractmethod
    async def start(self) -> None
    
    @abstractmethod
    async def stop(self) -> None
    
    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None
    
    async def transcribe_audio(self, file_path: str | Path) -> str
    def is_allowed(self, sender_id: str) -> bool
    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None
    
    @classmethod
    def default_config(cls) -> dict[str, Any]
    
    @property
    def is_running(self) -> bool
```

### 关键模式

- **权限控制**: `is_allowed()` 检查 `allow_from` 列表 - 空拒绝所有，`["*"]` 允许所有
- **音频转录**: 可选的 Groq Whisper 集成用于语音消息
- **消息总线集成**: `_handle_message()` 在权限检查后发布 `InboundMessage` 事件
- **会话作用域**: `session_key` 参数启用线程作用域的对话

---

## 2. registry.py - 自动发现系统

### 职责

动态发现内置和外部插件通道。

### 函数

```python
def discover_channel_names() -> list[str]
    # 扫描包中的通道模块（排除 base, manager, registry）

def load_channel_class(module_name: str) -> type[BaseChannel]
    # 导入模块并返回第一个 BaseChannel 子类

def discover_plugins() -> dict[str, type[BaseChannel]]
    # 从 entry_points 组 "nanobot.channels" 加载外部插件

def discover_all() -> dict[str, type[BaseChannel]]
    # 合并内置 + 插件（内置优先）
```

**设计决策**: 内置通道不能被外部插件覆盖 - 防止意外覆盖。

---

## 3. manager.py - 通道管理器

### 职责

管理通道生命周期和路由出站消息。

### 类签名

```python
class ChannelManager:
    def __init__(self, config: Config, bus: MessageBus)
    
    async def start_all(self) -> None
        # 启动出站分发器和所有启用的通道
    
    async def stop_all(self) -> None
    
    def get_channel(self, name: str) -> BaseChannel | None
    def get_status(self) -> dict[str, Any]
    
    @property
    def enabled_channels(self) -> list[str]
    
    # 内部
    def _init_channels(self) -> None
    def _validate_allow_from(self) -> None
    async def _dispatch_outbound(self) -> None
```

### 关键模式

- **Groq 集成**: 自动从 providers 配置注入 `transcription_api_key`
- **安全验证**: 空 `allowFrom` 列表时快速失败（默认拒绝所有）
- **进度过滤**: 遵守 `send_progress` 和 `send_tool_hints` 配置标志

---

## 4. 通道实现

### 通用模式

1. **Pydantic 配置类**: 每个通道都有 `*Config(Base)` 类用于类型安全配置
2. **长期运行异步任务**: `start()` 方法无限运行直到调用 `stop()`
3. **连接弹性**: 带指数退避的自动重连
4. **媒体处理**: 下载附件到 `get_media_dir(channel_name)` 目录
5. **去重**: 消息 ID 缓存（OrderedDict/deque）带大小限制
6. **权限集成**: 所有在处理消息前检查 `is_allowed()`

### Telegram (telegram.py)

**架构**: 通过 `python-telegram-bot` SDK 长轮询

**关键特性**:
- **流式模拟**: 使用 `send_message_draft()` 进行渐进式渲染
- **Markdown 到 HTML**: 转换 markdown 到 Telegram 安全的 HTML 格式
- **表格渲染**: 特殊处理 markdown 表格 → 方框绘制字符
- **媒体组**: 在转发前缓冲多照片消息（600ms 延迟）
- **线程支持**: 论坛主题消息获得线程作用域会话
- **回复上下文**: 提取并包含回复消息内容
- **语音转录**: 使用 Groq Whisper 进行语音/OGG 音频

### Discord (discord.py)

**架构**: 直接 Gateway WebSocket 实现

**关键特性**:
- **无 SDK**: 直接使用 `websockets` 和 `httpx`
- **速率限制**: 429 错误时自动重试
- **心跳**: 发送 OP 1 心跳包
- **文件附件**: 通过 multipart/form-data 上传（最大 20MB）
- **输入指示器**: 周期性输入状态更新（8s 间隔）

### 飞书 (feishu.py)

**架构**: 通过 `lark-oapi` SDK 的 WebSocket 长连接

**关键特性**:
- **智能格式检测**: 根据内容复杂度自动选择 text/post/interactive card
- **富 Markdown**: 在 interactive cards 中支持表格、代码块、标题
- **反应反馈**: 在入站消息上添加表情反应
- **去重**: 有序消息 ID 缓存（1000 条）
- **媒体上传**: 处理图像、音频、视频、文件

### Slack (slack.py)

**架构**: 通过 `slack_sdk` 的 Socket Mode

**关键特性**:
- **线程回复**: 在通道中维护对话线程
- **Mrkdwn 转换**: 使用 `slackify_markdown` + 自定义表格处理器
- **反应指示器**: 在接收的消息上添加表情
- **DM 策略**: 独立的 `dm.enabled` 和 `dm.policy` 控制

### Email (email.py)

**架构**: IMAP 轮询 + SMTP 发送

**关键特性**:
- **安全门**: `consent_granted` 必须为 `true`（防止意外访问）
- **线程跟踪**: `In-Reply-To` 和 `References` 头
- **HTML 到文本**: 从 HTML 邮件最佳努力的文本提取
- **日期查询**: `fetch_messages_between_dates()` 用于历史摘要
- **主题处理**: 自动在回复前加 "Re: "

### QQ (qq.py)

**架构**: 使用 botpy SDK 的 WebSocket

**关键特性**:
- **双模式**: 支持 C2C（私聊）和群消息
- **格式选择**: `msg_format: "plain" | "markdown"` 用于兼容性
- **消息序列化**: `msg_seq` 防止 API 去重问题

### 钉钉 (dingtalk.py)

**架构**: 通过 `dingtalk-stream` SDK 的 Stream Mode

**关键特性**:
- **访问令牌缓存**: 带提前 60 秒过期的自动刷新
- **媒体上传**: 支持图像、语音、视频、文件
- **回调处理器**: 标准 SDK 处理器模式
- **HTTP + WebSocket**: 使用 WebSocket 接收，HTTP 发送

### Matrix (matrix.py)

**架构**: 通过 `nio` 库的长轮询同步

**关键特性**:
- **E2EE 支持**: 可选的端到端加密（`matrix-nio`）
- **HTML 清理**: `nh3` 清理器用于 Matrix 兼容的 HTML
- **输入保活**: 周期性输入指示器刷新（20s 间隔）
- **线程支持**: Matrix 线程（`m.thread` 关系类型）
- **媒体限制**: 遵守服务器上传限制 + 本地 `max_media_bytes` 配置

### Mochat (mochat.py)

**架构**: Socket.IO 带 HTTP 轮询回退

**关键特性**:
- **双传输**: 主要 WebSocket，自动 HTTP 回退
- **延迟响应**: 可配置的非提及回复延迟（默认 120s）
- **缓冲**: 在分发前聚合多条消息
- **游标持久化**: 将会话游标保存到 JSON 文件以便恢复

### 企业微信 (wecom.py)

**架构**: `wecom_aibot_sdk` WebSocket

**关键特性**:
- **帧存储**: 缓存对话帧用于回复上下文
- **混合内容**: 处理多部分消息（文本 + 图像 + 文件）
- **欢迎消息**: `enter_chat` 事件的可选问候
- **流式回复**: 使用 `reply_stream()` 进行渐进式输出

### WhatsApp (whatsapp.py)

**架构**: WebSocket 到 Node.js 桥接（`@whiskeysockets/baileys`）

**关键特性**:
- **桥接模式**: 通过 WebSocket JSON 消息的 Python ↔ Node.js
- **认证令牌**: 可选的 `bridge_token` 用于桥接认证
- **媒体下载**: 桥接下载并提供文件路径
- **QR 认证**: 桥接显示 QR 码用于设备链接

---

## 5. 如何实现新通道

### 步骤 1: 创建通道类

```python
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

class MyPlatformConfig(Base):
    enabled: bool = False
    api_key: str = ""
    allow_from: list[str] = Field(default_factory=list)

class MyPlatformChannel(BaseChannel):
    name = "myplatform"
    display_name = "My Platform"
    
    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MyPlatformConfig().model_dump(by_alias=True)
    
    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = MyPlatformConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MyPlatformConfig = config
    
    async def start(self) -> None:
        """连接并开始监听消息"""
        self._running = True
        
        while self._running:
            # 接收消息并调用 self._handle_message()
            await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """断开并清理"""
        self._running = False
    
    async def send(self, msg: OutboundMessage) -> None:
        """发送消息到平台"""
        # 发送 msg.content 和 msg.media
        pass
```

### 步骤 2: 处理入站消息

```python
await self._handle_message(
    sender_id=str(user_id),      # 必需
    chat_id=str(chat_id),        # 必需
    content=message_text,        # 必需
    media=media_paths,           # 可选: list[str]
    metadata={                   # 可选: dict[str, Any]
        "message_id": msg_id,
        "is_group": False,
    },
    session_key="thread:123"     # 可选: 用于线程作用域会话
)
```

### 步骤 3: 安装为插件（可选）

**setup.py** 或 **pyproject.toml**:
```toml
[project.entry-points."nanobot.channels"]
myplatform = "myplugin:MyPlatformChannel"
```

或放置文件在 `nanobot/channels/myplatform.py` 用于自动发现。

### 步骤 4: 测试配置

**~/.nanobot/config.json**:
```json
{
  "channels": {
    "myplatform": {
      "enabled": true,
      "api_key": "your-key",
      "allow_from": ["user123"]
    }
  }
}
```

---

## 6. 依赖矩阵

| 通道 | 核心依赖 | 可选依赖 |
|------|----------|----------|
| Base | `abc`, `typing`, `loguru` | - |
| Telegram | `python-telegram-bot` | - |
| Discord | `websockets`, `httpx` | - |
| Feishu | `lark-oapi` | - |
| Slack | `slack_sdk`, `slackify-markdown` | - |
| Email | `imaplib`, `smtplib`, `email` | - |
| QQ | `botpy` | - |
| DingTalk | `dingtalk-stream`, `httpx` | - |
| Matrix | `matrix-nio`, `mistune`, `nh3` | - |
| Mochat | `socketio`, `httpx`, `msgpack` | - |
| WeCom | `wecom_aibot_sdk` | - |
| WhatsApp | `websockets` | Node.js 桥接 |

---

## 7. 设计模式

### 异步生命周期管理
所有通道实现异步 `start()` / `stop()` 模式，带 `_running` 标志用于优雅关闭。

### 通过 Pydantic 配置
类型安全配置，使用 `Base` schema 和 `Field` 默认值。

### 权限优先
所有通道在处理前检查 `is_allowed(sender_id)` - 默认拒绝。

### 媒体抽象
通道下载媒体到 `get_media_dir(channel_name)` 并在内容中提供文件路径作为 `[type: /path]` 标签。

### 弹性优先
- 带退避的连接重试
- 速率限制处理（429）
- 去重缓存
- SDK 失败时的优雅降级

### 线程安全
- Mochat, Feishu: WebSocket 在专用线程中运行，带单独的事件循环
- Matrix: 输入任务在 dict 中，关闭时正确取消
- 所有: `asyncio.gather()` 带异常处理

### 平台特定格式处理
每个通道将 markdown 转换为平台原生格式：
- Telegram: HTML
- Slack: mrkdwn
- Discord: 纯文本
- Feishu: Interactive cards
- Matrix: HTML（清理后）
