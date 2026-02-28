// ===== Config storage =====
const LS_API = "myrss_api_base";
const LS_TOKEN = "myrss_token";
const LS_EXPIRES = "myrss_expires_at";

const $ = (id) => document.getElementById(id);

function getApiBase() {
  return (localStorage.getItem(LS_API) || "").trim().replace(/\/+$/, "");
}
function setApiBase(v) {
  localStorage.setItem(LS_API, (v || "").trim().replace(/\/+$/, ""));
}
function getToken() {
  return localStorage.getItem(LS_TOKEN) || "";
}
function setToken(token, expiresAt) {
  localStorage.setItem(LS_TOKEN, token || "");
  localStorage.setItem(LS_EXPIRES, expiresAt || "");
}
function clearAuth() {
  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_EXPIRES);
}

function pretty(x) {
  try { return JSON.stringify(x, null, 2); } catch { return String(x); }
}

async function api(path, { method="GET", body=null, auth=false } = {}) {
  const base = getApiBase();
  if (!base) throw new Error("Set the Worker Base URL first.");

  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const t = getToken();
    if (!t) throw new Error("Not logged in. Please login again.");
    headers["Authorization"] = `Bearer ${t}`;
  }

  const res = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null
  });

  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch { json = { ok:false, error:text || `HTTP ${res.status}`}; }

  if (!res.ok || json?.ok === false) {
    throw new Error(json?.error || `HTTP ${res.status}`);
  }
  return json;
}

// ===== Page wiring =====
document.addEventListener("DOMContentLoaded", () => {
  const p = location.pathname;
  const page = p.split("/").pop(); // "", "index.html", "app.html", etc.

  // /ui/ ends with "", treat as index
  const isIndex = (page === "" || page === "index.html");
  const isApp = (page === "app.html");

  if (isIndex) initIndex();
  if (isApp) initApp();
});

function initIndex() {
  // Prefill API base
  const apiBase = $("apiBase");
  if (apiBase) apiBase.value = getApiBase() || "https://myrss-api.melkyw.workers.dev";
  apiBase?.addEventListener("change", () => setApiBase(apiBase.value));

  const btnRegister = $("btnRegister");
  const btnLogin = $("btnLogin");

  btnRegister?.addEventListener("click", async () => {
    $("regOut").textContent = "";
    try {
      setApiBase(apiBase.value);
      const email = $("regEmail").value.trim();
      const password = $("regPass").value;

      const out = await api("/api/register", { method:"POST", body:{ email, password } });
      $("regOut").textContent = pretty(out) + "\n\nNow login on the right.";
    } catch (e) {
      $("regOut").textContent = String(e.message || e);
    }
  });

  btnLogin?.addEventListener("click", async () => {
    $("logOut").textContent = "";
    try {
      setApiBase(apiBase.value);
      const email = $("logEmail").value.trim();
      const password = $("logPass").value;

      const out = await api("/api/login", { method:"POST", body:{ email, password } });
      setToken(out.token, out.expires_at);
      $("logOut").textContent = pretty(out);

      // go to app
      location.href = "./app.html";
    } catch (e) {
      $("logOut").textContent = String(e.message || e);
    }
  });

  // If already logged in, jump
  if (getToken()) {
    // stay polite: only auto-jump if API base is set
    if (getApiBase()) location.href = "./app.html";
  }
}

async function initApp() {
  // Hard gate: require API base + token
  const base = getApiBase();
  const token = getToken();

  if (!base || !token) {
    location.replace("./index.html");
    return;
  }

  // Show base immediately
  const baseShow = $("apiBaseShow");
  if (baseShow) baseShow.textContent = base;

  // Validate token by pinging a protected endpoint
  // If it fails, force logout and redirect to login
  try {
    await api("/api/feeds", { method: "GET", auth: true });
  } catch (e) {
    clearAuth();
    location.replace("./index.html");
    return;
  }

  // Wire UI after auth passes
  $("btnLogout")?.addEventListener("click", () => {
    clearAuth();
    location.replace("./index.html");
  });

  $("btnPing")?.addEventListener("click", async () => {
    $("pingOut").textContent = "";
    try {
      const out = await api("/", { method: "GET" });
      $("pingOut").textContent = pretty(out);
    } catch (e) {
      $("pingOut").textContent = String(e.message || e);
    }
  });

  $("btnAddFeed")?.addEventListener("click", async () => {
    $("feedsOut").textContent = "";
    try {
      const title = $("feedTitle").value.trim();
      const url = $("feedUrl").value.trim();
      const out = await api("/api/feeds", { method: "POST", body: { title, url }, auth: true });
      $("feedsOut").textContent = pretty(out);
      await refreshFeeds();
    } catch (e) {
      $("feedsOut").textContent = String(e.message || e);
    }
  });

  $("btnRefreshFeeds")?.addEventListener("click", refreshFeeds);
  $("btnScrape")?.addEventListener("click", scrapeNow);
  $("btnClearResults")?.addEventListener("click", () => {
    $("results").innerHTML = "";
    $("scrapeOut").textContent = "";
  });

  // Load initial
  refreshFeeds().catch(() => {});
}
async function refreshFeeds() {
  const list = $("feedsList");
  const outEl = $("feedsOut");
  list.innerHTML = "";
  outEl.textContent = "";
  try {
    const out = await api("/api/feeds", { method:"GET", auth:true });
    const feeds = out.feeds || [];
    if (!feeds.length) {
      list.innerHTML = `<li class="muted small">No feeds saved yet.</li>`;
      return;
    }
    for (const f of feeds) {
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="mono small muted">${escapeHtml(f.id)}</div>
        <div><strong>${escapeHtml(f.title || "(no title)")}</strong></div>
        <div><a href="${escapeAttr(f.url)}" target="_blank" rel="noopener">Open feed</a></div>
        <div class="muted small">${escapeHtml(f.created_at || "")}</div>
      `;
      list.appendChild(li);
    }
  } catch (e) {
    outEl.textContent = String(e.message || e);
  }
}

async function scrapeNow() {
  const outEl = $("scrapeOut");
  const results = $("results");
  outEl.textContent = "";
  results.innerHTML = "";

  try {
    const url = $("scrapeUrl").value.trim();
    const out = await api("/api/scrape", { method:"POST", body:{ url }, auth:true });

    // XML passthrough
    if (out.kind === "xml") {
      outEl.textContent = "Returned XML (showing first 2000 chars):\n\n" + String(out.text || "").slice(0, 2000);
      return;
    }

    const items = out.items || [];
    if (!items.length) {
      results.innerHTML = `<div class="muted small">No items found.</div>`;
      return;
    }

    for (const it of items) {
      const div = document.createElement("div");
      div.className = "result";

      const img = document.createElement("img");
      img.className = "thumb";
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";

      // If image missing, hide thumbnail box
      if (it.image && typeof it.image === "string" && it.image.startsWith("http")) {
        img.src = it.image;
      } else {
        img.style.display = "none";
      }

      const body = document.createElement("div");
      body.innerHTML = `
        <h4>${escapeHtml(it.title || "(no title)")}</h4>
        <div><a href="${escapeAttr(it.link)}" target="_blank" rel="noopener">Open article</a></div>
        ${it.image ? `<div class="muted small mono">${escapeHtml(it.image)}</div>` : `<div class="muted small">No image detected</div>`}
      `;

      div.appendChild(img);
      div.appendChild(body);
      results.appendChild(div);
    }
  } catch (e) {
    outEl.textContent = String(e.message || e);
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}
function escapeAttr(s) {
  // basic safe attribute escaping
  return escapeHtml(s).replace(/"/g, "&quot;");
}
