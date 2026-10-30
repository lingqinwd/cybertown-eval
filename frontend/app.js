let state = null;
let selected = null;
let canvas = null;
let ctx = null;
let raf = 0;
let view = { cell: 56, dpr: 1, width: 0, height: 0 };

const $ = (id) => document.getElementById(id);

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function escapeHtml(value) {
  const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value).replace(/[&<>"']/g, (char) => entities[char]);
}

function setupCanvas() {
  const map = $("map");
  map.innerHTML = '<canvas id="townCanvas" aria-label="晨雾镇 2D 游戏地图"></canvas><div class="map-hint">点击居民查看资料 · WASD / 方向键移动</div>';
  canvas = $("townCanvas");
  ctx = canvas.getContext("2d");
  canvas.addEventListener("click", (event) => {
    if (!state) return;
    const rect = canvas.getBoundingClientRect();
    const gx = Math.round((event.clientX - rect.left) / view.cell);
    const gy = Math.round((event.clientY - rect.top) / view.cell);
    const npc = state.npcs.find((item) => Math.abs(item.x - gx) <= 1 && Math.abs(item.y - gy) <= 1);
    if (npc) selectNpc(npc.npc_id);
  });
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();
  cancelAnimationFrame(raf);
  const animate = (time) => { drawTown(time); raf = requestAnimationFrame(animate); };
  raf = requestAnimationFrame(animate);
}

function resizeCanvas() {
  if (!canvas) return;
  const rect = canvas.parentElement.getBoundingClientRect();
  view.dpr = Math.min(window.devicePixelRatio || 1, 2);
  view.width = Math.max(320, rect.width);
  view.cell = Math.max(38, Math.min(64, view.width / Math.max(10, (state?.width || 15) + 1)));
  view.height = (state?.height || 10) * view.cell;
  canvas.style.height = `${view.height}px`;
  canvas.width = view.width * view.dpr;
  canvas.height = view.height * view.dpr;
  ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
}

function roundedRect(x, y, width, height, radius, fill, stroke) {
  ctx.beginPath(); ctx.roundRect(x, y, width, height, radius);
  ctx.fillStyle = fill; ctx.fill();
  if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
}

function drawTown(time = 0) {
  if (!ctx || !state) return;
  const cell = view.cell;
  ctx.clearRect(0, 0, view.width, view.height);
  const gradient = ctx.createLinearGradient(0, 0, view.width, view.height);
  gradient.addColorStop(0, "#d8f4e6"); gradient.addColorStop(1, "#b9d7f3");
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, view.width, view.height);
  ctx.fillStyle = "rgba(255,255,255,.25)";
  for (let y = 0; y < state.height; y += 1) for (let x = 0; x < state.width; x += 1) ctx.fillRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2);
  ctx.fillStyle = "rgba(255,255,255,.7)";
  for (let y = 1; y < state.height; y += 3) ctx.fillRect(0, y * cell - 9, view.width, 18);
  for (let x = 2; x < state.width; x += 5) ctx.fillRect(x * cell - 9, 0, 18, view.height);
  const buildings = [[1,1,"档案馆","#8b7cf6"],[7,1,"广场","#ffb454"],[11,6,"咖啡馆","#ef6f9a"],[2,7,"诊所","#35b6aa"]];
  buildings.forEach(([x,y,label,color]) => {
    const px=x*cell+7, py=y*cell+7, w=cell*2-14, h=cell*1.35;
    roundedRect(px,py,w,h,12,color,"rgba(255,255,255,.9)");
    ctx.fillStyle="rgba(255,255,255,.24)"; ctx.fillRect(px+10,py+10,w-20,10);
    ctx.fillStyle="#fff"; ctx.font="700 11px Inter, sans-serif"; ctx.fillText(label,px+12,py+h-13);
  });
  const drawActor = (actor, isPlayer) => {
    const bob = Math.sin(time / 330 + actor.x) * 2;
    const px = actor.x * cell + cell / 2, py = actor.y * cell + cell / 2 + bob;
    const radius = isPlayer ? 18 : 16;
    ctx.save(); ctx.shadowColor="rgba(16,24,40,.25)"; ctx.shadowBlur=12; ctx.shadowOffsetY=6;
    ctx.beginPath(); ctx.arc(px,py,radius,0,Math.PI*2); ctx.fillStyle=isPlayer?"#101828":actor.color; ctx.fill();
    ctx.shadowColor="transparent"; ctx.lineWidth=3; ctx.strokeStyle="#fff"; ctx.stroke();
    ctx.fillStyle="#fff"; ctx.font="800 15px Inter, sans-serif"; ctx.textAlign="center"; ctx.textBaseline="middle"; ctx.fillText(isPlayer?"你":actor.name[0],px,py);
    if (!isPlayer && selected?.npc_id === actor.npc_id) { ctx.beginPath(); ctx.arc(px,py,radius+7,0,Math.PI*2); ctx.strokeStyle="#155eef"; ctx.lineWidth=3; ctx.setLineDash([4,4]); ctx.stroke(); ctx.setLineDash([]); }
    ctx.restore();
  };
  drawActor(state.player, true); state.npcs.forEach((npc) => drawActor(npc, false));
}

