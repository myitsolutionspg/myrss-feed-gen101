// ===== Config storage =====
const LS_API = "myrss_api_base";
const LS_TOKEN = "myrss_token";
const LS_EXPIRES = "myrss_expires_at";

const $ = (id) => document.getElementById(id);

const GENERATED_RSS_BASE = "https://myrss-api.melkyw.workers.dev/rss";

let lastDetectedFeedUrl = "";
let lastDetectedFeedTitle = "";
let lastScrapedInputUrl = "";

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

    // --- RSS options (SS01 controls) ---
  const elRssContent = $("rssContent"); // <select id="rssContent">
  const elRssMax     = $("rssMax");     // <select id="rssMax">

  function refreshGeneratedRssUrl() {
    const src = ($("scrapeUrl")?.value || "").trim();
    const gen = buildGeneratedRssUrl(src);

    // store latest (optional, but useful)
    window.__generatedRssUrl = gen;

    // show under Results for debugging (optional)
    const out = $("scrapeOut");
    if (out && gen) out.textContent = `Generated RSS:\n${gen}\n`;
  }

  // When the user changes max/content, update generated URL immediately
  elRssContent?.addEventListener("change", refreshGeneratedRssUrl);
  elRssMax?.addEventListener("change", refreshGeneratedRssUrl);
  $("scrapeUrl")?.addEventListener("input", refreshGeneratedRssUrl);

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

   $("btnSaveScrapedAsFeed")?.addEventListener("click", async () => {
    const outEl = $("feedsOut");
    if (outEl) outEl.textContent = "";
  
    try {
      if (!lastDetectedFeedUrl) throw new Error("No feed URL detected yet. Click Scrape first.");
  
      const res = await api("/api/feeds", {
        method: "POST",
        body: { title: lastDetectedFeedTitle || "Saved Feed", url: lastDetectedFeedUrl },
        auth: true
      });
  
      if (outEl) outEl.textContent = pretty(res);
      await refreshFeeds();
    } catch (e) {
      if (outEl) outEl.textContent = String(e.message || e);
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
        <div class="feedRow">
          <div class="feedLeft">
            <div class="mono small muted">${escapeHtml(f.id)}</div>
            <div><strong>${escapeHtml(f.title || "(no title)")}</strong></div>
            <div class="mono small">
              <a href="${escapeAttr(f.url)}" target="_blank" rel="noopener">${escapeHtml(f.url)}</a>
            </div>
            <div class="muted small">${escapeHtml(f.created_at || "")}</div>
            <div class="muted small copyHint" data-copyhint></div>
          </div>
          <div class="feedRight">
            <button class="btn" data-copy="${escapeAttr(f.url)}">Copy URL</button>
            <button class="btn" data-rename="${escapeAttr(f.id)}" data-oldtitle="${escapeAttr(f.title || "")}">Rename</button>
            <button class="btn" data-del="${escapeAttr(f.id)}">Delete</button>
          </div>
        </div>
      `;
      list.appendChild(li);

      const ren = li.querySelector("[data-rename]");
      ren?.addEventListener("click", async () => {
        const id = ren.getAttribute("data-rename") || "";
        const oldTitle = ren.getAttribute("data-oldtitle") || "";
        const newTitle = (prompt("Rename feed:", oldTitle) || "").trim();
        if (!id) return;
        if (!newTitle && oldTitle === "") return; // nothing to do
      
        try {
          await api(`/api/feeds/${encodeURIComponent(id)}`, {
            method: "PATCH",
            body: { title: newTitle },
            auth: true
          });
          await refreshFeeds();
        } catch (e) {
          const hint = li.querySelector("[data-copyhint]");
          if (hint) hint.textContent = String(e.message || e);
        }
      });

      const del = li.querySelector("[data-del]");
      del?.addEventListener("click", async () => {
        const id = del.getAttribute("data-del") || "";
        if (!id) return;
      
        // quick confirm to avoid accidents
        if (!confirm("Delete this feed?")) return;
      
        try {
          await api(`/api/feeds/${encodeURIComponent(id)}`, { method: "DELETE", auth: true });
          await refreshFeeds();
        } catch (e) {
          const hint = li.querySelector("[data-copyhint]");
          if (hint) hint.textContent = String(e.message || e);
        }
      });

      const btn = li.querySelector("[data-copy]");
      btn?.addEventListener("click", async () => {
        const u = btn.getAttribute("data-copy") || "";
        try {
          await navigator.clipboard.writeText(u);
          const hint = li.querySelector("[data-copyhint]");
          if (hint) hint.textContent = "Copied.";
          setTimeout(() => { if (hint) hint.textContent = ""; }, 1200);
        } catch {
          const hint = li.querySelector("[data-copyhint]");
          if (hint) hint.textContent = "Copy blocked. Showing URL to copy.";
          window.prompt("Copy this URL:", u);
        }
      });
      
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

  // Reset "Save as Feed" state per scrape
  lastScrapedInputUrl = "";
  lastDetectedFeedUrl = "";
  lastDetectedFeedTitle = "";

  const btnSave = $("btnSaveScrapedAsFeed");
  if (btnSave) {
    btnSave.disabled = true;
    btnSave.textContent = "Save as Feed";
  }

  try {
    const url = $("scrapeUrl").value.trim();
    lastScrapedInputUrl = url;

    // make sure generated URL reflects current dropdown state
    window.__generatedRssUrl = buildGeneratedRssUrl(url);

    const max = parseInt(($("rssMax")?.value ?? "5"), 10) || 5;
    const deep = ($("rssContent")?.value ?? "0") === "1"; // if you want content to influence scrape "depth"
    
    const out = await api("/api/scrape", {
      method: "POST",
      body: { url, deep: deep ? 1 : 0, deepMax: max },   // ✅ tell Worker to cap
      auth: true
    });

    // Detect a feed URL we can save
    const detected = detectFeedUrl(url, out);
    if (detected) {
      lastDetectedFeedUrl = detected;
      lastDetectedFeedTitle = guessTitleFromUrl(url);

      if (btnSave) {
        btnSave.disabled = false;
        btnSave.textContent = detected.startsWith(GENERATED_RSS_BASE)
          ? "Save Feed (Generated RSS)"
          : `Save Feed (${detected})`;
      }
    } else {
      if (btnSave) {
        btnSave.disabled = true;
        btnSave.textContent = "Save as Feed (no feed detected)";
      }
    }

    // XML passthrough
    if (out.kind === "xml") {
      outEl.textContent =
        "Returned XML (showing first 2000 chars):\n\n" + String(out.text || "").slice(0, 2000);
      return;
    }

    // Read UI values (now that the IDs exist in app.html)
    const max = Math.max(1, parseInt($("rssMax")?.value ?? "10", 10) || 10);
    
    // Render only up to max
    const items = (out.items || []).slice(0, max);
    
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

function detectFeedUrl(inputUrl, scrapeResponse) {
  const u = String(inputUrl || "").trim();
  if (!u) return null;

  // If response is XML, user already provided a feed URL
  if (scrapeResponse && scrapeResponse.kind === "xml") return u;

  const lower = u.toLowerCase();

  // If user pasted a feed-looking URL, accept it
  if (lower.endsWith(".xml") || lower.includes("/feed") || lower.includes("rss")) return u;

  // Otherwise generate a Worker RSS URL for this source site
  // (works for sites without RSS like nbc.com.pg)
  return buildGeneratedRssUrl(u);
}

function buildGeneratedRssUrl(srcUrl) {
  const base = (getApiBase() || "").replace(/\/+$/, ""); // ✅ use getApiBase()
  const src = String(srcUrl || "").trim();
  if (!base || !src) return "";

  const content = ($("rssContent")?.value ?? "0").trim();
  const max     = ($("rssMax")?.value ?? "10").trim();

  const qs = new URLSearchParams();
  qs.set("src", src);
  if (content === "1") qs.set("content", "1");
  if (max) qs.set("max", max);

  return `${base}/rss?${qs.toString()}`;
} 

function guessTitleFromUrl(inputUrl) {
  try {
    const u = new URL(inputUrl);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return "Saved Feed";
  }
}

function refreshGeneratedRssUrl() {
  const src = (document.getElementById("scrapeUrl")?.value || "").trim();
  const gen = buildGeneratedRssUrl(src);

  // Store it somewhere your Save button already uses:
  window.__generatedRssUrl = gen;

  // Optional: show it in the scrape output for easy verification
  const out = document.getElementById("scrapeOut");
  if (out) out.textContent = gen ? `Generated RSS:\n${gen}\n` : "";
}

