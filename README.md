# Chroma Portal

一个用于管理 Chroma 向量数据库的全栈平台，包含：

- **前端**：Vue 3 + Vite（管理台 UI）
- **后端**：FastAPI（集合管理、分片管理、检索 API）
- **向量数据库**：Chroma
- **Embedding 服务**：Ollama（默认 `nomic-embed-text`）

项目目标是提供一套可运营的 RAG 控制台：从集合生命周期、分片治理、素材入库到检索验证（关键词 / 语义 / 混合重排）。

---

## 核心能力

### 1) 集合管理（Collection CRUD）

- 新建集合（支持选择 `cosine` / `l2` / `ip`）
- 编辑集合（重命名 + 备注）
- 删除集合
- 列表查看集合基础信息（相似度、默认切分、数据量、备注）

### 2) 分片管理（Chunk CRUD）

- 新增单条分片
- 编辑单条分片（内容 + metadata）
- 删除单条分片
- 批量删除分片
- **跨页全选** + 批量删除

### 3) 素材入库

- 手动粘贴素材内容
- 预览切分结果
- 写入集合并自动向量化

支持切分模式：

- `semantic`（语义/标题结构）
- `paragraph`（段落）
- `sentence`（句子）
- `fixed`（固定长度 + overlap）

### 4) 检索能力

- `keyword`：关键词匹配
- `semantic`：纯向量语义检索
- `hybrid`：语义 + 词面融合重排（短词场景更稳）

---

## 项目结构

```text
chroma-portal/
├─ backend/
│  ├─ app.py
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  ├─ package.json
│  └─ vite.config.js
└─ README.md
```

---

## 环境要求

- Python 3.10+
- Node.js 18+
- Chroma 服务可访问
- Ollama 服务可访问（并已拉取 embedding 模型）

---

## 本地开发

### 后端

```bash
cd backend
python3 -m pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 18080 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

默认前端通过 `/api/*` 代理到后端。

---

## 关键环境变量（后端）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CHROMA_HOST` | `127.0.0.1` | Chroma 地址 |
| `CHROMA_PORT` | `8000` | Chroma 端口 |
| `CHROMA_TENANT` | `default_tenant` | Chroma tenant |
| `CHROMA_DATABASE` | `default_database` | Chroma database |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/embeddings` | Embedding 接口 |
| `OLLAMA_MODEL` | `nomic-embed-text` | Embedding 模型 |
| `EMBEDDING_MAX_CHARS` | `1200` | 单段 embedding 最大字符数 |
| `EMBED_BATCH_SIZE` | `12` | embedding 批量处理大小 |

---

## API 概览

### 健康检查

- `GET /health`

### 集合管理

- `GET /collections`
- `POST /collections`
- `PATCH /collections/{collection_name}`
- `DELETE /collections/{collection_name}`

### 素材与分片

- `POST /chunk/preview`
- `POST /collections/{collection_name}/ingest`
- `GET /collections/{collection_name}/records`
- `POST /collections/{collection_name}/records`
- `PATCH /collections/{collection_name}/records/{record_id}`
- `DELETE /collections/{collection_name}/records/{record_id}`
- `POST /collections/{collection_name}/records/batch-delete`

### 检索

- `POST /search/keyword`
- `POST /search/semantic`
- `POST /search/hybrid`

---

## 部署说明（当前实践）

- 后端以 `systemd` 运行：`chroma-portal-api.service`
- 前端为静态构建产物（`frontend/dist`）
- Nginx 对外提供站点并反向代理 `/api` 到后端

---

## License

当前仓库未声明开源协议，如需开源建议补充 `LICENSE` 文件。
