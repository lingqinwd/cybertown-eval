let state = null;
let selected = null;

const $ = (id) => document.getElementById(id);

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function escapeHtml(value) {
  const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value).replace(/[&<>"']/g, (char) => entities[char]);
}

function render(world) {
  state = world;
  $("position").textContent = `(${world.player.x}, ${world.player.y})`;
  $("tick").textContent = world.tick;
  const map = $("map");
  map.querySelectorAll(".actor").forEach((node) => node.remove());
  const unitX = 100 / world.width;
  const unitY = 100 / world.height;
  const player = document.createElement("div");
  player.className = "actor player";
  player.textContent = "你";
  player.style.left = `calc(${world.player.x * unitX}% + 7px)`;
  player.style.top = `calc(${world.player.y * unitY}% + 7px)`;
  map.appendChild(player);
  world.npcs.forEach((npc) => {
    const actor = document.createElement("div");
    actor.className = "actor npc";
    actor.textContent = npc.name[0];
    actor.title = `${npc.name} · ${npc.role}`;
    actor.style.background = npc.color;
    actor.style.left = `calc(${npc.x * unitX}% + 7px)`;
    actor.style.top = `calc(${npc.y * unitY}% + 7px)`;
    actor.onclick = () => selectNpc(npc.npc_id);
    map.appendChild(actor);
  });
  $("events").innerHTML = world.events
    .map((event) => `<div class="event"><i>#${event.tick}</i><span>${escapeHtml(event.text)}</span></div>`)
    .join("");
}

function selectNpc(id) {
  selected = state.npcs.find((npc) => npc.npc_id === id);
  if (!selected) return;
  $("npcName").textContent = selected.name;
  const near = Math.abs(state.player.x - selected.x) + Math.abs(state.player.y - selected.y) <= 2;
  $("npcRole").textContent = `${selected.role}${near ? " · 已在对话范围内" : " · 请先走近"}`;
  $("affinity").textContent = selected.affinity;
  $("memoryCount").textContent = selected.memories.length;
  $("memories").innerHTML = selected.memories.length
    ? selected.memories.slice(-3).reverse().map((memory) => `<div>• ${escapeHtml(memory.text)}</div>`).join("")
    : "暂无可显示记忆";
}

async function refresh() {
  const data = await api("api/state");
  $("backendBadge").textContent = `memory backend · ${data.memory_backend.device}`;
  render(data.state);
}

async function move(dx, dy) {
  const data = await api("api/move", { method: "POST", body: JSON.stringify({ dx, dy }) });
  render(data.state);
  if (selected) selectNpc(selected.npc_id);
}

document.addEventListener("keydown", (event) => {
  const key = event.key.toLowerCase();
  if (["arrowup", "w"].includes(key)) move(0, -1);
  if (["arrowdown", "s"].includes(key)) move(0, 1);
  if (["arrowleft", "a"].includes(key)) move(-1, 0);
  if (["arrowright", "d"].includes(key)) move(1, 0);
});

$("talkBtn").onclick = async () => {
  if (!selected) {
    $("reply").textContent = "请先选择 NPC。";
    return;
  }
  try {
    const data = await api("api/talk", {
      method: "POST",
      body: JSON.stringify({ npc_id: selected.npc_id, message: $("message").value.trim() || "你好" }),
    });
    $("reply").textContent = data.reply;
    render(data.state);
    selectNpc(selected.npc_id);
  } catch (error) {
    $("reply").textContent = error.message;
  }
};

$("resetBtn").onclick = async () => {
  const data = await api("api/reset", { method: "POST" });
  selected = null;
  $("reply").textContent = "世界已重置。";
  render(data.state);
};

refresh().catch((error) => {
  $("backendBadge").textContent = `memory backend · error: ${error.message}`;
});
