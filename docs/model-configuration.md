# 模型配置

默认关闭模型；目录检索和监控可独立运行。页面设置只影响新发起的请求，正在执行的搜索固定使用自己的 Agent 与预算。

## 协议与地址

| `provider` | 根地址形式 | 请求端点 | 状态流 |
| --- | --- | --- | --- |
| `openai-responses` | `https://服务地址/v1` | `/responses` | 可选 Responses SSE |
| `openai-chat` | `https://服务地址/v1` | `/chat/completions` | 接收完整响应 |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta` | `/models/{model}:generateContent` | 接收完整响应 |

示例位于 `examples/`，兼容服务示例的 `api.example.com` 和 `your-model-name` 都须替换。客户端不包含模型权重或推理服务。

## 常用参数

| 参数 | 含义 |
| --- | --- |
| `api_key_required` | 是否需要认证 |
| `api_key_env` | 读取凭据的环境变量名；示例为 `SHOPAGENT_MODEL_API_KEY` |
| `stream` | Responses 是否使用 SSE；其他协议保持完整响应 |
| `reasoning_effort` | 默认 `none`；其他档位取决于供应商能力 |
| `max_context_tokens` | 完整请求预算，示例 24576，含输出预留 |
| `max_output_tokens` | 每次请求输出预算 |
| `timeout_sec` | 连接及无数据读取等待上限，不是整个搜索的总时限 |
| `max_retries` | 临时网络错误的当前轮重试次数，页面默认 2，范围 0–5 |
| `search_limits` | `max_searches/max_inspections/max_model_rounds`，默认 2/3/7 |

上下文预算是客户端估算，不会扩大模型服务的实际窗口。独立的工具协议补正每次搜索固定最多 2 次，计入总模型轮次；网络重试只重发当前轮，不重新执行之前的工具。

## 凭据与持久化

环境变量示例（值自行替换）：

```powershell
$env:SHOPAGENT_MODEL_API_KEY = "<YOUR_API_KEY>"
.\.venv\Scripts\python.exe -m shopagent_monitor --model-config examples/model-openai-compatible.json
```

页面输入的 Key 保存到状态目录下的独立凭据 JSON，配置文件引用该文件。Key 留空表示保留原值，清除需要明确勾选；更换服务地址或协议时需要提供对应凭据。页面不会回显 Key，诊断会脱敏，但本机凭据文件本身未加密。

已保存的页面配置优先于 `--model-config`。`--catalog-only` 只在本次启动禁用模型，页面可重新开启。切换启动目录时需指定相同 `--data-dir`，才能恢复同一份配置和历史。

模型需支持原生工具调用；在文本中输出一段工具 JSON 不视为成功。连接测试只验证一次工具调用，不能代表多轮商品筛选一定成功。第三方模型不可用时搜索与建议会明确显示实际来源。
