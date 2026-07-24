/* ============================================================
   JATAYU OS — app.js
   Client-side routing, WebSocket pipeline, voice loop, and the
   orb state machine. Ambient starfield & waveform initializers.
   ============================================================ */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const VIEWS = [
  "dashboard", "battleground", "chat",
  "agents", "integrations", "settings",
];

const ORB_STATES = ["IDLE", "LISTENING", "THINKING", "SPEAKING", "ALERT"];

const VOICE_STATUS_TEXT = {
  IDLE: "Tap orb or hold [ Space ] to speak",
  LISTENING: "Listening — release space or tap again when done",
  THINKING: "Thinking",
  SPEAKING: "Speaking",
  ALERT: "Attention needed",
};

const CLUSTER_KEYWORDS = {
  google: ["gmail", "calendar", "drive", "docs", "sheets", "google"],
  comms: ["telegram", "slack", "discord", "whatsapp"],
  knowledge: ["obsidian", "knowledge", "vault"],
  voice: ["whisper", "elevenlabs", "voice", "tts", "stt", "speech"],
};

const App = {
  ws: null,
  currentConversationId: null,
  conversation_mode: "chat",

  wsReady: false,
  wsRetries: 0,
  orbState: "IDLE",
  killSwitch: false,
  status: null,
  panels: null,
  agentsRaw: null,
  pluginsRaw: null,
  clusterHealth: null,

  bg: null,
  bgReady: null,

  mediaRecorder: null,
  recChunks: [],
  recStream: null,
  recTarget: null,
  audioCtx: null,
  analyser: null,
  analyserData: null,
  ttsAudio: null,
  ttsUrl: null,
  fallbackSpeaking: false,

  streamBuf: "",
  chatStreamEl: null,
  thinkingTimer: null,
  alertFlashTimer: null,
};

/* ============================================================
   ROUTING
   ============================================================ */

function route() {
  let view = location.hash.slice(1) || "dashboard";
  // fallback handled below
  if (!VIEWS.includes(view)) view = "dashboard";

  $$(".view").forEach((s) => s.classList.toggle("active", s.id === "view-" + view));
  $$("#nav a[data-view]").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === view)
  );

  if (view === "battleground") {
    App.conversation_mode = "voice";
    enterBattleground();
  } else {
    App.conversation_mode = "chat";
    if (App.bg) App.bg.pause();
  }

  if (view === "dashboard" && window.initDailyContextBar) window.initDailyContextBar();
  if (view === "chat") fetchConversations();
  if (view === "agents") renderAgentsView();
  if (view === "integrations") renderIntegrationsView();
  if (view === "settings") renderSettings();
}

async function enterBattleground() {
  if (!App.bgReady) {
    App.bgReady = import("./battleground.js").then((mod) => {
      App.bg = mod.default;
      return App.bg.init({
        container: $("#bg-host"),
        getAudioLevel,
      });
    });
  }
  await App.bgReady;
  App.bg.setState(App.orbState);
  if (App.clusterHealth) App.bg.setClusterHealth(App.clusterHealth);
  App.bg.resume();
}

/* ============================================================
   ORB STATE MACHINE
   ============================================================ */

function setOrbState(state) {
  if (!ORB_STATES.includes(state)) return;
  if (App.killSwitch && state !== "ALERT") return;

  App.orbState = state;
  document.body.dataset.orbState = state;
  document.body.dataset.state = state.toLowerCase();
  if (App.bg) App.bg.setState(state);

  const statusEl = $("#bg-voice-status");
  if (statusEl) {
    statusEl.textContent =
      App.killSwitch && state === "ALERT"
        ? "Kill switch engaged. All tools are paused."
        : VOICE_STATUS_TEXT[state];
  }

  const stateLabel = $("#stateLabel");
  if (stateLabel) {
    const labels = { IDLE: '◈ Standing By ◈', LISTENING: '◈ Listening ◈', THINKING: '◈ Processing ◈', SPEAKING: '◈ Responding ◈', ALERT: '◈ Attention ◈' };
    stateLabel.textContent = labels[state] || '◈ Standing By ◈';
  }
}

/* ============================================================
   WEBSOCKET
   ============================================================ */

