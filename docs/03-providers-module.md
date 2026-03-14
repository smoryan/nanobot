# Providers 模块 (nanobot/providers/)

提供者模块实现了用于 LLM 抽象的**提供者注册表模式**。所有提供者元数据都集中在 `registry.py` 中，使其成为单一数据源。添加新提供者只需 2 步，无需修改 if-elif 链。

## 目录结构

```
nanobot/providers/
├── __init__.py              # 模块导出
├── base.py                  # 基础 LLM 提供者抽象
├── registry.py              # 提供者注册表（关键）
├── litellm_provider.py      # LiteLLM 多提供者支持
├── custom_provider.py       # 直接 OpenAI 兼容端点
├── azure_openai_provider.py # Azure OpenAI 特定实现
├── openai_codex_provider.py # OAuth 基础的 OpenAI Codex
└── transcription.py         # Groq Whisper 语音转录
```

---

## 1. base.py - 基础提供者抽象

### 职责

定义所有 LLM 提供者的抽象接口和请求/响应的共享数据结构。

### 关键类

```python
@dataclass
class ToolCallRequest:
    """LLM 的工具调用请求"""
    id: str
    name: str
    arguments: dict[str, Any]
    provider_specific_fields: dict[str, Any] | None = None
    
    def to_openai_tool_call(self) -> dict[str, Any]: ...

@dataclass
class LLMResponse:
    """LLM 提供者的响应"""
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None  # 用于 Kimi, DeepSeek-R1
    thinking_blocks: list[dict] | None = None  # Anthropic 扩展思考
    
    @property
    def has_tool_calls(self) -> bool: ...

@dataclass(frozen=True)
class GenerationSettings:
    """存储在提供者上的默认生成参数"""
    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None

class LLMProvider(ABC):
    """LLM 提供者的抽象基类"""
    
    def __init__(self, api_key: str | None = None, api_base: str | None = None): ...
    
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse: ...
    
    async def chat_with_retry(self, ...) -> LLMResponse: ...
    
    @abstractmethod
    def get_default_model(self) -> str: ...
```

### 关键特性

- **重试逻辑**: 瞬态错误（429, 500-504, 超时）自动重试，带指数退避（1s, 2s, 4s）
- **内容清理**: 空内容被替换以避免提供者 400 错误
- **消息过滤**: 只传递提供者安全的键

---

## 2. registry.py - 提供者注册表（关键）

### 职责

**单一数据源**，用于所有 LLM 提供者元数据。所有提供者发现、模型前缀、环境变量设置和配置匹配都从此注册表派生。

### ProviderSpec 类

```python
@dataclass(frozen=True)
class ProviderSpec:
    """一个 LLM 提供者的元数据"""
    
    # 身份
    name: str              # 配置字段名，如 "dashscope"
    keywords: tuple[str, ...]  # 模型名关键词（小写）
    env_key: str           # LiteLLM 环境变量，如 "DASHSCOPE_API_KEY"
    display_name: str = "" # 在 `nanobot status` 中显示
    
    # 模型前缀
    litellm_prefix: str = ""     # "dashscope" → 模型变为 "dashscope/{model}"
    skip_prefixes: tuple[str, ...] = ()  # 如果已前缀则不前缀
    
    # 额外环境变量
    env_extras: tuple[tuple[str, str], ...] = ()  # 如 (("ZHIPUAI_API_KEY", "{api_key}"),)
    
    # 网关/本地检测
    is_gateway: bool = False       # 路由任何模型（OpenRouter, AiHubMix）
    is_local: bool = False         # 本地部署（vLLM, Ollama）
    detect_by_key_prefix: str = ""  # 匹配 api_key 前缀，如 "sk-or-"
    detect_by_base_keyword: str = "" # 匹配 api_base URL 中的子串
    default_api_base: str = ""     # 回退基础 URL
    
    # 网关行为
    strip_model_prefix: bool = False  # 重新前缀前剥离
    
    # 每模型参数覆盖
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()
    
    # OAuth 提供者
    is_oauth: bool = False  # 使用 OAuth 流而不是 API key
    
    # 直接提供者
    is_direct: bool = False  # 完全绕过 LiteLLM
    
    # 提示缓存
    supports_prompt_caching: bool = False  # Anthropic 提示缓存
```

