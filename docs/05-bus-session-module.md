# Bus & Session 模块 (nanobot/bus/, nanobot/session/)

## Bus 模块 - 消息总线

### 职责

提供解耦的消息路由系统，将聊天通道（Telegram, Discord 等）与代理核心分离。通过事件驱动消息实现异步通信。

### events.py - 事件类型

```python
@dataclass
class InboundMessage:
    """从聊天通道接收的消息"""
    channel: str              # telegram, discord, slack, whatsapp
    sender_id: str            # 用户标识符
    chat_id: str              # 聊天/通道标识符
    content: str              # 消息文本
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_key_override: str | None = None  # 线程作用域会话
    
    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"

@dataclass
class OutboundMessage:
    """发送到聊天通道的消息"""
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### queue.py - 消息队列

```python
class MessageBus:
    """解耦聊天通道与代理核心的异步消息总线"""
    
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
    
    # 生产者方法
    async def publish_inbound(self, msg: InboundMessage) -> None
    async def publish_outbound(self, msg: OutboundMessage) -> None
    
    # 消费者方法
    async def consume_inbound(self) -> InboundMessage
    async def consume_outbound(self) -> OutboundMessage
    
    # 监控
    @property
    def inbound_size(self) -> int
    @property
    def outbound_size(self) -> int
```

### 消息路由流程

```
┌─────────────────┐     publish_inbound()      ┌──────────────┐
│   Chat Channel  │ ────────────────────────→ │   Message    │
│   (Telegram)    │                             │     Bus      │
└─────────────────┘     publish_outbound()     │ (queue.py)   │
                         ←────────────────────└──────────────┘
                          consume_outbound()              │
                                                        ↓
                                               consume_inbound()
                                                    ┌──────────┐
                                                    │  Agent   │
                                                    │  Core    │
                                                    └──────────┘
```

### 解耦优势

- 通道不阻塞代理处理
- 代理不阻塞通道交付
- 多个通道可共享一个代理
- 队列大小提供背压信号

---

## Session 模块 - 会话管理

### 职责

管理带持久化存储的对话历史。跨交互维护会话状态，处理消息整合以提高内存效率。

### manager.py - 会话管理器

```python
@dataclass
class Session:
    """一个对话会话"""
    key: str                           # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0        # 已整合到文件的消息数
    
    def add_message(self, role: str, content: str, **kwargs) -> None
    
    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """返回未整合的消息用于 LLM 输入，对齐到用户轮次"""
    
    def clear(self) -> None


class SessionManager:
    """管理对话会话"""
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self._cache: dict[str, Session] = {}  # 内存缓存
    
    # 会话生命周期
    def get_or_create(self, key: str) -> Session
    
    # 持久化
    def save(self, session: Session) -> None
    
    # 缓存管理
    def invalidate(self, key: str) -> None
    
    # 发现
    def list_sessions(self) -> list[dict[str, Any]]
```

### 会话生命周期

```
1. 创建会话
   User Message → InboundMessage.session_key → get_or_create(key)
   ├─ 检查内存缓存 → 存在则返回
   └─ 尝试从磁盘加载
       ├─ 找到 → 加载 Session
       └─ 未找到 → 创建新 Session(key=key)

2. 消息处理
   User Message → add_message(role, content, **kwargs)
   → messages.append(msg)
   → updated_at = now()

3. 上下文检索（用于 LLM）
   get_history(max) → messages[last_consolidated:max]
   → 丢弃开头的非用户消息（避免孤立的 tool_results）
   → 过滤到: role, content, tool_calls, tool_call_id, name

4. 整合（外部进程，如 MEMORY.md）
   → 摘要整合的消息到文件
   → 更新 last_consolidated 索引
   → 不修改 messages 列表

5. 持久化
   save(session)
   ├─ 写入元数据行 (_type="metadata")
   ├─ 每条消息作为 JSON 行写入
   └─ 更新内存缓存

6. 缓存失效
   invalidate(key) → 从 _cache dict 移除
```

### 存储格式

**JSONL 文件结构** (`workspace/sessions/telegram_123456789.jsonl`):

```json
{"_type":"metadata","key":"telegram:123456789","created_at":"2026-03-14T10:00:00","updated_at":"2026-03-14T10:30:00","metadata":{},"last_consolidated":0}
{"role":"user","content":"Hello!","timestamp":"2026-03-14T10:00:00"}
{"role":"assistant","content":"Hi there! How can I help?","timestamp":"2026-03-14T10:00:01"}
{"role":"user","content":"What's the weather?","timestamp":"2026-03-14T10:30:00","tool_calls":[{"id":"call_123","type":"function","function":{"name":"get_weather","arguments":"{}"}}]}
{"role":"tool","tool_call_id":"call_123","content":"Temperature: 72°F","timestamp":"2026-03-14T10:30:01","name":"get_weather"}
```

### 关键设计决策

1. **只追加消息**: 保留 LLM 缓存效率（不变的消息 ID）
2. **整合跟踪**: `last_consolidated` 索引分隔活动和归档消息
3. **JSONL 格式**: 基于行、人类可读、易于追加、可流式传输
4. **内存缓存**: 避免频繁访问会话的磁盘 I/O
5. **旧版迁移**: 自动将会话从 `~/.nanobot/sessions/` 移动到工作区

---

## 集成: Bus + Session 流

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       完整消息流程                                │
└────────────────────────────────────────────────────────────────────────────┘

用户通过 Telegram 发送消息
              │
              ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 通道层 (channels/telegram.py)                                               │
│ - 接收消息                                                                   │
│ - 创建 InboundMessage(channel="telegram", sender_id="...", ...)              │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 总线层 (bus/)                                                                │
│ - message_bus.publish_inbound(inbound_msg)                                  │
│ - 放入 asyncio.Queue                                                        │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 会话层 (session/)                                                            │
│ - session_manager.get_or_create(inbound_msg.session_key)                    │
│ - session.add_message(role="user", content=...)                             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 代理层 (agent/)                                                              │
│ - session.get_history() → LLM 上下文                                        │
│ - 使用工具/LLM 处理                                                          │
│ - 生成响应                                                                    │
│ - session.add_message(role="assistant", content=...)                         │
│ - session_manager.save(session)                                              │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 总线层 (bus/)                                                                │
│ - message_bus.publish_outbound(outbound_msg)                                │
│ - 放入 asyncio.Queue                                                        │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 通道层 (channels/telegram.py)                                               │
│ - 消费出站消息                                                               │
│ - 通过 Telegram API 发送响应给用户                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 关键设计模式

### 生产者-消费者模式
- **Bus**: 通道是生产者，代理是消费者（出站反之）
- **Queues**: asyncio.Queue 提供线程安全的阻塞/异步操作

### 仓库模式
- **SessionManager**: 抽象存储细节，提供 CRUD 操作
- **Session**: 带业务逻辑的领域模型（add_message, get_history）

### 缓存旁路模式
- **SessionManager._cache**: 频繁访问会话的内存缓存
- **invalidate()**: 外部更改时的显式缓存失效

### 事件驱动架构
- **松耦合**: 通道不了解代理内部
- **可扩展**: 无需修改核心即可添加新通道

### 不可变消息历史
- **只追加**: 消息从不删除或修改
- **整合**: 外部进程将摘要写入文件
- **缓存效率**: 保留消息 ID 用于 LLM 提示缓存