function connectWS() {
  const url = `ws://${location.host}/ws`;
  App.ws = new WebSocket(url);

  App.ws.onopen = () => {
    App.wsReady = true;
    App.wsRetries = 0;
    setConnBadge(true);
  };

  App.ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    switch (msg.type) {
      case "chunk": handleChunk(msg); break;
      case "done": handleDone(msg); break;
      case "panels": handlePanels(msg); break;
      case "confirm_request": handleConfirmRequest(msg); break;
    }
  };

function handleConfirmRequest(msg) {
  const container = $("#chat-thread") || document.body;
  const card = document.createElement("div");
  card.className = "confirm-card";
  card.id = `confirm-${msg.request_id}`;

  const argsStr = JSON.stringify(msg.args || {}, null, 2);
  card.innerHTML = `
    <div style="background: rgba(255, 170, 0, 0.12); border: 1px solid rgba(255, 170, 0, 0.4); border-radius: 8px; padding: 12px 16px; margin: 10px 0; font-family: sans-serif;">
      <div style="font-weight: bold; color: #ffaa00; font-size: 14px; margin-bottom: 6px;">
        🔒 Confirmation Required: ${msg.tool}
      </div>
      <div style="font-size: 12px; color: #ccc; margin-bottom: 10px;">
        ${msg.description ? msg.description + '<br>' : ''}
        <pre style="background: rgba(0,0,0,0.3); padding: 6px; border-radius: 4px; font-size: 11px; overflow-x: auto; color: #e2e8f0;">${argsStr}</pre>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <button id="btn-approve-${msg.request_id}" style="background: #22c55e; color: #fff; border: none; padding: 8px 18px; border-radius: 6px; font-weight: bold; cursor: pointer;">Approve</button>
        <button id="btn-deny-${msg.request_id}" style="background: #ef4444; color: #fff; border: none; padding: 8px 18px; border-radius: 6px; font-weight: bold; cursor: pointer;">Deny</button>
      </div>
    </div>
  `;
  container.appendChild(card);
  container.scrollTop = container.scrollHeight;

  const btnApprove = document.getElementById(`btn-approve-${msg.request_id}`);
  const btnDeny = document.getElementById(`btn-deny-${msg.request_id}`);
  if (btnApprove) btnApprove.onclick = () => respondConfirm(msg.request_id, true, card);
  if (btnDeny) btnDeny.onclick = () => respondConfirm(msg.request_id, false, card);
}

function respondConfirm(reqId, approved, cardEl) {
  if (App.wsReady && App.ws) {
    App.ws.send(JSON.stringify({
      type: "confirm_response",
      request_id: reqId,
      approved: approved
    }));
  }
  if (cardEl) {
    const inner = cardEl.querySelector("div");
    if (inner) {
      inner.style.borderColor = approved ? "#22c55e" : "#ef4444";
      inner.style.background = approved ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)";
      const actions = inner.querySelector("div:last-child");
      if (actions) {
        actions.innerHTML = `<span style="font-size: 13px; font-weight: bold; color: ${approved ? '#22c55e' : '#ef4444'}">${approved ? '✅ ACTION APPROVED & EXECUTING...' : '❌ ACTION DENIED'}</span>`;
      }
    }
  }
}

  App.ws.onclose = () => {
    App.wsReady = false;
    setConnBadge(false);
    const delay = Math.min(10000, 1000 * Math.pow(1.6, App.wsRetries++));
    setTimeout(connectWS, delay);
  };

  App.ws.onerror = () => App.ws.close();
}

function setConnBadge(ok) {
  const badge = $("#conn-badge");
  if (badge) {
    badge.textContent = ok ? "LINKED" : "OFFLINE";
    badge.className = "badge " + (ok ? "ok" : "err");
  }
  updateCoreStatusLine();
}

function sendText(text) {
  if (!App.wsReady) {
    if (App.conversation_mode === "voice") {
      $("#bg-voice-status").textContent = "Jatayu is offline. Reconnecting.";
      setOrbState("IDLE");
    }
    return false;
  }
  const payload = { text };
  if (App.currentConversationId) payload.conversation_id = App.currentConversationId;
  App.ws.send(JSON.stringify(payload));

  App.streamBuf = "";
  setOrbState("THINKING");

  clearTimeout(App.thinkingTimer);
  App.thinkingTimer = setTimeout(() => {
    if (App.orbState === "THINKING") {
      handleTurnError({ text: "No response from Jatayu. Try again." });
    }
  }, 90000);
  return true;
}

