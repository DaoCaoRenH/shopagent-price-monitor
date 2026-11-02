"use strict";
const $ = (id) => document.getElementById(id);
const state = {watches: [], alerts: [], selected: null, tab: "monitor", product: null, description: "", productRequest:"", history: null, status: null, presets:null, modelSettings:null, advice:new Map(), advicePrefs:new Map(), advicePending:new Set(), adviceErrors:new Map(), searchHistory:[], searchHistorySelected:null, searchHistoryCursor:null, searchHistoryQuery:"", activeSearchRecord:null};
const iconPaths = {
  bag: '<path d="M5 7h14l1 14H4L5 7Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2m-6 6 3 3 4-5"/>',
  activity: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m6 14 4-4 4 3 4-6"/>',
  history: '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7M12 7v5l3 2"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrowRight: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  arrowLeft: '<path d="M19 12H5m6-6-6 6 6 6"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  spark: '<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Zm7-1v4m-2-2h4"/>',
  chart: '<path d="M4 3v17h17M7 14l4-5 4 3 5-7"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
  down: '<path d="M12 3v17m-6-6 6 6 6-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
  settings: '<path d="m9 3-1 3-3 1-2 5 2 5 3 1 1 3h6l1-3 3-1 2-5-2-5-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
};
function icon(name) { return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${iconPaths[name] || iconPaths.bag}</svg>`; }
function hydrateIcons(root = document) { root.querySelectorAll("[data-icon]").forEach(el => {el.innerHTML = icon(el.dataset.icon);}); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c])); }
function date(value, full = false) {
  if (!value) return "尚未检查";
  return new Date(value).toLocaleString("zh-CN", {month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", ...(full ? {second:"2-digit"} : {}), hour12:false});
}
function amount(value) { return Number(value).toLocaleString("zh-CN", {minimumFractionDigits:2, maximumFractionDigits:2}); }
function variant(watch) { return Object.entries(watch.selections).map(([k,v]) => `${k}：${v}`).join(" · ") || "无可选规格"; }
function modeTag(mode) { return `<span class="tag ${mode === "simulation" ? "simulation" : ""}">${mode === "simulation" ? "模拟监控" : "价格快照"}</span>`; }
function interval(seconds) { return seconds < 60 ? `${seconds} 秒` : seconds < 3600 ? `${seconds/60} 分钟` : `${seconds/3600} 小时`; }
function sourceLabel(source) { return {catalog:"目录基准", import:"导入快照", simulation:"手动/旧版模拟",event_simulation:"事件模拟",scenario_replay:"场景回放"}[source] || "价格记录"; }

function scenarioList(scenario, current = -1) {
  return `<ol class="scenario-steps">${scenario.steps.map((step,index) => `<li class="${index === current ? "current" : ""}"><span>${index+1}</span><strong>${step.percent == null ? "获取失败" : step.percent+"%"}</strong><small>${esc(step.event)}</small></li>`).join("")}</ol>`;
}
function updateSimulationSettings() {
  const enabled = $("watch-mode").value === "simulation", replay = $("simulation-engine").value === "replay";
  $("simulation-settings").hidden = !enabled;
  $("simulation-seed").disabled = !enabled || replay;
  $("seed-field").hidden = replay; $("scenario-field").hidden = !replay;
  $("scenario-preview").hidden = !replay;
  $("mode-help").textContent = enabled ? "模拟价格与真实快照分开保存。价格按时钟推进，同一步内反复检查不会改价。" : "定期检查最新已导入快照；静态目录本身不会产生价格变化。";
  const slow = Number($("watch-interval").value) > Number($("simulation-period").value);
  $("simulation-help").textContent = replay ? "按固定序列自动回放，结束后停止采样；重播会保留本次记录。"+(slow ? " 请将检查间隔调至不大于价格推进间隔。" : "") : "大部分时间同价，偶尔调价或限时促销，促销结束恢复正常售价。固定种子可复现事件序列。"+(slow ? " 采样较慢时可能错过中间价格。" : "");
  const scenario = state.presets?.scenarios.find(s => s.id === $("simulation-scenario").value);
  $("scenario-preview").innerHTML = scenario ? '<details><summary>预览固定价格序列</summary><p>相对初始报价的比例</p>'+scenarioList(scenario)+'</details>' : "";
}
function simulationPanel(watch) {
  const sim = watch.simulation;
  if (!sim) return "";
  const replay = sim.engine === "replay", scenario = state.presets?.scenarios.find(s => s.id === sim.scenario);
  return `<section class="simulation-summary" aria-label="模拟运行状态"><div class="simulation-title"><strong>${replay ? "固定场景回放" : "事件驱动模拟"}</strong><span class="tag simulation">${replay ? `${sim.complete ? "已完成 · " : ""}${sim.tick+1} / ${sim.total_steps} 步` : `第 ${sim.tick+1} 步`}</span></div><p>${esc(replay ? sim.scenario_name : `正常售价 ¥${amount(sim.normal_price)}`)}</p><div class="simulation-event">${esc(sim.event)}</div><p class="quiet-label">每 ${interval(sim.tick_seconds)}推进一步 · ${replay ? "固定序列" : "种子 "+sim.seed}<br>同一步报价固定；暂停或离线期间时钟继续，恢复后采集当前步。</p>${scenario ? `<details><summary>查看固定序列与当前步骤</summary><p class="quiet-label">数值为相对初始报价的比例</p>${scenarioList(scenario,sim.tick)}</details><button class="button secondary" id="restart-replay">重新回放（保留记录）</button>` : ""}</section>`;
}
function advicePrefs(id) { return state.advicePrefs.get(id) || {budget:"",urgency:"flexible"}; }
function adviceResult(watch) {
  const advice = state.advice.get(watch.id), prefs = advicePrefs(watch.id);
  if (!advice) return '<p class="advice-empty">结合价格记录和你的购买计划，分析当前是否适合入手。</p>';
  const based = advice.based_on;
  const stale = advice.model_revision !== state.status?.model_revision || based.history_revision !== watch.history_revision || based.last_error !== watch.last_error || based.active !== watch.active || based.interval_seconds !== watch.interval_seconds || advice.preferences.urgency !== prefs.urgency || (prefs.budget ? Number(prefs.budget) : null) !== (advice.preferences.budget == null ? null : Number(advice.preferences.budget)) || (advice.decision !== "refresh_quote" && Date.now() > new Date(advice.valid_until).getTime());
  if (stale) return `<div class="advice-outdated"><strong>建议待更新</strong><p>价格、监控状态、购买偏好或模型配置已变化，请重新生成建议。</p><small>上次分析 ${date(advice.generated_at,true)}</small></div>`;
  return `<div class="advice-conclusion"><strong>${esc(advice.title)}</strong><span class="tag ${advice.engine === "rules" ? "" : "agent"}">${advice.engine === "model" ? "Agent 分析" : "监控规则"}</span></div><p class="advice-message">${esc(advice.message)}</p><ul class="advice-reasons">${advice.reasons.map(reason => `<li>${esc(reason.text)}</li>`).join("")}</ul><div class="advice-next"><strong>下一步</strong><p>${esc(advice.next_step)}</p></div><p class="advice-scope">${esc(advice.scope)}<br>采样范围 ${date(advice.metrics.first_observed_at,true)} → ${date(advice.metrics.latest_observed_at,true)}<br>分析时间 ${date(advice.generated_at,true)}</p>`;
}
function renderAdvice(watch) {
  const panel = $("purchase-advice"), prefs = advicePrefs(watch.id), pending = state.advicePending.has(watch.id);
  if (!panel) return;
  const error = state.adviceErrors.get(watch.id);
  panel.innerHTML = `<div class="advice-heading"><h3>${icon("spark")}购买建议</h3>${watch.mode === "simulation" ? '<span class="tag simulation">模拟数据</span>' : ""}</div><form id="advice-form"><div class="advice-fields"><label class="field-label" for="advice-budget">预算上限（可选）<input id="advice-budget" type="number" min="0.01" max="1000000000" step="0.01" placeholder="例如 100" value="${esc(prefs.budget)}" ${pending ? "disabled" : ""}></label><label class="field-label" for="advice-urgency">购买时间<select id="advice-urgency" ${pending ? "disabled" : ""}><option value="flexible" ${prefs.urgency === "flexible" ? "selected" : ""}>不急用，可以等</option><option value="soon" ${prefs.urgency === "soon" ? "selected" : ""}>近期需要购买</option></select></label></div><button type="submit" class="button secondary" ${pending ? "disabled" : ""}>${pending ? "正在分析…" : state.advice.has(watch.id) ? "重新分析" : "生成购买建议"}</button></form><div id="advice-result" class="advice-result" aria-live="polite" aria-busy="${pending}">${adviceResult(watch)}</div>${error ? `<p class="notice error" role="alert">${esc(error)}</p>` : ""}`;
  const savePrefs = () => {
    state.advicePrefs.set(watch.id,{budget:$("advice-budget").value,urgency:$("advice-urgency").value});
    $("advice-result").innerHTML = adviceResult(watch);
  };
  $("advice-budget").addEventListener("input",savePrefs);
  $("advice-urgency").addEventListener("change",savePrefs);
  $("advice-form").addEventListener("submit",async event => {
    event.preventDefault(); savePrefs();
    const requestPrefs = advicePrefs(watch.id);
    state.advicePending.add(watch.id); state.adviceErrors.delete(watch.id); renderAdvice(watch);
    try {
      const result = await post(`/api/watches/${watch.id}/advice`,{budget:requestPrefs.budget || null,urgency:requestPrefs.urgency});
      state.advice.set(watch.id,result);
    } catch(error) {state.adviceErrors.set(watch.id,error.message);}
    finally {
      state.advicePending.delete(watch.id);
      if (state.selected === watch.id && state.history?.watch?.id === watch.id) renderAdvice(state.history.watch);
    }
  });
}
async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type":"application/json"}, ...options});
  let result;
  try { result = await response.json(); } catch { throw new Error("服务响应异常，请稍后重试"); }
  if (!response.ok) {
    let message = result.detail;
    if (Array.isArray(message)) message = message.map(e => `${e.loc.slice(1).join(".")}：${e.msg}`).join("；");
    throw new Error(typeof message === "string" ? message : "操作失败，请检查输入后重试");
  }
  return result;
}
const post = (path, body = {}) => api(path, {method:"POST", body:JSON.stringify(body)});
let toastTimer;
function toast(message) { $("toast").textContent = message; $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => {$("toast").hidden = true;}, 4500); }
function feedback(id, message, error = false) { $(id).textContent = message; $(id).classList.toggle("error", error); $(id).hidden = !message; }
async function busy(button, label, action) {
  const old = button.innerHTML;
  button.disabled = true; button.textContent = label;
  try { return await action(); } finally { button.innerHTML = old; button.disabled = false; }
}
let activeSearchRun = null;
function elapsedLabel(ms) {
  const seconds = Math.floor(ms / 1000);
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds/60)} 分 ${seconds%60} 秒`;
}
function searchEngineLabel(engine) {
  return {model:"Agent 筛选",partial:"已有候选 · 筛选未完成",catalog:"目录检索"}[engine] || "准备中";
}
function startSearchProgress() {
  const run = {started:performance.now(),steps:new Map(),sequence:0,round:0,roundLimit:0,engine:null};
  activeSearchRun = run;
  $("search-progress").hidden = false; $("search-progress").dataset.state = "running";
  $("search-progress").setAttribute("aria-busy","true");
  $("search-progress-title").textContent = "正在准备搜索";
  $("search-progress-message").textContent = "正在提交搜索请求…";
  $("search-progress-stats").textContent = "等待执行";
  $("search-progress-engine").textContent = "连接中";
  $("search-progress-log").innerHTML = ""; $("search-progress-count").textContent = "0 步";
  $("search-progress-bar").removeAttribute("aria-valuenow");
  $("search-progress-bar").setAttribute("aria-valuetext","正在提交搜索请求");
  const tick = () => {$("search-progress-elapsed").textContent = `已用时 ${elapsedLabel(performance.now()-run.started)}`;};
  tick(); run.timer = setInterval(tick,500);
  return run;
}
function renderSearchSteps(run) {
  const log = $("search-progress-log"), atBottom = log.scrollHeight-log.scrollTop-log.clientHeight < 35;
  const labels = {running:"进行中",completed:"已完成",notice:"提示",blocked:"已阻断",interrupted:"已中止"};
  log.innerHTML = [...run.steps.values()].map(step => {
    const status = Object.hasOwn(labels,step.status) ? step.status : "notice";
    return `<li class="search-step is-${status}"><span class="search-step-dot" aria-hidden="true"></span><div><p>${esc(step.message)}</p><small>${elapsedLabel(step.elapsed_ms)}</small></div><span class="search-step-status">${labels[status]}</span></li>`;
  }).join("");
  if (atBottom) log.scrollTop = log.scrollHeight;
  $("search-progress-count").textContent = `${run.steps.size} 步`;
  const steps = [...run.steps.values()];
  const searches = steps.filter(step=>step.stage === "searching" && step.status === "completed").length;
  const inspections = steps.filter(step=>step.stage === "inspecting" && step.status === "completed").length;
  $("search-progress-stats").textContent = `${run.round ? `第 ${run.round}${run.roundLimit ? "/"+run.roundLimit : ""} 轮分析 · ` : ""}已检索 ${searches} 次 · 已查看 ${inspections} 次`;
}
function updateSearchProgress(run,event) {
  if (activeSearchRun !== run || event.sequence <= run.sequence) return;
  run.sequence = event.sequence;
  if (["fallback","retaining"].includes(event.stage)) {
    for (const step of run.steps.values()) if (step.status === "running") step.status = "interrupted";
  }
  run.steps.set(event.step_id,event);
  run.round = Math.max(run.round,event.round || 0); run.engine = event.engine || run.engine;
  run.roundLimit = event.round_limit || run.roundLimit;
  const titles = {starting:"正在准备搜索",planning:"Agent 正在分析",model_stream:"正在接收模型响应",model_retry:"正在重试当前轮",tool_repair:"正在补正工具调用",model_error:"模型调用未能完成",searching:"正在检索商品",inspecting:"正在核对商品",summarizing:"正在整理候选",retaining:"正在保留已有候选",fallback:"正在使用目录检索",tool_limit:"正在调整执行步骤",completed:"正在接收搜索结果"};
  $("search-progress-title").textContent = titles[event.stage] || "正在执行搜索";
  $("search-progress-message").textContent = event.message;
  $("search-progress-bar").setAttribute("aria-valuetext",event.message);
  $("search-progress-engine").textContent = searchEngineLabel(run.engine);
  renderSearchSteps(run);
}
function finishSearchProgress(run,result,error) {
  clearInterval(run.timer);
  $("search-progress-elapsed").textContent = `总用时 ${elapsedLabel(performance.now()-run.started)}`;
  $("search-progress").dataset.state = error ? "error" : result.engine === "partial" ? "partial" : "complete";
  $("search-progress").setAttribute("aria-busy","false");
  $("search-progress-title").textContent = error ? "搜索已中断" : result.engine === "partial" ? "已保留候选，筛选未完成" : result.engine === "catalog" ? "目录检索已完成" : "Agent 搜索已完成";
  const message = error ? error.message : result.engine === "partial" ? result.message : result.products.length ? `已返回 ${result.products.length} 个候选，请继续核对商品与规格。` : "本次未找到候选，可以调整关键词后重新搜索。";
  $("search-progress-message").textContent = message;
  $("search-progress-bar").setAttribute("aria-valuetext",message);
  if (!error) $("search-progress-bar").setAttribute("aria-valuenow","100");
  else $("search-progress-bar").removeAttribute("aria-valuenow");
  for (const step of run.steps.values()) if (step.status === "running") step.status = "interrupted";
  renderSearchSteps(run);
  if (result) $("search-progress-engine").textContent = searchEngineLabel(result.engine);
}
async function streamSearch(description,onProgress) {
  const result = await streamOperation("/api/search/stream",{description},onProgress);
  if (!Array.isArray(result.products)) throw new Error("搜索结果格式不正确，请重试。");
  return result;
}
async function streamOperation(url,body,onProgress) {
  let response;
  try {response = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/x-ndjson"},body:JSON.stringify(body)});}
  catch {throw new Error("无法连接服务，请确认服务已启动后重试。");}
  if (!response.ok) {
    const body = await response.json().catch(()=>({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `搜索请求失败（HTTP ${response.status}），请重试。`);
  }
  if (!response.body) throw new Error("浏览器未能接收执行进度，请刷新后重试。");
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
  function consume(line) {
    if (!line.trim()) return;
    let event;
    try {event=JSON.parse(line);} catch {throw new Error("搜索进度数据不完整，请重新搜索。");}
    if (event.type === "progress") onProgress(event);
    if (event.type === "error") throw new Error(event.message || "搜索未能完成，请稍后重试。");
    if (event.type === "result") {
      if (!event.result || typeof event.result !== "object") throw new Error("响应结果格式不正确，请重试。");
      return event.result;
    }
  }
  try {
    while (true) {
      const {value,done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value,{stream:true});
      const lines=buffer.split("\n"); buffer=lines.pop();
      for (const line of lines) {const result=consume(line);if(result) return result;}
      if (done) break;
    }
    if (buffer.trim()) {const result=consume(buffer);if(result) return result;}
    throw new Error("连接已中断，尚未收到完整结果，请重试。");
  } catch(error) {
    if (error instanceof TypeError) throw new Error("请求连接已中断，尚未收到完整结果，请重试。");
    throw error;
  } finally {
    await reader.cancel().catch(()=>{}); reader.releaseLock();
  }
}
function updateRoute(tab, replace = false) {
  const hash = tab === "watch-detail" ? `#watch/${encodeURIComponent(state.selected)}` : `#${tab}`;
  if (window.location.hash !== hash) window.history[replace ? "replaceState" : "pushState"](null,"",hash);
}
function changeTab(tab, {updateLocation = true} = {}) {
  if (updateLocation) updateRoute(tab);
  state.tab = tab;
  document.body.classList.toggle("settings-view",tab === "settings");
  document.body.classList.toggle("watch-detail-view",tab === "watch-detail");
  ["monitor", "watches", "watch-detail", "history", "alerts", "data", "settings"].forEach(name => {$("view-"+name).hidden = name !== tab;});
  document.querySelector(".metrics").hidden = ["settings","history","watch-detail"].includes(tab);
  const navTab = tab === "watch-detail" ? "watches" : tab;
  document.querySelectorAll("[data-tab]").forEach(button => {
    button.classList.toggle("active", button.dataset.tab === navTab);
    if (button.dataset.tab === navTab) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  const titles = {monitor:["价格监控", "商品价格监控", "关注想买的商品，等一个更合适的价格。"], watches:["我的监控", "我的监控", "关注的商品都在这里，选择一项查看具体价格走势。"], "watch-detail":["我的监控 / 价格走势", "商品价格走势", "查看所选规格的价格变化、采样依据与购买建议。"], history:["搜索记录", "回到上一次的好选择", "找回搜索时的候选与理由，继续比较，随时加入监控。"], alerts:["低价提醒", "低价提醒", "每一次新低，都有对应的价格记录。"], data:["数据管理", "价格数据管理", "导入明确报价，为关注的商品积累价格历史。"], settings:["模型配置", "配置你的 Agent", "选择模型服务，为商品搜索和购买建议提供分析。"]};
  $("breadcrumb-current").textContent = titles[tab][0]; $("page-title").textContent = titles[tab][1]; $("page-subtitle").textContent = titles[tab][2];
  if (tab === "settings" && !state.modelSettings) loadModelSettings();
  if (tab === "history") loadSearchHistory();
  if (tab === "watches") renderWatches();
  window.scrollTo({top:0,behavior:"instant"});
}
function restoreRoute(initial = false) {
  const hash = window.location.hash.slice(1);
  if (hash === "main") return;
  if (hash.startsWith("watch/")) {
    let id;
    try {id=decodeURIComponent(hash.slice(6));} catch {id="";}
    if (id) {
      state.selected=id;
      if (initial) changeTab("watch-detail",{updateLocation:false});
      else openWatch(id,{updateLocation:false});
      return;
    }
  }
  const tab = ["monitor","watches","history","alerts","data","settings"].includes(hash) ? hash : "monitor";
  changeTab(tab,{updateLocation:false});
}
window.addEventListener("hashchange",()=>restoreRoute());
document.querySelector(".skip-link").addEventListener("click",event=>{
  event.preventDefault(); $("main").setAttribute("tabindex","-1"); $("main").focus();
});
async function openWatch(id, {updateLocation = true} = {}) {
  state.selected=id;
  changeTab("watch-detail",{updateLocation});
  $("detail-panel").innerHTML='<p class="history-placeholder" role="status">正在读取价格走势…</p>';
  $("detail-panel").setAttribute("aria-busy","true");
  $("page-title").setAttribute("tabindex","-1"); $("page-title").focus({preventScroll:true});
  try {await loadDetail(id);} catch(error) {
    if (state.tab === "watch-detail" && state.selected === id) renderWatchError(error.message);
  }
}
function renderWatchError(message) {
  $("detail-panel").setAttribute("aria-busy","false");
  $("detail-panel").innerHTML=`<div class="empty-state"><span class="empty-icon">${icon("chart")}</span><h3>暂时无法显示价格走势</h3><p>${esc(message)}</p><button class="button secondary" id="retry-watch-detail">重新读取</button></div>`;
  $("retry-watch-detail").addEventListener("click",()=>openWatch(state.selected,{updateLocation:false}));
}

function renderProductList(container, products, description, historical = false) {
  container.innerHTML = products.length ? products.map(p => `<div class="product-row"><div class="product-symbol">${icon("bag")}</div><div><div class="product-title">${esc(p.title)}</div><div class="product-meta">店铺：${esc(p.shop || "未提供")} · 分类：${esc(p.category || "未提供")}</div><div class="product-facts"><span>${p.option_group_count ? `${Number(p.option_group_count)} 组可选规格` : "无可选规格"}</span><span>商品 ID：${esc(p.asin)}</span></div>${p.reason ? `<p class="product-reason">${esc(p.reason)}</p>` : ""}</div><div class="product-price"><strong>${p.price == null ? "待确认" : "¥"+amount(p.price)}</strong><small>${historical ? "当次目录参考价" : "目录参考价"}</small></div><button class="button secondary" data-product="${esc(p.asin)}" aria-label="查看详情：${esc(p.title)}">查看详情 ${icon("arrowRight")}</button></div>`).join("") : '<div class="empty-state"><h3>没有找到相关商品</h3><p>试试保留品类、品牌或型号，减少场景描述。</p></div>';
  container.querySelectorAll("[data-product]").forEach(button => button.addEventListener("click", () => openProduct(button.dataset.product, description)));
}
let historyListRevision = 0, historyDetailRevision = 0;
function renderHistoryList() {
  $("search-history-list").innerHTML = state.searchHistory.length ? state.searchHistory.map(record => `<button class="history-row ${record.id === state.searchHistorySelected ? "selected" : ""}" data-search-record="${esc(record.id)}" aria-pressed="${record.id === state.searchHistorySelected}"><span class="history-row-time">${date(record.completed_at,true)}</span><strong>${esc(record.description)}</strong><span class="history-row-meta"><span>${record.result_count} 个候选 · ${esc(searchEngineLabel(record.engine))}</span><span>${elapsedLabel(record.elapsed_ms)}</span></span></button>`).join("") : `<div class="empty-state history-list-empty"><span class="empty-icon">${icon("history")}</span><h3>${state.searchHistoryQuery ? "没有匹配的记录" : "还没有搜索记录"}</h3><p>${state.searchHistoryQuery ? "试试其他需求关键词。" : "完成一次商品搜索后，<br>候选和理由会自动保存在这里。"}</p></div>`;
  $("search-history-list").querySelectorAll("[data-search-record]").forEach(button => button.addEventListener("click", () => selectSearchHistory(button.dataset.searchRecord)));
}
async function loadSearchHistory(append = false) {
  const revision = ++historyListRevision;
  const query = new URLSearchParams({q:state.searchHistoryQuery,limit:"20"});
  if (append && state.searchHistoryCursor) query.set("before",state.searchHistoryCursor);
  $("more-search-history").disabled = true;
  $("search-history-list").setAttribute("aria-busy","true");
  feedback("search-history-feedback", "");
  try {
    const result = await api(`/api/search-history?${query}`);
    if (revision !== historyListRevision) return;
    state.searchHistory = append ? [...state.searchHistory,...result.records] : result.records;
    state.searchHistoryCursor = result.next_cursor;
    $("search-history-total").textContent = result.total;
    $("more-search-history").hidden = !result.next_cursor;
    renderHistoryList();
    if (!append) {
      if (state.searchHistorySelected) selectSearchHistory(state.searchHistorySelected);
      else if (result.records.length) selectSearchHistory(result.records[0].id);
      else {
        ++historyDetailRevision;
        $("search-history-detail").setAttribute("aria-busy","false");
        $("search-history-detail").innerHTML = `<div class="empty-state"><span class="empty-icon">${icon("history")}</span><h3>留住每一次比较</h3><p>完成搜索后，可以在这里找回候选商品。<br>本次升级前未保存的候选无法追溯。</p><button class="button secondary" id="history-start-search">去搜索商品 ${icon("arrowRight")}</button></div>`;
        $("history-start-search").addEventListener("click",()=>{changeTab("monitor");$("description").focus();});
      }
    }
  } catch(error) {
    if (revision === historyListRevision) feedback("search-history-feedback",`读取失败：${error.message}。请点击“刷新”重试。`,true);
  } finally {
    if (revision === historyListRevision) {$("more-search-history").disabled=false;$("search-history-list").setAttribute("aria-busy","false");}
  }
}
async function selectSearchHistory(id) {
  const revision = ++historyDetailRevision;
  state.searchHistorySelected = id; renderHistoryList();
  const panel = $("search-history-detail");
  panel.setAttribute("aria-busy","true");
  panel.innerHTML = '<p class="history-placeholder" role="status">正在读取当次候选…</p>';
  try {
    const record = await api(`/api/search-history/${encodeURIComponent(id)}`);
    if (revision !== historyDetailRevision) return;
    const labels = {running:"已中止",completed:"已完成",notice:"提示",blocked:"已阻断",interrupted:"已中止"};
    const events = record.events.map(step => {
      const status = Object.hasOwn(labels,step.status) ? step.status : "notice";
      return `<li class="search-step is-${status === "running" ? "interrupted" : status}"><span class="search-step-dot" aria-hidden="true"></span><div><p>${esc(step.message)}</p><small>${elapsedLabel(step.elapsed_ms)}</small></div><span class="search-step-status">${labels[status]}</span></li>`;
    }).join("");
    panel.innerHTML = `<div class="history-detail-heading"><div class="history-detail-meta"><span class="tag ${record.engine === "model" ? "agent" : ""}">${esc(searchEngineLabel(record.engine))}</span><time>${date(record.completed_at,true)}</time><span>用时 ${elapsedLabel(record.elapsed_ms)}</span></div><h2>${esc(record.description)}</h2><p class="body-copy">${esc(record.message)}</p></div><div class="history-price-note">保留搜索当时的候选与参考价。查看详情会读取当前目录；加入监控时请重新确认规格与报价。</div><div class="panel-heading"><h3>当次候选 <span class="count">${record.products.length}</span></h3><span class="quiet-label">可继续查看并加入监控</span></div><div id="history-products"></div>${events ? `<details class="history-execution search-progress-details"><summary>查看当次执行记录 <span>${record.events.length} 步</span></summary><ol aria-label="历史搜索执行记录">${events}</ol></details>` : ""}`;
    renderProductList($("history-products"),record.products,record.description,true);
  } catch(error) {
    if (revision !== historyDetailRevision) return;
    panel.innerHTML = `<div class="empty-state"><h3>未能读取这条记录</h3><p>${esc(error.message)}</p><button class="button secondary" id="retry-history-detail">重新读取</button></div>`;
    $("retry-history-detail").addEventListener("click",()=>selectSearchHistory(id));
  } finally {if (revision === historyDetailRevision) panel.setAttribute("aria-busy","false");}
}
$("refresh-search-history").addEventListener("click",()=>loadSearchHistory());
$("more-search-history").addEventListener("click",()=>loadSearchHistory(true));
$("history-filter-form").addEventListener("submit",event=>{
  event.preventDefault(); state.searchHistoryQuery=$("history-filter").value.trim();
  state.searchHistorySelected=null; ++historyDetailRevision; loadSearchHistory();
});
$("last-search-record").addEventListener("click",()=>{
  state.searchHistorySelected=state.activeSearchRecord;
  state.searchHistoryQuery=""; $("history-filter").value=""; changeTab("history");
});

const reasoningLabels = {none:"默认",minimal:"极低（minimal）",low:"低（low）",medium:"中（medium）",high:"高（high）",xhigh:"极高（xhigh）",max:"最大（max）",ultra:"扩展（ultra）"};
function modelDraft() {
  return {enabled:$("model-enabled").checked, provider:$("model-provider").value,
    model:$("model-name").value.trim(), base_url:$("model-url").value.trim(),
    api_key_required:$("model-auth").checked, api_key:$("model-key").value.trim() || null,
    clear_api_key:$("model-clear-key").checked, timeout_sec:Number($("model-timeout").value),
    max_output_tokens:Number($("model-output").value), temperature:Number($("model-temperature").value),
    strict_tool_schema:$("model-strict").checked, reasoning_effort:$("model-reasoning").value,
    stream:$("model-provider").value === "openai-responses" && $("model-stream").checked,
    max_retries:Number($("model-retries").value),
    max_context_tokens:Number($("model-context").value),
    search_limits:{max_searches:Number($("search-max-searches").value),
      max_inspections:Number($("search-max-inspections").value),
      max_model_rounds:Number($("search-max-rounds").value)}};
}
function modelHelp() {
  const provider = $("model-provider").value;
  $("model-stream").disabled = provider !== "openai-responses";
  $("model-stream-help").textContent = provider === "openai-responses" ? "实时检测生成和工具参数；完整接收并校验后才执行工具。" : "当前协议使用完整响应；自动重试仍有效。";
  $("model-url-help").textContent = provider === "gemini" ? "填写根地址，例如 https://generativelanguage.googleapis.com/v1beta；无需填写模型路径。" : `填写根地址，通常包含 /v1；无需填写 ${provider === "openai-chat" ? "/chat/completions" : "/responses"}。`;
  $("model-key").placeholder = state.modelSettings?.has_api_key ? "已配置，留空保留；输入新密钥可替换" : "不需要认证时可留空";
  $("model-reasoning-help").textContent = provider === "gemini" ? "默认思考预算为 0；其他强度映射为思考 Token 预算，需模型支持。" : "默认不额外指定思考参数；其他档位需模型服务支持。";
}
function applyModelSettings(value) {
  value = {reasoning_effort:"none",max_context_tokens:24576,stream:true,max_retries:2,...value};
  value.search_limits = {max_searches:2,max_inspections:3,max_model_rounds:7,...value.search_limits};
  state.modelSettings = value;
  for (const [field,key] of Object.entries({"model-name":"model","model-url":"base_url","model-provider":"provider","model-timeout":"timeout_sec","model-output":"max_output_tokens","model-temperature":"temperature","model-reasoning":"reasoning_effort","model-context":"max_context_tokens","model-retries":"max_retries"})) $(field).value = value[key];
  for (const [field,key] of Object.entries({"model-enabled":"enabled","model-auth":"api_key_required","model-strict":"strict_tool_schema","model-stream":"stream"})) $(field).checked = value[key];
  for (const [field,key] of Object.entries({"search-max-searches":"max_searches","search-max-inspections":"max_inspections","search-max-rounds":"max_model_rounds"})) $(field).value = value.search_limits[key];
  $("model-key").value = ""; $("model-clear-key").checked = false;
  $("model-clear-wrap").hidden = !value.has_api_key; $("model-fields").disabled = false;
  $("model-draft-state").textContent = "与当前配置一致"; $("model-retry").hidden = true;
  $("model-current").innerHTML = `<span class="tag ${value.enabled ? "agent" : ""}">${value.enabled ? "模型已启用" : "模型已关闭"}</span><dl class="settings-facts"><dt>模型</dt><dd>${esc(value.model)}</dd><dt>接口</dt><dd>${esc({"openai-responses":"Responses","openai-chat":"Chat Completions",gemini:"Gemini 原生"}[value.provider])}</dd><dt>地址</dt><dd>${esc(value.base_url)}</dd><dt>认证</dt><dd>${value.api_key_required ? value.has_api_key ? "已配置密钥" : "尚未配置密钥" : "无需认证"}</dd><dt>思考强度</dt><dd>${esc(reasoningLabels[value.reasoning_effort] || value.reasoning_effort)}</dd><dt>上下文</dt><dd>${Number(value.max_context_tokens).toLocaleString("zh-CN")} Token</dd><dt>搜索上限</dt><dd>${Number(value.search_limits.max_searches)} 次 / 每次搜索任务</dd><dt>查看上限</dt><dd>${Number(value.search_limits.max_inspections)} 次 / 每次搜索任务</dd><dt>轮次上限</dt><dd>${Number(value.search_limits.max_model_rounds)} 轮模型调用</dd></dl><p class="field-help">${value.persistent ? "配置保存在本机，重启应用后继续使用。" : "配置在本次服务会话生效。"}</p>`;
  modelHelp();
  const transport = document.createElement("p"); transport.className="field-help";
  transport.textContent = `${value.stream ? "流式接收" : "完整响应"} · 失败后最多自动重试 ${value.max_retries} 次`;
  $("model-current").append(transport);
}
async function loadModelSettings() {
  $("model-fields").disabled = true;
  try {const value = await api("/api/model-settings"); applyModelSettings(value); feedback("model-feedback",value.load_error || "",!!value.load_error);}
  catch(error) {feedback("model-feedback",error.message,true);$("model-retry").hidden=false;$("model-draft-state").textContent="读取失败";}
}
$("model-retry").addEventListener("click",loadModelSettings);
$("model-reset").addEventListener("click",loadModelSettings);
$("model-settings-form").addEventListener("input",() => {$("model-draft-state").textContent="有未保存的修改";feedback("model-feedback","");modelHelp();});
$("model-settings-form").addEventListener("change",modelHelp);
async function submitModelSettings(save) {
  if (!$("model-settings-form").reportValidity()) return;
  const body = modelDraft(); $("model-fields").disabled = true;
  feedback("model-feedback",save ? "正在保存配置…" : "正在验证连接与工具调用…");
  try {
    const result = save ? await api("/api/model-settings",{method:"PUT",body:JSON.stringify(body)}) :
      await streamOperation("/api/model-settings/test/stream",body,event=>feedback("model-feedback",`${event.message}\n已用时 ${elapsedLabel(event.elapsed_ms)}`));
    if (save) {
      applyModelSettings(result); if (state.status) state.status.model_revision=result.revision;
      feedback("model-feedback", "配置已保存，新请求立即生效。"); await loadDashboard();
    } else {
      const detail = result.error;
      const diagnostic = detail ? `\n错误类型：${detail.kind} / ${detail.exception_type}${detail.http_status ? ` · HTTP ${detail.http_status}` : ""}\n具体原因：${detail.detail}\n请求地址：${detail.endpoint}` : "";
      feedback("model-feedback",result.message+(result.ok ? ` 耗时 ${result.latency_ms} ms，配置尚未保存。` : diagnostic),!result.ok);
    }
  } catch(error) {feedback("model-feedback",error.message,true);}
  finally {$("model-fields").disabled=false;}
}
$("model-settings-form").addEventListener("submit",event=>{event.preventDefault();submitModelSettings(true);});
$("model-test").addEventListener("click",()=>submitModelSettings(false));
document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => changeTab(button.dataset.tab)));
document.querySelectorAll("[data-open-tab]").forEach(button => button.addEventListener("click", () => changeTab(button.dataset.openTab)));
$("new-watch").addEventListener("click", () => {changeTab("monitor"); $("description").focus(); $("search-form").scrollIntoView({block:"center", behavior:"instant"});});
document.querySelectorAll("[data-query]").forEach(button => button.addEventListener("click", () => {$("description").value = button.dataset.query; $("description").focus();}));
$("close-results").addEventListener("click", () => {$("search-results").hidden = true;});
$("search-form").addEventListener("submit", async event => {
  event.preventDefault(); if (activeSearchRun) return;
  state.description = $("description").value.trim(); if (!state.description) return;
  const run=startSearchProgress();
  state.activeSearchRecord=null; $("last-search-record").hidden=true;
  feedback("search-feedback", ""); $("search-results").hidden = true;
  try {
    const result = await busy($("search-button"), "正在搜索…", () => streamSearch(state.description,event=>updateSearchProgress(run,event)));
    finishSearchProgress(run,result,null);
    state.activeSearchRecord=result.search_id || null; $("last-search-record").hidden=!state.activeSearchRecord;
    feedback("search-feedback", `${searchEngineLabel(result.engine)} · ${result.message}${result.history_warning ? "\n"+result.history_warning : ""}`,result.engine === "partial" || !!result.history_warning);
    $("result-count").textContent = `${result.products.length} 个`;
    renderProductList($("product-list"),result.products,state.description);
    $("search-results").hidden = false;
  } catch (error) { finishSearchProgress(run,null,error); feedback("search-feedback", error.message, true); }
  finally {activeSearchRun=null;}
});

let dashboardRevision = 0;
async function loadDashboard() {
  const revision = ++dashboardRevision;
  try {
    const [status, watches, alerts, presets] = await Promise.all([api("/api/status"), api("/api/watches"), api("/api/alerts"), state.presets || api("/api/simulation-presets")]);
    if (revision !== dashboardRevision) return;
    state.status = status; state.watches = watches.watches; state.alerts = alerts.alerts; state.presets = presets;
    $("catalog-demo-note").hidden = !status.catalog_is_demo;
    if (!$("simulation-scenario").options.length) $("simulation-scenario").innerHTML = presets.scenarios.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
    $("global-error").hidden = true; $("connection").textContent = status.scheduler_error ? "检查异常，将重试" : status.scheduler_enabled ? "自动检查已开启" : "自动检查已关闭"; $("connection").classList.toggle("offline", !!status.scheduler_error);
    $("metric-watches").textContent = status.watch_count; $("metric-active").textContent = status.active_count; $("metric-samples").textContent = status.observation_count; $("metric-alerts").textContent = status.unread_count;
    $("monitor-watch-count").textContent = status.watch_count;
    $("monitor-watch-summary").textContent = status.watch_count ? `${status.watch_count} 项监控，${status.active_count} 项正在更新。查看价格走势、采样记录与购买建议。` : "添加商品后，在这里集中查看价格走势与采样记录。";
    $("nav-unread").textContent = status.unread_count; $("nav-unread").hidden = status.unread_count === 0;
    $("catalog-count").textContent = `${status.catalog_count.toLocaleString()} 个商品`;
    $("scheduler-detail").textContent = `后台检查${status.scheduler_enabled ? "已开启" : "已关闭"} · 最近轮询 ${date(status.scheduler_last_poll)}。应用运行期间按每项监控的间隔检查。`;
    const selectedExists = state.watches.some(w => w.id === state.selected);
    if (!selectedExists && state.tab !== "watch-detail") state.selected = state.watches[0]?.id || null;
    renderWatches(); renderAlerts();
    if (state.tab === "watch-detail") {
      if (selectedExists) {
        try {await loadDetail(state.selected);} catch(error) {if(state.tab === "watch-detail") renderWatchError(error.message);}
      } else renderWatchError("该监控不存在或已被删除，请返回“我的监控”选择其他商品。");
    }
  } catch (error) {
    if (revision !== dashboardRevision) return;
    $("connection").textContent = "连接已断开"; $("connection").classList.add("offline"); feedback("global-error", `无法连接监控服务：${error.message}。恢复后页面会自动重试。`, true);
  }
}
function renderWatches() {
  $("watch-count").textContent = state.watches.length;
  const filter = $("watch-filter").value;
  const watches = state.watches.filter(w => filter === "all" || (filter === "active" && w.active) || (filter === "paused" && !w.active) || (filter === "simulation" && w.mode === "simulation"));
  if (!watches.length) {
    $("watch-list").innerHTML = `<div class="empty-state"><span class="empty-icon">${icon("bag")}</span><h3>${state.watches.length ? "没有符合筛选的监控" : "还没有监控商品"}</h3><p>${state.watches.length ? "切换筛选条件查看其他监控。" : "先搜索商品并确认规格，<br>添加监控后就能在这里查看价格走势。"}</p>${state.watches.length ? "" : `<a class="button secondary" href="#monitor">去搜索商品 ${icon("arrowRight")}</a>`}</div>`; return;
  }
  $("watch-list").innerHTML = '<div class="watch-table-head"><span>商品 / 监控状态</span><span>当前价格</span><span>采集最低</span><span>操作</span></div>' + watches.map(w => `<a class="watch-row" href="#watch/${encodeURIComponent(w.id)}" data-watch="${esc(w.id)}" aria-label="查看价格走势：${esc(w.title)}"><div><div class="product-title">${esc(w.title)}</div><div class="watch-variant" title="${esc(variant(w))}">${esc(variant(w))}</div><div class="watch-tags"><span class="status-label ${w.active ? "" : "paused"}">${w.active ? "● 监控中" : "Ⅱ 已暂停"}</span>${modeTag(w.mode)}${w.last_error ? '<span class="tag simulation">更新异常</span>' : ""}</div></div><div class="watch-price">¥${amount(w.current_price)}<small>${date(w.current_observed_at)}</small></div><div class="watch-price low">¥${amount(w.low_price)}<small>${w.sample_count} 次采样</small></div><span class="button secondary watch-trend-link">查看价格走势 ${icon("arrowRight")}</span></a>`).join("");
  $("watch-list").querySelectorAll("[data-watch]").forEach(button => button.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); openWatch(button.dataset.watch);
  }));
  $("watch-list").querySelectorAll("[data-watch]").forEach(button => {
    const watch = watches.find(w => w.id === button.dataset.watch);
    if (watch?.simulation?.complete) button.querySelector(".status-label").textContent = "✓ 回放完成";
  });
}
$("watch-filter").addEventListener("change", renderWatches);
function chart(observations, lowMinor) {
  if (!observations.length) return '<div class="chart-empty">还没有价格记录</div>';
  const width = 560, height = 210, padL = 55, padR = 12, padT = 18, padB = 28;
  const amounts = observations.map(p => p.amount_minor), min = Math.min(...amounts, lowMinor), max = Math.max(...amounts);
  const extra = Math.max((max-min)*.22, max*.02, 1), lo = min-extra, hi = max+extra;
  const start = new Date(observations[0].observed_at).getTime(), end = new Date(observations.at(-1).observed_at).getTime();
  const x = p => end === start ? (padL+width-padR)/2 : padL+(new Date(p.observed_at).getTime()-start)/(end-start)*(width-padL-padR);
  const y = amount => padT+(hi-amount)/(hi-lo)*(height-padT-padB);
  const lowY = y(lowMinor);
  const grid = [0,.5,1].map(t => {const value = hi-(hi-lo)*t, pos = y(value);return `<line x1="${padL}" x2="${width-padR}" y1="${pos}" y2="${pos}" stroke="#edf1ee"/><text x="${padL-9}" y="${pos+3}" text-anchor="end" fill="#78867f" font-size="10">${(value/100).toFixed(2)}</text>`;}).join("");
  const points = observations.map(p => `${x(p)},${y(p.amount_minor)}`).join(" ");
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${observations.length} 条价格记录，已采集最低价 ${lowMinor/100} 元"><title>价格记录与已采集最低价</title>${grid}<line x1="${padL}" x2="${width-padR}" y1="${lowY}" y2="${lowY}" stroke="#81ab90" stroke-dasharray="4 4"/>${observations.length > 1 ? `<polyline points="${points}" fill="none" stroke="#1b6351" stroke-width="2.2" stroke-linejoin="round"/>` : ""}${observations.map(p => `<circle cx="${x(p)}" cy="${y(p.amount_minor)}" r="${observations.length > 70 ? 1.5 : 3.5}" fill="#1b6351" stroke="white" stroke-width="1.5"><title>${date(p.observed_at, true)} · ¥${amount(p.price)} · ${sourceLabel(p.source)}</title></circle>`).join("")}<text x="${padL}" y="${height-4}" fill="#78867f" font-size="10">${date(observations[0].observed_at)}</text>${end === start ? "" : `<text x="${width-padR}" y="${height-4}" text-anchor="end" fill="#78867f" font-size="10">${date(observations.at(-1).observed_at)}</text>`}</svg>`;
}
let watchDetailRevision = 0;
async function loadDetail(id) {
  const revision = ++watchDetailRevision;
  let data;
  try {data=await api(`/api/watches/${encodeURIComponent(id)}/history`);} catch(error) {
    if (revision !== watchDetailRevision || state.selected !== id || state.tab !== "watch-detail") return;
    throw error;
  }
  if (revision !== watchDetailRevision || state.selected !== id || state.tab !== "watch-detail") return;
  const sameWatch = state.history?.watch?.id === id;
  const sequenceOpen = sameWatch && !!$("detail-panel").querySelector('.simulation-summary details[open]');
  state.history = data;
  const w = data.watch, observations = data.observations;
  const simInput = sameWatch ? $("simulation-price")?.value : "";
  $("detail-panel").setAttribute("aria-busy","false");
  $("detail-panel").innerHTML = `<div class="detail-body"><div class="watch-product-heading"><h2>${esc(w.title)}</h2>${modeTag(w.mode)}<div class="detail-variant">${esc(variant(w))}</div></div>
      <div class="watch-detail-columns"><section class="watch-trend" aria-label="所选规格的价格曲线与采样">
        <div class="detail-prices"><div><span class="price-label">最近采样价格</span><strong class="large-price"><span>¥</span>${amount(w.current_price)}</strong><div class="price-change ${w.change_percent < 0 ? "down" : w.change_percent > 0 ? "up" : ""}">${w.change_percent === 0 ? "与首次采样持平" : `${w.change_percent < 0 ? "↓" : "↑"} ${Math.abs(w.change_percent)}% · 相比首次采样`}</div></div><div class="low-price"><span class="price-label">已采集最低价</span><strong>¥${amount(w.low_price)}</strong></div></div>
        <div class="chart-heading"><h3>价格轨迹 ${w.mode === "simulation" ? "· 模拟数据" : ""}</h3><span class="chart-legend">采集最低</span></div><div class="watch-chart-wrap">${chart(observations, w.low_minor)}</div>
        <div class="chart-caption"><span>${observations.length === 1 ? "首个采样点已记录，后续更新将形成曲线" : `共 ${data.total} 次采样${data.total > data.limit ? `，显示最近 ${data.limit} 次` : ""}`}</span><span>CNY</span></div>
        <h4 class="sample-heading">最近采样记录</h4><div class="sample-list">${observations.slice(-12).reverse().map(o => `<div class="sample-row"><span>${date(o.observed_at, true)} <span class="tag ${o.source === "simulation" ? "simulation" : ""}">${sourceLabel(o.source)}</span></span><strong>¥${amount(o.price)}</strong></div>`).join("")}</div>
        <p class="watch-history-scope">“历史最低”仅指此商品规格开始采集以来的记录。</p>
      </section><aside class="watch-support" aria-label="购买建议与监控设置">
        ${simulationPanel(w)}<section id="purchase-advice" class="purchase-advice" aria-label="购买建议"></section>
        <section class="watch-manage"><h3>监控管理</h3><div class="detail-actions"><button class="button secondary" id="refresh-watch" ${w.active ? "" : "disabled"}>${icon("refresh")}立即检查</button><button class="button secondary" id="toggle-watch">${w.active ? "暂停监控" : "恢复监控"}</button><button class="text-button" id="delete-watch">删除监控</button></div>
          <div class="detail-schedule">每 ${interval(w.interval_seconds)}检查 · ${w.active ? `下次 ${date(w.next_check_at)}` : "已暂停自动检查"}<br>最近检查 ${date(w.last_checked_at)} · 报价来源：${sourceLabel(w.source)}</div>
          ${w.last_error ? `<div class="notice error">${esc(w.last_error)}，将在后续检查中重试。</div>` : ""}
          ${w.mode === "simulation" ? '<form id="simulation-form" class="simulate-box"><label class="field-label" for="simulation-price">手动注入模拟报价（不改变自动事件序列）</label><div class="simulate-controls"><input id="simulation-price" type="number" min="0.01" max="1000000000" step="0.01" required placeholder="例如 89.90"><button class="button secondary" type="submit">写入模拟报价</button></div></form>' : '<div class="scope-note" style="margin-top:18px">当前使用静态目录与导入快照。需要新的价格记录时，请在数据管理中导入报价。</div>'}
          <div class="detail-schedule">监控 ID：<span style="overflow-wrap:anywhere">${esc(w.id)}</span></div>
        </section>
      </aside></div>
    </div>`;
  if ($("simulation-price") && simInput) $("simulation-price").value = simInput;
  if (w.simulation) {
    const sequence = $("detail-panel").querySelector('.simulation-summary details');
    if (sequence) sequence.open = sequenceOpen;
    if (w.simulation.engine === "replay") $("simulation-form")?.remove();
    if (w.simulation.complete) $("toggle-watch").hidden = true;
  }
  renderAdvice(w);
  $("detail-panel").querySelectorAll(".sample-row").forEach((row,index) => {
    const record = observations.slice(-12).reverse()[index];
    if (record.event) {const event = document.createElement("small"); event.className = "sample-event"; event.textContent = `第 ${record.simulation_tick+1} 步 · ${record.event}`; row.firstElementChild.append(event);}
  });
  if ($("restart-replay")) $("restart-replay").addEventListener("click", async event => {
    try {const result = await busy(event.currentTarget,"开始新回放…",() => post(`/api/watches/${id}/replay/restart`));state.selected=result.watch.id;updateRoute("watch-detail",true);toast("新回放已开始，上一轮记录已保留并暂停");await loadDashboard();} catch(error) {toast(error.message);}
  });
  $("refresh-watch").addEventListener("click", async event => {try {const result = await busy(event.currentTarget, "检查中…", () => post(`/api/watches/${id}/refresh`)); toast(result.status === "error" ? result.error : result.status === "skipped" ? "已有检查正在进行" : result.inserted ? "新报价已记录" : "已检查，尚无新的价格快照"); await loadDashboard();} catch(error) {toast(error.message);}});
  $("toggle-watch").addEventListener("click", async event => {try {await busy(event.currentTarget, "保存中…", () => api(`/api/watches/${id}`, {method:"PATCH", body:JSON.stringify({active:!w.active})})); toast(w.active ? "监控已暂停" : "监控已恢复"); await loadDashboard();} catch(error) {toast(error.message);}});
  $("delete-watch").addEventListener("click", () => {$("confirm-dialog").dataset.watch = id; $("confirm-dialog").showModal();});
  if ($("simulation-form")) $("simulation-form").addEventListener("submit", async event => {event.preventDefault(); const button = event.currentTarget.querySelector("button");try {const result = await busy(button, "记录中…", () => post(`/api/watches/${id}/simulate`, {price:$("simulation-price").value})); toast(result.alerts_created ? "模拟价格创下新低，已生成提醒" : "模拟报价已记录"); $("simulation-price").value = ""; await loadDashboard();} catch(error) {toast(error.message);}});
}
$("confirm-cancel").addEventListener("click", () => $("confirm-dialog").close());
$("confirm-delete").addEventListener("click", async event => {const id = $("confirm-dialog").dataset.watch;try {await busy(event.currentTarget, "删除中…", () => api(`/api/watches/${id}`, {method:"DELETE"})); $("confirm-dialog").close(); state.selected=null; changeTab("watches"); toast("监控及对应记录已删除"); await loadDashboard();} catch(error) {toast(error.message);}});

