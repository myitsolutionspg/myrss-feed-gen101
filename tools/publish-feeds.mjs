import fs from "node:fs";
import path from "node:path";

const WORKER_BASE = (process.env.WORKER_BASE || "").replace(/\/+$/, "");
if (!WORKER_BASE) {
  console.error("Missing WORKER_BASE env var");
  process.exit(1);
}

const FEEDS_DIR = path.resolve("feeds");
fs.mkdirSync(FEEDS_DIR, { recursive: true });

function safeSlug(slug) {
  return String(slug || "")
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

async function getPublishedFeeds() {
  const res = await fetch(`${WORKER_BASE}/public/published-feeds`);
  if (!res.ok) throw new Error(`Failed published list: HTTP ${res.status}`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "published list failed");
  return data.feeds || [];
}

async function fetchText(url) {
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`Fetch failed ${url}: HTTP ${res.status}`);
  return await res.text();
}

(async () => {
  const feeds = await getPublishedFeeds();

  // Optional: remove files that are no longer published
  const keep = new Set(feeds.map(f => `${safeSlug(f.slug)}.xml`));
  for (const file of fs.readdirSync(FEEDS_DIR)) {
    if (file.endsWith(".xml") && !keep.has(file)) {
      fs.unlinkSync(path.join(FEEDS_DIR, file));
    }
  }

  // Write each feed
  for (const f of feeds) {
    const slug = safeSlug(f.slug);
    if (!slug) continue;

    const xml = await fetchText(f.url);

    const outPath = path.join(FEEDS_DIR, `${slug}.xml`);
    fs.writeFileSync(outPath, xml, "utf8");
    console.log("Wrote", outPath);
  }

  // Write a small index so you can browse what’s published
  const index = feeds.map(f => ({
    slug: safeSlug(f.slug),
    title: f.title || "",
    pages_url: `https://myitsolutionspg.github.io/myrss-feed-gen101/feeds/${safeSlug(f.slug)}.xml`,
    source_url: f.url
  }));
  fs.writeFileSync(path.join(FEEDS_DIR, `index.json`), JSON.stringify(index, null, 2), "utf8");
  console.log("Wrote feeds/index.json");
})();
