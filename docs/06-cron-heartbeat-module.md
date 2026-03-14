# Cron & Heartbeat 模块 (nanobot/cron/, nanobot/heartbeat/)

这两个模块提供定时和周期性任务执行能力。

## 目录结构

```
nanobot/cron/
├── __init__.py    # 公共 API 导出
├── types.py       # 类型定义
└── service.py     # Cron 服务实现

nanobot/heartbeat/
├── __init__.py    # 公共 API 导出
└── service.py     # Heartbeat 服务实现
```

---

## 1. Cron 模块

### 职责

为 nanobot 代理提供定时任务管理，支持基于时间的代理轮次和系统事件执行。任务持久化到磁盘，可以动态管理。

### types.py - 类型定义

#### CronSchedule
```python
@dataclass
class CronSchedule:
    """Cron 任务的调度定义"""
    
    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None       # 一次性执行时间戳（毫秒）
    every_ms: int | None = None    # 周期执行间隔（毫秒）
    expr: str | None = None        # Cron 表达式
    tz: str | None = None          # 时区
```

#### CronPayload
```python
@dataclass
class CronPayload:
    """任务运行时要做什么"""
    
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""              # 发送给代理的任务消息
    deliver: bool = False          # 是否发送响应到通道
    channel: str | None = None     # 通道名
    to: str | None = None          # 收件人标识符
```

#### CronJobState
```python
@dataclass
class CronJobState:
    """任务的运行时状态"""
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None
```

#### CronJob
```python
@dataclass
class CronJob:
    """完整的定时任务"""
    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule
    payload: CronPayload
    state: CronJobState
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False  # 用于一次性任务
```

### service.py - Cron 服务

#### CronService
```python
class CronService:
    """管理和执行定时任务的服务"""
    
    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None
    ): ...
    
    # 生命周期
    async def start(self) -> None
    def stop(self) -> None
    
    # 公共 API
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]
    
    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> CronJob
    
    def remove_job(self, job_id: str) -> bool
    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None
    async def run_job(self, job_id: str, force: bool = False) -> bool
    def status(self) -> dict
```

### 定时任务工作原理

1. **初始化**: `start()` 从 `jobs.json` 加载任务，计算下次运行时间，设置定时器
2. **定时循环**: `_arm_timer()` 调度异步任务在最早下次运行时间唤醒
3. **执行**: 定时器触发时，`_on_timer()` 找到到期的任务并执行
4. **状态更新**: 执行后，更新任务状态（last_run_at_ms, last_status, last_error）
5. **重新调度**:
   - 'at' 任务: 禁用任务（或如果 delete_after_run=True 则删除）
   - 'every'/'cron' 任务: 计算下次运行时间并重新设置定时器
6. **持久化**: `_save_store()` 将所有任务写回 `jobs.json`

### 调度类型

| 类型 | 描述 | 示例 |
|------|------|------|
| `at` | 一次性执行 | 在特定时间戳执行一次 |
| `every` | 固定间隔 | 每 3600000ms (1小时) 执行 |
| `cron` | Cron 表达式 | `0 9 * * *` (每天 9:00) |

---

## 2. Heartbeat 模块

### 职责

通过读取 HEARTBEAT.md 文件，使用 LLM 评估是否有活动任务，并通过代理循环执行它们，提供周期性任务检查。

### 两阶段设计

- **阶段 1（决策）**: 读取 HEARTBEAT.md，通过虚拟工具调用询问 LLM 决定是否有活动任务
- **阶段 2（执行）**: 如果阶段 1 返回 "run"，通过完整代理循环执行任务并投递结果

这种设计避免了不可靠的自由文本解析和已弃用的 HEARTBEAT_OK 令牌。

### service.py - Heartbeat 服务

#### 虚拟工具定义
```python
_HEARTBEAT_TOOL = [{
    "type": "function",
    "function": {
        "name": "heartbeat",
        "description": "Review tasks and report heartbeat decision.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["skip", "run"]},
                "tasks": {"type": "string", "description": "Active tasks summary"},
            },
            "required": ["action"],
        },
    },
}]
```