function handleChunk(msg) {
  App.streamBuf += msg.text;
  if (App.conversation_mode === "voice") {
    const el = $("#bg-assistant-text");
    if (el) {
      el.textContent = App.streamBuf;
      el.parentElement.scrollTop = el.parentElement.scrollHeight;
    }
  } else {
    if (!App.chatStreamEl) App.chatStreamEl = appendChatBubble("assistant", "");
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = App.streamBuf;
      scrollThread();
    }
  }
}

function handleDone(msg) {
  clearTimeout(App.thinkingTimer);
  App.currentConversationId = msg.conversation_id;

  if (App.conversation_mode === "voice") {
    const el = $("#bg-assistant-text");
    if (el) el.textContent = msg.text;
    speakReply(msg.text);
  } else {
    if (!App.chatStreamEl) App.chatStreamEl = appendChatBubble("assistant", "");
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = msg.text;
      App.chatStreamEl = null;
      scrollThread();
    }
    setOrbState("IDLE");
    fetchConversations();
  }

  addTimelineEntry(msg.text);
}

function handlePanels(msg) {
  App.panels = msg;
  renderPanels(msg);
  renderWorkspace();
}

function handleTurnError(msg) {
  clearTimeout(App.thinkingTimer);
  const text = msg.text || "Something went wrong.";

  if (App.conversation_mode === "voice") {
    const el = $("#bg-assistant-text");
    if (el) el.textContent = text;
  } else {
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = text;
      App.chatStreamEl = null;
    } else {
      appendChatBubble("assistant", text);
    }
  }

  if (!App.killSwitch) {
    setOrbState("ALERT");
    clearTimeout(App.alertFlashTimer);
    App.alertFlashTimer = setTimeout(() => {
      if (!App.killSwitch && App.orbState === "ALERT") setOrbState("IDLE");
    }, 4000);
  }
}

/* ============================================================
   VOICE PIPELINE
   ============================================================ */

function ensureAudioGraph() {
  if (App.audioCtx) return;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  App.audioCtx = new Ctx();
  App.ttsAudio = new Audio();
  App.ttsAudio.crossOrigin = "anonymous";
  const src = App.audioCtx.createMediaElementSource(App.ttsAudio);
  App.analyser = App.audioCtx.createAnalyser();
  App.analyser.fftSize = 512;
  App.analyserData = new Uint8Array(App.analyser.fftSize);
  src.connect(App.analyser);
  App.analyser.connect(App.audioCtx.destination);
}

function getAudioLevel() {
  if (App.fallbackSpeaking) return null;
  if (!App.analyser || !App.ttsAudio || App.ttsAudio.paused) return null;
  App.analyser.getByteTimeDomainData(App.analyserData);
  let sum = 0;
  for (let i = 0; i < App.analyserData.length; i++) {
    const v = (App.analyserData[i] - 128) / 128;
    sum += v * v;
  }
  return Math.min(1, Math.sqrt(sum / App.analyserData.length) * 3.2);
}

async function startRecording(target) {
  try {
    App.recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    if (target === "voice") {
      const statusEl = $("#bg-voice-status");
      if (statusEl) statusEl.textContent = "Microphone unavailable. Check browser permissions.";
    }
    return false;
  }
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";
  App.recChunks = [];
  App.recTarget = target;
  App.mediaRecorder = new MediaRecorder(App.recStream, { mimeType: mime });
  App.mediaRecorder.ondataavailable = (e) => {
    if (e.data.size) App.recChunks.push(e.data);
  };
  App.mediaRecorder.start();
  if (target === "voice") setOrbState("LISTENING");
  return true;
}

function stopRecording() {
  return new Promise((resolve) => {
    if (!App.mediaRecorder || App.mediaRecorder.state === "inactive") {
      resolve(null);
      return;
    }
    App.mediaRecorder.onstop = () => {
      App.recStream.getTracks().forEach((t) => t.stop());
      resolve(new Blob(App.recChunks, { type: "audio/webm" }));
    };
    App.mediaRecorder.stop();
  });
}

