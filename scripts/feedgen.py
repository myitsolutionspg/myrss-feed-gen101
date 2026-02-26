import json
import sys
import hashlib
import datetime
from email.utils import format_datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

# -------- helpers --------
def utc_now_rfc2822():
    return format_datetime(datetime.datetime.now(datetime.timezone.utc))

def safe_text(s: str) -> str:
    if s is None:
        return ""
    return str(s).strip()

def get(url: str, timeout=30) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "myrss-feed-gen101/1.0 (+https://myitsolutionspg.github.io/myrss-feed-gen101/)"
        },
    )
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def hash_id(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()

def parse_rss_or_atom(xml_bytes: bytes, source_name: str):
    """
    Returns list of normalized items:
      {title, link, guid, pubDate, description, source}
    """
    items = []
    root = ET.fromstring(xml_bytes)

    # Atom: <feed xmlns="http://www.w3.org/2005/Atom">
    tag_lower = root.tag.lower()
    is_atom = tag_lower.endswith("feed")
    if is_atom:
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        for entry in root.findall(f"{ns}entry"):
            title = safe_text(entry.findtext(f"{ns}title"))
            link = ""
            # Atom links are attributes
            for l in entry.findall(f"{ns}link"):
                rel = l.attrib.get("rel", "alternate")
                if rel == "alternate" and l.attrib.get("href"):
                    link = l.attrib["href"]
                    break
            if not link:
                # fallback first link
                first = entry.find(f"{ns}link")
                if first is not None and first.attrib.get("href"):
                    link = first.attrib["href"]

            guid = safe_text(entry.findtext(f"{ns}id")) or link
            published = safe_text(entry.findtext(f"{ns}published")) or safe_text(entry.findtext(f"{ns}updated"))
            # Keep published as-is; RSS needs RFC2822 but readers tolerate ISO. We’ll convert if possible.
            pub_rfc = to_rfc2822(published) or utc_now_rfc2822()

            summary = safe_text(entry.findtext(f"{ns}summary"))
            content = safe_text(entry.findtext(f"{ns}content"))
            desc = summary or content

            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "guid": guid,
                    "pubDate": pub_rfc,
                    "description": desc,
                    "source": source_name,
                })
        return items

    # RSS 2.0: <rss><channel><item>...
    channel = root.find("channel") if root.tag.lower().endswith("rss") else None
    if channel is None:
        # Some feeds use namespaces; brute-force find channel
        for child in root:
            if child.tag.lower().endswith("channel"):
                channel = child
                break
    if channel is None:
        return items

    for it in channel.findall("item"):
        title = safe_text(it.findtext("title"))
        link = safe_text(it.findtext("link"))
        guid = safe_text(it.findtext("guid")) or link
        pub = safe_text(it.findtext("pubDate"))
        pub_rfc = to_rfc2822(pub) or utc_now_rfc2822()

        # prefer content:encoded if present
        desc = safe_text(it.findtext("description"))
        if not desc:
            # Try namespaced content
            for c in it:
                if c.tag.lower().endswith("encoded") and (c.text or "").strip():
                    desc = safe_text(c.text)
                    break

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "guid": guid,
                "pubDate": pub_rfc,
                "description": desc,
                "source": source_name,
            })
    return items

def to_rfc2822(dt_str: str):
    """
    Try convert common ISO-like date strings to RFC2822.
    If conversion fails, return None.
    """
    s = (dt_str or "").strip()
    if not s:
        return None

    # Already RFC2822-ish
    if "," in s and ("GMT" in s or "+" in s or "-" in s):
        return s

    # Try ISO 8601
    try:
        # handle Z
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        d = datetime.datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return format_datetime(d.astimezone(datetime.timezone.utc))
    except Exception:
        return None

def build_rss(config: dict, items: list):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = safe_text(config.get("title"))
    ET.SubElement(channel, "link").text = safe_text(config.get("site_url"))
    ET.SubElement(channel, "description").text = "Aggregated feed generated by myrss-feed-gen101"
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = utc_now_rfc2822()

    for x in items:
        it = ET.SubElement(channel, "item")
        ET.SubElement(it, "title").text = safe_text(x["title"])
        ET.SubElement(it, "link").text = safe_text(x["link"])
        ET.SubElement(it, "guid").text = safe_text(x["guid"])
        ET.SubElement(it, "pubDate").text = safe_text(x["pubDate"])

        # add source marker in description (simple + robust)
        desc = safe_text(x.get("description"))
        src = safe_text(x.get("source"))
        combined = f"[{src}] {desc}" if src else desc
        ET.SubElement(it, "description").text = combined

    # Pretty-ish output (ElementTree doesn't indent by default)
    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return xml_bytes

def main():
    cfg_path = "feeds/sources.json"
    out_path = "feeds/png-latest-news.xml"

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    max_total = int(cfg.get("max_items_total", 60))
    sources = cfg.get("sources", [])

    all_items = []
    for src in sources:
        name = safe_text(src.get("name")) or "Source"
        url = safe_text(src.get("url"))
        if not url:
            continue
        try:
            data = get(url)
            items = parse_rss_or_atom(data, name)
            all_items.extend(items)
        except (HTTPError, URLError, ET.ParseError) as e:
            # Log and continue. We don't want one broken source to kill the run.
            print(f"[WARN] Source failed: {name} {url} :: {e}", file=sys.stderr)
            continue

    # De-dupe by link/guid hash
    seen = set()
    uniq = []
    for it in all_items:
        key = hash_id(it.get("guid", ""), it.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # Sort newest-first by pubDate (best-effort)
    def sort_key(it):
        # try parse RFC2822 via email.utils
        try:
            # format_datetime produces RFC2822, but parsing is messy; do best-effort
            # fallback keeps stable order
            return it.get("pubDate", "")
        except Exception:
            return it.get("pubDate", "")

    uniq.sort(key=sort_key, reverse=True)
    uniq = uniq[:max_total]

    rss_bytes = build_rss(cfg, uniq)

    with open(out_path, "wb") as f:
        f.write(rss_bytes)

    print(f"Generated {out_path} with {len(uniq)} items from {len(sources)} sources")

if __name__ == "__main__":
    main()