#### HeartbeatService
```python
class HeartbeatService:
    """周期性唤醒代理检查任务的 Heartbeat 服务"""
    
    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,  # 默认 30 分钟
        enabled: bool = True,
    ): ...
    
    @property
    def heartbeat_file(self) -> Path:
        """返回工作区中 HEARTBEAT.md 的路径"""
    
    async def start(self) -> None
    def stop(self) -> None
    async def trigger_now(self) -> str | None
```

### Heartbeat 周期任务工作原理

1. **启动**: `start()` 创建运行 `_run_loop()` 的异步任务
2. **循环**: `_run_loop()` 休眠 `interval_s` 秒，然后调用 `_tick()`
3. **读取文件**: `_tick()` 从工作区读取 HEARTBEAT.md
4. **阶段 1 - 决策**: `_decide()` 通过虚拟工具将内容发送给 LLM
   - LLM 调用 heartbeat 工具，action="skip" 或 "run"
   - 如果是 "run"，包含任务摘要
5. **阶段 2 - 执行**: 仅当 action="run" 时
   - 调用 `on_execute(tasks)` 通过代理循环运行
   - 使用 `evaluate_response()` 检查结果是否应该投递
   - 如果是，调用 `on_notify(response)` 发送到通道
6. **重复**: 循环继续直到服务停止

### HEARTBEAT.md 格式

```markdown
# Heartbeat Tasks

此文件每 30 分钟由你的 nanobot 代理检查。
在下方添加你希望代理周期性处理的任务。

如果此文件没有任务（只有标题和注释），代理将跳过 heartbeat。

## Active Tasks

<!-- 在此行下方添加你的周期性任务 -->

- [ ] 检查天气预报并发送摘要
- [ ] 扫描收件箱查找紧急邮件
- [ ] 回顾每日新闻并发送亮点

## Completed

<!-- 将完成的任务移到这里或删除它们 -->
```

**重要**: 代理也可以在被要求"添加周期性任务"时更新此文件。

---

## 3. 配置

### Heartbeat 配置 (config.json)

```json
{
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  }
}
```

---

## 4. 集成

### 在 Gateway 中使用

```python
# nanobot/cli/commands.py

# 设置 cron 回调
async def on_cron_job(job: CronJob) -> str | None:
    return await agent.process_direct(
        message=job.payload.message,
        session_key=f"cron:{job.id}",
    )

cron_service = CronService(
    store_path=get_cron_dir() / "jobs.json",
    on_job=on_cron_job
)

# 设置 heartbeat 回调
async def on_heartbeat_execute(task: str) -> str:
    return await agent.process_direct(message=task, session_key="heartbeat")

async def on_heartbeat_notify(response: str) -> None:
    target = _pick_heartbeat_target(config)
    if target:
        await bus.publish_outbound(OutboundMessage(
            channel=target["channel"],
            chat_id=target["chat_id"],
            content=response
        ))

heartbeat_service = HeartbeatService(
    workspace=workspace,
    provider=provider,
    model=model,
    on_execute=on_heartbeat_execute,
    on_notify=on_heartbeat_notify,
    interval_s=config.gateway.heartbeat.interval_s,
    enabled=config.gateway.heartbeat.enabled
)

# 启动服务
await cron_service.start()
await heartbeat_service.start()
```

---

## 5. 使用场景对比

| 场景 | 使用 Cron | 使用 Heartbeat |
|------|-----------|----------------|
| 固定时间提醒 | ✅ `0 9 * * *` | ❌ |
| 固定间隔任务 | ✅ 每 1 小时 | ✅ 每 30 分钟 |
| 条件性执行 | ❌ | ✅ LLM 决定 |
| 用户定义任务 | ✅ | ✅ |
| 持久化 | ✅ jobs.json | ❌ 内存中 |
| 一次性行务 | ✅ `at` + delete_after_run | ❌ |
