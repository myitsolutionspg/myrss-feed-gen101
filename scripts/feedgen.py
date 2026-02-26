import json
import sys
import hashlib
import datetime
from email.utils import format_datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

# ---------------- helpers ----------------
def utc_now_rfc2822():
    return format_datetime(datetime.datetime.now(datetime.timezone.utc))

def safe_text(s) -> str:
    if s is None:
        return ""
    return str(s).strip()

def localname(tag: str) -> str:
    # "{ns}name" -> "name"
    if tag is None:
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag

def child_text_by_local(parent: ET.Element, name: str) -> str:
    if parent is None:
        return ""
    for ch in list(parent):
        if localname(ch.tag).lower() == name.lower():
            return safe_text(ch.text)
    return ""

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

def to_rfc2822(dt_str: str):
    s = (dt_str or "").strip()
    if not s:
        return None

    # Already RFC2822-ish
    if "," in s and ("GMT" in s or "+" in s or "-" in s):
        return s

    # Try ISO 8601
    try:
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

# ---------------- parsing ----------------
def parse_atom(root: ET.Element, source_name: str):
    items = []
    # Detect default namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    for entry in root.findall(f"{ns}entry"):
        title = safe_text(entry.findtext(f"{ns}title"))

        link = ""
        for l in entry.findall(f"{ns}link"):
            rel = l.attrib.get("rel", "alternate")
            if rel == "alternate" and l.attrib.get("href"):
                link = l.attrib["href"]
                break
        if not link:
            first = entry.find(f"{ns}link")
            if first is not None and first.attrib.get("href"):
                link = first.attrib["href"]

        guid = safe_text(entry.findtext(f"{ns}id")) or link
        published = safe_text(entry.findtext(f"{ns}published")) or safe_text(entry.findtext(f"{ns}updated"))
        pub_rfc = to_rfc2822(published) or utc_now_rfc2822()

        summary = safe_text(entry.findtext(f"{ns}summary"))
        content = safe_text(entry.findtext(f"{ns}content"))
        desc = summary or content

        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "guid": guid,
                    "pubDate": pub_rfc,
                    "description": desc,
                    "source": source_name,
                }
            )

    return items

def parse_rss(root: ET.Element, source_name: str):
    items = []

    # Find <channel> namespace-agnostic
    channel = None
    for el in root.iter():
        if localname(el.tag).lower() == "channel":
            channel = el
            break
    if channel is None:
        return items

    # Find <item> namespace-agnostic
    for it in channel.iter():
        if localname(it.tag).lower() != "item":
            continue

        title = child_text_by_local(it, "title")
        link = child_text_by_local(it, "link")
        guid = child_text_by_local(it, "guid") or link
        pub = child_text_by_local(it, "pubDate")

        # description or content:encoded (namespace-agnostic)
        desc = child_text_by_local(it, "description")
        if not desc:
            for ch in list(it):
                if localname(ch.tag).lower() == "encoded" and safe_text(ch.text):
                    desc = safe_text(ch.text)
                    break

        pub_rfc = to_rfc2822(pub) or utc_now_rfc2822()

        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "guid": guid,
                    "pubDate": pub_rfc,
                    "description": desc,
                    "source": source_name,
                }
            )

    return items

def parse_rss_or_atom(xml_bytes: bytes, source_name: str):
    root = ET.fromstring(xml_bytes)
    root_name = localname(root.tag).lower()

    # Atom
    if root_name == "feed":
        return parse_atom(root, source_name)

    # RSS (root can be <rss> or sometimes <rdf:RDF>)
    return parse_rss(root, source_name)

# ---------------- build output ----------------
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

        desc = safe_text(x.get("description"))
        src = safe_text(x.get("source"))
        combined = f"[{src}] {desc}" if src else desc
        ET.SubElement(it, "description").text = combined

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)

def main():
    cfg_path = "feeds/sources.json"
    out_path = "feeds/png-latest-news.xml"

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    max_total = int(cfg.get("max_items_total", 120))
    sources = cfg.get("sources", [])

    all_items = []
    ok_sources = 0
    for src in sources:
        name = safe_text(src.get("name")) or "Source"
        url = safe_text(src.get("url"))
        if not url:
            continue
        try:
            data = get(url)
            items = parse_rss_or_atom(data, name)
            if items:
                ok_sources += 1
            all_items.extend(items)
            print(f"[INFO] {name}: {len(items)} items")
        except (HTTPError, URLError, ET.ParseError) as e:
            print(f"[WARN] Source failed: {name} {url} :: {e}", file=sys.stderr)
            continue

    # De-dupe
    seen = set()
    uniq = []
    for it in all_items:
        key = hash_id(it.get("guid", ""), it.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # Best-effort sort (newest first) using pubDate string
    uniq.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    uniq = uniq[:max_total]

    rss_bytes = build_rss(cfg, uniq)
    with open(out_path, "wb") as f:
        f.write(rss_bytes)

    print(f"[DONE] Generated {out_path}: {len(uniq)} items (sources ok: {ok_sources}/{len(sources)})")

if __name__ == "__main__":
    main()
