const $ = (selector) => document.querySelector(selector);
const toast = (message) => { const node = $('#toast'); node.textContent = message; node.classList.add('visible'); setTimeout(() => node.classList.remove('visible'), 3000); };
let cachedDocuments = [];
let activeConversationId = null;
let conversationLoadToken = 0;

function appendInline(parent, text, onCitation = null) {
  const tokenPattern = /(\*\*[^*]+\*\*|`[^`]+`|\[S\d+\])/g;
  let cursor = 0;
  for (const match of text.matchAll(tokenPattern)) {
    parent.append(document.createTextNode(text.slice(cursor, match.index)));
    const value = match[0]; let node;
    if (value.startsWith('**')) { node = document.createElement('strong'); node.textContent = value.slice(2, -2); }
    else if (value.startsWith('`')) { node = document.createElement('code'); node.textContent = value.slice(1, -1); }
    else { node = document.createElement('button'); node.type = 'button'; node.className = 'citation-ref'; node.textContent = value; node.addEventListener('click', () => onCitation ? onCitation(value.slice(1, -1)) : document.getElementById(`citation-${value.slice(1, -1)}`)?.scrollIntoView({behavior:'smooth',block:'center'})); }
    parent.append(node); cursor = match.index + value.length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}

function appendMarkdown(parent, text, onCitation = null) {
  const lines = text.split('\n'); let list = null;
  for (let index = 0; index < lines.length; index++) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();
    if (!line.trim()) { list = null; continue; }
    const next = (lines[index + 1] || '').trim();
    if (line.includes('|') && /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(next)) {
      list = null;
      const cells = (value) => value.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
      const table = document.createElement('table'); const thead = document.createElement('thead'); const headerRow = document.createElement('tr');
      cells(line).forEach((value) => { const th = document.createElement('th'); appendInline(th, value, onCitation); headerRow.append(th); });
      thead.append(headerRow); table.append(thead); const tbody = document.createElement('tbody'); index += 2;
      while (index < lines.length && lines[index].includes('|')) {
        const row = document.createElement('tr'); cells(lines[index]).forEach((value) => { const td = document.createElement('td'); appendInline(td, value, onCitation); row.append(td); }); tbody.append(row); index++;
      }
      index--; table.append(tbody); parent.append(table); continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) { list = null; const node = document.createElement(`h${Math.min(heading[1].length + 2, 6)}`); appendInline(node, heading[2], onCitation); parent.append(node); continue; }
    const unordered = /^\s*[-*]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const tag = unordered ? 'ul' : 'ol';
      if (!list || list.tagName.toLowerCase() !== tag) { list = document.createElement(tag); parent.append(list); }
      const item = document.createElement('li'); appendInline(item, (unordered || ordered)[1], onCitation); list.append(item); continue;
    }
    list = null; const paragraph = document.createElement('p'); appendInline(paragraph, line, onCitation); parent.append(paragraph);
  }
}

