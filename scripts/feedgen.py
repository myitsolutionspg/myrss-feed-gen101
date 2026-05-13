import json
import sys
import hashlib
import datetime
import re
from copy import deepcopy
from html import unescape
from io import BytesIO
from email.utils import format_datetime, parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
from pathlib import Path

ATOM_NS = "http://www.w3.org/2005/Atom"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

RADIO_SAMOA_SOURCE_FEED = "https://feed.podbean.com/podcastradiosamoa/feed.xml"

RADIO_SAMOA_PROGRAMMES = [
    {
        "name": "Taimi with Tuaman",
        "patterns": [
            "Taimi with TUAMAN*",
            "Taimi with Tuaman*",
            "*Taimi with TUAMAN*",
            "*Taimi with Tuaman*",
            "*TUAMAN*",
            "*Tuaman*",
        ],
        "output": "feeds/radio-samoa-taimi-with-tuaman.xml",
        "link": "https://radiosamoa.co.nz/podcast-taimi-with-tuaman/",
    },
    {
        "name": "Malu i Fale",
        "patterns": [
            "Malu i Fale*",
            "*Malu i Fale*",
        ],
        "output": "feeds/radio-samoa-malu-i-fale.xml",
        "link": "https://radiosamoa.co.nz/podcast-malu-i-fale/",
    },
    {
        "name": "O Oe Male Tulafono",
        "patterns": [
            "O Oe Male Tulafono*",
            "*O Oe Male Tulafono*",
        ],
        "output": "feeds/radio-samoa-o-oe-male-tulafono.xml",
        "link": "https://radiosamoa.co.nz/podcast-polokalame-leoleo/",
    },
    {
        "name": "O le Vaofilifili o Samoa",
        "patterns": [
            "O le Vaofilifili o Samoa*",
            "*O le Vaofilifili o Samoa*",
        ],
        "output": "feeds/radio-samoa-o-le-vaofilifili-o-samoa.xml",
        "link": "https://radiosamoa.co.nz/podcast-o-le-vaofilifili-o-samoa/",
    },
    {
        "name": "Tu'utu'u le Upega ile Loloto",
        "patterns": [
            "Tu'utu'u le Upega ile Loloto*",
            "*Tu'utu'u le Upega ile Loloto*",
        ],
        "output": "feeds/radio-samoa-tuutuu-le-upega-ile-loloto.xml",
        "link": RADIO_SAMOA_SOURCE_FEED,
    },
    {
        "name": "Tia with Queen Poke",
        "patterns": [
            "*Queen Poke*",
            "*Tia with Queen Poke*",
            "*QueenPoke*",
            "*Tia and the Queen*",
            "*Tiatia*",
            "*18854112*",
        ],
        "output": "feeds/radio-samoa-tia-with-queen-poke.xml",
        "link": "https://radiosamoa.co.nz/podcast-tia-with-queen-poke/",
    },
    {
        "name": "Hawaii & USA Report",
        "patterns": [
            "Hawaii & USA Report*",
            "Hawaii & USA report*",
            "*Hawaii & USA Report*",
            "*Hawaii & USA report*",
            "Hawaii and USA Report*",
            "*Hawaii and USA Report*",
            "*18868353&ss*",
        ],
        "output": "feeds/radio-samoa-hawaii-usa-report.xml",
        "link": RADIO_SAMOA_SOURCE_FEED,
    },
    {
        "name": "TUA i le ELEELE",
        "patterns": [
            "TUA i le ELEELE*",
            "Tua i le Eleele*",
            "*TUA i le ELEELE*",
            "*Tua i le Eleele*",
        ],
        "output": "feeds/radio-samoa-tua-i-le-eleele.xml",
        "link": RADIO_SAMOA_SOURCE_FEED,
    },
    {
        "name": "Autalaina o le Tulafono",
        "patterns": [
            "Autalaina o le Tulafono*",
            "*Autalaina o le Tulafono*",
        ],
        "output": "feeds/radio-samoa-autalaina-o-le-tulafono.xml",
        "link": RADIO_SAMOA_SOURCE_FEED,
    },
    {
        "name": "Interviews",
        "patterns": [
            "Interviews*",
            "Interview*",
            "*Interviews*",
            "*Interview*",
        ],
        "output": "feeds/radio-samoa-interviews.xml",
        "link": "https://radiosamoa.co.nz/podcast-interviews/",
    },
    {
        "name": "Talatalaga",
        "patterns": [
            "Talatalaga*",
            "*Talatalaga*",
        ],
        "output": "feeds/radio-samoa-talatalaga.xml",
        "link": RADIO_SAMOA_SOURCE_FEED,
    },
]

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

