# nanobot 项目概述与架构

## 项目简介

**nanobot** 是一个超轻量级的个人 AI 助手框架，灵感来自 [OpenClaw](https://github.com/openclaw/openclaw)。它以 **99% 更少的代码** 实现了 OpenClaw 的核心代理功能，同时保持代码简洁、易读、易于研究和扩展。

### 核心特性

| 特性 | 描述 |
|------|------|
| 🪶 **超轻量** | 比 OpenClaw 少 99% 代码，显著更快 |
| 🔬 **研究友好** | 代码清晰可读，易于理解、修改和扩展 |
| ⚡️ **极速启动** | 最小占用意味着更快的启动和迭代 |
| 💎 **易于使用** | 一键部署，开箱即用 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              nanobot 架构                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Telegram  │     │   Discord   │     │   Feishu    │     │   WhatsApp  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │                   │
       └───────────────────┴───────────────────┴───────────────────┘
                                   │
                                   ▼
                         ┌─────────────────┐
                         │  ChannelManager │  ← channels/manager.py
                         │   (通道管理器)   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   MessageBus    │  ← bus/queue.py
                         │   (消息总线)    │
                         └────────┬────────┘
                                  │
       ┌──────────────────────────┼──────────────────────────┐
       │                          │                          │
       ▼                          ▼                          ▼
┌─────────────┐          ┌─────────────┐          ┌─────────────┐
│ AgentLoop   │          │ CronService │          │HeartbeatSvc │
│ (核心循环)  │          │ (定时任务)  │          │ (周期任务)  │
└──────┬──────┘          └─────────────┘          └─────────────┘
       │
       ├──────────────────────────────────────────────────────────┐
       │                          │                               │
       ▼                          ▼                               ▼
┌─────────────┐          ┌─────────────┐          ┌─────────────────────┐
│ContextBlder │          │MemoryConsol │          │    ToolRegistry     │
│ (上下文构建)│          │ (内存整合)  │          │ (工具注册表)        │
└─────────────┘          └─────────────┘          └──────────┬──────────┘
                                                            │
                         ┌──────────────────────────────────┼───────────────┐
                         │                                  │               │
                         ▼                                  ▼               ▼
                  ┌─────────────┐                    ┌─────────────┐ ┌─────────────┐
                  │ LLMProvider │                    │  MCP Tools  │ │ SubagentMgr │
                  │ (LLM 提供者)│                    │ (MCP 工具)  │ │ (子代理)    │
                  └──────┬──────┘                    └─────────────┘ └─────────────┘
                         │
    ┌────────────────────┼────────────────────────────┐
    │                    │                            │
    ▼                    ▼                            ▼
┌─────────┐       ┌───────────┐               ┌───────────┐
│ LiteLLM │       │  Custom   │               │AzureOpenAI│
│         │       │  Provider │               │  Provider │
└─────────┘       └───────────┘               └───────────┘
```

---

## 模块概览

| 模块 | 路径 | 职责 |
|------|------|------|
| **agent/** | `nanobot/agent/` | 核心代理逻辑：LLM ↔ 工具执行循环、上下文构建、内存管理 |
| **channels/** | `nanobot/channels/` | 聊天平台集成：Telegram、Discord、Feishu、Slack、Email、QQ、钉钉、Matrix、WhatsApp 等 |
| **providers/** | `nanobot/providers/` | LLM 提供者抽象：LiteLLM、自定义端点、Azure OpenAI、OAuth 提供者 |
| **config/** | `nanobot/config/` | 配置管理：Schema 定义、加载/保存、路径解析 |
| **bus/** | `nanobot/bus/` | 消息路由：事件类型、异步队列 |
| **session/** | `nanobot/session/` | 会话管理：对话历史持久化 |
| **cron/** | `nanobot/cron/` | 定时任务：Cron 表达式、一次性任务、周期任务 |
| **heartbeat/** | `nanobot/heartbeat/` | 周期检查：HEARTBEAT.md 文件监控 |
| **skills/** | `nanobot/skills/` | 技能系统：内置技能、加载机制、创建工具 |
| **cli/** | `nanobot/cli/` | 命令行接口：所有 CLI 命令定义 |
| **utils/** | `nanobot/utils/` | 工具函数：文件操作、消息处理、Token 估算 |
| **templates/** | `nanobot/templates/` | 模板文件：AGENTS.md、SOUL.md、USER.md 等 |
| **bridge/** | `bridge/` | WhatsApp 桥接：TypeScript/Node.js 实现 |

---

## 核心数据流

### 1. 消息处理流程

```
用户消息
    ↓
Channel._handle_message()
    ↓ (权限检查)
InboundMessage → MessageBus.publish_inbound()
    ↓
AgentLoop.consume_inbound()
    ↓
SessionManager.get_or_create()
    ↓
ContextBuilder.build_messages()
    ↓ (构建系统提示 + 历史 + 技能)
LLMProvider.chat_with_retry()
    ↓ (带工具定义)
工具执行循环 (最多 40 次迭代)
    ↓
MemoryConsolidator.maybe_consolidate()
    ↓
SessionManager.save()
    ↓
OutboundMessage → MessageBus.publish_outbound()
    ↓
Channel.send() → 平台 API
```

### 2. 提供者选择流程

```
用户请求模型
    ↓
Config._match_provider()
    ↓
1. 检查显式 provider 配置
2. 检查模型名前缀 (如 "deepseek/")
3. 检查模型名关键词 (从注册表匹配)
4. 回退到网关检测 (api_key 前缀、api_base 关键词)
    ↓
实例化提供者:
- is_direct? → CustomProvider, AzureOpenAIProvider, OpenAICodexProvider
- is_oauth? → OpenAICodexProvider
- 否则 → LiteLLMProvider
    ↓
Provider.chat() → LLMResponse
```

---

## 关键设计模式

### 1. 生产者-消费者模式
- **MessageBus**: 通道是生产者，代理是消费者（出站反之）
- **asyncio.Queue**: 线程安全的阻塞/异步操作

### 2. 注册表模式
- **ProviderSpec**: 单一数据源，所有提供者元数据
- **ToolRegistry**: 动态工具注册/注销
- **ChannelRegistry**: 自动发现内置和插件通道

### 3. 仓库模式
- **SessionManager**: 抽象存储细节，提供 CRUD 操作
- **CronService**: 任务持久化到 JSON 文件

### 4. 事件驱动架构
- **松耦合**: 通道不了解代理内部
- **可扩展**: 无需修改核心即可添加新通道

### 5. 不可变消息历史
- **只追加**: 消息从不删除或修改
- **整合**: 外部进程将摘要写入文件
- **缓存效率**: 保留消息 ID 用于 LLM 提示缓存

---

## 配置体系

### 配置文件位置
- 默认: `~/.nanobot/config.json`
- 多实例: `~/.nanobot-<name>/config.json` (通过 `--config` 指定)

### 配置结构
```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto"
    }
  },
  "channels": {
    "telegram": { "enabled": true, "token": "...", "allowFrom": [] }
  },
  "providers": {
    "openrouter": { "apiKey": "sk-or-..." }
  },
  "gateway": {
    "port": 18790,
    "heartbeat": { "enabled": true, "intervalS": 1800 }
  },
  "tools": {
    "restrictToWorkspace": false,
    "mcpServers": {}
  }
}
```

---

## 快速开始

```bash
# 1. 安装
pip install -e .