### ProviderSpec 字段含义

| 字段 | 描述 | 示例 |
|------|------|------|
| `name` | 配置字段名（必须匹配 config 中的 `providers.{name}`） | `"dashscope"` |
| `keywords` | 模型名关键词用于自动匹配 | `("deepseek",)` 匹配 `deepseek-chat` |
| `env_key` | LiteLLM 环境变量 | `"DEEPSEEK_API_KEY"` |
| `display_name` | `nanobot status` 显示的人 readable 名称 | `"DeepSeek"` |
| `litellm_prefix` | 添加到模型名的前缀 | `"deepseek"` → `deepseek/deepseek-chat` |
| `skip_prefixes` | 如果已以此开头则不前缀 | `("deepseek/",)` 避免双重前缀 |
| `env_extras` | 要设置的额外环境变量 | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `is_gateway` | 可以路由任何模型（如 OpenRouter） | `True` |
| `is_local` | 本地部署 | `True` 用于 vLLM/Ollama |
| `detect_by_key_prefix` | 通过 API key 前缀匹配网关 | `"sk-or-"` → OpenRouter |
| `detect_by_base_keyword` | 通过 API base URL 匹配网关 | URL 中的 `"aihubmix"` |
| `is_oauth` | 使用 OAuth 而不是 API key | `True` 用于 OpenAI Codex |
| `is_direct` | 完全绕过 LiteLLM | `True` 用于 CustomProvider |

### 注册表函数

```python
def find_by_model(model: str) -> ProviderSpec | None:
    """通过模型名关键词匹配标准提供者（不区分大小写）。
    跳过网关/本地 — 那些通过 api_key/api_base 匹配"""

def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    """检测网关/本地提供者：
    1. provider_name（配置键）
    2. api_key 前缀
    3. api_base 关键词"""

def find_by_name(name: str) -> ProviderSpec | None:
    """通过配置字段名查找提供者规范，如 'dashscope'"""
```

### 如何添加新提供者

**步骤 1**: 在 `registry.py` 的 `PROVIDERS` 中添加 `ProviderSpec`：

```python
ProviderSpec(
    name="myprovider",                   # 配置字段名
    keywords=("myprovider", "mymodel"),  # 模型名关键词
    env_key="MYPROVIDER_API_KEY",        # LiteLLM 环境变量
    display_name="My Provider",          # 在状态中显示
    litellm_prefix="myprovider",         # 自动前缀
    skip_prefixes=("myprovider/",),     # 避免双重前缀
),
```

**步骤 2**: 在 `config/schema.py` 的 `ProvidersConfig` 中添加字段：

```python
class ProvidersConfig(Base):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

就这样！环境变量、模型前缀、配置匹配和 `nanobot status` 显示都会自动工作。

### 注册表中的提供者（按优先级排序）

1. **custom** - 直接 OpenAI 兼容端点（绕过 LiteLLM）
2. **azure_openai** - Azure OpenAI 直接 API
3. **网关**（通过 api_key/api_base 检测，在回退中胜出）:
   - openrouter, aihubmix, siliconflow
   - volcengine, volcengine_coding_plan
   - byteplus, byteplus_coding_plan
4. **标准提供者**（通过模型名关键词匹配）:
   - anthropic, openai, openai_codex, github_copilot
   - deepseek, gemini, zhipu, dashscope, moonshot, minimax
5. **本地部署**:
   - vllm, ollama
6. **辅助**:
   - groq（主要用于 Whisper 转录）

---

## 3. litellm_provider.py - LiteLLM 集成

### 职责

通过 [LiteLLM](https://github.com/BerriAI/litellm) 库提供多提供者支持。通过注册表驱动统一接口处理 20+ 提供者。

### 类签名

```python
class LiteLLMProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ): ...
```

### 关键特性

- **网关检测**: 通过 `provider_name`、`api_key` 前缀或 `api_base` 关键词自动检测网关
- **模型前缀**: 自动应用提供者前缀（如 `gpt-4` → `openai/gpt-4`）
- **缓存控制**: 为 Anthropic 提示缓存注入 `cache_control`
- **模型覆盖**: 应用每模型参数覆盖（如 kimi-k2.5 temperature >= 1.0）
- **工具调用规范化**: 将工具调用 ID 缩短为 9 字符字母数字形式以兼容提供者

---

## 4. custom_provider.py - 直接 OpenAI 兼容端点

### 职责

完全绕过 LiteLLM，直接调用 OpenAI 兼容 API（LM Studio, llama.cpp, 本地服务器, Together AI, Fireworks 等）。

### 类签名

```python
class CustomProvider(LLMProvider):
    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = "http://localhost:8000/v1",
        default_model: str = "default",
    ): ...