function render(world) {
  state = world;
  $("position").textContent = `(${world.player.x}, ${world.player.y})`;
  $("tick").textContent = world.tick;
  resizeCanvas();
  $("events").innerHTML = world.events.map((event) => `<div class="event"><i>#${event.tick}</i><span>${escapeHtml(event.text)}</span></div>`).join("");
}

function selectNpc(id) {
  selected = state?.npcs.find((npc) => npc.npc_id === id);
  if (!selected) return;
  $("npcName").textContent = selected.name;
  const near = Math.abs(state.player.x - selected.x) + Math.abs(state.player.y - selected.y) <= 2;
  $("npcRole").textContent = `${selected.role}${near ? " · 已在对话范围内" : " · 请先走近"}`;
  $("affinity").textContent = selected.affinity;
  $("memoryCount").textContent = selected.memories.length;
  $("memories").innerHTML = selected.memories.length ? selected.memories.slice(-3).reverse().map((memory) => `<div>• ${escapeHtml(memory.text)}</div>`).join("") : "暂无可显示记忆";
}

async function refresh() {
  const data = await api("api/state");
  $("backendBadge").textContent = `memory backend · ${data.memory_backend.device}`;
  render(data.state);
}

async function move(dx, dy) {
  const data = await api("api/move", { method: "POST", body: JSON.stringify({ dx, dy }) });
  render(data.state); if (selected) selectNpc(selected.npc_id);
}

document.addEventListener("keydown", (event) => {
  if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  const key = event.key.toLowerCase();
  if (["arrowup", "w"].includes(key)) move(0, -1);
  if (["arrowdown", "s"].includes(key)) move(0, 1);
  if (["arrowleft", "a"].includes(key)) move(-1, 0);
  if (["arrowright", "d"].includes(key)) move(1, 0);
});

$("talkBtn").onclick = async () => {
  if (!selected) { $("reply").textContent = "请先选择 NPC。"; return; }
  try { const data = await api("api/talk", { method:"POST", body:JSON.stringify({ npc_id:selected.npc_id, message:$("message").value.trim() || "你好" }) }); $("reply").textContent=data.reply; render(data.state); selectNpc(selected.npc_id); }
  catch (error) { $("reply").textContent=error.message; }
};

$("resetBtn").onclick = async () => { const data=await api("api/reset", {method:"POST"}); selected=null; $("reply").textContent="世界已重置。"; render(data.state); };

setupCanvas();
refresh().catch((error) => { $("backendBadge").textContent=`memory backend · error: ${error.message}`; });
