const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const form = document.getElementById("form");
const messageInput = document.getElementById("message");
const usernameInput = document.getElementById("username");
const replyPreview = document.getElementById("reply-preview");
const replyText = document.getElementById("reply-text");
const cancelReply = document.getElementById("cancel-reply");

let socket;
let replyTo = null;
const messageCache = new Map();

usernameInput.value = localStorage.getItem("redis-chat-name") || "";

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws`);

  socket.addEventListener("open", () => {
    statusEl.textContent = "В сети";
    statusEl.classList.add("online");
  });

  socket.addEventListener("close", () => {
    statusEl.textContent = "Нет соединения — переподключение…";
    statusEl.classList.remove("online");
    setTimeout(connect, 1500);
  });

  socket.addEventListener("error", () => socket.close());

  socket.addEventListener("message", (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }

    if (data.type === "system") {
      addSystem(data.text);
    } else if (data.type === "error") {
      addSystem(data.text);
    } else if (data.type === "ack") {
      addSystem(data.text);
    } else if (data.type === "message") {
      renderMessage(data);
    }
  });
}

function addSystem(text) {
  const el = document.createElement("div");
  el.className = "system";
  el.textContent = text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderMessage(data) {
  messageCache.set(data.id, data);
  const el = document.createElement("article");
  el.className = "message" + (data.username === currentName() ? " mine" : "");
  el.dataset.id = data.id;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (data.reply_to && messageCache.has(data.reply_to)) {
    const original = messageCache.get(data.reply_to);
    const quote = document.createElement("div");
    quote.className = "reply-quote";
    quote.textContent = `${original.username}: ${original.text}`;
    bubble.appendChild(quote);
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  const author = document.createElement("strong");
  author.textContent = data.username || "Гость";
  const time = document.createElement("span");
  time.textContent = data.time ? new Date(data.time).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : "";
  meta.append(author, time);

  const content = document.createElement("div");
  content.className = "content";
  content.textContent = data.text || "";

  const replyButton = document.createElement("button");
  replyButton.type = "button";
  replyButton.className = "reply-action";
  replyButton.textContent = "Ответить";
  replyButton.addEventListener("click", () => setReply(data));

  bubble.append(meta, content, replyButton);
  el.appendChild(bubble);
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function currentName() {
  return usernameInput.value.trim() || "Гость";
}

function setReply(data) {
  replyTo = data.id;
  replyText.textContent = `Ответ на ${data.username}: ${data.text.slice(0, 100)}`;
  replyPreview.classList.remove("hidden");
  messageInput.focus();
}

function clearReply() {
  replyTo = null;
  replyPreview.classList.add("hidden");
  replyText.textContent = "";
}

cancelReply.addEventListener("click", clearReply);
usernameInput.addEventListener("change", () => {
  localStorage.setItem("redis-chat-name", usernameInput.value.trim());
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text) return;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    addSystem("Нет соединения с сервером. Попробуйте ещё раз.");
    return;
  }

  socket.send(JSON.stringify({
    username: currentName(),
    text,
    reply_to: replyTo
  }));
  messageInput.value = "";
  clearReply();
  messageInput.focus();
});

connect();
