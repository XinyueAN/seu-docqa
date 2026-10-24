# 知序 DocQA

面向个人资料的本地优先多模态文档问答系统。当前基础版本已提供中文工作台、PDF / DOCX / PPTX / Markdown / TXT 文本抽取、本地图片提取与 Markdown 图文归档、本地 SQLite 文档库、页码切片、BM25 + TF-IDF 稀疏召回、可选本地语义向量、RRF 融合和可选 Cross-Encoder 重排，以及基于 DeepSeek Flash 的证据约束回答。

## 启动

1. 安装 Python 3.11 或更新版本。
2. 在项目目录创建并激活虚拟环境：

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. 将 DeepSeek API Key 放在项目根目录的 `deepseek-api-keys.txt`（支持单独一行 key，或 `DEEPSEEK_API_KEY=...`）。该文件已加入 `.gitignore`，不要复制到代码或聊天记录。
4. 启动服务：

   ```powershell
   python -m uvicorn docqa.web.app:app --host 127.0.0.1 --port 8000
   ```

5. 浏览器访问 `http://127.0.0.1:8000`。

## 命令行

```powershell
python -m docqa build .\示例文档
python -m docqa list
python -m docqa query "这个项目的核心流程是什么？"
python -m docqa test --top-k 5
```

`build` 默认递归扫描目录；根据 SHA-256 内容指纹跳过已入库的重复文件。只有显式传入 `--vision` 才会调用 DeepSeek Flash 分析图片。

本地上传文件、图片、Markdown 解析结果和 SQLite 数据库存放在 `data/`。设置 `DATA_DIR` 可更改存储目录。上传时可以选分类，也可以在文档列表中筛选、调整分类或删除。上传时可选勾选 DeepSeek Flash 图片理解；勾选后，最多 `VISION_MAX_IMAGES` 张图（默认 12 张）会作为视觉输入发送到 DeepSeek API 生成中文图像说明，说明会进入本地检索索引。默认不勾选时，图片仍会提取并本地归档，但不会发送给模型。

后台目录监控默认开启，收件目录为 `data/watch/`，每 30 秒递归扫描一次。复制新文档或覆盖已有文件即可触发增量入库；扫描指纹保存在本地 `data/watch_state.json`。可在 `.env` 中调整 `WATCH_ENABLED`、`WATCH_DIR` 和 `WATCH_INTERVAL_SECONDS`。监控导入默认只做本地文本/图片提取，不启用云端视觉分析。

网页上传会创建后台解析任务，前端可查看文本抽取、视觉解析、建立检索索引和完成状态；命令行 `build` 也会输出逐文件进度。问答区支持安全渲染基础 Markdown 和 Mermaid 流程图，答案中的 `[S1]` 引用可跳转到来源卡片。

## 启用本地语义向量和重排

BM25 与 TF-IDF 始终在本地工作。语义向量和 Cross-Encoder 重排是可选项，默认关闭，避免默认安装大型机器学习运行时或首次运行时自动下载权重：

```powershell
pip install -r requirements-ml.txt
Copy-Item .env.example .env
```

在 `.env` 中设置 `ENABLE_LOCAL_EMBEDDING=true` 和 / 或 `ENABLE_LOCAL_RERANKER=true`，然后重启服务。默认中文 Embedding 为 `BAAI/bge-small-zh-v1.5`；首次建索引时需下载模型权重。可在检索实验室使用“为现有文档建立向量索引”补齐已有文档。通过 `EMBEDDING_MODEL` 和 `RERANKER_MODEL` 可替换本地模型。Embedding 与重排在本机执行，不会把文档发送到 DeepSeek。

## 当前能力边界

- Word 与 PPT 的页码以文档段落页 / 幻灯片近似表示；PDF 保留真实 PDF 页码。Word 表格和 PPT 表格/图表会转成 Markdown 表格。
- 扫描页和图表图片可在上传时选择 DeepSeek Flash 视觉解析：输出可见文字转写、关系说明和要点，作为图文 Markdown 与检索片段保存。该过程需要用户勾选，图片才会发送到 API；系统没有独立本地 OCR 引擎。
- BM25、TF-IDF 和 RRF 已实现；本地语义向量与 Cross-Encoder 可选启用。后台目录监控默认开启，会扫描新增/更新文件；从监控目录删除源文件不会自动删除知识库文档，需要在网页中手动删除。
- 默认关闭本地语义模型时，语义召回为空，BM25 与 TF-IDF 仍可使用；启用并建立索引后才会加入语义召回。
- 没有解析到文本的扫描版 PDF，只有在上传时主动勾选视觉分析且 DeepSeek 成功返回转写后，相关图像内容才可检索；默认本地模式不会对扫描页自动 OCR。
- Word 页码按段落位置近似映射、PPT 页码对应幻灯片；复杂排版、跨页表格和图表视觉关系可能需要人工核对。文档详情支持查看抽取正文和图片；预览不会改变原始文件。
- 设置面板展示模型、密钥配置状态、数据目录、视觉分析上限与本地模型开关；密钥值始终不返回前端。运行参数通过 `.env` 调整并重启服务。
- 文件上传最大 30 MB，支持 PDF、DOCX、PPTX、Markdown 和 TXT。当前评估以文档级期望来源计算 Recall@K、Hit Rate 与 MRR；课程报告应记录具体语料、模型配置和运行条件，避免将样例指标泛化。

## 工程结构

- `docqa/doc2md/` 文档抽取与 Markdown 归一化
- `docqa/docbase/` 本地切片、SQLite 持久化与检索
- `docqa/agent/` 证据约束问答
- `docqa/service/` DeepSeek API 接入
- `docqa/web/` FastAPI API 与中文工作台
- `AGENTS.md` Agent 工作约定与数据边界

## 课程交付材料

- [需求映射与验收清单](docs/requirements-mapping.md)
- [系统架构与关键流程](docs/architecture.md)
- [现场演示脚本与报告建议](docs/demo-and-report.md)