async function transcribe(blob) {
  const res = await fetch("/api/transcribe", {
    method: "POST",
    headers: { "Content-Type": "audio/webm" },
    body: blob,
  });
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return (data.transcript || "").trim();
}

async function toggleMic() {
  ensureAudioGraph();
  if (App.audioCtx && App.audioCtx.state === "suspended") App.audioCtx.resume();

  switch (App.orbState) {
    case "IDLE":
      await startRecording("voice");
      break;

    case "LISTENING": {
      setOrbState("THINKING");
      const statusEl = $("#bg-voice-status");
      if (statusEl) statusEl.textContent = "Transcribing voice";
      const blob = await stopRecording();
      if (!blob || blob.size === 0) {
        setOrbState("IDLE");
        return;
      }
      try {
        const transcript = await transcribe(blob);
        if (!transcript) {
          setOrbState("IDLE");
          if (statusEl) statusEl.textContent = "Nothing heard. Tap orb to try again.";
          return;
        }
        const userLine = $("#bg-user-line");
        const asstText = $("#bg-assistant-text");
        if (userLine) userLine.textContent = transcript;
        if (asstText) asstText.textContent = "";
        sendText(transcript);
      } catch {
        setOrbState("IDLE");
        if (statusEl) statusEl.textContent = "Transcription failed. Tap orb to try again.";
      }
      break;
    }

    case "SPEAKING":
      cancelSpeech();
      break;
  }
}

async function speakReply(text) {
  setOrbState("SPEAKING");
  try {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const ttsError = res.headers.get("X-TTS-Error");
    const buf = await res.arrayBuffer();
    if (!res.ok || ttsError || buf.byteLength === 0) {
      _speakWithBrowserFallback(text);
      return;
    }
    ensureAudioGraph();
    const blob = new Blob([buf], { type: "audio/mpeg" });
    if (App.ttsUrl) URL.revokeObjectURL(App.ttsUrl);
    App.ttsUrl = URL.createObjectURL(blob);

    if (App.ttsAudio) {
      App.ttsAudio.src = App.ttsUrl;
      App.ttsAudio.onended = () => setOrbState("IDLE");
      App.ttsAudio.onerror = () => _speakWithBrowserFallback(text);
      App.ttsAudio.play().catch(() => _speakWithBrowserFallback(text));
    } else {
      const el = new Audio(App.ttsUrl);
      el.onended = () => setOrbState("IDLE");
      el.play().catch(() => _speakWithBrowserFallback(text));
    }
  } catch {
    _speakWithBrowserFallback(text);
  }
}

function _speakWithBrowserFallback(text) {
  if (!("speechSynthesis" in window)) {
    setOrbState("IDLE");
    return;
  }
  App.fallbackSpeaking = true;
  const utter = new SpeechSynthesisUtterance(text);
  utter.onend = utter.onerror = () => {
    App.fallbackSpeaking = false;
    setOrbState("IDLE");
  };
  window.speechSynthesis.speak(utter);
}

function cancelSpeech() {
  if (App.ttsAudio && !App.ttsAudio.paused) App.ttsAudio.pause();
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  App.fallbackSpeaking = false;
  setOrbState("IDLE");
}

/* ============================================================
   CHAT VIEW
   ============================================================ */

async function fetchConversations() {
  try {
    const res = await fetch("/api/conversations?limit=50");
    const data = await res.json();
    renderConversationList(data.conversations || []);
  } catch {
    /* sidebar stays as-is while offline */
  }
}

function renderConversationList(conversations) {
  const list = $("#conv-list");
  if (!list) return;
  list.innerHTML = "";
  for (const conv of conversations) {
    const li = document.createElement("li");
    li.dataset.id = conv.id;
    if (conv.id === App.currentConversationId) li.classList.add("active");
    li.innerHTML =
      `<div class="conv-title">${escapeHtml(conv.title || "Untitled")}</div>` +
      `<div class="conv-time">${relTime(conv.updated_at)}</div>`;
    li.addEventListener("click", () => loadConversation(conv.id));
    list.appendChild(li);
  }
}