function renderMermaid(parent, source) {
  const lines = source.split('\n').map((line) => line.trim()).filter((line) => line && !line.startsWith('%%'));
  const direction = /^(?:flowchart|graph)\s+LR/i.test(lines[0] || '') ? 'LR' : 'TD';
  const nodePattern = /([A-Za-z0-9_]+)(?:\[([^\]]*)\]|\{([^}]*)\}|\(\((.*?)\)\)|\((.*?)\))?/g;
  const nodes = new Map(); const edges = [];
  for (const line of lines) {
    if (/^(flowchart|graph|classDef|class|style|subgraph|end)\b/i.test(line)) continue;
    const matches = [...line.matchAll(nodePattern)];
    if (!matches.length) continue;
    for (const match of matches) {
      const id = match[1]; const label = match[2] ?? match[3] ?? match[4] ?? match[5] ?? id;
      nodes.set(id, {id,label,type:match[3] !== undefined ? 'decision' : match[4] !== undefined ? 'circle' : 'normal'});
    }
    if (/-->|---|==>/.test(line)) {
      const edgeLabel = /(?:-->|==>)\|([^|]+)\|/.exec(line)?.[1] || '';
      for (let i=0;i<matches.length-1;i++) edges.push({from:matches[i][1],to:matches[i+1][1],label:edgeLabel});
    }
  }
  if (nodes.size < 2 || !edges.length) { const pre = document.createElement('pre'); pre.textContent = source; parent.append(pre); return; }
  const horizontal = direction === 'LR'; const entries = [...nodes.values()];
  const width = horizontal ? Math.max(720, entries.length * 230 + 80) : 720;
  const height = horizontal ? 360 : Math.max(240, entries.length * 112 + 40);
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('viewBox',`0 0 ${width} ${height}`); svg.setAttribute('role','img'); svg.setAttribute('aria-label','由回答生成的流程图');
  const arrowId=`arrow-${Math.random().toString(36).slice(2)}`; const defs = document.createElementNS(svg.namespaceURI,'defs'); const marker = document.createElementNS(svg.namespaceURI,'marker'); marker.setAttribute('id',arrowId); marker.setAttribute('viewBox','0 0 10 10'); marker.setAttribute('refX','8'); marker.setAttribute('refY','5'); marker.setAttribute('markerWidth','7'); marker.setAttribute('markerHeight','7'); marker.setAttribute('orient','auto-start-reverse'); const tip = document.createElementNS(svg.namespaceURI,'path'); tip.setAttribute('d','M 0 0 L 10 5 L 0 10 z'); tip.setAttribute('fill','#70a38d'); marker.append(tip); defs.append(marker); svg.append(defs);
  const positions = new Map();
  entries.forEach((node,index) => positions.set(node.id, horizontal ? {x:50+index*230,y:150} : {x:width/2-110,y:25+index*112}));
  edges.forEach((edge) => {
    const a=positions.get(edge.from), b=positions.get(edge.to); if(!a||!b)return;
    const ax=horizontal?a.x+220:a.x+110, ay=horizontal?a.y+29:a.y+58, bx=horizontal?b.x:b.x+110, by=horizontal?b.y+29:b.y;
    const path=document.createElementNS(svg.namespaceURI,'path'); path.setAttribute('d',horizontal?`M ${ax} ${ay} C ${ax+28} ${ay}, ${bx-28} ${by}, ${bx} ${by}`:`M ${ax} ${ay} C ${ax} ${ay+28}, ${bx} ${by-28}, ${bx} ${by}`); path.setAttribute('fill','none'); path.setAttribute('stroke','#70a38d'); path.setAttribute('stroke-width','2'); path.setAttribute('marker-end',`url(#${arrowId})`); svg.append(path);
    if(edge.label){const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String((ax+bx)/2+8));label.setAttribute('y',String((ay+by)/2-7));label.setAttribute('class','mermaid-edge-label');label.textContent=edge.label;svg.append(label);}
  });
  entries.forEach((node) => {
    const {x,y}=positions.get(node.id); const group=document.createElementNS(svg.namespaceURI,'g');
    let shape;
    if(node.type==='decision'){shape=document.createElementNS(svg.namespaceURI,'polygon');shape.setAttribute('points',`${x+110},${y} ${x+220},${y+29} ${x+110},${y+58} ${x},${y+29}`);}
    else {shape=document.createElementNS(svg.namespaceURI,node.type==='circle'?'ellipse':'rect'); if(node.type==='circle'){shape.setAttribute('cx',String(x+110));shape.setAttribute('cy',String(y+29));shape.setAttribute('rx','108');shape.setAttribute('ry','28');} else {shape.setAttribute('x',String(x));shape.setAttribute('y',String(y));shape.setAttribute('width','220');shape.setAttribute('height','58');shape.setAttribute('rx','12');}}
    shape.setAttribute('fill',node.type==='decision'?'#fff8e9':'#f3f8f4');shape.setAttribute('stroke','#b7d2c3');shape.setAttribute('stroke-width','1.5'); group.append(shape);
    const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String(x+110));label.setAttribute('y',String(y+34));label.setAttribute('text-anchor','middle');label.setAttribute('class','mermaid-node-label');label.textContent=node.label;group.append(label);svg.append(group);
  });
  const wrapper=document.createElement('div');wrapper.className='mermaid-diagram';wrapper.append(svg);parent.append(wrapper);
}

function renderAnswer(parent, text, onCitation = null) {
  parent.replaceChildren(); const codePattern=/```([\w-]*)\s*\n([\s\S]*?)```/g; let cursor=0;
  for(const match of text.matchAll(codePattern)){
    appendMarkdown(parent,text.slice(cursor,match.index),onCitation);
    if(match[1].toLowerCase()==='mermaid') renderMermaid(parent,match[2]);
    else {const pre=document.createElement('pre');const code=document.createElement('code');code.textContent=match[2];pre.append(code);parent.append(pre);}
    cursor=match.index+match[0].length;
  }
  appendMarkdown(parent,text.slice(cursor),onCitation);
}

