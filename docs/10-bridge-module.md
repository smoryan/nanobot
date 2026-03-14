# Bridge 模块 (bridge/)

WhatsApp Bridge 是一个 TypeScript/Node.js 模块，使 nanobot 的 Python 后端能够与 WhatsApp 消息服务通信。它使用 **基于 WebSocket 的架构** 来桥接 Python nanobot 代理与 WhatsApp Web 协议。

## 目录结构

```
bridge/
├── package.json       # 项目元数据和依赖
├── tsconfig.json      # TypeScript 编译配置
└── src/
    ├── index.ts       # 入口点
    ├── server.ts      # WebSocket 服务器实现
    ├── whatsapp.ts    # WhatsApp 客户端包装器
    └── types.d.ts     # QR 码终端模块的类型定义
```

---

## 为什么需要 Bridge？

WhatsApp 的 Web 协议复杂，Python 原生不支持。Bridge 利用:
- **@whiskeysockets/baileys** (v7.0.0-rc.9) — Node.js 中 WhatsApp Web 实现的事实标准
- **WebSocket** — Python 和 TypeScript 之间的实时双向通信
- **隔离** — 通过仅绑定到 localhost (127.0.0.1) 实现安全性

---

## 架构概述

```
┌─────────────────┐         WebSocket (ws://127.0.0.1:3001)         ┌──────────────────┐
│  Python Agent   │ ◄─────────────────────────────────────────────► │   Bridge Server  │
│  (nanobot)      │                                                   │  (TypeScript)   │
│  whatsapp.py    │                                                   │  server.ts       │
└─────────────────┘                                                   └────────┬─────────┘
                                                                               │
                                                                       Baileys Protocol
                                                                               │
                                                                       ┌────────▼─────────┐
                                                                       │  WhatsApp Server │
                                                                       │  (messaging)     │
                                                                       └──────────────────┘
```

---

## 1. index.ts - 入口点

```typescript
// 为 Baileys 设置 crypto polyfill
const PORT = process.env.BRIDGE_PORT || '3001';
const AUTH_DIR = process.env.AUTH_DIR || '~/.nanobot/whatsapp-auth';
const TOKEN = process.env.BRIDGE_TOKEN;  // 可选认证

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN);
server.start();
```

**职责**:
- 为 Baileys polyfill `crypto`（ESM 需要）
- 从环境变量加载配置
- 创建 `BridgeServer` 实例
- 处理优雅关闭（SIGINT, SIGTERM）

---

## 2. server.ts - Bridge 服务器

管理到 Python 客户端的 WebSocket 连接并转发消息到/从 WhatsApp。

### 连接流程

1. **WebSocket 服务器设置**
   - 绑定到 `127.0.0.1:PORT`（仅 localhost，安全）
   - 可选令牌认证（第一条消息必须是 `{"type": "auth", "token": "..."}`）
   - 5 秒认证超时

2. **WhatsApp 客户端初始化**
   - 创建 `WhatsAppClient` 实例
   - 注册事件回调:
     - `onMessage` → 广播到所有 Python 客户端
     - `onQR` → 广播 QR 码用于认证
     - `onStatus` → 广播连接状态

3. **消息处理**
   - 从 Python 接收 `{"type": "send", "to": "...", "text": "..."}`
   - 转发到 WhatsApp 客户端
   - 响应 `{"type": "sent", "to": "..."}`

4. **广播**
   - 发送消息、状态更新和 QR 码到所有连接的 Python 客户端
   - 优雅处理客户端断开连接

---

## 3. whatsapp.ts - WhatsApp 客户端

使用 Baileys 库实现 WhatsApp Web 协议。

### 连接生命周期

1. **认证状态管理**
   ```typescript
   const { state, saveCreds } = await useMultiFileAuthState(authDir);
   ```
   - 在 `~/.nanobot/whatsapp-auth/` 存储凭据
   - 跨重启持久化
   - 连接丢失时自动重连

2. **QR 码流程**
   - 首次: 生成在终端显示的 QR 码
   - 用户使用 WhatsApp → 已链接设备扫描
   - 凭据保存到 `authDir`

3. **消息接收**
   - 监听 `messages.upsert` 事件
   - 过滤掉:
     - 自己发送的消息 (`fromMe`)
     - 状态广播
     - 非通知消息
   - 提取文本、媒体（图像、视频、文档）
   - 下载媒体到 `~/.nanobot/media/`

4. **媒体处理**
   - 图像: 使用唯一文件名前缀下载
   - 文档: 保留原始文件名 + 唯一前缀
   - 视频: 使用派生扩展名下载
   - 语音消息: 标记为 `[Voice Message]`（不下载）

5. **重连逻辑**
   - 断开时自动重连（登出除外）
   - 重连尝试之间 5 秒延迟
   - 通知 Python 客户端状态变化

---

## 4. 通信协议