async function loadConversation(id) {
  const res = await fetch(`/api/conversations/${id}`);
  const data = await res.json();
  App.currentConversationId = id;
  App.chatStreamEl = null;

  const thread = $("#chat-thread");
  if (!thread) return;
  thread.innerHTML = "";
  for (const m of data.messages || []) {
    if (m.role !== "user" && m.role !== "assistant") continue;
    appendChatBubble(m.role, m.content);
  }
  scrollThread();
  $$("#conv-list li").forEach((li) =>
    li.classList.toggle("active", li.dataset.id === id)
  );
}

function newChat() {
  App.currentConversationId = null;
  App.chatStreamEl = null;
  const thread = $("#chat-thread");
  if (thread) {
    thread.innerHTML =
      '<div class="chat-empty" id="chat-empty"><p>Ask anything, or give Jatayu something to do.</p></div>';
  }
  $$("#conv-list li").forEach((li) => li.classList.remove("active"));
  const input = $("#chat-input");
  if (input) input.focus();
}

function appendChatBubble(role, text) {
  const empty = $("#chat-empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML =
    role === "assistant"
      ? '<span class="avatar" aria-hidden="true"></span><div class="bubble"></div>'
      : '<div class="bubble"></div>';
  div.querySelector(".bubble").textContent = text;
  const thread = $("#chat-thread");
  if (thread) thread.appendChild(div);
  return div;
}

function scrollThread() {
  const t = $("#chat-thread");
  if (t) t.scrollTop = t.scrollHeight;
}

function sendChatMessage() {
  const input = $("#chat-input");
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  appendChatBubble("user", text);
  scrollThread();
  App.chatStreamEl = null;
  if (sendText(text)) input.value = "";
}

async function toggleChatMic() {
  const btn = $("#btn-chat-mic");
  if (!btn) return;
  if (App.mediaRecorder && App.mediaRecorder.state === "recording" && App.recTarget === "chat") {
    btn.classList.remove("recording");
    const blob = await stopRecording();
    if (!blob) return;
    try {
      const transcript = await transcribe(blob);
      if (transcript) {
        const input = $("#chat-input");
        if (input) {
          input.value = (input.value ? input.value + " " : "") + transcript;
          input.focus();
        }
      }
    } catch {
      /* leave input untouched */
    }
  } else {
    const ok = await startRecording("chat");
    if (ok) btn.classList.add("recording");
  }
}

/* ============================================================
   STATUS / AGENTS POLLING
   ============================================================ */

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    App.status = status;

    const wasKilled = App.killSwitch;
    App.killSwitch = !!status.kill_switch;

    setText("#bg-model", status.model || "—");
    setText("#bg-model-footer", status.model || "—");
    setText("#bg-tools", String(status.tools ?? "—"));
    setText("#bg-kill", App.killSwitch ? "ENGAGED" : "OFF");
    setText("#stat-status", (status.status || "—").toUpperCase());

    const badge = $("#status-badge");
    if (badge) {
      badge.textContent = (status.status || "—").toUpperCase();
      badge.className =
        "badge " +
        (App.killSwitch ? "err" : status.status === "optimal" ? "ok" : "warn");
    }

    updateCoreStatusLine();

    if (App.killSwitch && !wasKilled) {
      App.killSwitch = false;
      setOrbState("ALERT");
      App.killSwitch = true;
    } else if (!App.killSwitch && wasKilled) {
      setOrbState("IDLE");
    }
  } catch {
    /* status endpoint offline */
  }
}

function updateCoreStatusLine() {
  const line = $("#bg-status-line");
  const dash = $("#dash-status-line");
  let stateWord;
  if (App.killSwitch) stateWord = "PAUSED";
  else if (!App.wsReady) stateWord = "STANDBY";
  else if (App.status && App.status.status !== "optimal")
    stateWord = App.status.status.toUpperCase();
  else stateWord = "ACTIVE";
  if (line) line.textContent = `ADVANCED AGI — ${stateWord}`;
  if (dash) dash.textContent = `SYSTEM ${stateWord}`;
}

const HEALTH_RANK = { healthy: 0, connected: 0, active: 0, configured: 0, available: 0, degraded: 1 };

async function pollAgents() {
  try {
    const pluginsRes = await fetch("/api/plugins");
    App.pluginsRaw = await pluginsRes.json();
    App.agentsRaw = {};

    App.clusterHealth = computeClusterHealth(App.agentsRaw, App.pluginsRaw);
    if (App.bg) App.bg.setClusterHealth(App.clusterHealth);

    renderAgentsView();
    renderIntegrationsView();
  } catch {
    /* leave last known state */
  }
}

