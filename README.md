# 标书生成

本仓库用于从招标文件 Word 中拆分生成商务标、技术标模版，并支持后续按字段清单让 AI 填充，再把结果回填到 Word 文档。

## 目录约定

默认输入文件：

```text
4.15测试-箱室类/招标文件/GKZH-25ZXH856-401.88项目箱室设备采购-招标文件-发布版1128.docx
```

默认输出目录分开管理：

```text
4.15测试-箱室类/输出模版/     # 拆分出的商务标模版、技术标模版、待填项清单、Qwen 请求包
4.15测试-箱室类/填充结果/     # AI 填充后回写出的 Word 文档
```

## 环境准备

需要 Python 3 和 `python-docx`。

```bash
pip install python-docx
```

## Docker 本地部署

镜像不会内置任何用户 key。部署前复制示例环境文件并填写 key：

```bash
cp .env.docker.example .env
```

关键环境变量：

```text
LLM_BASE_URL=http://10.25.1.48/v1
LLM_API_KEY=你的大模型接口key
LLM_MODEL=qwen-max
UPLOAD_BASE_URL=平台文件上传地址
PLATFORM_KEY=你的平台key
```

构建并启动：

```bash
docker build -t bid-generator:local .
docker compose up -d bid-generator
```

服务默认监听 `18010`，可通过 `BID_GENERATOR_PORT` 调整宿主机端口。健康检查：

```bash
curl http://127.0.0.1:18010/api/health
```

## 1. 生成商务标/技术标模版

使用默认招标文件和默认输出目录：

```bash
python3 scripts/generate_bid_templates.py
```

输出：

```text
4.15测试-箱室类/输出模版/*_商务标模版.docx
4.15测试-箱室类/输出模版/*_技术标模版.docx
```

如需查看为什么识别为商务标/技术标：

```bash
python3 scripts/generate_bid_templates.py --verbose
```

如需指定输入文件或输出目录：

```bash
python3 scripts/generate_bid_templates.py /path/to/招标文件.docx --output-dir /path/to/输出模版
```

## 2. 提取模版待填项清单

默认会读取 `输出模版` 下的商务标模版，并生成待填项 JSON：

```bash
python3 scripts/extract_bid_template_items.py
```

输出示例：

```text
4.15测试-箱室类/输出模版/*_商务标模版.待填项清单.json
```

也可以指定模版和类型：

```bash
python3 scripts/extract_bid_template_items.py /path/to/商务标模版.docx --template-type business --output /path/to/待填项清单.json
```

## 2.1 用 AI 辅助提取待填项清单

旧的规则抽取脚本保留不变。AI 辅助抽取脚本会把商务标/技术标模版 DOCX 先转成 PDF，再把 PDF 每页输出为 PNG 图片；随后按页组合“页面图片 + 对应页 DOCX XML”，交给视觉大模型直接输出待填项 JSON。最终输出仍然兼容后续 `fill_bid_template.py`。

先只生成页面图片和给 AI 的请求包，方便检查：

```bash
python3 scripts/extract_bid_template_items_ai.py --dry-run-request
```

这一步依赖本机可用的 LibreOffice/soffice 和 `pdftoppm`，会输出：

- `runtime/extract_ai_pages/.../pages/page-*.png`：每页图片
- `.AI抽取请求.json`：发给视觉模型的 OpenAI-compatible 请求，包含每页图片和每页 DOCX XML

实际调用模型抽取前，需要设置 DashScope/OpenAI-compatible API Key：

```bash
export DASHSCOPE_API_KEY="你的key"
python3 scripts/extract_bid_template_items_ai.py
```

默认输出：

```text
4.15测试-箱室类/输出模版/*_商务标模版.AI抽取请求.json
4.15测试-箱室类/输出模版/*_商务标模版.AI抽取响应.json
4.15测试-箱室类/输出模版/*_商务标模版.AI待填项清单.json
```

如果要用 AI 版清单继续回填，把 `--items` 指向 `.AI待填项清单.json` 即可：

```bash
python3 scripts/fill_bid_template.py \
  /path/to/商务标模版.docx \
  --items /path/to/商务标模版.AI待填项清单.json \
  --answers /path/to/AI填充结果.json \
  --output /path/to/填充结果/商务标_已填充.docx
```

## 3. 生成 Qwen 请求包并调用模型

根据待填项清单生成发给 `qwen3-vl-30b-a3b-instruct` 的 OpenAI 兼容请求包 JSON，并读取环境变量或仓库根目录 `.env` 里的 `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` 调用模型，输出回填用的 `AI填充结果.json`：

