<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const view = ref('home')
const collections = ref([])
const selectedCollection = ref('')

const loadingCollections = ref(false)
const loadingRecords = ref(false)
const loadingSearch = ref(false)
const loadingPreview = ref(false)
const loadingIngest = ref(false)
const creating = ref(false)
const renaming = ref(false)
const deleting = ref(false)

const notice = ref('')
const error = ref('')

const records = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const searchMode = ref('hybrid')
const searchText = ref('')
const searchResults = ref([])
const isSearching = ref(false)

const drawerOpen = ref(false)
const drawerType = ref('create')

const createForm = ref({
  name: '',
  similarity_space: 'cosine',
  chunk_strategy_default: 'semantic',
  remark: '',
})

const renameForm = ref({
  sourceName: '',
  newName: '',
  remark: '',
})

const ingestForm = ref({
  mode: 'semantic',
  chunk_size: 420,
  overlap: 60,
  clear_existing: false,
  text: '',
})

const chunkPreview = ref([])
const chunkPreviewCount = ref(0)

const selectedChunkIds = ref([])
const allSelectedAcrossPages = ref(false)
const deselectedChunkIds = ref([])
const chunkEditorOpen = ref(false)
const chunkEditorMode = ref('create')
const chunkForm = ref({
  id: '',
  document: '',
  metadataText: '{}',
})

const selectedCount = computed(() => {
  if (allSelectedAcrossPages.value) {
    return Math.max(0, total.value - deselectedChunkIds.value.length)
  }
  return selectedChunkIds.value.length
})

const currentCollection = computed(() => {
  return collections.value.find((item) => item.name === selectedCollection.value) || null
})

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

const pipeline = [
  { title: '数据接入', desc: '接收知识文本，清洗结构化字段与来源标签' },
  { title: '分片策略', desc: '语义/段落/句子/固定长度，平衡上下文完整性与颗粒度' },
  { title: '向量化', desc: '统一 embedding 模型与维度，避免跨模型检索漂移' },
  { title: '召回', desc: '语义召回 + 关键词召回 + 混合召回' },
  { title: '重排序', desc: '融合语义分、词面命中、标题命中，输出稳定 Top-K' },
  { title: '生成上下文', desc: '将高质量片段拼接成可解释上下文供 LLM 使用' },
]

const apiGet = async (path) => {
  const res = await fetch(`/api/${path}`)
  if (!res.ok) throw new Error(`请求失败: ${res.status}`)
  return res.json()
}