function alertRows(alerts) {
  if (!alerts.length) return `<div class="alert-empty">${icon("bell")}还没有低价提醒。后续报价低于此前采集最低价时，会显示在这里。</div>`;
  return alerts.map(a => `<article class="alert-row"><span class="alert-emblem">${icon("down")}</span><div class="alert-info"><h3>${a.is_read ? "" : '<span class="unread-dot" aria-label="未读"></span>'}${esc(a.title)}</h3><p><strong>¥${amount(a.price)}</strong> · 比此前最低 ¥${amount(a.previous_low)} 再降 ${a.drop_percent}% ${a.mode === "simulation" ? '<span class="tag simulation">模拟提醒</span>' : ""}</p><div class="alert-time">${date(a.observed_at, true)} · ${esc(Object.values(a.selections).join(" / ") || "无可选规格")}</div></div><div class="alert-side"><button class="text-button" data-alert-watch="${a.watch_id}">查看价格走势</button>${a.is_read ? '<span class="quiet-label">已读</span>' : `<button class="text-button" data-read-alert="${a.id}">标为已读</button>`}</div></article>`).join("");
}
function renderAlerts() {
  $("recent-alert-list").innerHTML = alertRows(state.alerts.slice(0,3)); $("alert-list").innerHTML = alertRows(state.alerts);
  document.querySelectorAll("[data-read-alert]").forEach(button => button.addEventListener("click", async () => {try {await post(`/api/alerts/${button.dataset.readAlert}/read`); await loadDashboard();} catch(error) {toast(error.message);}}));
  document.querySelectorAll("[data-alert-watch]").forEach(button => button.addEventListener("click", () => openWatch(button.dataset.alertWatch)));
}