```bash
python3 scripts/prepare_qwen_fill_request.py
```

默认输出：

```text
4.15测试-箱室类/输出模版/*_商务标模版.qwen请求包.json
4.15测试-箱室类/输出模版/*_商务标模版.AI填充结果.json
```

如果只想生成请求包、不调用模型：

```bash
python3 scripts/prepare_qwen_fill_request.py --no-call
```

可补充投标人资料、资质索引、招标要求、报价、写作规则等材料：

```bash
python3 scripts/prepare_qwen_fill_request.py \
  /path/to/待填项清单.json \
  --bidder-profile /path/to/投标人资料.json \
  --credential-index /path/to/资质材料索引.json \
  --tender-requirements /path/to/招标要求.json \
  --quotation /path/to/报价信息.json \
  --writing-rules /path/to/写作规则.json \
  --output /path/to/Qwen请求包.json
```

## 4. 回填 AI 结果到 Word

上一步生成 `AI填充结果.json` 后，执行回填：

```bash
python3 scripts/fill_bid_template.py
```

默认输出到单独目录：

```text
4.15测试-箱室类/填充结果/*_商务标模版_已填充.docx
```

指定输入和输出：

```bash
python3 scripts/fill_bid_template.py \
  /path/to/商务标模版.docx \
  --items /path/to/待填项清单.json \
  --answers /path/to/AI填充结果.json \
  --output /path/to/填充结果/商务标_已填充.docx
```

没有填到的字段默认写入：

```text
【待确认】
```

可以用 `--missing-marker` 修改：

```bash
python3 scripts/fill_bid_template.py --missing-marker "待人工确认"
```

## 完整流程命令

```bash
python3 scripts/generate_bid_templates.py --verbose
python3 scripts/extract_bid_template_items.py
python3 scripts/prepare_qwen_fill_request.py
python3 scripts/fill_bid_template.py
```

## 测试

```bash
python3 -m unittest \
  scripts/test_generate_bid_templates.py \
  scripts/test_extract_and_fill_bid_template.py \
  scripts/test_prepare_qwen_fill_request.py \
  scripts/test_stepwise_template_api.py
```

## 脚本说明

```text
scripts/generate_bid_templates.py       从招标文件拆分商务标/技术标 Word 模版
scripts/extract_bid_template_items.py   从模版提取待填字段清单 JSON
scripts/extract_bid_template_items_ai.py 用 AI 辅助从模版提取待填字段清单 JSON
scripts/prepare_qwen_fill_request.py    组装发给 Qwen 的请求包 JSON，并调用模型输出 AI 填充结果 JSON
scripts/fill_bid_template.py            根据 AI 填充结果回写 Word
```

当前仓库根目录没有 `run.sh`，启动时直接使用上面的 `python3 scripts/...` 命令。

## FastAPI 后端接口（简化版）

如果你希望前端按步骤调用后端接口，可以启动：

```bash
pip install fastapi uvicorn
python fastapi_backend.py
```

默认地址：

```text
http://127.0.0.1:18010
```

前端页面：

```text
http://127.0.0.1:18010/
```

页面入口是 `frontend/index.html`，视觉风格参考 `frontend/qqq.html`，当前接入了模板生成、规则抽取、AI 抽取和模版回填接口。

健康检查：

```text
GET /health
GET /api/health
```

### 1) 生成商务标/技术标模版

接口：

```text
POST /api/generate-templates
```

最小入参：

```text
file: <招标文件.docx>
```

可选入参：

```text
verbose: false
```

输出：

```json
{
  "success": true,
  "job_id": "generate_xxx",
  "input_path": "/path/to/runtime/fastapi_jobs/generate_xxx/招标文件.docx",
  "business_template_url": "https://demo.langcore.cn/api/file/xxx",
  "technical_template_url": "https://demo.langcore.cn/api/file/yyy"
}
```

### 2) 识别招标文件项目信息（AI版）

接口：

```text
POST /api/extract-tender-metadata
```

最小入参：

```text
file: <招标文件.docx>
```

说明：后端保存上传的招标文件后，读取 DOCX 第一页文本并调用 `qwen3.6-plus`，提取「招标编号」和「项目名称」。请求包、原始响应和抽取结果会保存到同一个 `runtime/fastapi_jobs/metadata_xxx/` 目录，便于排查。

输出：