const apiPost = async (path, body) => {
  const res = await fetch(`/api/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error((await res.text()) || `请求失败: ${res.status}`)
  return res.json()
}

const apiPatch = async (path, body) => {
  const res = await fetch(`/api/${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error((await res.text()) || `请求失败: ${res.status}`)
  return res.json()
}

const apiDelete = async (path) => {
  const res = await fetch(`/api/${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error((await res.text()) || `请求失败: ${res.status}`)
  return res.json()
}

const clearNotice = () => {
  notice.value = ''
  error.value = ''
}

const openDrawer = (type) => {
  drawerType.value = type
  drawerOpen.value = true
  clearNotice()
  if (type === 'rename' && selectedCollection.value) {
    renameForm.value.sourceName = selectedCollection.value
    renameForm.value.newName = selectedCollection.value
    const meta = collections.value.find((item) => item.name === selectedCollection.value)
    renameForm.value.remark = meta?.remark || ''
  }
}

const openRenameDrawerFor = (name) => {
  const meta = collections.value.find((item) => item.name === name)
  renameForm.value.sourceName = name
  renameForm.value.newName = name
  renameForm.value.remark = meta?.remark || ''
  openDrawer('rename')
}

const closeDrawer = () => {
  drawerOpen.value = false
}

const loadCollections = async () => {
  loadingCollections.value = true
  try {
    const data = await apiGet('collections')
    collections.value = data
    if (!selectedCollection.value && data.length > 0) {
      selectedCollection.value = data[0].name
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loadingCollections.value = false
  }
}

const loadRecords = async () => {
  if (!selectedCollection.value) return
  loadingRecords.value = true
  try {
    const data = await apiGet(
      `collections/${encodeURIComponent(selectedCollection.value)}/records?page=${page.value}&page_size=${pageSize.value}`,
    )
    records.value = data.records || []
    total.value = data.total || 0
  } catch (err) {
    error.value = err.message
  } finally {
    loadingRecords.value = false
  }
}

const createCollection = async () => {
  if (!createForm.value.name.trim()) {
    error.value = '请输入集合名称。'
    return
  }
  creating.value = true
  clearNotice()
  try {
    await apiPost('collections', createForm.value)
    notice.value = '集合创建成功。'
    selectedCollection.value = createForm.value.name
    createForm.value.name = ''
    createForm.value.remark = ''
    await loadCollections()
    closeDrawer()
  } catch (err) {
    error.value = err.message
  } finally {
    creating.value = false
  }
}

const renameCollection = async () => {
  if (!renameForm.value.sourceName || !renameForm.value.newName.trim()) {
    error.value = '请选择集合并输入新名称。'
    return
  }
  renaming.value = true
  clearNotice()
  try {
    await apiPatch(`collections/${encodeURIComponent(renameForm.value.sourceName)}`, {
      new_name: renameForm.value.newName,
      remark: renameForm.value.remark,
    })
    notice.value = '集合重命名成功。'
    selectedCollection.value = renameForm.value.newName
    await loadCollections()
    closeDrawer()
  } catch (err) {
    error.value = err.message
  } finally {
    renaming.value = false
  }
}

const removeCollection = async (name) => {
  if (!window.confirm(`确认删除集合 ${name}？`)) return
  deleting.value = true
  clearNotice()
  try {
    await apiDelete(`collections/${encodeURIComponent(name)}`)
    notice.value = '集合已删除。'
    if (selectedCollection.value === name) {
      selectedCollection.value = ''
      records.value = []
      total.value = 0
    }
    await loadCollections()
  } catch (err) {
    error.value = err.message
  } finally {
    deleting.value = false
  }
}

const openCollectionDetail = async (name) => {
  selectedCollection.value = name
  page.value = 1
  isSearching.value = false
  searchResults.value = []
  searchText.value = ''
  view.value = 'detail'
  await loadRecords()
}

const runSearch = async () => {
  if (!selectedCollection.value || !searchText.value.trim()) {
    error.value = '请输入检索内容。'
    return
  }
  loadingSearch.value = true
  clearNotice()
  try {
    const endpoint =
      searchMode.value === 'keyword'
        ? 'search/keyword'
        : searchMode.value === 'semantic'
          ? 'search/semantic'
          : 'search/hybrid'
    const body =
      searchMode.value === 'keyword'
        ? { collection: selectedCollection.value, keyword: searchText.value }
        : { collection: selectedCollection.value, query: searchText.value, n_results: 10 }
    const data = await apiPost(endpoint, body)
    searchResults.value = data.records || []
    isSearching.value = true
    notice.value = `检索完成，共 ${searchResults.value.length} 条。`
  } catch (err) {
    error.value = err.message
  } finally {
    loadingSearch.value = false
  }
}

const resetSearch = () => {
  isSearching.value = false
  searchResults.value = []
}

const openCreateChunkEditor = () => {
  chunkEditorMode.value = 'create'
  chunkForm.value = { id: '', document: '', metadataText: '{}' }
  chunkEditorOpen.value = true
  clearNotice()
}

const openEditChunkEditor = (record) => {
  chunkEditorMode.value = 'edit'
  chunkForm.value = {
    id: record.id,
    document: record.document || '',
    metadataText: JSON.stringify(record.metadata || {}, null, 2),
  }
  chunkEditorOpen.value = true
  clearNotice()
}

const closeChunkEditor = () => {
  chunkEditorOpen.value = false
}

const saveChunk = async () => {
  if (!selectedCollection.value) {
    error.value = '请先选择集合。'
    return
  }
  if (!chunkForm.value.document.trim()) {
    error.value = '分片内容不能为空。'
    return
  }

  let parsedMetadata = {}
  try {
    parsedMetadata = chunkForm.value.metadataText.trim() ? JSON.parse(chunkForm.value.metadataText) : {}
  } catch {
    error.value = 'metadata 必须是合法 JSON。'
    return
  }

  clearNotice()
  try {
    if (chunkEditorMode.value === 'create') {
      await apiPost(`collections/${encodeURIComponent(selectedCollection.value)}/records`, {
        document: chunkForm.value.document,
        metadata: parsedMetadata,
      })
      notice.value = '新增分片成功。'
    } else {
      await apiPatch(`collections/${encodeURIComponent(selectedCollection.value)}/records/${encodeURIComponent(chunkForm.value.id)}`, {
        document: chunkForm.value.document,
        metadata: parsedMetadata,
      })
      notice.value = '分片更新成功。'
    }
    chunkEditorOpen.value = false
    await loadCollections()
    await loadRecords()
  } catch (err) {
    error.value = err.message
  }
}

const deleteChunk = async (recordId) => {
  if (!window.confirm(`确认删除分片 ${recordId}？`)) return
  clearNotice()
  try {
    await apiDelete(`collections/${encodeURIComponent(selectedCollection.value)}/records/${encodeURIComponent(recordId)}`)
    selectedChunkIds.value = selectedChunkIds.value.filter((id) => id !== recordId)
    notice.value = '分片删除成功。'
    await loadCollections()
    await loadRecords()
  } catch (err) {
    error.value = err.message
  }
}

const toggleChunkSelection = (recordId) => {
  if (allSelectedAcrossPages.value) {
    if (deselectedChunkIds.value.includes(recordId)) {
      deselectedChunkIds.value = deselectedChunkIds.value.filter((id) => id !== recordId)
    } else {
      deselectedChunkIds.value = [...deselectedChunkIds.value, recordId]
    }
    return
  }

  if (selectedChunkIds.value.includes(recordId)) {
    selectedChunkIds.value = selectedChunkIds.value.filter((id) => id !== recordId)
  } else {
    selectedChunkIds.value = [...selectedChunkIds.value, recordId]
  }
}

const isChunkChecked = (recordId) => {
  if (allSelectedAcrossPages.value) {
    return !deselectedChunkIds.value.includes(recordId)
  }
  return selectedChunkIds.value.includes(recordId)
}

const toggleSelectAllAcrossPages = () => {
  if (allSelectedAcrossPages.value) {
    allSelectedAcrossPages.value = false
    deselectedChunkIds.value = []
    selectedChunkIds.value = []
    notice.value = '已取消跨页全选。'
    return
  }

  allSelectedAcrossPages.value = true
  selectedChunkIds.value = []
  deselectedChunkIds.value = []
  notice.value = `已启用跨页全选，当前集合共 ${total.value} 条。`
}

const loadAllRecordIds = async () => {
  const ids = []
  const maxPageSize = 200
  let currentPage = 1
  while (true) {
    const data = await apiGet(
      `collections/${encodeURIComponent(selectedCollection.value)}/records?page=${currentPage}&page_size=${maxPageSize}`,
    )
    const pageRecords = data.records || []
    ids.push(...pageRecords.map((item) => item.id))
    if (ids.length >= (data.total || 0) || pageRecords.length === 0) {
      break
    }
    currentPage += 1
  }
  return ids
}

const deleteSelectedChunks = async () => {
  if (!selectedCount.value) {
    error.value = '请先选择要删除的分片。'
    return
  }
  if (!window.confirm(`确认批量删除 ${selectedCount.value} 个分片？`)) return

  clearNotice()
  try {
    let idsToDelete = []
    if (allSelectedAcrossPages.value) {
      const allIds = await loadAllRecordIds()
      const removed = new Set(deselectedChunkIds.value)
      idsToDelete = allIds.filter((id) => !removed.has(id))
    } else {
      idsToDelete = [...selectedChunkIds.value]
    }

    if (!idsToDelete.length) {
      error.value = '没有可删除的分片。'
      return
    }

    await apiPost(`collections/${encodeURIComponent(selectedCollection.value)}/records/batch-delete`, {
      ids: idsToDelete,
    })
    notice.value = `已批量删除 ${idsToDelete.length} 个分片。`
    selectedChunkIds.value = []
    deselectedChunkIds.value = []
    allSelectedAcrossPages.value = false
    await loadCollections()
    await loadRecords()
  } catch (err) {
    error.value = err.message
  }
}

const previewChunks = async () => {
  if (!ingestForm.value.text.trim()) {
    error.value = '请先输入素材内容。'
    return
  }
  loadingPreview.value = true
  clearNotice()
  try {
    const data = await apiPost('chunk/preview', {
      text: ingestForm.value.text,
      mode: ingestForm.value.mode,
      chunk_size: ingestForm.value.chunk_size,
      overlap: ingestForm.value.overlap,
    })
    chunkPreview.value = data.preview || []
    chunkPreviewCount.value = data.count || 0
    notice.value = `切分预览完成：共 ${chunkPreviewCount.value} 段。`
  } catch (err) {
    error.value = err.message
  } finally {
    loadingPreview.value = false
  }
}

const ingestMaterial = async () => {
  if (!selectedCollection.value) {
    error.value = '请先选择集合。'
    return
  }
  if (!ingestForm.value.text.trim()) {
    error.value = '请先输入素材内容。'
    return
  }
  loadingIngest.value = true
  clearNotice()
  try {
    const data = await apiPost(`collections/${encodeURIComponent(selectedCollection.value)}/ingest`, {
      text: ingestForm.value.text,
      mode: ingestForm.value.mode,
      chunk_size: ingestForm.value.chunk_size,
      overlap: ingestForm.value.overlap,
      clear_existing: ingestForm.value.clear_existing,
    })
    notice.value = `写入完成：新增 ${data.added} 条。`
    ingestForm.value.text = ''
    chunkPreview.value = []
    chunkPreviewCount.value = 0
    await loadCollections()
    await loadRecords()
    view.value = 'detail'
  } catch (err) {
    error.value = err.message
  } finally {
    loadingIngest.value = false
  }
}

watch(selectedCollection, (name) => {
  if (name) {
    renameForm.value.sourceName = name
  }
})

watch(page, async () => {
  if (view.value === 'detail' && !isSearching.value) {
    await loadRecords()
  }
})

watch([view, selectedCollection], () => {
  if (view.value !== 'detail') {
    selectedChunkIds.value = []
    deselectedChunkIds.value = []
    allSelectedAcrossPages.value = false
  }
  if (view.value === 'detail' && selectedCollection.value) {
    selectedChunkIds.value = []
    deselectedChunkIds.value = []
    allSelectedAcrossPages.value = false
  }
})

onMounted(async () => {
  await loadCollections()
})
</script>

<template>
  <div class="app-shell">
    <header class="top-hero">
      <div>
        <p class="tag">RAG 知识中台</p>
        <h1>向量知识管理平台</h1>
        <p class="hero-sub">覆盖知识入库、分片治理、召回验证与重排序评估的一体化控制台</p>
      </div>
      <button class="btn btn-primary" @click="view = 'collections'; loadCollections()">集合列表</button>
    </header>

    <section v-if="view === 'home'" class="panel home-panel">
      <h2>RAG 全流程体系图</h2>
      <p class="lead">首页仅展示架构能力，不展示集合数据。点击右上角进入集合管理。</p>

      <div class="pipeline">
        <article class="step" v-for="(item, index) in pipeline" :key="item.title">
          <span class="step-no">{{ index + 1 }}</span>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </article>
      </div>

      <div class="flowline" aria-label="RAG 流程图示">
        <span>文档输入</span>
        <b>→</b>
        <span>分片</span>
        <b>→</b>
        <span>Embedding</span>
        <b>→</b>
        <span>召回</span>
        <b>→</b>
        <span>重排序</span>
        <b>→</b>
        <span>生成上下文</span>
      </div>

      <div class="notes">
        <h3>关键细节</h3>
        <ul>
          <li>分片：按业务场景选择策略，保证“召回覆盖”与“上下文完整”平衡。</li>
          <li>召回：短词优先词面命中，长句优先语义召回，再做混合融合。</li>
          <li>重排序：按 semanticScore + lexicalScore + 标题命中做可解释排序。</li>
          <li>上下文编排：Top-K 片段按来源与主题归并，供生成层稳定引用。</li>
        </ul>
      </div>
    </section>

    <section v-else-if="view === 'collections'" class="panel">
      <div class="toolbar">
        <h2>集合列表与管理</h2>
        <div class="row">
          <button class="btn" @click="view = 'home'">返回首页</button>
          <button class="btn" @click="openDrawer('create')">新建集合</button>
          <button class="btn" @click="loadCollections">刷新</button>
        </div>
      </div>

      <p v-if="error" class="error-text">{{ error }}</p>
      <p v-else-if="notice" class="ok-text">{{ notice }}</p>

      <table class="table" v-if="!loadingCollections">
        <thead>
          <tr>
            <th>名称</th>
            <th>相似度</th>
            <th>默认切分</th>
            <th>备注</th>
            <th>数据量</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in collections" :key="item.name">
            <td>{{ item.name }}</td>
            <td>{{ item.similaritySpace }}</td>
            <td>{{ item.chunkStrategy }}</td>
            <td>{{ item.remark || '-' }}</td>
            <td>{{ item.count }}</td>
            <td class="row">
              <button class="btn" @click="openCollectionDetail(item.name)">进入详情</button>
              <button class="btn" @click="openRenameDrawerFor(item.name)">编辑</button>
              <button class="btn btn-danger" :disabled="deleting" @click="removeCollection(item.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">加载中...</p>
    </section>

    <section v-else-if="view === 'detail'" class="panel">
      <div class="toolbar">
        <div>
          <h2>集合详情：{{ selectedCollection }}</h2>
          <p class="muted" v-if="currentCollection">
            相似度 {{ currentCollection.similaritySpace }} · 数据总量 {{ currentCollection.count }}
          </p>
        </div>
        <div class="row">
          <button class="btn" @click="view = 'collections'">返回集合列表</button>
          <button class="btn" @click="openCreateChunkEditor">新增分片</button>
          <button class="btn" @click="toggleSelectAllAcrossPages">
            {{ allSelectedAcrossPages ? '取消跨页全选' : '跨页全选' }}
          </button>
          <button class="btn btn-danger" @click="deleteSelectedChunks">批量删除分片</button>
          <button class="btn btn-primary" @click="view = 'ingest'">添加素材</button>
        </div>
      </div>

      <p v-if="error" class="error-text">{{ error }}</p>
      <p v-else-if="notice" class="ok-text">{{ notice }}</p>

      <div class="search-box">
        <select v-model="searchMode">
          <option value="hybrid">增强检索</option>
          <option value="semantic">纯语义</option>
          <option value="keyword">关键词</option>
        </select>
        <input
          v-model="searchText"
          type="text"
          placeholder="输入关键词或问题，例如：色彩 / HashMap线程不安全"
          @keyup.enter="runSearch"
        />
        <button class="btn btn-primary" :disabled="loadingSearch" @click="runSearch">{{ loadingSearch ? '检索中...' : '搜索' }}</button>
        <button class="btn" @click="resetSearch">查看全部分片</button>
      </div>

      <p class="muted">当前选择：{{ selectedCount }} 条分片（支持跨页全选）</p>

      <div class="result-list" v-if="isSearching">
        <article class="result-item" v-for="item in searchResults" :key="item.id">
          <div class="result-head">
            <strong>{{ item.id }}</strong>
            <div class="chips">
              <span v-if="item.score !== undefined">score {{ Number(item.score).toFixed(4) }}</span>
              <span v-if="item.distance !== undefined && item.distance !== null">distance {{ Number(item.distance).toFixed(4) }}</span>
            </div>
          </div>
          <p>{{ item.document }}</p>
          <pre>{{ JSON.stringify(item.metadata || {}, null, 2) }}</pre>
        </article>
      </div>

      <div class="result-list" v-else>
        <p v-if="loadingRecords" class="muted">加载分片中...</p>
        <article v-else class="result-item" v-for="item in records" :key="item.id">
          <div class="result-head">
            <div class="row">
              <input
                type="checkbox"
                class="record-check"
                :checked="isChunkChecked(item.id)"
                @change="toggleChunkSelection(item.id)"
              />
              <strong>{{ item.id }}</strong>
            </div>
            <div class="row">
              <span class="chip">dim {{ item.embeddingDimension }}</span>
              <button class="btn btn-mini" @click="openEditChunkEditor(item)">编辑</button>
              <button class="btn btn-danger btn-mini" @click="deleteChunk(item.id)">删除</button>
            </div>
          </div>
          <p>{{ item.document }}</p>
          <pre>{{ JSON.stringify(item.metadata || {}, null, 2) }}</pre>
        </article>

        <div class="pager">
          <button class="btn" :disabled="page <= 1" @click="page = page - 1">上一页</button>
          <span>{{ page }} / {{ pageCount }}</span>
          <button class="btn" :disabled="page >= pageCount" @click="page = page + 1">下一页</button>
        </div>
      </div>
    </section>

    <section v-else-if="view === 'ingest'" class="panel">
      <div class="toolbar">
        <h2>添加素材：{{ selectedCollection }}</h2>
        <div class="row">
          <button class="btn" @click="view = 'detail'">返回详情</button>
        </div>
      </div>

      <p v-if="error" class="error-text">{{ error }}</p>
      <p v-else-if="notice" class="ok-text">{{ notice }}</p>

      <div class="row wrap">
        <label>
          切分模式
          <select v-model="ingestForm.mode">
            <option value="semantic">semantic</option>
            <option value="paragraph">paragraph</option>
            <option value="sentence">sentence</option>
            <option value="fixed">fixed</option>
          </select>
        </label>
        <label>
          chunk size
          <input v-model.number="ingestForm.chunk_size" type="number" min="80" max="4000" />
        </label>
        <label>
          overlap
          <input v-model.number="ingestForm.overlap" type="number" min="0" max="800" />
        </label>
        <label class="check-row">
          <input v-model="ingestForm.clear_existing" type="checkbox" />
          写入前清空集合
        </label>
      </div>

      <textarea v-model="ingestForm.text" rows="12" placeholder="粘贴素材内容"></textarea>

      <div class="row">
        <button class="btn" :disabled="loadingPreview" @click="previewChunks">{{ loadingPreview ? '预览中...' : '预览切分' }}</button>
        <button class="btn btn-primary" :disabled="loadingIngest" @click="ingestMaterial">{{ loadingIngest ? '写入中...' : '写入集合' }}</button>
      </div>

      <div class="preview-box" v-if="chunkPreview.length > 0">
        <h3>切分预览（共 {{ chunkPreviewCount }} 段）</h3>
        <article class="snippet" v-for="(chunk, idx) in chunkPreview" :key="idx">
          <strong>Chunk {{ idx + 1 }}</strong>
          <p>{{ chunk }}</p>
        </article>
      </div>
    </section>

    <div v-if="chunkEditorOpen" class="drawer-mask" @click.self="closeChunkEditor">
      <aside class="drawer">
        <div class="drawer-head">
          <h3>{{ chunkEditorMode === 'create' ? '新增分片' : `编辑分片：${chunkForm.id}` }}</h3>
          <button class="btn" @click="closeChunkEditor">关闭</button>
        </div>
        <div class="drawer-body">
          <label>
            分片内容
            <textarea v-model="chunkForm.document" rows="8" placeholder="输入分片文本内容"></textarea>
          </label>
          <label>
            metadata (JSON)
            <textarea v-model="chunkForm.metadataText" rows="8" placeholder='{"source":"manual"}'></textarea>
          </label>
          <button class="btn btn-primary" @click="saveChunk">{{ chunkEditorMode === 'create' ? '确认新增' : '保存修改' }}</button>
        </div>
      </aside>
    </div>

    <div v-if="drawerOpen" class="drawer-mask" @click.self="closeDrawer">
      <aside class="drawer">
        <div class="drawer-head">
          <h3>{{ drawerType === 'create' ? '新建集合' : '重命名集合' }}</h3>
          <button class="btn" @click="closeDrawer">关闭</button>
        </div>

        <div v-if="drawerType === 'create'" class="drawer-body">
          <label>
            集合名称
            <input v-model="createForm.name" placeholder="例如 java_interview" />
          </label>
          <label>
            相似度
            <select v-model="createForm.similarity_space">
              <option value="cosine">cosine</option>
              <option value="l2">l2</option>
              <option value="ip">ip</option>
            </select>
          </label>
          <label>
            默认切分
            <select v-model="createForm.chunk_strategy_default">
              <option value="semantic">semantic</option>
              <option value="paragraph">paragraph</option>
              <option value="sentence">sentence</option>
              <option value="fixed">fixed</option>
            </select>
          </label>
          <label>
            备注
            <input v-model="createForm.remark" placeholder="可填写业务说明" />
          </label>
          <button class="btn btn-primary" :disabled="creating" @click="createCollection">{{ creating ? '创建中...' : '创建集合' }}</button>
        </div>

        <div v-else class="drawer-body">
          <label>
            当前集合
            <input :value="renameForm.sourceName" disabled />
          </label>
          <label>
            新名称
            <input v-model="renameForm.newName" placeholder="输入新名称" />
          </label>
          <label>
            备注
            <input v-model="renameForm.remark" placeholder="更新该集合备注" />
          </label>
          <button class="btn btn-primary" :disabled="renaming" @click="renameCollection">{{ renaming ? '修改中...' : '确认修改' }}</button>
        </div>
      </aside>
    </div>
  </div>
</template>