def child_by_local(parent: ET.Element, name: str) -> ET.Element | None:
    if parent is None:
        return None
    want = name.lower()
    for ch in list(parent):
        if localname(ch.tag).lower() == want:
            return ch
    return None

def get(url: str, timeout: int = 30) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "myrss-feed-gen101/1.0 (+https://myitsolutionspg.github.io/myrss-feed-gen101/)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
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
    u = (url or "").lower().split("?", 1)[0]
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    if u.endswith(".gif"):
        return "image/gif"
    if u.endswith(".svg"):
        return "image/svg+xml"
    return "image/jpeg"

def find_image_from_item(item: ET.Element) -> str | None:
    for ch in list(item):
        ln = localname(ch.tag).lower()
        if ln == "enclosure" and ch.attrib.get("url"):
            return ch.attrib.get("url")
        if ln in ("thumbnail", "content") and ch.attrib.get("url"):
            return ch.attrib.get("url")
    return None

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

def extract_namespaces(xml_bytes: bytes) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    try:
        for _, ns in ET.iterparse(BytesIO(xml_bytes), events=("start-ns",)):
            prefix, uri = ns
            if prefix not in namespaces:
                namespaces[prefix] = uri
    except ET.ParseError:
        return namespaces
    return namespaces

def register_namespaces(namespaces: dict[str, str]) -> None:
    ET.register_namespace("atom", ATOM_NS)
    ET.register_namespace("itunes", ITUNES_NS)
    ET.register_namespace("content", CONTENT_NS)

    for prefix, uri in namespaces.items():
        # Do not register default namespace.
        # Also skip namespaces we already register manually above.
        if not prefix or prefix in ("xml", "xmlns", "atom", "itunes", "content"):
            continue

        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            # Ignore reserved or invalid namespace prefixes.
            continue

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
                    "length": "0",
                },
            )

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)

# ---------------- Radio Samoa filtered podcast feeds ----------------
def find_rss_channel(root: ET.Element) -> ET.Element | None:
    for el in root.iter():
        if localname(el.tag).lower() == "channel":
            return el
    return None

def get_item_search_text(item: ET.Element) -> str:
    """
    Build searchable text from all useful RSS / podcast item fields.
    This catches programme names stored in title, description,
    content:encoded, itunes:summary, category, link, guid, or attributes.
    """
    parts: list[str] = []

    for ch in item.iter():
        if ch.text and safe_text(ch.text):
            parts.append(safe_text(ch.text))

        for attr_value in ch.attrib.values():
            if attr_value and safe_text(attr_value):
                parts.append(safe_text(attr_value))

    return "\n".join(parts)


def wildcard_pattern_matches(text: str, pattern: str) -> bool:
    """
    Supports simple '*' wildcard matching.

    Examples:
      "Taimi with TUAMAN*" matches "Taimi with TUAMAN - #41"
      "*Queen Poke*" matches anything containing "Queen Poke"
      "Talatalaga*" matches titles/descriptions beginning with Talatalaga
    """
    text_normalized = safe_text(text).casefold()
    pattern_normalized = safe_text(pattern).casefold()

    if not pattern_normalized:
        return False

    if "*" not in pattern_normalized:
        return pattern_normalized in text_normalized

    escaped = re.escape(pattern_normalized).replace(r"\*", ".*")
    return re.search(escaped, text_normalized, flags=re.IGNORECASE | re.DOTALL) is not None


def item_matches_programme(item: ET.Element, programme: dict) -> bool:
    search_text = get_item_search_text(item)

    patterns = programme.get("patterns")
    if not patterns:
        old_keyword = programme.get("keyword", "")
        patterns = [old_keyword]

    return any(wildcard_pattern_matches(search_text, pattern) for pattern in patterns)

def copy_channel_value(source_channel: ET.Element, target_channel: ET.Element, tag_name: str) -> None:
    value = child_text_by_local(source_channel, tag_name)
    if value:
        ET.SubElement(target_channel, tag_name).text = value

def build_radio_samoa_programme_feed(
    source_channel: ET.Element,
    programme: dict[str, str],
    matching_items: list[ET.Element],
) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = programme["name"]
    ET.SubElement(channel, "link").text = programme["link"]
    ET.SubElement(channel, "description").text = (
        f"Filtered Radio Samoa podcast feed for {programme['name']}."
    )
    ET.SubElement(channel, "language").text = child_text_by_local(source_channel, "language") or "en"
    ET.SubElement(channel, "lastBuildDate").text = utc_now_rfc2822()
    ET.SubElement(channel, "generator").text = "myrss-feed-gen101 Radio Samoa filtered podcast feed generator"

    # Keep useful channel-level metadata where present.
    for tag_name in ("copyright", "managingEditor", "webMaster"):
        copy_channel_value(source_channel, channel, tag_name)

    source_image = child_by_local(source_channel, "image")
    if source_image is not None:
        channel.append(deepcopy(source_image))

    for item in matching_items:
        channel.append(deepcopy(item))

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)

