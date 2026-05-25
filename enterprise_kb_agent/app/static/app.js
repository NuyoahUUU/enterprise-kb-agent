const state = {
  documents: [],
  sessions: [],
  activeDocumentId: "",
  activeDocumentName: "全部文档",
  sessionId: "",
  sessionDocs: [],
  models: [],
  currentModel: "",
  currentProvider: "",
  thinkMode: true,
  currentLibrary: localStorage.getItem("kb_library") || "enterprise",
  permissionMode: localStorage.getItem("permission_mode") || "read_only",
};

const LIB_NAMES = { enterprise: "企业库", research: "研究库" };

const $ = (id) => document.getElementById(id);
const DEFAULT_CONVERSATION_TITLE = "新对话";

function activeSessionKey(library = state.currentLibrary) {
  return `active_session_${library}`;
}

function sessionTitle(session) {
  if (!session) return state.sessionId ? "当前对话" : DEFAULT_CONVERSATION_TITLE;
  const fallback = (session.question || "未命名对话").slice(0, 60);
  return getDisplayName("session_names", session.session_id, fallback);
}

function currentSession() {
  return state.sessions.find((s) => s.session_id === state.sessionId);
}

function setActiveSessionId(sessionId, persist = true) {
  state.sessionId = sessionId || "";
  if (persist) {
    if (state.sessionId) {
      localStorage.setItem(activeSessionKey(), state.sessionId);
    } else {
      localStorage.removeItem(activeSessionKey());
    }
  }
  updateConversationLabel();
}

function restoreActiveSessionId() {
  state.sessionId = localStorage.getItem(activeSessionKey()) || "";
  updateConversationLabel();
}

function updateConversationLabel() {
  const el = $("sessionId");
  if (!el) return;
  el.textContent = sessionTitle(currentSession());
}

function setStatus(text, isError = false) {
  const node = $("statusText");
  node.textContent = text;
  node.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.code >= 400) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload.data;
}

/* ---------- 折叠/展开 ---------- */

function setupCollapsibleSections() {
  document.querySelectorAll(".section-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.target;
      const body = document.getElementById(targetId);
      if (!body) return;
      const icon = btn.querySelector(".toggle-icon");
      body.classList.toggle("collapsed");
      if (body.classList.contains("collapsed")) {
        icon.textContent = "▸";
      } else {
        icon.textContent = "▾";
      }
    });
  });
}

/* ---------- 名称管理（会话 + 文档） ---------- */

function loadNames(key) {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); }
  catch { return {}; }
}
function saveName(key, id, name) {
  const names = loadNames(key);
  if (name) names[id] = name; else delete names[id];
  localStorage.setItem(key, JSON.stringify(names));
}
function getDisplayName(key, id, fallback) {
  return loadNames(key)[id] || fallback || "(空)";
}

function startRename(el, oldName, key, id) {
  const input = document.createElement("input");
  input.value = oldName;
  input.className = "rename-input";
  input.style.width = "100%";
  el.replaceWith(input);
  input.addEventListener("click", (e) => e.stopPropagation());
  input.focus(); input.select();
  let saved = false;
  const done = () => {
    if (saved) return;
    saved = true;
    const newName = input.value.trim();
    saveName(key, id, newName);
    const restore = el.cloneNode(true);
    restore.textContent = newName || oldName || "(空)";
    input.replaceWith(restore);
  };
  let composing = false, composeJustEnded = false;
  input.addEventListener("compositionstart", (e) => { e.stopPropagation(); composing = true; });
  input.addEventListener("compositionend", (e) => { e.stopPropagation(); composing = false; composeJustEnded = true; setTimeout(() => { composeJustEnded = false; }, 400); });
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (composing || e.isComposing || e.keyCode === 229) return;
    if (e.key === "Escape") { input.value = oldName; done(); return; }
    if (e.key === "Enter") { e.preventDefault(); done(); }
  });
  return input;
}

/* ---------- 会话列表 ---------- */