function computeClusterHealth(agents, plugins) {
  const worst = { google: 0, comms: 0, knowledge: 0, voice: 0 };
  const entries = [
    ...Object.entries(agents || {}),
    ...Object.entries(plugins || {}),
  ];
  for (const [name, info] of entries) {
    const key = name.toLowerCase();
    const status = String(info.status || "healthy").toLowerCase();
    const rank = HEALTH_RANK[status] ?? 0;
    for (const [cluster, words] of Object.entries(CLUSTER_KEYWORDS)) {
      if (words.some((w) => key.includes(w))) {
        worst[cluster] = Math.max(worst[cluster], rank);
        break;
      }
    }
  }
  const label = ["healthy", "degraded", "failed"];
  return Object.fromEntries(
    Object.entries(worst).map(([k, v]) => [k, label[v]])
  );
}



async function loadDashboard() {
  try {
    const [reminders, schedule, drafts, memory] = await Promise.all(
      ["reminders", "schedule", "drafts", "memory"].map((p) =>
        fetch(`/api/${p}`).then((r) => r.json())
      )
    );
    renderPanels({
      reminders: reminders.reminders,
      schedule,
      drafts: drafts.drafts,
      memory: memory.memories,
    });
    renderWorkspace();
  } catch {
    /* panels stay empty while offline */
  }
}

function renderPanels(data) {
  App.panels = data;

  const reminders = data.reminders || [];
  fillList(
    "#panel-reminders",
    reminders.slice(0, 5).map(
      (r) =>
        `<li><span>${escapeHtml(r.text)}</span><span class="meta">${escapeHtml(r.due_time || "")}</span></li>`
    ),
    "Nothing pending."
  );

  const tasks = (data.schedule && data.schedule.tasks) || [];
  fillList(
    "#panel-schedule",
    tasks.map(
      (t) =>
        `<li><i class="prio ${escapeHtml(t.priority)}"></i><span>${escapeHtml(t.description)}</span></li>`
    ),
    "No tasks scheduled today."
  );
  setText("#stat-tasks", String(tasks.length));

  const drafts = data.drafts || [];
  fillList(
    "#panel-drafts",
    drafts.map((d) => `<li><span>${escapeHtml(d.text || d.summary || JSON.stringify(d))}</span></li>`),
    "No drafts waiting for review."
  );

  const memories = data.memory || [];
  fillList(
    "#panel-memory",
    memories.slice(0, 6).map(
      (m) =>
        `<li><span>${escapeHtml(m.fact)}</span><span class="meta">${escapeHtml(m.category || "")}</span></li>`
    ),
    "Nothing remembered yet."
  );
  setText("#stat-memories", String(memories.length));
}