async function refreshHealth() {
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    $('#system-status').textContent = data.configured ? '模型已连接' : '等待配置密钥';
    $('#model-status').textContent = `${data.model} · 对话模型`;
    $('#footer-health').textContent = data.configured ? '模型服务已就绪' : '请检查本地模型密钥';
    const retrieval = data.retrieval;
    $('#retrieval-model-notice').textContent = retrieval.embedding_enabled
      ? `语义模型：${retrieval.embedding_model} · 重排：${retrieval.reranker_enabled ? retrieval.reranker_model : '未启用'}`
      : `语义向量未启用；当前 BM25 + TF‑IDF 可用。首次启用本地模型会下载权重，不会上传文档。模型：${retrieval.embedding_model}`;
    $('#reindex-button').hidden = !retrieval.embedding_enabled;
  } catch {
    $('#system-status').textContent = '服务未连接';
    $('#footer-health').textContent = '无法连接到本地服务';
  }
}

async function refreshWatcher() {
  try {
    const response = await fetch('/api/watcher'); const state = await response.json();
    const node = $('#watcher-status'); node.className = `watcher-status ${state.state}`;
    const libraryNode = $('#library-watcher'); libraryNode.className = `watcher-status ${state.state}`;
    const label = state.state === 'disabled' ? '目录监控已关闭'
      : state.state === 'indexing' ? `正在增量导入：${state.current_file || '文档'}`
      : state.state === 'error' ? `监控遇到错误：${state.last_error || '请检查目录'}`
      : `目录监控中 · ${state.files_seen} 个文件 · 已新增 ${state.indexed} 份`;
    node.querySelector('span').textContent = label;
    libraryNode.querySelector('span').textContent = label;
    node.title = `本地收件目录：${state.directory}${state.last_scan ? `\n最近扫描：${state.last_scan}` : ''}`;
  } catch {
    $('#watcher-status').querySelector('span').textContent = '目录监控状态暂不可用';
    $('#library-watcher').querySelector('span').textContent = '目录监控状态暂不可用';
  }
}