let quoteRevision = 0, productRevision = 0;
function productDetails(product) {
  const groups = Object.entries(product.option_groups || {});
  const attributes = (product.attributes || []).filter(value => String(value).trim());
  const chips = values => values.map(v => `<span class="spec-chip ${v.available ? "" : "unavailable"}">${esc(v.value)}${v.available ? "" : " · 不可选"}</span>`).join("");
  return `<div class="dialog-product"><h3>${esc(product.title)}</h3><div class="product-overview"><dl class="product-metadata"><div><dt>店铺</dt><dd>${esc(product.shop || "目录未提供")}</dd></div><div><dt>分类</dt><dd>${esc(product.category || "目录未提供")}</dd></div><div><dt>商品 ID</dt><dd>${esc(product.asin)}</dd></div></dl><div class="product-reference-price"><span>目录参考价</span><strong>${product.price == null ? "待确认" : "¥"+amount(product.price)}</strong><small>具体规格价格以确认结果为准</small></div></div></div>
    <div data-detail-only><section class="product-information" aria-labelledby="product-attributes-title"><h3 id="product-attributes-title">商品参数</h3>${attributes.length ? `<ul class="product-attributes">${attributes.map(value => `<li>${esc(value)}</li>`).join("")}</ul>` : '<p class="product-empty">目录暂未提供商品参数。</p>'}</section>
    <section class="product-information" aria-labelledby="product-description-title"><h3 id="product-description-title">商品介绍</h3><p class="product-description">${esc(product.description?.trim() || "目录暂未提供商品介绍，请结合标题、参数和规格核对商品。")}</p></section>
    <section class="product-information" aria-labelledby="product-specifications-title"><h3 id="product-specifications-title">可选规格${groups.length ? `<span>${groups.length} 组</span>` : ""}</h3>${groups.length ? groups.map(([group, values]) => `<div class="product-spec-group"><h4>${esc(group)}<span>${values.length} 项</span></h4><div class="spec-chips">${chips(values.slice(0,4))}</div>${values.length > 4 ? `<details class="more-specs"><summary>查看全部 ${values.length} 项</summary><div class="spec-chips">${chips(values.slice(4))}</div></details>` : ""}${!values.length ? '<p class="product-empty">暂无可选值。</p>' : ""}</div>`).join("") : '<p class="product-empty">该商品没有可选规格，设置监控时会按商品本身记录价格。</p>'}</section></div>`;
}
function productStage(configure) {
  ++quoteRevision;
  $("watch-settings").hidden = !configure;
  $("dialog-product").querySelectorAll("[data-detail-only]").forEach(el => {el.hidden = configure;});
  $("dialog-title").textContent = configure ? "设置价格监控" : "商品详情";
  $("start-watch").hidden = configure;
  $("add-watch").hidden = !configure;
  $("back-to-product").hidden = !configure;
  $("cancel-watch").hidden = configure;
  $("dialog-error").hidden = true;
  $("product-dialog").scrollTop = 0;
  if (configure) { updateSimulationSettings(); updateQuote(); }
}
async function openProduct(asin, description = state.description) {
  const revision = ++productRevision;
  state.productRequest = description;
  state.product = null;
  $("watch-form").reset();
  $("option-fields").innerHTML = "";
  $("quote-preview").textContent = "请选择完整规格";
  $("quote-preview").classList.remove("invalid");
  $("add-watch").disabled = true;
  $("start-watch").disabled = true;
  $("retry-product").hidden = true;
  $("product-dialog").dataset.asin = asin;
  $("dialog-product").innerHTML = '<p class="product-loading" role="status">正在读取商品介绍、参数与可选规格…</p>';
  $("dialog-product").setAttribute("aria-busy", "true");
  productStage(false);
  if (!$("product-dialog").open) $("product-dialog").showModal();
  try {
    const product = await api(`/api/products/${encodeURIComponent(asin)}`);
    if (revision !== productRevision || !$("product-dialog").open) return;
    state.product = product;
    $("dialog-product").innerHTML = productDetails(product);
    $("option-fields").innerHTML = Object.entries(state.product.option_groups).map(([group, values]) => `<label class="field-label option-field">${esc(group)}<select data-option="${esc(group)}" required><option value="">请选择${esc(group)}</option>${values.map(v => `<option value="${esc(v.value)}" ${v.available ? "" : "disabled"}>${esc(v.value)}${v.available ? "" : "（不可选）"}</option>`).join("")}</select></label>`).join("");
    $("option-fields").querySelectorAll("select").forEach(select => {
      const available = [...select.options].filter(o => o.value && !o.disabled);
      if (available.length === 1) select.value = available[0].value;
      select.addEventListener("change", updateQuote);
    });
    $("option-help").textContent = Object.keys(product.option_groups).length ? "选择完整规格后确认基准价，每个规格组合单独记录价格历史。" : "该商品没有可选规格，将按商品本身记录价格历史。";
    $("start-watch").disabled = false;
  } catch(error) {
    if (revision !== productRevision || !$("product-dialog").open) return;
    $("dialog-product").innerHTML = '<p class="product-empty">未能读取商品详情，可以重新加载或关闭后查看其他商品。</p>';
    feedback("dialog-error", error.message, true); $("retry-product").hidden = false;
  } finally {if (revision === productRevision) $("dialog-product").setAttribute("aria-busy", "false");}
}
function selections() {return Object.fromEntries([...$("option-fields").querySelectorAll("select")].filter(s => s.value).map(s => [s.dataset.option, s.value]));}
async function updateQuote() {
  if (!state.product || $("watch-settings").hidden) return;
  const revision = ++quoteRevision; $("add-watch").disabled = true;
  $("quote-preview").classList.remove("invalid"); $("quote-preview").textContent = "正在确认目录基准价…";
  try {
    const result = await post(`/api/products/${encodeURIComponent(state.product.asin)}/quote`, {selections:selections()});
    if (revision !== quoteRevision) return;
    $("quote-preview").classList.remove("invalid"); $("quote-preview").innerHTML = `<span>${Object.keys(state.product.option_groups).length ? "所选规格目录基准价" : "商品目录基准价"}</span><strong>¥${amount(result.price)}</strong>`; $("add-watch").disabled = false;
  } catch(error) {if (revision !== quoteRevision) return; $("quote-preview").classList.add("invalid"); $("quote-preview").textContent = error.message;}
}
$("start-watch").addEventListener("click", () => {if (state.product) {productStage(true); $("watch-settings").querySelector("select").focus({preventScroll:true});}});
$("back-to-product").addEventListener("click", () => {productStage(false); $("start-watch").focus({preventScroll:true});});
$("retry-product").addEventListener("click", () => openProduct($("product-dialog").dataset.asin,state.productRequest));
$("product-dialog").addEventListener("close", () => {++productRevision; ++quoteRevision; state.product = null;});
$("close-dialog").addEventListener("click", () => $("product-dialog").close()); $("cancel-watch").addEventListener("click", () => $("product-dialog").close());
$("watch-mode").addEventListener("change", () => {if ($("watch-mode").value === "simulation") $("watch-interval").value="30"; updateSimulationSettings();});
["simulation-engine","simulation-scenario","simulation-period","watch-interval"].forEach(id => $(id).addEventListener("change",updateSimulationSettings));
$("watch-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!state.product || $("watch-settings").hidden) return; $("dialog-error").hidden = true;
  try {
    const sim = $("watch-mode").value === "simulation" ? {simulation:{engine:$("simulation-engine").value,scenario:$("simulation-engine").value === "replay" ? $("simulation-scenario").value : null,seed:$("simulation-engine").value === "replay" ? 42 : Number($("simulation-seed").value),tick_seconds:Number($("simulation-period").value)}} : {};
    const result = await busy($("add-watch"), "正在加入…", () => post("/api/watches", {asin:state.product.asin, selections:selections(), request:state.productRequest, mode:$("watch-mode").value, interval_seconds:Number($("watch-interval").value),...sim}));
    state.selected = result.watch.id; $("product-dialog").close();
    toast(result.created ? "已加入监控，首次价格已记录" : "该商品规格已在监控中，保留原有历史"); await loadDashboard();
    if (state.tab === "monitor") document.querySelector(".monitor-entry").scrollIntoView({block:"center", behavior:"instant"});
  } catch(error) {feedback("dialog-error", error.message, true);}
});

