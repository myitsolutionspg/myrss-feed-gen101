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

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function getPublishedFeeds() {
  const res = await fetch(`${WORKER_BASE}/public/published-feeds`, {
    redirect: "follow",
    headers: {
      "User-Agent": "GuamLatestNewsFeedBot/1.0 (+https://myitsolutionspg.github.io/myrss-feed-gen101/)",
      "Accept": "application/json, */*"
    }
  });

  if (!res.ok) throw new Error(`Failed published list: HTTP ${res.status}`);

  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "published list failed");

  return data.feeds || [];
}

async function fetchText(url, attempts = 3) {
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt++) {
    const res = await fetch(url, {
      redirect: "follow",
      headers: {
        "User-Agent": "GuamLatestNewsFeedBot/1.0 (+https://myitsolutionspg.github.io/myrss-feed-gen101/)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
      }
    });

    if (res.ok) {
      return await res.text();
    }

    lastError = new Error(`Fetch failed ${url}: HTTP ${res.status}`);

    if (res.status === 429 && attempt < attempts) {
      const waitMs = attempt * 15000;
      console.warn(
        `HTTP 429 for ${url}. Waiting ${waitMs / 1000}s before retry ${attempt + 1}/${attempts}...`
      );
      await sleep(waitMs);
      continue;
    }

    throw lastError;
  }

  throw lastError;
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

    const outPath = path.join(FEEDS_DIR, `${slug}.xml`);

    try {
      await sleep(8000);

      const xml = await fetchText(f.url);

      fs.writeFileSync(outPath, xml, "utf8");
      console.log("Wrote", outPath);
    } catch (err) {
      console.warn(`Skipped ${slug}: ${err.message}`);
      continue;
    }
  }

  // Write a small index so you can browse what’s published.
  // Only include feeds where the XML file exists.
  const index = feeds
    .map(f => {
      const slug = safeSlug(f.slug);
      return {
        slug,
        title: f.title || "",
        pages_url: `https://myitsolutionspg.github.io/myrss-feed-gen101/feeds/${slug}.xml`,
        source_url: f.url
      };
    })
    .filter(f => f.slug && fs.existsSync(path.join(FEEDS_DIR, `${f.slug}.xml`)));

  fs.writeFileSync(
    path.join(FEEDS_DIR, "index.json"),
    JSON.stringify(index, null, 2),
    "utf8"
  );

  console.log("Wrote feeds/index.json");
})();