async function refreshDocuments() {
  try {
    const response = await fetch('/api/documents');
    const docs = await response.json(); cachedDocuments = docs;
    $('#doc-count').textContent = docs.length;
    $('#chunk-count').textContent = docs.reduce((sum, doc) => sum + doc.chunks, 0);
    $('#nav-count').textContent = docs.length;
    $('#library-count').textContent = docs.length;
    const overview = $('#overview-documents'); overview.replaceChildren();
    if (!docs.length) {
      const emptyRecent = document.createElement('div'); emptyRecent.className = 'overview-empty';
      emptyRecent.textContent = '添加文档后，最近入库的资料会显示在这里。'; overview.append(emptyRecent);
    } else {
      docs.slice(0, 4).forEach((doc) => {
        const row = document.createElement('button'); row.type = 'button'; row.className = 'overview-doc-row';
        const ext = doc.name.split('.').pop().toLowerCase();
        const glyph = document.createElement('span'); glyph.className = `doc-glyph ${ext}`; glyph.textContent = ext.toUpperCase();
        const info = document.createElement('span'); info.className = 'overview-doc-info';
        const name = document.createElement('b'); name.textContent = doc.name;
        const meta = document.createElement('small'); meta.textContent = `${doc.category} · ${doc.pages} 页 · ${doc.chunks} 个片段`;
        const arrow = document.createElement('span'); arrow.className = 'overview-arrow'; arrow.textContent = '↗';
        info.append(name, meta); row.append(glyph, info, arrow); row.addEventListener('click', () => showDocumentImages(doc)); overview.append(row);
      });
    }
    const empty = document.querySelector('.empty-library');
    empty.style.display = docs.length ? 'none' : 'flex';
    const list = $('#document-list'); list.replaceChildren();
    const filter = $('#document-filter').value;
    const visibleDocs = docs.filter((doc) => filter === '全部' || doc.category === filter);
    if (docs.length && !visibleDocs.length) { const note = document.createElement('div'); note.className = 'filter-empty'; note.textContent = '这个分类暂时没有文档。'; list.append(note); }
    visibleDocs.forEach((doc) => {
      const row = document.createElement('div'); row.className = 'doc-row';
      const ext = doc.name.split('.').pop().toLowerCase();
      const glyph = document.createElement('span'); glyph.className = `doc-glyph ${ext}`; glyph.textContent = ext.toUpperCase();
      const meta = document.createElement('span'); meta.className = 'doc-meta';
      const title = document.createElement('b'); title.textContent = doc.name;
      const subtitle = document.createElement('small'); subtitle.textContent = `${doc.category} · ${doc.pages} 页 · ${doc.chunks} 个知识片段`;
      meta.append(title, subtitle);
      const status = document.createElement('span'); status.className = 'doc-ready'; status.textContent = '已索引';
      row.append(glyph, meta, status); row.tabIndex = 0; row.setAttribute('role', 'button'); row.setAttribute('aria-label', `查看 ${doc.name} 中提取的图片`);
      const remove = document.createElement('button'); remove.className = 'doc-remove'; remove.type = 'button'; remove.textContent = '×'; remove.title = '删除文档及本地索引';
      remove.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (!window.confirm(`删除“${doc.name}”及其本地解析内容和索引？`)) return;
        const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}`, {method:'DELETE'});
        const result = await response.json();
        if (!response.ok) { toast(result.detail || '删除失败'); return; }
        toast('文档及本地索引已删除'); refreshDocuments();
      });
      row.append(remove);
      const category = document.createElement('select'); category.className = 'doc-category'; category.setAttribute('aria-label', `设置 ${doc.name} 的分类`);
      ['未分类','课程','项目','论文','技术资料','其他'].forEach((value) => { const option = document.createElement('option'); option.value = value; option.textContent = value; category.append(option); });
      category.value = doc.category;
      category.addEventListener('click', (event) => event.stopPropagation());
      category.addEventListener('keydown', (event) => event.stopPropagation());
      category.addEventListener('change', async (event) => {
        event.stopPropagation();
        const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/category`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:category.value})});
        if (!response.ok) { toast('分类更新失败'); return; }
        toast('文档分类已更新'); refreshDocuments();
      });
      row.append(category);
      row.addEventListener('click', () => showDocumentImages(doc));
      row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showDocumentImages(doc); } });
      list.append(row);
    });
  } catch { /* Keep the empty state visible while the local API is unavailable. */ }
}

async function showDocumentImages(doc) {
  $('#dialog-title').textContent = doc.name;
  const gallery = $('#image-gallery'); gallery.replaceChildren();
  const preview = $('#document-preview'); preview.replaceChildren();
  const dialog = $('#document-dialog'); dialog.showModal();
  try {
    const markdownResponse = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/markdown`);
    if (!markdownResponse.ok) throw new Error('文档预览暂不可用');
    const documentData = await markdownResponse.json();
    const body = documentData.markdown.replace(/^!\[[^\]]*\]\([^\n]*\)\s*$/gm, '').trim();
    appendMarkdown(preview, body || '未提取到可预览的正文内容。');
    const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/images`);
    const images = await response.json();
    if (!images.length) { gallery.textContent = '这份文档没有可提取的图片。'; return; }
    images.forEach((item) => {
      const card = document.createElement('article'); card.className = 'gallery-card';
      const image = document.createElement('img'); image.src = `/api/images/${encodeURIComponent(item.id)}`; image.alt = `${doc.name} 第 ${item.page} 页图片`;
      const meta = document.createElement('div'); meta.className = 'gallery-meta';
      const title = document.createElement('b'); title.textContent = `${item.name} · 第 ${item.page} 页`;
      const caption = document.createElement('p'); caption.textContent = item.caption || '未生成图片说明。重新上传并勾选“使用 DeepSeek Flash 理解图片”即可解析。';
      meta.append(title, caption); card.append(image, meta); gallery.append(card);
    });
  } catch { gallery.textContent = '暂时无法载入图片列表。'; }
}

