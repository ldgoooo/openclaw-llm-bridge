# openclaw-llm-bridge

高性能桥接网关：连接 OpenClaw 与 OpenAI 协议 API，提供 Token 计费、Key 管理与审计日志。

## 技术栈

- **Python 3.12** · **FastAPI** · **motor**（MongoDB 异步）· **LiteLLM**（调用 Azure/后端模型）· **tiktoken**（Token 计数）· **pydantic-settings**（配置）

## 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `MONGODB_URI` | MongoDB 连接串 | `mongodb://localhost:27017` |
| `MONGODB_DB` | 数据库名 | `openclaw_llm_bridge` |
| `ADMIN_TOKEN` | 管理端鉴权 Token | 任意字符串 |
| `LLM_API_KEY` | 后端 API Key（如 Azure） | |
| `LLM_MODEL` | 模型/部署名 | `gpt-5-nano` |
| `LLM_ENDPOINT` | 后端 API 地址 | `https://monster.cognitiveservices.azure.com` |
| `LLM_API_VERSION` | API 版本（Azure） | `2024-12-01-preview` |
| `TIKTOKEN_ENCODING` | tiktoken 编码 | `cl100k_base`（默认） |

## 安装与运行

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 设置上述环境变量（或 .env）
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 接口说明

### OpenAI 兼容

- **POST /v1/chat/completions**  
  - 请求头：`Authorization: Bearer <api_key>`  
  - 支持 `stream: true`（SSE）。  
  - 使用 tiktoken 计算 Input/Output Token，MongoDB `$inc` 原子扣费；余额不足或 Key 无效时返回 `insufficient_quota` 等 OpenAI 规范错误。

### 管理端（需 `Authorization: Bearer <ADMIN_TOKEN>`）

- **POST /admin/keys** — 创建 Key（body: `api_key`, `user_name`, `balance_tokens`, `status`）
~~~

curl -X POST "http://127.0.0.1:8000/admin/keys" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "sk-my-user-key-001",
    "user_name": "张三",
    "balance_tokens": 10000,
    "status": "active"
  }'



~~~
- **GET /admin/keys** — 列出所有 Key 及余额
- **PATCH /admin/keys/{api_key}** — 充值（`balance_tokens` 累加）或冻结（`status`）

### 日志与审计

- 每次成功请求写入 MongoDB 集合 **audit_logs**：`timestamp`, `user_id`, `api_key`, `model`, `input_tokens`, `output_tokens`, `total_tokens`, `duration_ms`, `status_code`。
- 系统与访问日志通过 Python `logging` 输出到**控制台**和**本地文件 `app.log`**。

## 项目结构

```
main.py           # 路由入口
config.py         # 配置（pydantic-settings）
models.py         # Pydantic / 集合 Schema
database.py       # MongoDB 连接
services/
  auth_service.py    # Key 校验、管理员校验
  billing_service.py # 余额预检、原子扣费
  proxy_service.py   # LiteLLM 流式调用
  audit_service.py   # 审计写入
utils/
  token_counter.py   # tiktoken 异步计数
  logger.py         # 日志配置
```

## License

MIT