function addTimelineEntry(text) {
  const timeline = $("#timeline");
  if (!timeline) return;
  const empty = timeline.querySelector(".empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  const snippet = text.length > 90 ? text.slice(0, 90) + "…" : text;
  li.innerHTML = `<span>${escapeHtml(snippet)}</span><span class="meta">${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>`;
  timeline.prepend(li);
  while (timeline.children.length > 12) timeline.lastChild.remove();
}

/* ============================================================
   SECONDARY VIEWS
   ============================================================ */

function renderAgentsView() {
  if (!App.agentsRaw) return;
  fillList(
    "#agents-list",
    Object.entries(App.agentsRaw).map(([name, info]) => {
      const s = String(info.status || "connected").toLowerCase();
      const cls = s === "connected" || s === "healthy" ? "healthy" : s === "degraded" ? "degraded" : "healthy";
      return `<li><i class="health-dot ${cls}"></i><span>${escapeHtml(info.display_name || name)}</span><span class="meta">${escapeHtml(s)}</span></li>`;
    }),
    "No agents registered."
  );
}

function renderIntegrationsView() {
  const googleList = [
    { name: "Google Workspace Core", status: "connected" },
    { name: "Gmail Integration", status: "connected" },
    { name: "Google Calendar", status: "connected" },
    { name: "Google Drive & Docs", status: "connected" },
  ];
  fillList(
    "#cluster-google",
    googleList.map(item => `<li><i class="health-dot healthy"></i><span>${escapeHtml(item.name)}</span><span class="meta">connected</span></li>`),
    "Google Workspace idle."
  );

  const commsList = [
    { name: "Telegram Bot Provider", status: "connected" },
    { name: "WhatsApp Gateway (Paused)", status: "standby" },
    { name: "Slack / Discord Dispatcher", status: "configured" },
  ];
  fillList(
    "#cluster-comms",
    commsList.map(item => `<li><i class="health-dot ${item.status === 'connected' ? 'healthy' : 'degraded'}"></i><span>${escapeHtml(item.name)}</span><span class="meta">${escapeHtml(item.status)}</span></li>`),
    "Comms Layer idle."
  );

  const knowledgeList = [
    { name: "Obsidian Local Vault", status: "connected" },
  ];
  fillList(
    "#cluster-knowledge",
    knowledgeList.map(item => `<li><i class="health-dot healthy"></i><span>${escapeHtml(item.name)}</span><span class="meta">${escapeHtml(item.status)}</span></li>`),
    "Knowledge Vault idle."
  );

  const voiceList = [
    { name: "OpenAI Whisper STT", status: "connected" },
    { name: "ElevenLabs Voice Synthesizer", status: "connected" },
  ];
  fillList(
    "#cluster-voice",
    voiceList.map(item => `<li><i class="health-dot healthy"></i><span>${escapeHtml(item.name)}</span><span class="meta">${escapeHtml(item.status)}</span></li>`),
    "Voice Engine idle."
  );

  const coreList = [
    { name: "Hermes Coding & Desktop Exec", status: "connected" },
    { name: "Tavily / ArXiv Web Search", status: "connected" },
    { name: "System Tool Registry", status: "connected" },
  ];
  fillList(
    "#cluster-core",
    coreList.map(item => `<li><i class="health-dot healthy"></i><span>${escapeHtml(item.name)}</span><span class="meta">${escapeHtml(item.status)}</span></li>`),
    "Core Execution idle."
  );
}

function renderWorkspace() {
  if (!App.panels) return;
  const { reminders = [], schedule = {}, drafts = [] } = App.panels;
  fillList(
    "#ws-reminders",
    reminders.map(
      (r) => `<li><span>${escapeHtml(r.text)}</span><span class="meta">${escapeHtml(r.due_time || "")}</span></li>`
    ),
    "Nothing pending."
  );
  fillList(
    "#ws-schedule",
    (schedule.tasks || []).map(
      (t) => `<li><i class="prio ${escapeHtml(t.priority)}"></i><span>${escapeHtml(t.description)}</span></li>`
    ),
    "No tasks scheduled today."
  );
  fillList(
    "#ws-drafts",
    drafts.map((d) => `<li><span>${escapeHtml(d.text || d.summary || JSON.stringify(d))}</span></li>`),
    "No drafts waiting for review."
  );
}

async function renderSettings() {
  try {
    const status = await fetch("/api/status").then((r) => r.json());
    const infoEl = $("#settings-info");
    if (!infoEl) return;
    infoEl.innerHTML = [
      ["Model", status.model],
      ["Tools available", status.tools],
      ["Kill switch", status.kill_switch ? "Engaged" : "Off"],
    ]
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`)
      .join("");
  } catch {
    /* keep loading placeholder */
  }
}

/* ============================================================
   STARFIELD CANVAS & WAVEFORM VISUALIZER
   ============================================================ */

function initStarfield() {
  const sc = document.getElementById('stars');
  if (!sc) return;
  const sx = sc.getContext('2d');
  let stars = [];
  function sizeStars() {
    sc.width = window.innerWidth;
    sc.height = window.innerHeight;
    stars = Array.from({ length: 160 }, () => ({
      x: Math.random() * sc.width,
      y: Math.random() * sc.height,
      r: Math.random() * 1.4 + 0.2,
      p: Math.random() * Math.PI * 2,
      s: 0.5 + Math.random(),
    }));
  }
  sizeStars();
  window.addEventListener('resize', sizeStars);
  (function loop(t) {
    if (document.hidden) {
      requestAnimationFrame(loop);
      return;
    }
    sx.clearRect(0, 0, sc.width, sc.height);
    for (const st of stars) {
      const a = 0.25 + 0.55 * Math.abs(Math.sin(t / 1000 * st.s + st.p));
      sx.fillStyle = `rgba(245, 199, 106, ${a})`;
      sx.beginPath();
      sx.arc(st.x, st.y, st.r, 0, 7);
      sx.fill();
    }
    requestAnimationFrame(loop);
  })(0);
}

function initWaveform() {
  const wc = document.getElementById('waveform');
  if (!wc) return;
  const wx = wc.getContext('2d');
  function sizeWave() {
    wc.width = wc.clientWidth * (window.devicePixelRatio || 1);
    wc.height = wc.clientHeight * (window.devicePixelRatio || 1);
  }
  sizeWave();
  window.addEventListener('resize', sizeWave);
  (function wave(t) {
    if (document.hidden || location.hash !== '#battleground') {
      requestAnimationFrame(wave);
      return;
    }
    wx.clearRect(0, 0, wc.width, wc.height);
    const st = App.orbState.toLowerCase();
    const amp = st === 'listening' ? 0.9 : st === 'speaking' ? 0.7 : st === 'thinking' ? 0.4 : 0.15;
    wx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--orb') || '#f5c76a';
    wx.lineWidth = 2;
    wx.beginPath();
    for (let x = 0; x < wc.width; x++) {
      const y = wc.height / 2 + Math.sin(x / 22 + t / 140) * Math.sin(x / 90 + t / 300) * (wc.height / 2) * amp * Math.sin(t / 220 + x / 60);
      x ? wx.lineTo(x, y) : wx.moveTo(x, y);
    }
    wx.stroke();
    requestAnimationFrame(wave);
  })(0);
}

/* ============================================================
   HELPERS
   ============================================================ */

function fillList(sel, items, emptyText) {
  const el = $(sel);
  if (!el) return;
  el.innerHTML = items.length
    ? items.join("")
    : `<li class="empty">${emptyText}</li>`;
}

function setText(sel, text) {
  const el = $(sel);
  if (el) el.textContent = text;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function relTime(iso) {
  const then = new Date(iso);
  if (isNaN(then)) return "";
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0)
    return "Today " + then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return then.toLocaleDateString();
}

/* ============================================================
   BOOT
   ============================================================ */

function bindEvents() {
  window.addEventListener("hashchange", route);

  const navToggle = $("#nav-toggle");
  if (navToggle) {
    navToggle.addEventListener("click", () => {
      const nav = $("#nav");
      if (!nav) return;
      const isCollapsed = nav.classList.toggle("collapsed");
      localStorage.setItem("sidebar_collapsed", isCollapsed ? "true" : "false");
    });
  }

  const orbBtn = $("#orb-button");
  if (orbBtn) orbBtn.addEventListener("click", toggleMic);

  const micBtnEngage = $("#micBtn");
  if (micBtnEngage) micBtnEngage.addEventListener("click", toggleMic);

  // No longer needed: btnRefreshBrief

  // Push-to-talk Spacebar
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      if (location.hash === "#battleground" || App.conversation_mode === "voice") {
        e.preventDefault();
        if (App.orbState === "IDLE") toggleMic();
      }
    }
  });
  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" && (location.hash === "#battleground" || App.conversation_mode === "voice")) {
      if (App.orbState === "LISTENING") toggleMic();
    }
  });

  const btnNewChat = $("#btn-new-chat");
  if (btnNewChat) btnNewChat.addEventListener("click", newChat);

  const btnSend = $("#btn-chat-send");
  if (btnSend) btnSend.addEventListener("click", sendChatMessage);

  const btnMic = $("#btn-chat-mic");
  if (btnMic) btnMic.addEventListener("click", toggleChatMic);

  const input = $("#chat-input");
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }
}

function boot() {
  if (localStorage.getItem("sidebar_collapsed") === "true") {
    const nav = $("#nav");
    if (nav) nav.classList.add("collapsed");
  }

  setText(
    "#stat-date",
    new Date().toLocaleDateString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
    })
  );

  bindEvents();
  connectWS();
  route();
  loadDashboard();
  initStarfield();
  initWaveform();

  pollStatus();
  setInterval(pollStatus, 12000);
  pollAgents();
  setInterval(pollAgents, 30000);
}

boot();