function renderSessions() {
  const list = $("sessionList");
  if (!state.sessions.length) {
    list.innerHTML = '<div class="muted-line">暂无历史</div>';
    updateConversationLabel();
    return;
  }
  list.innerHTML = state.sessions
    .map((s) => {
      const active = s.session_id === state.sessionId ? "active" : "";
      const turns = Math.max(1, Math.ceil((s.message_count || 0) / 2));
      const time = (s.updated_at || "").replace("T", " ").slice(0, 16);
      return `
        <div class="session-row ${active}">
          <button class="session-item" data-session-id="${escapeHtml(s.session_id)}">
            <div class="session-preview" title="双击修改名称">${escapeHtml(sessionTitle(s))}</div>
            <div class="session-meta">${LIB_NAMES[s.library]||""} · ${turns} 轮 · ${time}</div>
          </button>
          <button class="delete-btn session-delete-btn" data-session-id="${escapeHtml(s.session_id)}" title="删除会话">&times;</button>
        </div>
      `;
    })
    .join("");

  // 单击/双击 区分：双击改名称，单击加载历史
  let clickTimer = null;
  list.querySelectorAll(".session-item").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      // 有正在编辑的 input 时忽略 click
      if (btn.querySelector(".rename-input")) return;
      const sid = btn.dataset.sessionId;
      if (clickTimer) {
        // 双击 → 改名称
        clearTimeout(clickTimer); clickTimer = null;
        const old = (loadNames("session_names")[sid] || state.sessions.find(s => s.session_id === sid)?.question || "").slice(0, 60);
        const preview = btn.querySelector(".session-preview");
        if (!preview) return;
        const input = document.createElement("input");
        input.value = old;
        input.className = "rename-input";
        preview.replaceWith(input);
        input.addEventListener("click", (e) => e.stopPropagation()); // 防止点击冒泡到外层 button
        input.focus(); input.select();
        let saved = false;
        const save = () => {
          if (saved) return;
          saved = true;
          const newName = input.value.trim();
          saveName("session_names", sid, newName);
          const newPreview = document.createElement("div");
          newPreview.className = "session-preview";
          newPreview.title = "双击修改名称";
          newPreview.textContent = newName || old || "(空)";
          input.replaceWith(newPreview);
          updateConversationLabel();
        };
        let composing = false, composeJustEnded = false;
        input.addEventListener("compositionstart", (e) => { e.stopPropagation(); composing = true; });
        input.addEventListener("compositionend", (e) => { e.stopPropagation(); composing = false; composeJustEnded = true; setTimeout(() => { composeJustEnded = false; }, 400); });
        input.addEventListener("keydown", (ke) => {
          ke.stopPropagation(); // 防止冒泡到外层 button
          // 输入法组合中忽略所有操作
          if (composing || ke.isComposing || ke.keyCode === 229) return;
          if (ke.key === "Escape") {
            // 放弃修改
            saved = true;
            const restore = document.createElement("div");
            restore.className = "session-preview";
            restore.title = "双击修改名称";
            restore.textContent = old || "(空)";
            input.replaceWith(restore);
            return;
          }
          if (ke.key === "Enter") {
            ke.preventDefault(); save();
          }
        });
        return;
      }
      // 单击 → 加载历史
      clickTimer = setTimeout(() => {
        clickTimer = null;
        setActiveSessionId(sid);
        const session = state.sessions.find((s) => s.session_id === sid);
        state.sessionDocs = session?.documents || [];
        updateSessionDocs(session?.library);
        renderSessions();
        loadSessionHistory(sid);
      }, 280);
    });
  });

  // 删除按钮
  list.querySelectorAll(".session-delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const sid = btn.dataset.sessionId;
      showConfirmPopup(btn, () => deleteSession(sid).catch((err) => setStatus(err.message, true)));
    });
  });
}

function updateSessionDocs(sessionLibrary) {
  const el = $("sessionDocs");
  if (!state.sessionDocs.length) {
    el.textContent = "-";
    return;
  }
  const libName = LIB_NAMES[sessionLibrary || state.currentLibrary] || sessionLibrary || "?";
  el.innerHTML = state.sessionDocs
    .map((d) => {
      const name = d.filename || d.document_id?.slice(0, 10) || "?";
      return `<span class="session-doc-tag">${libName}:${escapeHtml(name)}</span>`;
    })
    .join(" ");
}

async function loadSessions() {
  try {
    const data = await api(`/api/agent/sessions?limit=50&library=${state.currentLibrary}`);
    state.sessions = data.sessions || [];
  } catch {
    state.sessions = [];
  }
  renderSessions();
  updateConversationLabel();
}