# 2. 初始化
nanobot onboard

# 3. 配置 API Key
vim ~/.nanobot/config.json

# 4. 启动代理
nanobot agent

# 5. 或启动网关（连接聊天平台）
nanobot gateway
```

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **语言** | Python 3.11+, TypeScript (桥接) |
| **CLI** | Typer, Rich, prompt_toolkit |
| **LLM** | LiteLLM, OpenAI SDK |
| **配置** | Pydantic, Pydantic-Settings |
| **异步** | asyncio, websockets |
| **聊天平台** | python-telegram-bot, discord.py, lark-oapi, slack-sdk, etc. |
| **MCP** | mcp (Model Context Protocol) |

---

## 文档目录

| 文档 | 内容 |
|------|------|
| [01-agent-module.md](./01-agent-module.md) | 代理核心模块 |
| [02-channels-module.md](./02-channels-module.md) | 通道模块 |
| [03-providers-module.md](./03-providers-module.md) | 提供者模块 |
| [04-config-module.md](./04-config-module.md) | 配置模块 |
| [05-bus-session-module.md](./05-bus-session-module.md) | 消息总线与会话管理 |
| [06-cron-heartbeat-module.md](./06-cron-heartbeat-module.md) | 定时任务与心跳 |
| [07-cli-module.md](./07-cli-module.md) | CLI 命令 |
| [08-skills-module.md](./08-skills-module.md) | 技能系统 |
| [09-utils-templates-module.md](./09-utils-templates-module.md) | 工具与模板 |
| [10-bridge-module.md](./10-bridge-module.md) | WhatsApp 桥接 |
