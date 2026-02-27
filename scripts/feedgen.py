import json
import sys
import hashlib
import datetime
import re
from html import unescape
from email.utils import format_datetime, parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

ATOM_NS = "http://www.w3.org/2005/Atom"

# ---------------- helpers ----------------
def utc_now_rfc2822() -> str:
    return format_datetime(datetime.datetime.now(datetime.timezone.utc))

def safe_text(s) -> str:
    if s is None:
        return ""
    return str(s).strip()

def localname(tag: str) -> str:
    if not tag:
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag

def child_text_by_local(parent: ET.Element, name: str) -> str:
    if parent is None:
        return ""
    want = name.lower()
    for ch in list(parent):
        if localname(ch.tag).lower() == want:
            return safe_text(ch.text)
    return ""

def get(url: str, timeout: int = 30) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "myrss-feed-gen101/1.0 (+https://myitsolutionspg.github.io/myrss-feed-gen101/)"
        },
    )
    with urlopen(req, timeout=timeout) as r:
        ct = r.headers.get("Content-Type", "")
        data = r.read()
        print(f"[FETCH] {url} :: status={getattr(r,'status','n/a')} ct={ct} bytes={len(data)} head={data[:60]!r}")
        return data

def hash_id(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()

def to_rfc2822(dt_str: str) -> str | None:
    s = (dt_str or "").strip()
    if not s:
        return None

    # If already RFC2822-ish, keep it
    if "," in s and ("GMT" in s or "+" in s or "-" in s):
        return s

    # Try ISO 8601
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        d = datetime.datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return format_datetime(d.astimezone(datetime.timezone.utc))
    except Exception:
        return None

def parse_rfc2822_to_dt(pub_rfc: str) -> datetime.datetime:
    try:
        d = parsedate_to_datetime(pub_rfc)
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.astimezone(datetime.timezone.utc)
    except Exception:
        return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

def guess_image_mime(url: str) -> str:
    u = (url or "").lower()
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    if u.endswith(".gif"):
        return "image/gif"
    if u.endswith(".svg"):
        return "image/svg+xml"
    return "image/jpeg"

def clean_html(text: str) -> tuple[str, str | None]:
    """
    Returns (clean_text, first_image_url)
    Important: unescape FIRST, then strip tags. This avoids turning &lt;p&gt; into real <p> later.
    """
    if not text:
        return "", None

    raw = unescape(text)

    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw, flags=re.I)
    image_url = img_match.group(1) if img_match else None

    # strip tags (do it twice defensively)
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"<[^>]+>", " ", clean)

    clean = re.sub(r"\s+", " ", clean).strip()

    # keep descriptions short
    return clean[:300], image_url

# ---------------- parsing ----------------
def parse_atom(root: ET.Element, source_name: str) -> list[dict]:
    items: list[dict] = []
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
                    # OUTPUT GUID MUST BE URL FOR VALIDATORS/READERS
                    "guid": link,
                    "pubDate": pub_rfc,
                    "description": desc,
                    "source": source_name,
                }
            )
    return items

def parse_rss(root: ET.Element, source_name: str) -> list[dict]:
    items: list[dict] = []

    channel = None
    for el in root.iter():
        if localname(el.tag).lower() == "channel":
            channel = el
            break
    if channel is None:
        return items

    for it in channel.iter():
        if localname(it.tag).lower() != "item":
            continue

        title = child_text_by_local(it, "title")
        link = child_text_by_local(it, "link")
        pub = child_text_by_local(it, "pubDate")

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
                    # OUTPUT GUID MUST BE URL FOR VALIDATORS/READERS
                    "guid": link,
                    "pubDate": pub_rfc,
                    "description": desc,
                    "source": source_name,
                }
            )

    return items

def parse_rss_or_atom(xml_bytes: bytes, source_name: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    root_name = localname(root.tag).lower()
    if root_name == "feed":
        return parse_atom(root, source_name)
    return parse_rss(root, source_name)

# ---------------- build output ----------------
def build_rss(config: dict, items: list[dict]) -> bytes:
    # Register atom namespace so ElementTree writes atom:link cleanly
    ET.register_namespace("atom", ATOM_NS)

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    title = safe_text(config.get("title"))
    site_url = safe_text(config.get("site_url"))
    feed_url = safe_text(config.get("feed_url"))

    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "Aggregated feed generated by myrss-feed-gen101"
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = utc_now_rfc2822()

    # atom:link rel="self" (validator recommendation)
    if feed_url:
        ET.SubElement(
            channel,
            f"{{{ATOM_NS}}}link",
            {
                "href": feed_url,
                "rel": "self",
                "type": "application/rss+xml",
            },
        )

    for x in items:
        it = ET.SubElement(channel, "item")
        link = safe_text(x.get("link"))
        ET.SubElement(it, "title").text = safe_text(x.get("title"))
        ET.SubElement(it, "link").text = link

        # GUID: always a full URL for maximum compatibility
        ET.SubElement(it, "guid").text = link

        pub = safe_text(x.get("pubDate"))
        ET.SubElement(it, "pubDate").text = pub

        raw_desc = safe_text(x.get("description"))
        clean_desc, image_url = clean_html(raw_desc)

        src = safe_text(x.get("source"))
        combined = f"[{src}] {clean_desc}" if src else clean_desc
        ET.SubElement(it, "description").text = combined

        if image_url:
            ET.SubElement(
                it,
                "enclosure",
                {
                    "url": image_url,
                    "type": guess_image_mime(image_url),
                },
            )

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)

def main() -> None:
    cfg_path = "feeds/sources.json"
    out_path = "feeds/png-latest-news.xml"

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    max_total = int(cfg.get("max_items_total", 120))
    sources = cfg.get("sources", [])

    all_items: list[dict] = []
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

    # De-dupe
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in all_items:
        key = hash_id(it.get("guid", ""), it.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # Proper sort: newest first by parsed datetime
    uniq.sort(key=lambda x: parse_rfc2822_to_dt(safe_text(x.get("pubDate"))), reverse=True)
    uniq = uniq[:max_total]

    rss_bytes = build_rss(cfg, uniq)
    with open(out_path, "wb") as f:
        f.write(rss_bytes)

    print(f"[DONE] Generated {out_path}: {len(uniq)} items (sources ok: {ok_sources}/{len(sources)})")

if __name__ == "__main__":
    main()