async function loadSessionHistory(sessionId) {
  try {
    const data = await api(`/api/agent/sessions/${sessionId}/history?limit=20`);
    const messages = data.messages || [];
    $("chatMessages").innerHTML = "";
    messages.forEach((m) => addMessage(m.role, m.content, m.created_at));
    updateConversationLabel();
    setStatus(`已加载 ${messages.length} 条历史`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function deleteSession(sessionId) {
  await api(`/api/agent/sessions/${sessionId}`, { method: "DELETE" });
  if (state.sessionId === sessionId) {
    jumpToNewSession();
  }
  await loadSessions();
  setStatus("对话已删除");
}

const GREETINGS = [
  "👋 你好呀！我是你的企业知识库助手，文档、论文、技术方案，尽管问我～",
  "🚀 准备好了！选个文档开始提问吧，我会帮你快速找到答案。",
  "💡 嗨！企业知识库已就绪，试试问我任何关于技术文档、论文或项目方案的问题～",
];

function pickGreeting() {
  const hour = new Date().getHours();
  // 约一半概率带时段问候，一半概率随机通用问候
  if (Math.random() < 0.5) {
    let timeGreeting;
    if (hour < 6) timeGreeting = "🌃 夜深了，注意休息。有问题我随时在。";
    else if (hour < 12) timeGreeting = "☀️ 早上好！今天想了解点什么？";
    else if (hour < 18) timeGreeting = "🌤️ 下午好！有什么可以帮你的？";
    else timeGreeting = "🌙 晚上好！还在加班吗，辛苦了～";
    return timeGreeting;
  }
  return GREETINGS[Math.floor(Math.random() * GREETINGS.length)];
}

function jumpToNewSession() {
  setActiveSessionId("");
  state.sessionDocs = [];
  updateSessionDocs();
  $("chatMessages").innerHTML = "";
  addMessage("agent", pickGreeting());
  renderSessions();
}

function newSession() {
  jumpToNewSession();
  setStatus("新对话");
}

/* ---------- 文档列表 ---------- */

function renderDocuments() {
  const list = $("documentList");
  const allActive = !state.activeDocumentId;
  const allButton = `
    <div class="document-row ${allActive ? "active" : ""}">
      <button class="document-item" data-document-id="" data-document-name="全部文档">
        <div class="document-title">全部文档</div>
        <div class="document-meta">${state.documents.length} 个文档</div>
      </button>
    </div>
  `;
  const items = state.documents
    .map((doc) => {
      const active = doc.document_id === state.activeDocumentId ? "active" : "";
      return `
        <div class="document-row ${active}">
          <button class="document-item" data-document-id="${escapeHtml(doc.document_id)}" data-document-name="${escapeHtml(doc.filename)}">
            <div class="document-title" title="双击修改名称">${escapeHtml(getDisplayName("doc_names", doc.document_id, doc.filename))}</div>
            <div class="document-meta">${doc.chunk_count} chunks · ${(doc.created_at||"").replace("T"," ").slice(0,16)}</div>
          </button>
          <button class="delete-btn doc-delete-btn" data-document-id="${escapeHtml(doc.document_id)}" data-document-name="${escapeHtml(doc.filename)}" title="删除文档">&times;</button>
        </div>
      `;
    })
    .join("");
  list.innerHTML = allButton + items;

  let docClickTimer = null;
  list.querySelectorAll(".document-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      // 有正在编辑的 input 时忽略
      if (row.querySelector(".rename-input")) return;
      const docBtn = row.querySelector(".document-item");
      const docId = docBtn?.dataset.documentId;
      if (!docId && docId !== "") return; // "" 是"全部文档"

      if (docClickTimer) {
        // 双击 → 改名称
        clearTimeout(docClickTimer); docClickTimer = null;
        const titleEl = row.querySelector(".document-title");
        if (!titleEl) return;
        const old = loadNames("doc_names")[docId] || titleEl.textContent || "";
        startRename(titleEl, old, "doc_names", docId);
        return;
      }
      // 单击 → 加载内容
      docClickTimer = setTimeout(() => {
        docClickTimer = null;
        state.activeDocumentId = docId || "";
        state.activeDocumentName = docBtn?.dataset.documentName || "全部文档";
        const libName = LIB_NAMES[state.currentLibrary] || state.currentLibrary;
        $("activeDocument").textContent = state.activeDocumentId
          ? `${libName} · ${state.activeDocumentName}`
          : `${libName} · 全部文档`;
        renderDocuments();
        if (state.activeDocumentId) {
          loadDocumentContent(state.activeDocumentId, state.activeDocumentName);
        } else {
          showDocContentPlaceholder();
        }
      }, 280);
    });
  });

  list.querySelectorAll(".doc-delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const docId = btn.dataset.documentId;
      showConfirmPopup(btn, () => deleteDocument(docId).catch((err) => setStatus(err.message, true)));
    });
  });
}

async function deleteDocument(documentId) {
  await api(`/documents/${documentId}?library=${state.currentLibrary}`, { method: "DELETE" });
  if (state.activeDocumentId === documentId) {
    state.activeDocumentId = "";
    state.activeDocumentName = "全部文档";
    $("activeDocument").textContent = "全部文档";
  }
  await loadDocuments();
  setStatus("文档已删除");
}