async function showSettings() {
  const dialog = $('#settings-dialog'); const content = $('#settings-content');
  content.textContent = '正在读取配置…'; dialog.showModal();
  try {
    const response = await fetch('/api/settings'); const data = await response.json();
    if (!response.ok) throw new Error('配置读取失败');
    content.replaceChildren();
    const rows = [
      ['对话模型', data.model], ['API 密钥', data.configured ? '已配置（值已隐藏）' : '未配置'],
      ['DeepSeek 接口', data.base_url], ['本地数据目录', data.data_directory],
      ['本地语义向量', data.embedding_enabled ? `已启用 · ${data.embedding_model}` : '未启用'],
      ['本地重排模型', data.reranker_enabled ? `已启用 · ${data.reranker_model}` : '未启用'],
      ['图片分析上限', `每份文档最多 ${data.vision_max_images} 张（需上传时主动勾选）`],
      ['目录监控', data.watcher.state === 'disabled' ? '已关闭' : data.watcher.directory + ' · ' + data.watcher.interval_seconds + ' 秒扫描一次'],
    ];
    rows.forEach(([label, value]) => {
      const row = document.createElement('div'); row.className = 'settings-row';
      const name = document.createElement('span'); name.textContent = label;
      const setting = document.createElement('b'); setting.textContent = value;
      row.append(name, setting); content.append(row);
    });
  } catch (error) { content.textContent = error.message; }
}

async function refreshEvaluationCases() {
  try {
    const response = await fetch('/api/evaluation/cases'); const cases = await response.json();
    $('#evaluation-count').textContent = `${cases.length} 个测试样例`;
    const target = $('#evaluation-cases'); target.replaceChildren(); $('#evaluation-metrics').replaceChildren();
    cases.forEach((item) => {
      const row = document.createElement('div'); row.className = 'evaluation-case'; row.dataset.caseId = item.id;
      const text = document.createElement('div'); const question = document.createElement('b'); question.textContent = item.question; const expected = document.createElement('small'); expected.textContent = `期望来源：${item.relevant_documents.join('、')}`; text.append(question, expected);
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '移除'; remove.addEventListener('click', async () => { await fetch(`/api/evaluation/cases/${encodeURIComponent(item.id)}`, {method:'DELETE'}); refreshEvaluationCases(); });
      row.append(text, remove); target.append(row);
    });
  } catch { $('#evaluation-count').textContent = '评估接口暂不可用'; }
}

function renderEvidence(citations = []) {
  const list = $('#evidence-list'); list.replaceChildren();
  $('#evidence-subtitle').textContent = citations.length ? `本轮命中 ${citations.length} 条来源` : '回答来源会显示在这里';
  if (!citations.length) {
    const empty = document.createElement('div'); empty.className = 'evidence-empty';
    const icon = document.createElement('span'); icon.textContent = '◌';
    const title = document.createElement('b'); title.textContent = '暂无检索证据';
    const text = document.createElement('p'); text.textContent = '当前回答没有引用到可展示的文档片段。'; empty.append(icon, title, text); list.append(empty); return;
  }
  citations.forEach((citation) => {
    const card = document.createElement('article'); card.className = 'evidence-card'; card.id = `citation-${citation.id}`;
    const label = document.createElement('span'); label.className = 'evidence-source-label'; label.textContent = citation.id;
    const heading = document.createElement('b'); heading.textContent = citation.document;
    const page = document.createElement('small'); page.textContent = `第 ${citation.page} 页`;
    const excerpt = document.createElement('p'); excerpt.textContent = citation.excerpt;
    const top = document.createElement('div'); top.className = 'evidence-card-head'; top.append(label, page);
    card.append(top, heading, excerpt);
    if (citation.image_url) { const image = document.createElement('img'); image.src = citation.image_url; image.alt = `${citation.document} 第 ${citation.page} 页相关图片`; image.loading = 'lazy'; card.append(image); }
    list.append(card);
  });
}

function appendChatMessage(message) {
  const row = document.createElement('article'); row.className = `chat-message ${message.role}`;
  const avatar = document.createElement('div'); avatar.className = 'message-avatar'; avatar.textContent = message.role === 'assistant' ? '知' : '我';
  const body = document.createElement('div'); body.className = 'message-body';
  const label = document.createElement('div'); label.className = 'message-label'; label.textContent = message.role === 'assistant' ? '知序' : '你';
  const content = document.createElement('div'); content.className = 'message-content';
  if (message.role === 'assistant') {
    renderAnswer(content, message.content, (citationId) => {
      renderEvidence(message.citations || []);
      requestAnimationFrame(() => document.getElementById(`citation-${citationId}`)?.scrollIntoView({behavior:'smooth',block:'center'}));
    });
    const actions = document.createElement('div'); actions.className = 'message-actions';
    const sourceButton = document.createElement('button'); sourceButton.type = 'button'; sourceButton.className = 'source-action';
    sourceButton.textContent = message.citations?.length ? `⌕ 查看本轮 ${message.citations.length} 条证据` : '⌕ 本轮无引用来源';
    sourceButton.disabled = !message.citations?.length;
    sourceButton.addEventListener('click', () => renderEvidence(message.citations || [])); actions.append(sourceButton); body.append(label, content, actions);
  } else { appendMarkdown(content, message.content); body.append(label, content); }
  row.append(avatar, body); $('#chat-thread').append(row); return row;
}