```json
{
  "success": true,
  "job_id": "metadata_xxx",
  "input_path": "/path/to/runtime/fastapi_jobs/metadata_xxx/招标文件.docx",
  "project_info": {
    "bid_number": "QT025WXR818C11506BD/GKZH-25ZXH856",
    "project_name": "401.88项目箱室设备采购",
    "confidence": 0.94,
    "evidence": []
  },
  "output_path": "/path/to/runtime/fastapi_jobs/metadata_xxx/招标文件.元信息.json",
  "request_output_path": "/path/to/runtime/fastapi_jobs/metadata_xxx/招标文件.元信息请求.json",
  "response_output_path": "/path/to/runtime/fastapi_jobs/metadata_xxx/招标文件.元信息响应.json"
}
```

### 3) 提取待填项清单（规则版）

接口：

```text
POST /api/extract-items
```

最小入参：

```text
template_url: https://demo.langcore.cn/api/file/xxx
```

可选入参：

```text
template_type: business | technical | price
output_path: /path/to/待填项清单.json
```

输出：

```json
{
  "success": true,
  "job_id": "extract_xxx",
  "template_url": "https://demo.langcore.cn/api/file/xxx",
  "template_path": "/path/to/runtime/fastapi_jobs/extract_xxx/template.docx",
  "items_count": 66,
  "output_path": "/path/to/待填项清单.json",
  "items_json": {
    "template_path": "/path/to/runtime/fastapi_jobs/extract_xxx/template.docx",
    "template_type": "business",
    "generated_at": "2026-04-27T00:00:00",
    "items": [],
    "answer_schema": {}
  }
}
```

### 4) 提取待填项清单（AI版）

接口：

```text
POST /api/extract-items-ai
```

最小入参：

```text
template_url: https://demo.langcore.cn/api/file/xxx
```

可选入参：

```text
template_type: business | technical | price
output_path: /path/to/AI待填项清单.json
```

说明：AI 版接口与普通 `extract-items` 的入参与输出结构保持一致，区别是待填项判断由大模型完成；代码再把对应的 Word XML、占位符和 locator 带回 `items_json.items[].locator`。

输出：

```json
{
  "success": true,
  "job_id": "extract_ai_xxx",
  "template_url": "https://demo.langcore.cn/api/file/xxx",
  "template_path": "/path/to/runtime/fastapi_jobs/extract_ai_xxx/template.docx",
  "items_count": 58,
  "output_path": "/path/to/AI待填项清单.json",
  "items_json": {
    "template_path": "/path/to/runtime/fastapi_jobs/extract_ai_xxx/template.docx",
    "template_type": "business",
    "items": []
  }
}
```

### 5) 根据用户确认值回填商务标模版

接口：

```text
POST /api/fill-bid-template
Content-Type: application/json
```

最小入参：

```json
{
  "items_json": {
    "template_path": "/path/to/runtime/fastapi_jobs/extract_xxx/template.docx",
    "items": []
  },
  "user_inputs": {
    "business_001": "航天晨光股份有限公司"
  }
}
```

可选入参：

```json
{
  "template_url": "https://demo.langcore.cn/api/file/xxx",
  "template_path": "/path/to/商务标模版.docx",
  "selected_item_ids": ["business_001", "business_002"],
  "output_path": "/path/to/已填充商务标.docx",
  "missing_marker": "【待确认】"
}
```

说明：

`items_json` 传上一步识别待填项返回的完整 JSON；`user_inputs` 可用 `item_id` 到填充值的对象，也可直接传 `answers[]` 结构。后端会生成兼容 `scripts/fill_bid_template.py` 的 `answers` JSON，并保留本次回填的待填项输入和用户填充输入。
图片类待填项（例如 `法定代表人（单位负责人）身份证复印件正面`）传本地图片路径、图片 URL、data URI，或 `{ "path": "/path/to/image.png" }` / `{ "image_url": "https://..." }`；回填时会按待填项清单里的 `image_placeholder` 定位，把图片写入对应矩形框内。
回填完成后，后端会把已填充的商务标 DOCX 上传到平台，并通过 `filled_template_url` 返回平台文件 URL；`output_path` 仍保留为本地调试产物路径。

输出：

```json
{
  "success": true,
  "job_id": "fill_xxx",
  "template_path": "/path/to/商务标模版.docx",
  "items_count": 66,
  "answers_count": 66,
  "filled_template_url": "https://demo.langcore.cn/api/file/zzz",
  "output_path": "/path/to/商务标模版_已填充.docx",
  "items_input_path": "/path/to/runtime/fastapi_jobs/fill_xxx/待填项输入.json",
  "answers_input_path": "/path/to/runtime/fastapi_jobs/fill_xxx/用户填充输入.json"
}
```