### Python → TypeScript Bridge (发送消息)

**请求:**
```json
{
  "type": "send",
  "to": "6281234567890@s.whatsapp.net",
  "text": "Hello from nanobot!"
}
```

**响应 (成功):**
```json
{
  "type": "sent",
  "to": "6281234567890@s.whatsapp.net"
}
```

**响应 (错误):**
```json
{
  "type": "error",
  "error": "Error message here"
}
```

### TypeScript Bridge → Python (接收消息)

**认证 (如果启用令牌):**
```json
{
  "type": "auth",
  "token": "your-bridge-token"
}
```

**入站消息:**
```json
{
  "type": "message",
  "id": "3EB0...",
  "sender": "6281234567890@s.whatsapp.net",
  "pn": "",
  "content": "Hello nanobot!",
  "timestamp": 1678901234,
  "isGroup": false,
  "media": ["/path/to/image.jpg"]
}
```

**QR 码 (用于认证):**
```json
{
  "type": "qr",
  "qr": "2@9F9..."
}
```

**状态更新:**
```json
{
  "type": "status",
  "status": "connected"  // 或 "disconnected"
}
```

**错误:**
```json
{
  "type": "error",
  "error": "Error description"
}
```

---

## 5. Python 通道实现

```python
# nanobot/channels/whatsapp.py

class WhatsAppChannel(BaseChannel):
    async def start(self):
        """连接到 bridge 并监听消息"""
        async with websockets.connect(self.config.bridge_url) as ws:
            if self.config.bridge_token:
                await ws.send(json.dumps({"type": "auth", "token": ...}))
            
            async for message in ws:
                await self._handle_bridge_message(message)
    
    async def send(self, msg: OutboundMessage):
        """通过 bridge 发送消息"""
        payload = {
            "type": "send",
            "to": msg.chat_id,
            "text": msg.content
        }
        await self._ws.send(json.dumps(payload))
```

---

## 6. 类型定义

### TypeScript 类型

```typescript
// 来自 WhatsApp 的入站消息
export interface InboundMessage {
  id: string;           // 唯一消息 ID
  sender: string;       // WhatsApp JID (如 phone@s.whatsapp.net)
  pn: string;           // 旧版电话号码（已弃用）
  content: string;      // 消息文本或标题
  timestamp: number;    // Unix 时间戳
  isGroup: boolean;     // 如果来自群聊为 True
  media?: string[];     // 下载的媒体路径数组
}

// WhatsApp 客户端选项
export interface WhatsAppClientOptions {
  authDir: string;                              // 认证状态目录
  onMessage: (msg: InboundMessage) => void;      // 消息回调
  onQR: (qr: string) => void;                    // QR 码回调
  onStatus: (status: string) => void;           // 状态回调
}

// 来自 Python 的发送命令
interface SendCommand {
  type: 'send';
  to: string;
  text: string;
}

// 到 Python 的 Bridge 消息
interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error';
  [key: string]: unknown;  // 基于类型的额外字段
}
```

### Python 类型

```python
class WhatsAppConfig(Base):
    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""
    allow_from: list[str] = []
```

---

## 7. 依赖

### 生产依赖
- **@whiskeysockets/baileys** (v7.0.0-rc.9) — WhatsApp Web 协议实现
- **ws** (v8.17.1) — WebSocket 服务器
- **qrcode-terminal** (v0.12.0) — 终端 QR 码显示
- **pino** (v9.0.0) — 日志库

### 开发依赖
- **typescript** (v5.4.0) — TypeScript 编译器
- **@types/node** (v20.14.0) — Node.js 类型定义
- **@types/ws** (v8.5.10) — WebSocket 类型定义

---

## 8. 安全考虑

1. **仅 Localhost**: WebSocket 服务器绑定到 `127.0.0.1`，从不暴露到外部网络
2. **可选令牌认证**: `BRIDGE_TOKEN` 环境变量用于额外安全
3. **无直接 WhatsApp API**: 使用 Baileys 库，不是官方 WhatsApp Business API
4. **媒体隔离**: 下载到 `~/.nanobot/media/`，使用唯一文件名
5. **去重**: Python 通道跟踪已处理的消息 ID（最后 1000 条）

---

## 9. 构建和运行

### 构建过程
```bash
cd bridge/
npm install    # 安装依赖
npm run build  # 编译 TypeScript 到 dist/
```

### 运行 Bridge
```bash
# 直接运行
npm start

# 通过 nanobot CLI
nanobot channels login
```

### 环境变量
- `BRIDGE_PORT`: WebSocket 服务器端口（默认: 3001）
- `AUTH_DIR`: WhatsApp 认证目录（默认: ~/.nanobot/whatsapp-auth）
- `BRIDGE_TOKEN`: 可选认证令牌

### TypeScript 配置
- Target: ES2022
- Module: ESNext
- Output: `dist/` 目录
- 启用严格模式