async function loadConversation(conversationId) {
  const token = ++conversationLoadToken;
  activeConversationId = conversationId;
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`); const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '无法读取会话');
    if (token !== conversationLoadToken) return;
    $('#active-conversation-title').textContent = data.title;
    $('#chat-thread').replaceChildren();
    $('#chat-welcome').hidden = data.messages.length > 0;
    data.messages.forEach(appendChatMessage);
    const lastAnswer = [...data.messages].reverse().find((message) => message.role === 'assistant');
    renderEvidence(lastAnswer?.citations || []);
    document.querySelectorAll('.conversation-item').forEach((item) => item.classList.toggle('active', item.dataset.conversationId === conversationId));
    $('#chat-scroll').scrollTop = $('#chat-scroll').scrollHeight;
  } catch (error) { toast(error.message || '无法读取会话'); }
}

async function refreshConversations(preferredId = null) {
  try {
    const response = await fetch('/api/conversations'); const sessions = await response.json();
    if (!response.ok) throw new Error('无法读取会话列表');
    const list = $('#conversation-list'); list.replaceChildren();
    if (!sessions.length) {
      const empty = document.createElement('div'); empty.className = 'session-empty'; empty.textContent = '还没有历史对话'; list.append(empty);
      const created = await fetch('/api/conversations', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
      const session = await created.json(); if (!created.ok) throw new Error(session.detail || '无法新建对话');
      return refreshConversations(session.id);
    }
    sessions.forEach((session) => {
      const item = document.createElement('button'); item.type = 'button'; item.className = 'conversation-item'; item.dataset.conversationId = session.id;
      const title = document.createElement('b'); title.textContent = session.title;
      const meta = document.createElement('small'); meta.textContent = session.message_count ? `${Math.ceil(session.message_count / 2)} 轮对话` : '尚未开始';
      const icon = document.createElement('span'); icon.className = 'conversation-item-icon'; icon.textContent = '▤';
      item.append(icon, title, meta); item.addEventListener('click', () => loadConversation(session.id)); list.append(item);
    });
    const nextId = preferredId && sessions.some((session) => session.id === preferredId) ? preferredId
      : sessions.some((session) => session.id === activeConversationId) ? activeConversationId : sessions[0].id;
    await loadConversation(nextId);
  } catch (error) { toast(error.message || '会话服务暂不可用'); }
}

async function startNewConversation() {
  const button = $('#new-chat'); button.disabled = true;
  try {
    const response = await fetch('/api/conversations', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const session = await response.json(); if (!response.ok) throw new Error(session.detail || '新建对话失败');
    await refreshConversations(session.id); $('#question').focus();
  } catch (error) { toast(error.message || '新建对话失败'); }
  finally { button.disabled = false; }
}

const pageTitles = {home:'知识概览',library:'我的文档',ask:'智能问答',retrieval:'检索实验室'};
function navigateToPage() {
  const requested = location.hash.slice(1);
  const route = Object.hasOwn(pageTitles, requested) ? requested : 'home';
  document.querySelectorAll('.app-page').forEach((page) => page.classList.toggle('active', page.dataset.page === route));
  document.querySelectorAll('.nav-item').forEach((item) => {
    const active = item.dataset.route === route;
    item.classList.toggle('active', active);
    if (active) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
  });
  $('#breadcrumb-title').textContent = pageTitles[route];
  document.title = `${pageTitles[route]} · 知序`;
}
window.addEventListener('hashchange', navigateToPage);
function setQuestion(question) {
  $('#question').value = question;
  if (location.hash !== '#ask') location.hash = 'ask';
  navigateToPage(); $('#question').focus();
}
document.querySelectorAll('[data-question]').forEach((button) => button.addEventListener('click', () => setQuestion(button.dataset.question)));
$('#new-chat').addEventListener('click', startNewConversation);
$('#upload-trigger').addEventListener('click', () => $('#file-input').click());
$('#empty-upload').addEventListener('click', () => $('#file-input').click());
$('#document-filter').addEventListener('change', () => refreshDocuments());
$('#dialog-close').addEventListener('click', () => $('#document-dialog').close());
$('#settings-trigger').addEventListener('click', showSettings);
$('#settings-close').addEventListener('click', () => $('#settings-dialog').close());
$('#retrieval-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const query = $('#retrieval-query').value.trim(); if (!query) return;
  const output = $('#retrieval-results'); output.replaceChildren(); output.textContent = '正在检索…';
  try {
    const params = new URLSearchParams({query, top_k: $('#retrieval-k').value});
    const response = await fetch(`/api/retrieval?${params}`); const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '检索失败');
    output.replaceChildren();
    const laneNames = {bm25:'BM25 关键词',tfidf:'TF‑IDF 稀疏向量',dense:'语义向量'};
    Object.entries(data.lanes).forEach(([lane, rows]) => {
      const card = document.createElement('section'); card.className = 'lane-card';
      const title = document.createElement('h3'); title.textContent = laneNames[lane]; card.append(title);
      if (!rows.length) { const empty = document.createElement('p'); empty.className = 'lane-empty'; empty.textContent = lane === 'dense' ? '未启用或尚无向量索引' : '暂无命中'; card.append(empty); }
      rows.forEach((item, index) => { const row = document.createElement('article'); row.className = 'lane-result'; const meta = document.createElement('small'); meta.textContent = `${index + 1}. ${item.document} · 第 ${item.page} 页 · ${item.score}`; const excerpt = document.createElement('p'); excerpt.textContent = item.excerpt; row.append(meta, excerpt); card.append(row); });
      output.append(card);
    });
    const fused = document.createElement('section'); fused.className = 'lane-card fused-card'; const fusedTitle = document.createElement('h3'); fusedTitle.textContent = 'RRF 融合与重排 Top‑K'; fused.append(fusedTitle);
    data.results.forEach((item, index) => { const row = document.createElement('article'); row.className = 'lane-result'; const meta = document.createElement('small'); meta.textContent = `${index + 1}. ${item.name} · 第 ${item.page} 页 · RRF ${item.fusion_score}${item.rerank_score !== undefined ? ` · 重排 ${Number(item.rerank_score).toFixed(3)}` : ''}`; const excerpt = document.createElement('p'); excerpt.textContent = item.content.slice(0, 240); row.append(meta, excerpt); fused.append(row); });
    output.append(fused);
  } catch (error) { output.textContent = error.message; }
});
$('#reindex-button').addEventListener('click', async (event) => {
  const button = event.currentTarget; button.disabled = true; button.textContent = '正在建立本地向量索引…';
  try { const response = await fetch('/api/reindex', {method:'POST'}); const result = await response.json(); if (!response.ok) throw new Error(result.detail); toast(`已为 ${result.indexed} 个片段建立向量索引`); }
  catch (error) { toast(error.message || '向量索引建立失败'); }
  finally { button.disabled = false; button.textContent = '为现有文档建立向量索引'; }
});
$('#evaluation-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const relevant_documents = $('#eval-documents').value.split(/[，,]/).map((value) => value.trim()).filter(Boolean);
  try {
    const response = await fetch('/api/evaluation/cases', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:$('#eval-question').value.trim(),relevant_documents})});
    const result = await response.json(); if (!response.ok) throw new Error(result.detail || '添加样例失败');
    $('#eval-question').value = ''; $('#eval-documents').value = ''; await refreshEvaluationCases(); toast('评估样例已保存到本地');
  } catch (error) { toast(error.message); }
});
$('#run-evaluation').addEventListener('click', async (event) => {
  const button = event.currentTarget; button.disabled = true; button.textContent = '评估中…';
  try {
    const response = await fetch(`/api/evaluation/run?top_k=${$('#evaluation-k').value}`, {method:'POST'}); const result = await response.json(); if (!response.ok) throw new Error(result.detail);
    const metrics = $('#evaluation-metrics'); metrics.replaceChildren();
    [['Recall@K',result.recall_at_k],['Hit Rate',result.hit_rate],['MRR',result.mrr]].forEach(([label,value]) => { const card = document.createElement('div'); card.className = 'metric-card'; const name = document.createElement('small'); name.textContent = label; const score = document.createElement('b'); score.textContent = Number(value).toFixed(3); card.append(name,score); metrics.append(card); });
    result.details.forEach((detail) => { const row = document.querySelector(`[data-case-id="${CSS.escape(detail.id)}"]`); if (row) { row.dataset.hit = String(detail.hit); const label = document.createElement('span'); label.className = `eval-result ${detail.hit ? 'hit' : 'miss'}`; label.textContent = detail.hit ? `命中 · RR ${detail.reciprocal_rank.toFixed(2)}` : '未命中'; row.append(label); } });
    toast(`已完成 ${result.cases} 个样例的检索评估`);
  } catch (error) { toast(error.message || '评估运行失败'); }
  finally { button.disabled = false; button.textContent = '运行评估'; }
});
$('#file-input').addEventListener('change', (event) => {
  const files = Array.from(event.target.files);
  if (!files.length) return;
  (async () => {
    let completed = 0;
    let visionSkipped = 0;
    for (const file of files) {
      const form = new FormData(); form.append('file', file); form.append('analyze_images', String($('#vision-toggle').checked)); form.append('category', $('#upload-category').value);
      try {
        const response = await fetch('/api/jobs', {method:'POST', body:form});
        const job = await response.json();
        if (!response.ok) throw new Error(job.detail || '无法创建解析任务');
        const progress = $('#upload-progress'); progress.hidden = false;
        let result;
        while (true) {
          const statusResponse = await fetch(`/api/jobs/${encodeURIComponent(job.id)}`);
          const status = await statusResponse.json();
          if (!statusResponse.ok) throw new Error(status.detail || '解析任务状态不可用');
          progress.textContent = `${file.name} · ${status.phase}`;
          if (status.status === 'completed') { result = status.result; break; }
          if (status.status === 'failed') throw new Error(status.error || '文档处理失败');
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
        completed++; visionSkipped += result.vision_skipped || 0;
      } catch (error) { toast(`${file.name}：${error.message}`); }
    }
    if (completed) toast(`已完成 ${completed} 份文档解析与索引${visionSkipped ? `，${visionSkipped} 张图片超过单文档视觉分析上限` : ''}`);
    await refreshDocuments();
    $('#upload-progress').hidden = true;
    event.target.value = '';
  })();
});
$('#question').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#ask-form').requestSubmit(); }
});
$('#ask-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (!question) return;
  const submit = event.currentTarget.querySelector('button[type="submit"]');
  submit.disabled = true; submit.textContent = '…';
  $('#chat-welcome').hidden = true;
  appendChatMessage({role:'user',content:question});
  const pending = document.createElement('article'); pending.className = 'chat-message assistant pending-message';
  const pendingAvatar = document.createElement('div'); pendingAvatar.className = 'message-avatar'; pendingAvatar.textContent = '知';
  const pendingText = document.createElement('div'); pendingText.className = 'pending-content'; pendingText.textContent = '正在检索资料并整理回答…';
  pending.append(pendingAvatar,pendingText); $('#chat-thread').append(pending); $('#chat-scroll').scrollTop = $('#chat-scroll').scrollHeight;
  $('#question').value = '';
  try {
    if (!activeConversationId) {
      const created = await fetch('/api/conversations', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
      const session = await created.json(); if (!created.ok) throw new Error(session.detail || '无法创建会话'); activeConversationId = session.id;
    }
    const response = await fetch('/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,conversation_id:activeConversationId})});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '暂时无法完成请求。');
    activeConversationId = payload.conversation_id || activeConversationId;
    pending.remove(); appendChatMessage({role:'assistant',content:payload.answer,citations:payload.citations});
    renderEvidence(payload.citations); $('#chat-scroll').scrollTop = $('#chat-scroll').scrollHeight;
    await refreshConversations(activeConversationId);
  } catch (error) {
    pending.remove(); appendChatMessage({role:'assistant',content:`暂时无法完成回答：${error.message}`,citations:[]});
    renderEvidence([]); $('#chat-scroll').scrollTop = $('#chat-scroll').scrollHeight;
  } finally {
    submit.disabled = false; submit.textContent = '↑';
  }
});
refreshHealth();
refreshDocuments();
refreshEvaluationCases();
refreshWatcher();
refreshConversations();
if (!location.hash) location.hash = 'home';
navigateToPage();
setInterval(refreshWatcher, 8000);