$("import-file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 900000) {feedback("import-feedback", "文件过大，请分批导入，每批最多 1000 条报价。", true);return;}
  $("import-json").value = await file.text(); feedback("import-feedback", `已读取 ${file.name}，检查后点击导入快照。`); event.target.value = "";
});
$("import-example").addEventListener("click", () => {
  const w = state.watches.find(w => w.id === state.selected);
  if (!w) {feedback("import-feedback", "请先添加并选中一个监控商品。", true);return;}
  $("import-json").value = JSON.stringify({observations:[{watch_id:w.id, price:w.current_price, observed_at:new Date().toISOString(), currency:"CNY", mode:w.mode}]}, null, 2);
  feedback("import-feedback", "已填入所选商品的当前价格示例，请修改为实际观测到的价格与时间。");
});
$("import-submit").addEventListener("click", async event => {
  feedback("import-feedback", "");
  try {let data;try {data = JSON.parse($("import-json").value);} catch {throw new Error("JSON 格式不正确，请检查引号、逗号和括号。");}
    const result = await busy(event.currentTarget, "导入中…", () => post("/api/prices/import", data));
    feedback("import-feedback", `已新增 ${result.inserted} 条价格记录，生成 ${result.alerts_created} 条低价提醒，跳过 ${result.duplicates} 条重复记录。`); await loadDashboard();
  } catch(error) {feedback("import-feedback", error.message, true);}
});
hydrateIcons();
$("today").textContent = new Date().toLocaleDateString("zh-CN", {year:"numeric", month:"long", day:"numeric", weekday:"long"});
restoreRoute(true);
loadDashboard();
setInterval(() => {if (!document.hidden && !$("product-dialog").open && !$("confirm-dialog").open && !["INPUT","SELECT","TEXTAREA"].includes(document.activeElement?.tagName)) loadDashboard();}, 10000);
