"use strict";
const $ = (id) => document.getElementById(id);
let state = null;
let busy = false;
let noticeTimer;
const traces = new Map();
const labels = {programme: "Programme", response_language: "Response language", response_style: "Response style"};
const viewTitles = {profile: "My profile", memory: "Remembered facts", approvals: "Approvals", tickets: "Support requests", activity: "Traces & audit"};
let conversationTitle = "";
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use"); use.setAttribute("href", `#i-${name}`); svg.append(use);
  return svg;
}
function initials(name) { return name.split(" ").map(n => n[0]).join("").slice(0, 2); }
function storage(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { return null; }
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  document.querySelectorAll(".theme-toggle").forEach(button => {
    button.querySelector("use").setAttribute("href", dark ? "#i-moon" : "#i-sun");
    button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  });
}
applyTheme(storage("theme") === "dark" ? "dark" : "light");
document.querySelectorAll(".theme-toggle").forEach(b => b.addEventListener("click", () => { const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; applyTheme(next); storage("theme", next); }));
const mobile = window.matchMedia("(max-width: 900px)");
function setSidebar(open) {
  if (mobile.matches) { document.body.classList.toggle("sidebar-open", open); $("sidebar-backdrop").hidden = !open; }
  else { $("workspace").classList.toggle("sidebar-collapsed", !open); storage("sidebar", open ? "open" : "collapsed"); }
  $("menu-open").setAttribute("aria-expanded", String(open));
  if (open) $("sidebar-toggle").focus(); else $("menu-open").focus();
}
$("workspace").classList.toggle("sidebar-collapsed", storage("sidebar") === "collapsed");
$("menu-open").addEventListener("click", () => setSidebar(true));
$("sidebar-toggle").addEventListener("click", () => setSidebar(false));
$("sidebar-backdrop").addEventListener("click", () => setSidebar(false));
mobile.addEventListener("change", () => { document.body.classList.remove("sidebar-open"); $("sidebar-backdrop").hidden = true; });
function closeAccountMenu() { $("account-menu").hidden = true; $("account-button").setAttribute("aria-expanded", "false"); }
$("account-button").addEventListener("click", (event) => { event.stopPropagation(); const open = $("account-menu").hidden; $("account-menu").hidden = !open; $("account-button").setAttribute("aria-expanded", String(open)); });
document.addEventListener("click", (event) => { if (!$("account-menu").hidden && !$("account-menu").contains(event.target)) closeAccountMenu(); });
$("logout").addEventListener("click", () => { if (busy) return; closeAccountMenu(); document.body.classList.remove("sidebar-open"); $("sidebar-backdrop").hidden = true; });
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("account-menu").hidden) { closeAccountMenu(); $("account-button").focus(); }
  else if (document.body.classList.contains("sidebar-open")) setSidebar(false);
});
$("password-toggle").addEventListener("click", () => {
  const show = $("password").type === "password"; $("password").type = show ? "text" : "password";
  $("password-toggle").setAttribute("aria-pressed", String(show)); $("password-toggle").setAttribute("aria-label", show ? "Hide password" : "Show password");
  $("password-toggle").querySelector("use").setAttribute("href", show ? "#i-eye" : "#i-eye-off");
});
const loginRoles = {
  student: {label: "Student ID", placeholder: "STU001", intro: "Continue to your student account. Your session gives the agent access to your own records."},
  staff: {label: "Staff ID", placeholder: "STF001", intro: "Student services staff can review and update support requests."},
  admin: {label: "Admin ID", placeholder: "ADM001", intro: "Administrators also see all accounts and the full audit log."},
};
function selectedRole() { return document.querySelector("input[name=role]:checked").value; }
function updateLoginRole() {
  const role = selectedRole(), copy = loginRoles[role];
  $("account-id-label").textContent = copy.label; $("account-id").placeholder = copy.placeholder; $("login-intro").textContent = copy.intro;
  document.querySelectorAll("[data-demo-role]").forEach(b => b.hidden = b.dataset.demoRole !== role);
  $("account-id").value = ""; $("login-error").hidden = true;
}
document.querySelectorAll("input[name=role]").forEach(r => r.addEventListener("change", updateLoginRole));
document.querySelectorAll("[data-demo-id]").forEach(b => b.addEventListener("click", () => { $("account-id").value = b.dataset.demoId; $("password").focus(); }));
function setCount(node, value) { node.textContent = value; node.hidden = !value; }
async function refreshApprovalBadge() {
  try {
    const {pending_approvals: pending, ticket_updates: updates} = await api("/api/notifications");
    setCount($("approval-count"), pending); setCount($("ticket-count"), updates); $("approval-dot").hidden = !(pending || updates);
    const parts = [pending && `${pending} approval${pending > 1 ? "s" : ""} pending`, updates && `${updates} request update${updates > 1 ? "s" : ""}`].filter(Boolean);
    document.querySelector(".bell").setAttribute("aria-label", parts.length ? `Notifications: ${parts.join(", ")}` : "Approvals");
    document.querySelector(".bell").dataset.view = pending || !updates ? "approvals" : "tickets";
  } catch { /* badge is optional */ }
}
function setTitle(text) { $("topbar-title").textContent = text; }
let currentConversation = null;
function filterRecent() {
  const term = $("chat-search").value.trim().toLowerCase();
  $("recent-list").querySelectorAll("li").forEach(li => li.hidden = !!term && !li.textContent.toLowerCase().includes(term));
}
$("chat-search").addEventListener("input", filterRecent);
async function loadHistory() {
  const {items, current} = await api("/api/conversations"); const list = $("recent-list"); list.replaceChildren();
  $("recent-empty").hidden = !!items.length;
  for (const item of items) {
    const row = el("li", undefined, "history-row"), button = el("button", undefined, "recent-item"); button.type = "button";
    button.append(icon("chat"), el("span", item.title)); button.title = `${item.title} · ${date(item.updated_at)}`;
    if (item.id === currentConversation) { button.classList.add("active"); button.setAttribute("aria-current", "true"); }
    button.addEventListener("click", async () => { if (busy) return; await openConversation(item.id); if (mobile.matches) setSidebar(false); });
    const remove = el("button", undefined, "icon-button history-delete"); remove.type = "button"; remove.setAttribute("aria-label", `Delete ${item.title}`); remove.title = "Delete conversation"; remove.append(icon("trash"));
    remove.addEventListener("click", async () => {
      if (busy || !confirm(`Delete “${item.title}”? This removes its messages permanently.`)) return;
      try { await api(`/api/conversations/${encodeURIComponent(item.id)}`, {method: "DELETE"}); if (item.id === currentConversation) clearConversation(); await loadHistory(); notify("Conversation deleted."); }
      catch (error) { notify(error.message); }
    });
    row.append(button, remove); list.append(row);
  }
  filterRecent();
  return {items, current};
}
async function openConversation(id, {background = false} = {}) {
  const {conversation, messages} = await api(`/api/conversations/${encodeURIComponent(id)}/open`, {method: "POST"});
  clearConversation(); currentConversation = conversation.id; conversationTitle = conversation.title;
  // A background resume must not pull the student away from a view they opened meanwhile.
  if (!background || !$("view-chat").hidden) await showView("chat");
  let lastTrace = null;
  for (const item of messages) {
    const node = message(item.role, item.content);
    if (item.role === "assistant" && item.trace) { traces.set(item.trace.id, item.trace); attachEvidence(node, item.trace); lastTrace = item.trace; }
  }
  if (lastTrace) renderTrace(lastTrace);
  await loadHistory();
}
function resizeComposer() { const box = $("message"); box.style.height = "auto"; box.style.height = `${Math.min(box.scrollHeight, 180)}px`; }
$("message").addEventListener("input", resizeComposer);
function notify(message) {
  $("notice").textContent = message; $("notice").hidden = false;
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $("notice").hidden = true, 6500);
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {"Content-Type": "application/json", "X-CSRF-Token": state?.csrf_token || "", ...options.headers}});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !path.endsWith("/login")) { clearConversation(); await initialize(); }
    throw new Error(data.error || "The request failed. Please try again.");
  }
  return data;
}
function date(value) { return new Date(value).toLocaleString(undefined, {dateStyle: "short", timeStyle: "short"}); }
function empty(container, text) { container.replaceChildren(el("p", text, "empty-state")); }
function clearConversation() {
  document.querySelectorAll(".message").forEach(n => n.remove());
  $("welcome").hidden = false; $("message").value = ""; traces.clear(); resizeComposer();
  $("trace-content").replaceChildren(el("p", "Your next answer’s evidence will appear here.", "empty-evidence"));
  currentConversation = null; $("recent-list").querySelectorAll(".recent-item.active").forEach(b => { b.classList.remove("active"); b.removeAttribute("aria-current"); });
  conversationTitle = ""; if (!$("view-chat").hidden) setTitle("New conversation");
}
async function initialize() {
  state = await api("/api/session");
  $("login-screen").hidden = !!(state.student || state.staff); $("workspace").hidden = !state.student; $("staff-workspace").hidden = !state.staff;
  if (state.staff) return initializeStaff(state.staff);
  if (!state.student) return;
  const s = state.student;
  $("student-name").textContent = s.name; $("student-meta").textContent = `${s.id} · ${s.programme}`;
  $("first-name").textContent = s.name.split(" ")[0];
  $("avatar").textContent = initials(s.name); $("topbar-avatar").textContent = initials(s.name); $("topbar-avatar").title = s.name;
  refreshApprovalBadge();
  $("config-banner").hidden = state.configured;
  $("connection-label").textContent = state.configured ? "Connected to Groq" : "Groq setup needed";
  $("memory-key").replaceChildren(...Object.keys(state.memory_options).map(k => { const option = el("option", labels[k]); option.value = k; return option; }));
  updateMemoryOptions();
  // After a page reload, reopen the conversation this session was in.
  const {items, current} = await loadHistory();
  if (!currentConversation && items.some(i => i.id === current)) await openConversation(current, {background: true});
}
function updateMemoryOptions() {
  $("memory-value").replaceChildren(...state.memory_options[$("memory-key").value].map(v => { const option = el("option", v); option.value = v; return option; }));
}
async function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.hidden = v.id !== `view-${name}`);
  document.querySelectorAll(".nav-item").forEach(b => { b.classList.toggle("active", b.dataset.view === name); if (b.dataset.view === name) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
  document.querySelector(".student-link").classList.toggle("active", name === "profile");
  setTitle(viewTitles[name] || conversationTitle || "New conversation"); closeAccountMenu();
  if (mobile.matches && document.body.classList.contains("sidebar-open")) { document.body.classList.remove("sidebar-open"); $("sidebar-backdrop").hidden = true; }
  try {
    if (name === "profile") await loadProfile();
    if (name === "memory") await loadMemory();
    if (name === "approvals") await loadApprovals();
    if (name === "tickets") await loadTickets();
    if (name === "activity") await loadActivity();
  } catch (error) { notify(error.message); }
}
// Read data-view at click time: the bell retargets itself to whichever view has news.
document.querySelectorAll("[data-view]").forEach(b => b.addEventListener("click", () => showView(b.dataset.view)));
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $("login-error").hidden = true;
  const role = selectedRole(), id = $("account-id").value.trim(), password = $("password").value;
  try {
    if (role === "student") state = await api("/api/login", {method: "POST", body: JSON.stringify({student_id: id, password})});
    else state = await api("/api/staff/login", {method: "POST", body: JSON.stringify({staff_id: id, role, password})});
    $("password").value = ""; clearConversation(); await initialize();
    if (role === "student") await showView("chat");
  } catch (error) { $("login-error").textContent = error.message; $("login-error").hidden = false; }
  finally { button.disabled = false; }
});
async function signOut() {
  if (busy) return notify("Please wait for the current response before signing out.");
  try { await api("/api/logout", {method: "POST"}); clearConversation(); await initialize(); } catch (error) { notify(error.message); }
}
$("logout").addEventListener("click", signOut);
$("staff-logout").addEventListener("click", signOut);
$("new-chat").addEventListener("click", async () => {
  if (busy) return;
  busy = true; $("message").disabled = true; $("send").disabled = true; $("new-chat").disabled = true;
  try { await api("/api/conversation/new", {method:"POST"}); clearConversation(); await showView("chat"); notify("New conversation started. Your earlier chats are in Chat history."); }
  catch (error) { notify(error.message); }
  finally { busy = false; $("message").disabled = false; $("send").disabled = false; $("new-chat").disabled = false; $("message").focus(); }
});
document.querySelectorAll("[data-prompt]").forEach(b => b.addEventListener("click", () => { $("message").value = b.dataset.prompt; $("message").focus(); }));
document.querySelectorAll("[data-prompt-view]").forEach(b => b.addEventListener("click", async () => { await showView("chat"); $("message").value = b.dataset.promptView; resizeComposer(); $("message").focus(); }));
const inr = new Intl.NumberFormat("en-IN", {style: "currency", currency: "INR", maximumFractionDigits: 0});
async function loadProfile() {
  const {profile: p, stats} = await api("/api/profile");
  $("profile-avatar").textContent = initials(p.name); $("profile-name").textContent = p.name; $("profile-id").textContent = `Student ID ${p.id}`;
  $("profile-programme").textContent = p.programme; $("profile-email").textContent = p.email;
  const outstanding = Math.max(p.fee_total - p.fee_paid, 0), percent = p.fee_total ? Math.min(100, Math.round(p.fee_paid / p.fee_total * 100)) : 100;
  $("fee-outstanding").textContent = inr.format(outstanding);
  $("fee-badge").textContent = outstanding ? "Balance due" : "Paid in full"; $("fee-badge").classList.toggle("warn", !!outstanding);
  $("fee-progress-bar").style.width = `${percent}%`; $("fee-progress").setAttribute("aria-valuenow", String(percent));
  $("fee-progress-label").textContent = `${inr.format(p.fee_paid)} paid of ${inr.format(p.fee_total)} (${percent}%)`;
  $("fee-due").textContent = outstanding ? `Due by ${new Date(p.fee_due).toLocaleDateString(undefined, {dateStyle: "medium"})}` : "Nothing left to pay this term.";
  $("scholarship-amount").textContent = inr.format(p.scholarship_amount || 0);
  $("scholarship-badge").textContent = p.scholarship_status || "None"; $("scholarship-badge").classList.toggle("warn", p.scholarship_status !== "approved");
  $("scholarship-name").textContent = p.scholarship || "No scholarship on record.";
  document.querySelectorAll("[data-stat]").forEach(tile => tile.querySelector("strong").textContent = String(stats[tile.dataset.stat] ?? 0));
}
// Minimal Markdown for model answers. Builds DOM nodes with textContent only, so model output never becomes HTML.
function inlineMarkdown(parent, text) {
  const pattern = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\s][^*\n]*\*|\[[A-Z][A-Z0-9]*-\d+\])/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parent.append(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**") || token.startsWith("__")) parent.append(el("strong", token.slice(2, -2)));
    else if (token.startsWith("`")) parent.append(el("code", token.slice(1, -1)));
    else if (token.startsWith("[")) parent.append(el("span", token.slice(1, -1), "cite"));
    else parent.append(el("em", token.slice(1, -1)));
    last = match.index + token.length;
  }
  if (last < text.length) parent.append(text.slice(last));
}
function renderMarkdown(text) {
  const root = document.createDocumentFragment(), lines = text.replace(/\r\n?/g, "\n").split("\n");
  const bullet = /^\s*[-*•]\s+(.*)$/, numbered = /^\s*\d+[.)]\s+(.*)$/, heading = /^\s*#{1,6}\s+(.*)$/, fence = /^\s*```/;
  const tableRow = l => /^\s*\|.*\|\s*$/.test(l), tableRule = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const blockStart = (l, next) => bullet.test(l) || numbered.test(l) || heading.test(l) || fence.test(l) || (tableRow(l) && next !== undefined && tableRule(next));
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (fence.test(line)) {
      const code = []; i++;
      while (i < lines.length && !fence.test(lines[i])) code.push(lines[i++]);
      i++; root.append(el("pre", code.join("\n"))); continue;
    }
    if (heading.test(line)) { const h = el("h4"); inlineMarkdown(h, line.match(heading)[1]); root.append(h); i++; continue; }
    if (tableRow(line) && i + 1 < lines.length && tableRule(lines[i + 1])) {
      const wrap = el("div", undefined, "md-table"), table = el("table"), head = el("thead"), body = el("tbody"), headRow = el("tr");
      for (const c of cells(line)) { const th = el("th"); inlineMarkdown(th, c); headRow.append(th); }
      head.append(headRow); i += 2;
      while (i < lines.length && tableRow(lines[i])) { const tr = el("tr"); for (const c of cells(lines[i])) { const td = el("td"); inlineMarkdown(td, c); tr.append(td); } body.append(tr); i++; }
      table.append(head, body); wrap.append(table); root.append(wrap); continue;
    }
    if (bullet.test(line) || numbered.test(line)) {
      const pattern = bullet.test(line) ? bullet : numbered, list = el(pattern === bullet ? "ul" : "ol");
      while (i < lines.length && pattern.test(lines[i])) {
        const li = el("li"); inlineMarkdown(li, lines[i].match(pattern)[1]); i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !blockStart(lines[i], lines[i + 1])) { li.append(" "); inlineMarkdown(li, lines[i].trim()); i++; }
        list.append(li);
      }
      root.append(list); continue;
    }
    const p = el("p"); inlineMarkdown(p, line.trim()); i++;
    while (i < lines.length && lines[i].trim() && !blockStart(lines[i], lines[i + 1])) { p.append(el("br")); inlineMarkdown(p, lines[i].trim()); i++; }
    root.append(p);
  }
  return root;
}
function setAnswer(node, text) {
  const body = node.querySelector(".message-text"); body.classList.add("md"); body.replaceChildren(renderMarkdown(text));
}
function message(role, text) {
  $("welcome").hidden = true;
  const node = el("article", undefined, `message ${role}`);
  node.append(el("span", role === "user" ? "You" : "Kaiju", "message-author"), el("div", role === "user" ? text : undefined, "message-text"));
  if (role === "assistant") setAnswer(node, text);
  $("messages").append(node); $("messages").scrollTop = $("messages").scrollHeight; node.scrollIntoView({block: "nearest"});
  return node;
}
function attachEvidence(node, trace) {
  const link = el("button", `View evidence · ${(trace.latency_ms / 1000).toFixed(2)} s`, "trace-link");
  link.addEventListener("click", () => { renderTrace(trace); $("trace-content").scrollIntoView({block: "nearest"}); }); node.append(link);
}
$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (busy) return;
  const question = $("message").value.trim(); if (!question) return;
  busy = true; $("send").disabled = true; $("new-chat").disabled = true;
  message("user", question); $("message").value = ""; resizeComposer();
  if (!conversationTitle) { conversationTitle = question.length > 60 ? `${question.slice(0, 57)}…` : question; setTitle(conversationTitle); }
  const pending = message("assistant", "Checking what you need…"); pending.classList.add("pending");
  try {
    const data = await api("/api/chat", {method: "POST", body: JSON.stringify({message: question})});
    setAnswer(pending, data.answer);
    if (data.approvals.length) refreshApprovalBadge();
    currentConversation = data.conversation_id; loadHistory().catch(() => { /* history list is optional */ });
    traces.set(data.trace.id, data.trace); renderTrace(data.trace); attachEvidence(pending, data.trace);
    if (data.approvals.length) {
      const box = el("div", undefined, "pending-note"); box.append(el("p", "A programme change is waiting for your confirmation."));
      const review = el("button", "Review change", "secondary"); review.addEventListener("click", () => showView("approvals")); box.append(review); pending.append(box);
    }
  } catch (error) { pending.querySelector(".message-text").replaceChildren(error.message); }
  finally { pending.classList.remove("pending"); busy = false; $("send").disabled = false; $("new-chat").disabled = false; $("messages").scrollTop = $("messages").scrollHeight; $("message").focus(); }
});
$("message").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("chat-form").requestSubmit(); } });
function renderTrace(trace) {
  const root = $("trace-content"); root.replaceChildren();
  const stats = el("dl", undefined, "trace-stats");
  for (const [label, value] of [["Response time", `${(trace.latency_ms / 1000).toFixed(2)} s`], ["Model calls", trace.model_calls], ["Input tokens", trace.input_tokens ?? "Not reported"], ["Output tokens", trace.output_tokens ?? "Not reported"]]) {
    const part = el("div"); part.append(el("dt", label), el("dd", String(value))); stats.append(part);
  }
  root.append(stats, el("p", `Run status: ${trace.status}`, "small muted"));
  const tools = el("section", undefined, "trace-section"); tools.append(el("h4", "Tools & permission decisions"));
  if (!trace.tools.length) tools.append(el("p", "No tools called.", "small muted"));
  for (const tool of trace.tools) { const step = el("div", undefined, "trace-step"); step.append(el("strong", tool.name), el("span", `${tool.decision}${tool.approval_status ? " · approval " + tool.approval_status : ""}${tool.error ? " · " + tool.error : ""}`)); tools.append(step); }
  root.append(tools);
  const policy = el("section", undefined, "trace-section"); policy.append(el("h4", "Policy evidence"));
  if (!trace.retrieved_evidence.length) policy.append(el("p", "No policy excerpts used.", "small muted"));
  for (const chunk of trace.retrieved_evidence) { const details = el("details", undefined, "evidence-chunk"); details.append(el("summary", `${chunk.id} · ${chunk.title}`), el("p", chunk.text)); policy.append(details); }
  root.append(policy);
  const memory = el("section", undefined, "trace-section"); memory.append(el("h4", "Remembered context"));
  memory.append(el("p", trace.memory_used.length ? trace.memory_used.map(m => `${labels[m.key] || m.key}: ${m.value}`).join(" · ") : "No saved preferences selected.", "small muted")); root.append(memory);
}
async function loadMemory() {
  const {items} = await api("/api/memory"); const list = $("memory-list"); list.replaceChildren();
  if (!items.length) return empty(list, "Nothing remembered yet. Add a preference below, or explicitly ask the agent to remember one.");
  for (const item of items) {
    const row = el("article", undefined, "record"); const content = el("div", undefined, "record-content");
    content.append(el("h3", labels[item.key]), el("p", item.value), el("small", `Saved ${date(item.updated_at)}`));
    const remove = el("button", "Forget", "secondary"); remove.setAttribute("aria-label", `Forget ${labels[item.key]}`);
    remove.addEventListener("click", async () => { try { await api(`/api/memory/${encodeURIComponent(item.key)}`, {method: "DELETE"}); await loadMemory(); notify("Preference removed."); } catch (error) { notify(error.message); } });
    row.append(content, remove); list.append(row);
  }
}
$("memory-key").addEventListener("change", updateMemoryOptions);
$("memory-form").addEventListener("submit", async (event) => {
  event.preventDefault(); event.submitter.disabled = true;
  try { await api("/api/memory", {method: "POST", body: JSON.stringify({key: $("memory-key").value, value: $("memory-value").value, consent: $("memory-consent").checked})}); $("memory-consent").checked = false; await loadMemory(); notify("Preference saved for future sessions."); }
  catch (error) { notify(error.message); } finally { event.submitter.disabled = false; }
});
async function loadApprovals() {
  const {items} = await api("/api/approvals"); const list = $("approvals-list"); list.replaceChildren(); refreshApprovalBadge();
  if (!items.length) return empty(list, "No changes awaiting review. Ask the agent to change your programme to try the approval flow.");
  for (const item of items) {
    const row = el("article", undefined, "record"); const content = el("div", undefined, "record-content");
    const expired = item.status === "pending" && new Date(item.expires_at) <= new Date();
    content.append(el("h3", "Programme change"), el("p", `${item.old_value} → ${item.new_value}`), el("small", `Requested ${date(item.created_at)} · Expires ${date(item.expires_at)}`));
    const actions = el("div", undefined, "record-actions");
    if (item.status === "pending" && !expired) {
      for (const [decision, label, className] of [["reject", "Reject", "secondary"], ["confirm", "Confirm change", "primary"]]) {
        const button = el("button", label, className); button.addEventListener("click", async () => {
          actions.querySelectorAll("button").forEach(b => b.disabled = true);
          try { const result = await api(`/api/approvals/${item.id}/decision`, {method: "POST", body: JSON.stringify({decision})}); notify(result.status === "awaiting_staff" ? "Sent to Student Services for review. Your record changes only after staff approve it." : "Request rejected. Your record is unchanged."); }
          catch (error) { notify(error.message); } finally { await loadApprovals(); }
        }); actions.append(button);
      }
    } else {
      actions.append(el("span", expired ? "expired" : approvalLabels[item.status] || item.status, `badge${item.status === "awaiting_staff" ? " warn" : ""}`));
      if (item.reviewed_at) content.append(el("small", `Reviewed by Student Services ${date(item.reviewed_at)}`));
    }
    row.append(content, actions); list.append(row);
  }
}
const approvalLabels = {pending: "Needs your confirmation", awaiting_staff: "Awaiting staff review", approved: "Approved", rejected: "Rejected", stale: "Outdated"};
function ticketThread(item, viewer) {
  const thread = el("div", undefined, "thread");
  for (const note of item.notes) {
    const mine = note.author_role === viewer, bubble = el("div", undefined, `note ${note.author_role}${mine ? " mine" : ""}`);
    bubble.append(el("strong", mine ? "You" : note.author_role === "staff" ? `${note.author_name} · Student Services` : note.author_name), el("p", note.body), el("small", date(note.created_at)));
    thread.append(bubble);
  }
  return thread;
}
function replyForm(path, label, onSent) {
  const form = el("form", undefined, "reply-form"), id = `reply-${Math.random().toString(36).slice(2)}`;
  const labelNode = el("label", label, "visually-hidden"); labelNode.htmlFor = id;
  const box = el("textarea"); box.id = id; box.rows = 2; box.maxLength = 1000; box.required = true; box.placeholder = label;
  const send = el("button", "Send reply", "secondary"); send.type = "submit";
  form.append(labelNode, box, send);
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (!box.value.trim()) return; send.disabled = true;
    try { await api(path, {method: "POST", body: JSON.stringify({body: box.value})}); box.value = ""; await onSent(); }
    catch (error) { notify(error.message); } finally { send.disabled = false; }
  });
  return form;
}
async function loadTickets() {
  const {items} = await api("/api/tickets"); const list = $("tickets-list"); list.replaceChildren();
  if (!items.length) return empty(list, "No support requests yet. In chat, ask to create a request and describe the issue.");
  for (const item of items) {
    const row = el("article", undefined, "record ticket"); const content = el("div", undefined, "record-content");
    const head = el("div", undefined, "ticket-head"); head.append(el("h3", `${item.id} · ${item.category}`), el("span", statusLabel(item.status), "badge"));
    if (item.unread) head.append(el("span", "New update", "badge warn"));
    content.append(head, el("p", item.description), el("small", `Opened ${date(item.created_at)} · Updated ${date(item.updated_at)}`), ticketThread(item, "student"));
    if (item.status !== "resolved") content.append(replyForm(`/api/tickets/${encodeURIComponent(item.id)}/notes`, "Add a reply for Student Services", loadTickets));
    row.append(content); list.append(row);
  }
  if (items.some(i => i.unread)) { await api("/api/tickets/seen", {method: "POST"}); refreshApprovalBadge(); }
}
const ticketStatuses = {open: "Open", in_progress: "In progress", resolved: "Resolved"};
function statusLabel(status) { return ticketStatuses[status] || status; }
function initializeStaff(staff) {
  $("staff-name").textContent = staff.name; $("staff-meta").textContent = `${staff.id} · ${staff.role === "admin" ? "Administrator" : "Staff"}`;
  $("staff-avatar").textContent = initials(staff.name);
  document.querySelectorAll("[data-admin-only]").forEach(b => b.hidden = staff.role !== "admin");
  refreshChangeCount();
  return showStaffView("tickets");
}
async function refreshChangeCount() {
  try { setCount($("change-count"), (await api("/api/staff/approvals?status=awaiting_staff")).items.length); } catch { /* badge is optional */ }
}
async function loadStaffChanges() {
  const filter = $("change-filter").value;
  const {items} = await api(`/api/staff/approvals?status=${encodeURIComponent(filter)}`);
  const list = $("staff-changes-list"); list.replaceChildren();
  if (filter === "awaiting_staff") setCount($("change-count"), items.length);
  if (!items.length) return empty(list, filter === "awaiting_staff" ? "Nothing to review. Confirmed programme change requests appear here." : "No requests with this status.");
  for (const item of items) {
    const row = el("article", undefined, "record"); const content = el("div", undefined, "record-content");
    content.append(el("h3", `${item.student_name} (${item.student_id})`), el("p", `Programme: ${item.old_value} → ${item.new_value}`),
                   el("small", `Requested ${date(item.created_at)} · Confirmed by student ${date(item.decided_at)}${item.reviewed_at ? ` · Reviewed by ${item.reviewed_by} ${date(item.reviewed_at)}` : ""}`));
    const actions = el("div", undefined, "record-actions");
    if (item.status === "awaiting_staff") {
      for (const [decision, label, className] of [["reject", "Reject", "secondary"], ["approve", "Approve change", "primary"]]) {
        const button = el("button", label, className); button.type = "button";
        button.addEventListener("click", async () => {
          actions.querySelectorAll("button").forEach(b => b.disabled = true);
          try { const result = await api(`/api/staff/approvals/${encodeURIComponent(item.id)}/review`, {method: "POST", body: JSON.stringify({decision})}); notify(result.executed ? `${item.student_name}’s programme is now ${item.new_value}.` : "Request rejected. The record is unchanged."); }
          catch (error) { notify(error.message); } finally { await loadStaffChanges(); }
        });
        actions.append(button);
      }
    } else actions.append(el("span", approvalLabels[item.status] || item.status, "badge"));
    row.append(content, actions); list.append(row);
  }
}
$("change-filter").addEventListener("change", () => loadStaffChanges().catch(error => notify(error.message)));
async function showStaffView(name) {
  document.querySelectorAll(".staff-view").forEach(v => v.hidden = v.id !== `staff-view-${name}`);
  document.querySelectorAll("[data-staff-view]").forEach(b => { b.classList.toggle("active", b.dataset.staffView === name); if (b.dataset.staffView === name) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
  try {
    if (name === "tickets") await loadStaffTickets();
    if (name === "changes") await loadStaffChanges();
    if (name === "accounts") await loadAccounts();
    if (name === "audit") await loadAdminAudit();
  } catch (error) { notify(error.message); }
}
document.querySelectorAll("[data-staff-view]").forEach(b => b.addEventListener("click", () => showStaffView(b.dataset.staffView)));
$("ticket-filter").addEventListener("change", () => loadStaffTickets().catch(error => notify(error.message)));
async function loadStaffTickets() {
  const filter = $("ticket-filter").value;
  const {items} = await api(`/api/staff/tickets${filter ? `?status=${encodeURIComponent(filter)}` : ""}`);
  const list = $("staff-tickets-list"); list.replaceChildren();
  if (!items.length) return empty(list, filter ? "No requests with this status." : "No support requests yet. Students raise them by asking Kaiju in chat.");
  for (const item of items) {
    const row = el("article", undefined, "record ticket"); const content = el("div", undefined, "record-content");
    content.append(el("h3", `${item.id} · ${item.category}`), el("p", item.description), el("small", `${item.student_name} (${item.student_id}) · Opened ${date(item.created_at)} · Updated ${date(item.updated_at)}`),
                   ticketThread(item, "staff"), replyForm(`/api/staff/tickets/${encodeURIComponent(item.id)}/notes`, `Reply to ${item.student_name}`, loadStaffTickets));
    const actions = el("div", undefined, "record-actions"), select = el("select", undefined, "status-select");
    select.id = `status-${item.id}`; select.setAttribute("aria-label", `Status of ${item.id}`);
    for (const [value, label] of Object.entries(ticketStatuses)) { const option = el("option", label); option.value = value; option.selected = value === item.status; select.append(option); }
    select.addEventListener("change", async () => {
      select.disabled = true;
      try { await api(`/api/staff/tickets/${encodeURIComponent(item.id)}/status`, {method: "POST", body: JSON.stringify({status: select.value})}); notify(`${item.id} marked ${statusLabel(select.value).toLowerCase()}.`); item.status = select.value; }
      catch (error) { notify(error.message); select.value = item.status; }
      finally { select.disabled = false; }
    });
    actions.append(select); row.append(content, actions); list.append(row);
  }
}
function fillTable(tbody, items, columns, emptyText) {
  tbody.replaceChildren();
  if (!items.length) { const row = el("tr"), cell = el("td", emptyText); cell.colSpan = columns.length; row.append(cell); tbody.append(row); }
  for (const item of items) { const row = el("tr"); for (const column of columns) row.append(el("td", String(column(item) ?? ""))); tbody.append(row); }
}
async function loadAccounts() {
  const {students, staff} = await api("/api/admin/accounts");
  fillTable($("student-accounts"), students, [s => s.id, s => s.name, s => s.programme, s => s.email], "No student accounts.");
  fillTable($("staff-accounts"), staff, [s => s.id, s => s.name, s => s.role === "admin" ? "Administrator" : "Staff", s => s.email], "No staff accounts.");
}
async function loadAdminAudit() {
  const {items} = await api("/api/admin/audit");
  fillTable($("admin-audit-list"), items, [i => date(i.timestamp), i => i.actor, i => i.action, i => i.target, i => i.decision, i => i.result], "No audit events yet.");
}
async function loadActivity() {
  const [runs, audits] = await Promise.all([api("/api/traces"), api("/api/audit")]);
  const list = $("traces-list"); list.replaceChildren();
  if (!runs.items.length) empty(list, "No runs yet. Ask the agent a question to capture a trace.");
  for (const run of runs.items) {
    const row = el("article", undefined, "record"); const content = el("div", undefined, "record-content");
    content.append(el("h3", `${date(run.created_at)} · ${run.status}`), el("p", `${run.latency_ms} ms · ${run.tools.length} tool calls · ${run.input_tokens ?? "N/A"} input / ${run.output_tokens ?? "N/A"} output tokens`));
    const details = el("details", undefined, "trace-details"); details.append(el("summary", "Inspect structured trace"), el("pre", JSON.stringify(run, null, 2))); content.append(details); row.append(content); list.append(row);
  }
  const tbody = $("audit-list"); tbody.replaceChildren();
  if (!audits.items.length) { const row = el("tr"); const cell = el("td", "No audit events yet."); cell.colSpan = 4; row.append(cell); tbody.append(row); }
  for (const item of audits.items) { const row = el("tr"); for (const text of [date(item.timestamp), item.action, item.decision, item.result]) row.append(el("td", text)); tbody.append(row); }
}
initialize().catch(error => { $("login-error").textContent = error.message; $("login-error").hidden = false; });