```

### 关键特性

- **直接 OpenAI 客户端**: 使用 `openai` 库的 `AsyncOpenAI`
- **会话亲和**: 设置 `x-session-affinity` 头用于后端缓存局部性
- **无 LiteLLM 开销**: 直接 API 调用，无模型前缀，无环境变量设置
- **空 API key 支持**: 适用于不需要认证的本地服务器

---

## 5. azure_openai_provider.py - Azure OpenAI 提供者

### 职责

Azure OpenAI 特定实现，符合 API 版本 2024-10-21。直接 HTTP 调用，绕过 LiteLLM。

### 关键特性

- **API 版本 2024-10-21**: 硬编码最新 API 版本
- **URL 中的部署名**: 在 URL 路径中使用模型字段作为 Azure 部署名
- **api-key 头**: 使用 `api-key` 头而不是 Authorization Bearer
- **max_completion_tokens**: 使用 `max_completion_tokens` 而不是 `max_tokens`
- **温度过滤**: 对推理模型（gpt-5, o1, o3, o4）省略温度

---

## 6. openai_codex_provider.py - OAuth 基础提供者

### 职责

使用 OAuth 认证调用 OpenAI 的 Codex Responses API。需要 ChatGPT Plus 或 Pro 账户。

### 关键特性

- **OAuth 认证**: 使用 `oauth_cli_kit` 进行令牌管理
- **SSE 流式传输**: 消费 Codex API 的 Server-Sent Events
- **消息转换**: 将 OpenAI 格式转换为 Codex 扁平格式
- **工具调用 ID 映射**: 分割复合工具调用 ID（`call_id|item_id`）
- **提示缓存**: 使用 SHA256 哈希作为缓存键

---

## 7. transcription.py - 语音转录

### 职责

使用 Groq 的 Whisper API 进行语音转录。提供极快的转录和慷慨的免费层。

### 类签名

```python
class GroqTranscriptionProvider:
    def __init__(self, api_key: str | None = None): ...
    
    async def transcribe(self, file_path: str | Path) -> str:
        """使用 Groq 转录音频文件"""
```

**特性**: 使用 `whisper-large-v3` 模型，失败时返回空字符串（已记录）

---

## 8. 提供者选择流程

```
用户请求模型
    ↓
Config._match_provider()
    ↓
如果 provider != "auto":
    → 使用指定提供者
否则:
    1. 检查显式提供者前缀（如 "anthropic/"）
    2. 通过模型关键词匹配（顺序遵循 PROVIDERS 注册表）
    3. 回退到网关检测（api_key 前缀，api_base 关键词）
    ↓
实例化提供者:
    - is_direct? → CustomProvider, AzureOpenAIProvider, OpenAICodexProvider
    - is_oauth? → OpenAICodexProvider, GitHub Copilot
    - 否则 → LiteLLMProvider
    ↓
Provider.chat() → LLMResponse
```

---

## 9. 提供者实例化映射

| 提供者规范 | 类 |
|------------|-----|
| `custom` | `CustomProvider` |
| `azure_openai` | `AzureOpenAIProvider` |
| `openai_codex` | `OpenAICodexProvider` |
| 所有其他 | `LiteLLMProvider` |

---

## 10. 依赖摘要

| 提供者 | 外部依赖 |
|--------|----------|
| `base.py` | `loguru` |
| `registry.py` | 无 |
| `litellm_provider.py` | `litellm`, `json_repair`, `loguru` |
| `custom_provider.py` | `openai`, `json_repair` |
| `azure_openai_provider.py` | `httpx`, `json_repair` |
| `openai_codex_provider.py` | `httpx`, `oauth_cli_kit`, `loguru` |
| `transcription.py` | `httpx`, `loguru` |