async function loadDocumentContent(documentId, filename) {
  $("docContentTitle").textContent = filename;
  $("docContentView").innerHTML = '<div class="muted-line">加载中...</div>';
  try {
    const data = await api(`/documents/${documentId}/content?library=${state.currentLibrary}`);
    $("docContentView").innerHTML = `<pre class="doc-content-pre">${escapeHtml(data.content)}</pre>`;
  } catch (error) {
    $("docContentView").innerHTML = `<div class="muted-line error">加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

function showDocContentPlaceholder() {
  $("docContentTitle").textContent = "文档内容";
  $("docContentView").innerHTML = '<div class="muted-line">点击左侧文档查看内容</div>';
}

async function loadDocuments() {
  const data = await api(`/documents?library=${state.currentLibrary}`);
  state.documents = data.documents || [];
  renderDocuments();
  setStatus("就绪");
}

/* ---------- 上传 ---------- */

async function uploadDocument(file, overwrite = false) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("library", state.currentLibrary);
  if (overwrite) formData.append("overwrite", "true");
  const data = await api("/upload", { method: "POST", body: formData });
  return data;
}

/* ---------- 聊天 ---------- */

function addMessage(role, text, createdAt) {
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper";

  const message = document.createElement("div");
  message.className = `message ${role}`;
  if (role === "agent" || role === "assistant") {
    message.className = `message agent`;
  }
  message.textContent = text;
  if (role === "agent" || role === "assistant") {
    message.appendChild(makeCopyBtn(message));
  }
  wrapper.appendChild(message);

  // 时间戳
  if (createdAt) {
    const timeEl = document.createElement("div");
    timeEl.className = `msg-time ${role}`;
    timeEl.textContent = createdAt.replace("T", " ").slice(0, 19);
    wrapper.appendChild(timeEl);
  }

  $("chatMessages").appendChild(wrapper);
  wrapper.scrollIntoView({ block: "end" });
  return message;
}

function makeCopyBtn(targetEl) {
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.textContent = "复制";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const text = targetEl.textContent.replace(/^复制$/, "").trim();
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = "已复制!";
      btn.classList.add("copied");
      setTimeout(() => { btn.textContent = "复制"; btn.classList.remove("copied"); }, 1500);
    });
  });
  return btn;
}

function renderSources(sources = []) {
  const sourceList = $("sourceList");
  if (!sources.length) {
    sourceList.innerHTML = '<div class="muted-line">无来源</div>';
    return;
  }
  sourceList.innerHTML = sources
    .map((source) => `
      <article class="source-item">
        <div class="source-title">${escapeHtml(source.filename)}</div>
        <div class="source-meta">
          ${escapeHtml(source.chunk_id)}
          ${source.similarity_score == null ? "" : ` · ${Number(source.similarity_score).toFixed(3)}`}
        </div>
        <div class="source-meta">${escapeHtml(source.content_preview)}</div>
      </article>
    `)
    .join("");
}

function renderOperationRequest(operation, hostMessage) {
  if (!operation || !hostMessage) return;
  const card = document.createElement("div");
  card.className = "operation-card";
  card.innerHTML = `
    <div class="operation-title">${escapeHtml(operation.title || "待批准操作")}</div>
    <div class="operation-summary">${escapeHtml(operation.summary || "")}</div>
    <pre class="operation-commands">${escapeHtml((operation.commands || []).join("\n"))}</pre>
    <div class="operation-actions">
      <button type="button" class="approve-btn">批准执行</button>
      <span class="operation-state">等待批准</span>
    </div>
  `;
  const button = card.querySelector(".approve-btn");
  const state = card.querySelector(".operation-state");
  button.addEventListener("click", () => approveOperation(operation, button, state));
  hostMessage.appendChild(card);
}

async function approveOperation(operation, button, stateNode) {
  button.disabled = true;
  stateNode.textContent = "执行中...";
  try {
    const data = await api("/operations/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation }),
    });
    const lines = data.steps
      .map((step) => {
        const output = [step.stdout, step.stderr].filter(Boolean).join("\n").trim();
        return `$ ${step.command}\n${output || `(退出码 ${step.returncode})`}`;
      })
      .join("\n\n");
    const result = document.createElement("pre");
    result.className = `operation-result ${data.status === "success" ? "success" : "failed"}`;
    result.textContent = lines;
    stateNode.closest(".operation-card").appendChild(result);
    stateNode.textContent = data.status === "success" ? "执行完成" : "执行失败";
    setStatus(data.status === "success" ? "操作完成" : "操作失败", data.status !== "success");
  } catch (error) {
    const result = document.createElement("pre");
    result.className = "operation-result failed";
    result.textContent = error.message;
    stateNode.closest(".operation-card").appendChild(result);
    stateNode.textContent = "执行失败";
    setStatus(error.message, true);
  }
}

function renderToolResult(hostMessage, toolName, payload) {
  // 为宿主工具渲染美观的结果卡片
  const hostTools = ["run_command", "read_file", "write_file"];

  if (!hostTools.includes(toolName)) {
    // 知识库工具：直接显示摘要文本
    const thinkSpan = hostMessage.querySelector(".think-text");
    if (thinkSpan) {
      thinkSpan.textContent += `   → ${payload.summary}\n`;
    }
    return;
  }

  // 宿主工具：解析 JSON 并渲染卡片
  let data = null;
  try {
    data = JSON.parse(payload.summary);
  } catch {
    // 不是 JSON（可能是截断的错误信息），显示原始文本
    const thinkSpan = hostMessage.querySelector(".think-text");
    if (thinkSpan) {
      thinkSpan.textContent += `   → ${payload.summary}\n`;
    }
    return;
  }

  if (!data) return;

  const card = document.createElement("div");
  card.className = "host-tool-result";

  if (toolName === "run_command") {
    const exitOk = data.returncode === 0;
    const badgeClass = exitOk ? "success" : "error";
    const badgeText = exitOk ? `退出码: ${data.returncode}` : `失败 (退出码: ${data.returncode})`;
    card.innerHTML = `
      <div class="tool-header">
        <span><span class="tool-icon">⚡</span>命令执行</span>
        <span class="tool-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
      </div>
      <div class="tool-label">$ ${escapeHtml(data.command || "")}  <span style="font-weight:400;color:var(--muted)">in ${escapeHtml(data.cwd || "")}</span></div>
    `;
    if (data.stdout) {
      card.innerHTML += `<pre class="cmd-block stdout">${escapeHtml(data.stdout)}</pre>`;
    }
    if (data.stderr) {
      card.innerHTML += `<pre class="cmd-block stderr">${escapeHtml(data.stderr)}</pre>`;
    }
    if (!data.stdout && !data.stderr) {
      card.innerHTML += `<div class="tool-label">(无输出)</div>`;
    }
  } else if (toolName === "read_file") {
    if (data.error) {
      card.innerHTML = `
        <div class="tool-header">
          <span><span class="tool-icon">📄</span>文件读取</span>
          <span class="tool-badge error">失败</span>
        </div>
        <div class="tool-label">${escapeHtml(data.file_path || "")}</div>
        <pre class="cmd-block stderr">${escapeHtml(data.error)}</pre>
      `;
    } else if (data.is_directory) {
      card.innerHTML = `
        <div class="tool-header">
          <span><span class="tool-icon">📁</span>目录列表</span>
          <span class="tool-badge success">${data.lines || 0} 项</span>
        </div>
        <div class="tool-label">${escapeHtml(data.file_path || "")}</div>
        <pre class="dir-list">${escapeHtml(data.content || "")}</pre>
      `;
    } else {
      const truncated = data.truncated ? " (截断)" : "";
      card.innerHTML = `
        <div class="tool-header">
          <span><span class="tool-icon">📄</span>文件内容</span>
          <span class="tool-badge success">${data.lines || 0}/${data.total_lines || "?"} 行${truncated}</span>
        </div>
        <div class="tool-label">${escapeHtml(data.file_path || "")} · ${(data.size_bytes || 0) < 1024 ? (data.size_bytes || 0) + "B" : ((data.size_bytes || 0) / 1024).toFixed(1) + "KB"}</div>
        <pre class="file-block">${escapeHtml(data.content || "")}</pre>
      `;
    }
  } else if (toolName === "write_file") {
    const isSuccess = data.status === "success";
    const badgeClass = isSuccess ? "success" : "error";
    const badgeText = isSuccess ? `写入 ${data.bytes_written || 0} 字节` : "失败";
    card.innerHTML = `
      <div class="tool-header">
        <span><span class="tool-icon">✏️</span>文件写入 (${escapeHtml(data.mode || "write")})</span>
        <span class="tool-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
      </div>
      <div class="tool-label">${escapeHtml(data.file_path || "")}</div>
    `;
    if (data.error) {
      card.innerHTML += `<pre class="cmd-block stderr">${escapeHtml(data.error)}</pre>`;
    }
    if (data.note) {
      card.innerHTML += `<div class="tool-label" style="color:var(--muted)">${escapeHtml(data.note)}</div>`;
    }
  }

  hostMessage.appendChild(card);
}

async function sendQuestion(event) {
  event.preventDefault();
  const input = $("questionInput");
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  addMessage("user", question, new Date().toISOString());
  const pending = document.createElement("div");
  pending.className = "message agent";
  const thinkSpan = document.createElement("span");
  thinkSpan.className = "think-text";
  const replySpan = document.createElement("span");
  replySpan.className = "reply-text";
  pending.appendChild(thinkSpan);
  pending.appendChild(replySpan);
  $("chatMessages").appendChild(pending);
  setStatus("生成中");
  $("sendBtn").disabled = true;

  try {
    const response = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        session_id: state.sessionId || null,
        document_id: state.activeDocumentId || null,
        top_k: Number($("topKInput").value || 4),
        model: state.currentModel || null,
        provider: state.currentProvider || null,
        library: state.currentLibrary,
        permission_mode: state.permissionMode,
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.message || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let metadata = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      let eventType = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const payload = JSON.parse(line.slice(6));
          if (eventType === "meta") {
            setActiveSessionId(payload.session_id);
          } else if (eventType === "agent_status") {
            setStatus(payload.text || `Agent 思考中 · 第 ${payload.iteration} 轮`);
          } else if (eventType === "thought") {
            thinkSpan.textContent += `💭 ${payload.text}\n`;
            pending.scrollIntoView({ block: "end" });
          } else if (eventType === "error_detail") {
            thinkSpan.textContent += `⚠️ ${payload.message}\n`;
            pending.scrollIntoView({ block: "end" });
          } else if (eventType === "tool_call") {
            thinkSpan.textContent += `\n🔧 ${payload.tool}(${JSON.stringify(payload.args)})\n`;
            // 记录最近一次工具名，用于 tool_result 渲染
            pending._lastToolName = payload.tool;
            pending.scrollIntoView({ block: "end" });
          } else if (eventType === "tool_result") {
            renderToolResult(pending, pending._lastToolName || "", payload);
            pending._lastToolName = "";
            pending.scrollIntoView({ block: "end" });
          } else if (eventType === "sources") {
            renderSources(payload.sources || []);
          } else if (eventType === "operation") {
            renderOperationRequest(payload, pending);
            $("usedTools").textContent = "operation_proposal";
          } else if (eventType === "tools_done") {
            $("usedTools").textContent = (payload.tools || []).join(", ") || "-";
            setStatus("生成回答中");
          } else if (eventType === "token") {
            replySpan.textContent += payload.token;
            pending.scrollIntoView({ block: "end" });
          } else if (eventType === "done") {
            setActiveSessionId(payload.session_id || state.sessionId);
          }
          eventType = "";
        }
      }
    }

    if (!pending.textContent.trim()) {
      replySpan.textContent = "无回答";
    }
    pending.appendChild(makeCopyBtn(pending));
    // 更新检索范围显示（带上库名）
    const libName = LIB_NAMES[state.currentLibrary] || state.currentLibrary;
    $("activeDocument").textContent = state.activeDocumentId
      ? `${libName} · ${state.activeDocumentName}`
      : `${libName} · 全部文档`;
    loadSessions().then(() => {
      updateConversationLabel();
      renderSessions();
    }).catch(() => {});
    setStatus("就绪");
  } catch (error) {
    if (!replySpan.textContent && !thinkSpan.textContent) {
      replySpan.textContent = error.message;
    }
    pending.classList.add("error");
    setStatus("请求失败", true);
  } finally {
    $("sendBtn").disabled = false;
  }
}

/* ---------- 模型选择 ---------- */

async function loadModels() {
  try {
    const data = await api("/models");
    state.models = data.models || [];
    // 兼容旧格式（字符串数组）
    if (state.models.length && typeof state.models[0] === "string") {
      state.models = state.models.map(m => ({ id: m, provider: "", label: m }));
    }
    state.currentModel = data.current || (state.models[0]?.id || "");
    state.currentProvider = state.models.find(m => m.id === state.currentModel)?.provider || "";
  } catch {
    state.models = [];
  }
  renderModelSelect();
}

function renderModelSelect() {
  const select = $("modelSelect");
  if (!state.models.length) {
    select.innerHTML = '<option>无模型</option>';
    return;
  }

  // 按 provider 分组
  const groups = { ollama: [], deepseek: [], openai: [], qwen: [], other: [] };
  for (const m of state.models) {
    const p = m.provider || "other";
    (groups[p] || groups.other).push(m);
  }

  const labels = { ollama: "本地 (Ollama)", deepseek: "DeepSeek", openai: "OpenAI", qwen: "Qwen", other: "其他" };
  let html = "";
  for (const [provider, models] of Object.entries(groups)) {
    if (!models.length) continue;
    html += `<optgroup label="${labels[provider] || provider}">`;
    for (const m of models) {
      html += `<option value="${escapeHtml(m.id)}" data-provider="${escapeHtml(m.provider)}" ${m.id === state.currentModel ? "selected" : ""}>${escapeHtml(m.label || m.id)}</option>`;
    }
    html += "</optgroup>";
  }
  select.innerHTML = html || '<option>无模型</option>';

  select.addEventListener("change", () => {
    state.currentModel = select.value;
    const opt = select.selectedOptions[0];
    state.currentProvider = opt?.dataset?.provider || "";
  });
  // 初始化当前 provider
  const selOpt = select.selectedOptions[0];
  state.currentProvider = selOpt?.dataset?.provider || "";
}

/* ---------- 重名处理对话框 ---------- */

function showDupDialog(dupNames) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "dup-overlay";
    overlay.innerHTML = `
      <div class="dup-dialog">
        <h3>${dupNames.length} 个文件已存在</h3>
        <div class="dup-list">${dupNames.map((n) => `<div>· ${escapeHtml(n)}</div>`).join("")}</div>
        <div class="dup-actions">
          <button class="dup-btn primary" data-action="overwrite">全部覆盖</button>
          <button class="dup-btn" data-action="skip">全部跳过</button>
          <button class="dup-btn" data-action="keep">全部保留（副本）</button>
        </div>
        <button class="dup-close" data-action="cancel">取消</button>
      </div>`;
    document.body.appendChild(overlay);

    overlay.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        overlay.remove();
        resolve(action === "cancel" ? null : action);
      });
    });
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) { overlay.remove(); resolve(null); }
    });
  });
}

/* ---------- 内联确认弹窗 ---------- */

function showConfirmPopup(anchor, onConfirm) {
  // 移除已有的弹窗
  document.querySelectorAll(".confirm-popup").forEach((p) => p.remove());

  const popup = document.createElement("div");
  popup.className = "confirm-popup";
  popup.innerHTML = `
    <span class="confirm-text">确认删除？</span>
    <button class="confirm-yes">删除</button>
    <button class="confirm-no">取消</button>
  `;
  popup.querySelector(".confirm-yes").addEventListener("click", () => {
    popup.remove();
    onConfirm();
  });
  popup.querySelector(".confirm-no").addEventListener("click", () => popup.remove());

  // 定位在 anchor 旁边
  const rect = anchor.getBoundingClientRect();
  popup.style.position = "fixed";
  popup.style.top = `${rect.bottom + 4}px`;
  popup.style.right = `${window.innerWidth - rect.right}px`;

  document.body.appendChild(popup);

  // 点击外部关闭
  const close = (e) => {
    if (!popup.contains(e.target) && e.target !== anchor) {
      popup.remove();
      document.removeEventListener("click", close);
    }
  };
  setTimeout(() => document.addEventListener("click", close), 0);
}

/* ---------- 拖拽调节面板宽度 ---------- */

function setupResizeHandles() {
  const root = document.documentElement;

  // 左右拖拽：调节左右面板宽度
  document.querySelectorAll(".resize-handle").forEach((handle) => {
    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener("mousedown", (e) => {
      dragging = true;
      startX = e.clientX;
      handle.classList.add("active");
      const side = handle.dataset.resize;
      const panel = side === "left" ? $("leftPanel") : $("insightPanel");
      startWidth = panel.getBoundingClientRect().width;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const side = handle.dataset.resize;
      // 左把手：向右拖增大左侧面板；右把手：向右拖缩小右侧面板
      const delta = side === "right" ? -(e.clientX - startX) : e.clientX - startX;
      const minW = side === "left" ? 180 : 220;
      const newWidth = Math.max(minW, startWidth + delta);
      const varName = side === "left" ? "--left-w" : "--right-w";
      root.style.setProperty(varName, `${newWidth}px`);
    });

    document.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("active");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    });
  });

  // 上下拖拽：调节会话/文档区域高度
  const hHandle = document.getElementById("sessionDocHandle");
  if (hHandle) {
    let dragging = false;
    let startY = 0;
    let startH = 0;

    hHandle.addEventListener("mousedown", (e) => {
      dragging = true;
      startY = e.clientY;
      hHandle.classList.add("active");
      startH = $("sessionSection").getBoundingClientRect().height;
      document.body.style.cursor = "row-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const newH = Math.max(40, startH + (e.clientY - startY));
      root.style.setProperty("--session-h", `${newH}px`);
    });

    document.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      hHandle.classList.remove("active");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    });
  }
}

/* ---------- 启动 ---------- */

function boot() {
  setupResizeHandles();
  setupCollapsibleSections();

  $("fileInput").addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    event.target.value = ""; // 允许重复选同一个文件

    // 检查重名
    const existingNames = new Set(state.documents.map((d) => d.filename));
    const dupFiles = files.filter((f) => existingNames.has(f.name));
    const newFiles = files.filter((f) => !existingNames.has(f.name));

    let dupAction = null; // "overwrite" | "skip" | "keep" | null(逐个问)
    if (dupFiles.length) {
      dupAction = await showDupDialog(dupFiles.map((f) => f.name));
      if (!dupAction) return; // 用户关闭了对话框
    }

    const allFiles = [...newFiles];
    if (dupAction === "overwrite" || dupAction === "keep") {
      allFiles.push(...dupFiles);
    }
    // "skip" 不添加任何重复文件

    if (!allFiles.length) {
      $("uploadState").textContent = "无文件需要上传";
      return;
    }

    $("uploadState").textContent = `上传 ${allFiles.length} 个文件...`;
    let ok = 0, fail = 0;
    for (const file of allFiles) {
      try {
        const isDup = existingNames.has(file.name);
        const needOverwrite = isDup && dupAction === "overwrite";
        const needKeep = isDup && dupAction === "keep";
        if (needKeep) {
          // 保留两份：修改文件名
          const newFile = new File([file], file.name.replace(/(\.[^.]+)$/, "_副本$1"), { type: file.type });
          await uploadDocument(newFile, false);
        } else {
          await uploadDocument(file, needOverwrite);
        }
        ok++;
        $("uploadState").textContent = `已上传 ${ok}/${allFiles.length}`;
      } catch (e) {
        fail++;
        setStatus(`${file.name}: ${e.message}`, true);
      }
    }
    await loadDocuments();
    $("uploadState").textContent = `完成: ${ok} 成功` + (fail ? `, ${fail} 失败` : "");
    if (ok) {
      state.activeDocumentId = "";
      state.activeDocumentName = "全部文档";
    }
  });
  $("newSessionBtn").addEventListener("click", newSession);
  $("librarySelect").addEventListener("change", () => {
    state.currentLibrary = $("librarySelect").value;
    localStorage.setItem("kb_library", state.currentLibrary);
    state.activeDocumentId = "";
    state.activeDocumentName = "全部文档";
    state.sessionDocs = [];
    restoreActiveSessionId();
    updateSessionDocs();
    const libName = LIB_NAMES[state.currentLibrary] || state.currentLibrary;
    $("activeDocument").textContent = `${libName} · 全部文档`;
    showDocContentPlaceholder();
    $("chatMessages").innerHTML = "";
    addMessage("agent", pickGreeting());
    loadDocuments().catch(() => {});
    loadSessions().then(() => {
      const session = currentSession();
      if (state.sessionId && session) {
        state.sessionDocs = session.documents || [];
        updateSessionDocs(session.library);
        renderSessions();
        loadSessionHistory(state.sessionId).catch(() => {});
      } else if (state.sessionId) {
        setActiveSessionId("");
        renderSessions();
      }
    }).catch(() => {});
  });
  $("permissionMode").value = state.permissionMode;
  $("permissionMode").addEventListener("change", () => {
    state.permissionMode = $("permissionMode").value;
    localStorage.setItem("permission_mode", state.permissionMode);
    setStatus(state.permissionMode === "approve_execute" ? "批准执行模式" : "只读模式");
  });
  $("chatForm").addEventListener("submit", sendQuestion);

  // 思考/极速 切换
  $("thinkToggle").addEventListener("click", () => {
    state.thinkMode = !state.thinkMode;
    const btn = $("thinkToggle");
    btn.textContent = state.thinkMode ? "思考" : "极速";
    btn.classList.toggle("on", state.thinkMode);
  });

  // Enter 发送，Shift+Enter 换行，输入法激活时不触发
  let composing = false;
  $("questionInput").addEventListener("compositionstart", () => { composing = true; });
  $("questionInput").addEventListener("compositionend", () => { composing = false; });
  $("questionInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !composing) {
      e.preventDefault();
      $("chatForm").dispatchEvent(new Event("submit"));
    }
  });

  addMessage("agent", pickGreeting());
  renderSources([]);
  $("librarySelect").value = state.currentLibrary;
  restoreActiveSessionId();
  $("activeDocument").textContent = `${LIB_NAMES[state.currentLibrary]} · 全部文档`;
  loadDocuments().catch(() => setStatus("文档加载失败", true));
  loadSessions().then(() => {
    const session = currentSession();
    if (state.sessionId && session) {
      state.sessionDocs = session.documents || [];
      updateSessionDocs(session.library);
      renderSessions();
      loadSessionHistory(state.sessionId).catch(() => {});
    } else if (state.sessionId) {
      setActiveSessionId("");
      renderSessions();
    }
  }).catch(() => {});
  loadModels();
}

boot();