def write_xml_no_bom(output_path: str, xml_bytes: bytes) -> None:
    path = pathlib_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(xml_bytes)

def pathlib_path(path: str) -> 'Path':
    from pathlib import Path
    return Path(path)

def validate_rss_file(output_path: str) -> None:
    path = pathlib_path(output_path)

    if not path.exists():
        raise RuntimeError(f"Missing RSS output file: {output_path}")

    raw = path.read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError(f"RSS output contains UTF-8 BOM: {output_path}")

    root = ET.fromstring(raw)

    if localname(root.tag).lower() != "rss":
        raise RuntimeError(f"Invalid RSS root element in {output_path}: {root.tag}")

    if root.attrib.get("version") != "2.0":
        raise RuntimeError(f"RSS version is not 2.0 in {output_path}")

    channel = find_rss_channel(root)
    if channel is None:
        raise RuntimeError(f"Missing channel element in {output_path}")

    title = child_text_by_local(channel, "title")
    description = child_text_by_local(channel, "description")

    if not title:
        raise RuntimeError(f"Missing channel title in {output_path}")

    if not description:
        raise RuntimeError(f"Missing channel description in {output_path}")

def generate_radio_samoa_filtered_podcast_feeds() -> None:
    print("[INFO] Generating Radio Samoa filtered podcast feeds...")

    source_xml = get(RADIO_SAMOA_SOURCE_FEED, timeout=60)
    namespaces = extract_namespaces(source_xml)
    register_namespaces(namespaces)

    source_root = ET.fromstring(source_xml)
    source_channel = find_rss_channel(source_root)

    if source_channel is None:
        raise RuntimeError("Radio Samoa source feed does not contain a channel element.")

    source_items = [
        item for item in list(source_channel) if localname(item.tag).lower() == "item"
    ]

    summary: list[tuple[str, int]] = []

    for programme in RADIO_SAMOA_PROGRAMMES:
        matching_items = [
            item
            for item in source_items
            if item_matches_programme(item, programme)
        ]

        xml_bytes = build_radio_samoa_programme_feed(
            source_channel=source_channel,
            programme=programme,
            matching_items=matching_items,
        )

        write_xml_no_bom(programme["output"], xml_bytes)
        validate_rss_file(programme["output"])

        summary.append((programme["name"], len(matching_items)))

    print("Radio Samoa filtered podcast feed summary:")
    for programme_name, item_count in summary:
        print(f"- {programme_name}: {item_count} items")

# ---------------- main workflow ----------------
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

            limit = int(src.get("max_items", 15))
            items = items[:limit]

            if items:
                ok_sources += 1
            all_items.extend(items)
            print(f"[INFO] {name}: {len(items)} items")
        except (HTTPError, URLError, ET.ParseError) as e:
            print(f"[WARN] Source failed: {name} {url} :: {e}", file=sys.stderr)

    # De-dupe after all sources have been fetched. Keep first occurrence.
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in all_items:
        key = hash_id(it.get("guid", ""), it.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # Group by source, sort each source newest-first.
    by_source: dict[str, list[dict]] = {}
    for it in uniq:
        src = safe_text(it.get("source")) or "Unknown"
        by_source.setdefault(src, []).append(it)

    for src, arr in by_source.items():
        arr.sort(key=lambda x: parse_rfc2822_to_dt(safe_text(x.get("pubDate"))), reverse=True)

    # Round-robin merge across sources for a balanced feed.
    sources_order = sorted(by_source.keys(), key=str.lower)
    merged: list[dict] = []
    idx = 0
    while len(merged) < max_total:
        progressed = False
        for src in sources_order:
            arr = by_source.get(src, [])
            if idx < len(arr):
                merged.append(arr[idx])
                progressed = True
                if len(merged) >= max_total:
                    break
        if not progressed:
            break
        idx += 1

    uniq = merged

    rss_bytes = build_rss(cfg, uniq)
    with open(out_path, "wb") as f:
        f.write(rss_bytes)

    print(f"[DONE] Generated {out_path}: {len(uniq)} items (sources ok: {ok_sources}/{len(sources)})")

    # Additional additive output. This does not change the existing aggregated feed.
    generate_radio_samoa_filtered_podcast_feeds()

if __name__ == "__main__":
    main()
