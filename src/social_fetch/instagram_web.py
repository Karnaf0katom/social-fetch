"""Save public Instagram videos using SnapInsta.lc's ordinary web form.

Network acquisition only: validate/decode saved MP4s separately through cpu-slot.sh.
No Instagram account, session cookies, installer, extension, or paid API is used.
The manifest retains source identity and captions, never temporary download URLs.
"""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import json
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SITE = "https://snapinsta.lc"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def shortcode_id(code):
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,16}", code):
        raise ValueError("Invalid Instagram post shortcode")
    number = 0
    for letter in code:
        number = number * 64 + ALPHABET.index(letter)
    return str(number)


def post_code(url):
    parts = urlsplit(url)
    match = re.fullmatch(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,16})/?", parts.path)
    if (parts.scheme != "https" or parts.hostname not in {"instagram.com", "www.instagram.com"}
            or parts.username or parts.password or parts.port not in (None, 443) or not match):
        raise ValueError("Use a public HTTPS Instagram post or Reel URL")
    return match[1]


def permitted_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
            or not (host in {"snapinsta.lc", "instacdn.beubagah.com"}
                    or host.endswith(".cdninstagram.com") or host.endswith(".fbcdn.net"))):
        raise ValueError("Unexpected media delivery host")
    return url


class DeliveryRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        permitted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(path, data=None):
    url = permitted_url(path if path.startswith("https://") else SITE + path)
    body = urlencode(data).encode() if data is not None else None
    return build_opener(DeliveryRedirects()).open(Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0", "Referer": SITE + "/", "Origin": SITE,
        **({"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"} if body else {}),
    }), timeout=60)


def page(path, data=None):
    with request(path, data) as response:
        result = response.read(6 * 1024**2 + 1)
    if len(result) > 6 * 1024**2:
        raise ValueError("Unexpectedly large web form response")
    return result.decode("utf-8")


def api(path, data=None):
    return json.loads(page(path, data))


class Node:
    def __init__(self, tag="root", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        return "".join(child.text() if isinstance(child, Node) else child for child in self.children)


class Form(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)
        if tag == "br":
            self.stack[-1].children.append("\n")

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def videos(form, standalone_code=None):
    posts = [node for node in form.root.walk() if "data-post-id" in node.attrs]
    if standalone_code:
        posts = [form.root]
    rows = []
    for post in posts:
        code = standalone_code or post.attrs["data-post-id"]
        caption = next((n.text().strip() for n in post.walk()
                        if "profile-post-caption" in n.attrs.get("class", "").split()), "")
        for collection in (n for n in post.walk() if "data-collection" in n.attrs):
            for item in (n for n in collection.walk() if n.attrs.get("data-media-type") == "video"):
                media_id = item.attrs["data-media-id"].split("_")[0]
                if media_id != shortcode_id(code):
                    raise ValueError(f"Web form returned a different post for {code}")
                index = item.attrs.get("data-media-index", "0")
                if not index.isdigit():
                    raise ValueError("Invalid media index")
                expected_duration = None
                try:
                    metadata = parse_qs(urlsplit(item.attrs["data-media-src"]).query)["efg"][0]
                    metadata = json.loads(base64.b64decode(metadata + "=" * (-len(metadata) % 4)))
                    expected_duration = float(metadata.get("duration_s") or 0) or None
                except (KeyError, ValueError):
                    pass
                rows.append({"shortcode": code, "index": int(index), "media_id": media_id,
                             "source_url": f"https://www.instagram.com/p/{code}/", "caption": caption,
                             "source_duration_seconds": expected_duration,
                             "poster_url": item.attrs.get("data-media-poster"),
                             "media_url": item.attrs["data-media-src"],
                             "collection": collection.attrs["data-collection"]})
    return rows


def discover_profile(username, cached_pages=None, limit=None, max_pages=150):
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
        raise ValueError("Use an Instagram username")
    if cached_pages:
        summary = json.loads((cached_pages / "enumeration-summary.json").read_text())
        files = [cached_pages / "profile-result.html"]
        files.extend(cached_pages / f"profile-page{n}.html" for n in range(2, summary["page_count"] + 1))
        forms = [Form(file.read_text()) for file in files]
        overview = next(n for n in forms[0].root.walk() if "data-username" in n.attrs)
        if overview.attrs["data-username"] != username:
            raise ValueError("Cached profile belongs to another account")
        rows = list({(row["shortcode"], row["index"]): row
                     for form in forms for row in videos(form)}.values())
        selected = rows if limit is None else rows[:limit]
        return selected, {**summary, "limit": limit, "selected_videos": len(selected),
                          "limit_reached": limit is not None and len(rows) >= limit}
    html = page("/process", {"q": f"https://www.instagram.com/{username}/", "scope": "home", "lang": "en"})
    rows, cursors = [], set()
    for number in range(1, max_pages + 1):
        form = Form(html)
        if number == 1:
            overview = next(n for n in form.root.walk() if "data-username" in n.attrs)
            if overview.attrs["data-username"] != username:
                raise ValueError("Web form returned another profile")
            session = overview.attrs["data-viewer-session"]
        additions = videos(form)
        rows.extend(additions)
        rows = list({(row["shortcode"], row["index"]): row for row in rows}.values())
        more = next((n for n in form.root.walk() if "profile-more" in n.attrs.get("class", "").split()), None)
        print(f"discovery page={number} videos={len(additions)} total={len(rows)}", flush=True)
        if more is None:
            if not additions and "No available items" not in form.root.text():
                raise ValueError("Empty profile response does not establish completion")
            selected = rows if limit is None else rows[:limit]
            return selected, {"page_count": number, "terminal_page_reached": True,
                              "limit": limit, "selected_videos": len(selected),
                              "limit_reached": limit is not None and len(rows) >= limit}
        if limit is not None and len(rows) >= limit:
            return rows[:limit], {"page_count": number, "terminal_page_reached": False,
                                 "limit": limit, "selected_videos": limit, "limit_reached": True}
        cursor = more.attrs["data-after"]
        if cursor in cursors:
            raise ValueError("Profile pagination repeated its cursor")
        cursors.add(cursor)
        if number == max_pages:
            if limit is not None:
                return rows[:limit], {'page_count': number, 'terminal_page_reached': False,
                                     'limit': limit, 'selected_videos': min(len(rows), limit),
                                     'limit_reached': len(rows) >= limit, 'page_bound_reached': True}
            raise ValueError('Profile exceeds this run\'s page bound')
        html = page("/viewer", {"username": username, "viewerSession": session,
                                "view": "posts", "after": cursor, "lang": "en"})
    raise ValueError("Profile exceeds this run's 150-page bound")


def transfer(row, output, target):
    filename = row["shortcode"] + (f"-{row['index']}" if row["index"] else "") + ".mp4"
    final = output / "source" / filename
    partial = final.with_suffix(".part")
    size, digest = 0, hashlib.sha256()
    transfer_deadline = time.monotonic() + 300
    with request(target) as response, partial.open("wb") as file:
        if response.status != 200:
            raise ValueError("Expected a complete HTTP 200 media response")
        expected = response.headers.get("Content-Length")
        if expected and int(expected) > 512 * 1024**2:
            raise ValueError("Media exceeds the 512 MiB per-file bound")
        while chunk := response.read(256 * 1024):
            file.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if size > 512 * 1024**2 or time.monotonic() > transfer_deadline:
                raise ValueError("Media transfer exceeded its size or time bound")
    with partial.open("rb") as file:
        signature = file.read(128)
    if size < 1024 or b"ftyp" not in signature:
        raise ValueError("Download response is not an MP4")
    if expected and size != int(expected):
        raise ValueError("Incomplete media transfer")
    partial.replace(final)
    return {"status": "downloaded", "file": "source/" + filename,
            "bytes": size, "sha256": digest.hexdigest()}


def download(row, output):
    # The viewer exposes the same public progressive MP4 its video player uses.
    # Prefer that CDN asset; retain the website's prepared delivery as a fallback.
    started = time.monotonic()
    try:
        receipt = transfer(row, output, permitted_url(row["media_url"]))
        return {**receipt, "delivery": "instagram_cdn", "transfer_seconds": round(time.monotonic() - started, 2)}
    except Exception:
        pass
    state = api("/media-jobs", {"collection": row["collection"], "kind": "video", "index": row["index"]})
    job = state.get("job", "")
    if not re.fullmatch(r"[a-f0-9]{32}", job):
        raise ValueError("Invalid media preparation response")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = api("/media-jobs/" + job)
        if state.get("status") == "ready":
            break
        if state.get("status") == "error":
            raise ValueError(state.get("message", "Media preparation failed"))
        time.sleep(1.5)
    else:
        raise TimeoutError("Media preparation did not complete in 180 seconds")
    relative = state.get("download", "")
    if not re.fullmatch(r"/media-download/[a-f0-9]{32}", relative):
        raise ValueError("Invalid media delivery response")
    target = permitted_url(state.get("cdn_download") or SITE + relative)
    receipt = transfer(row, output, target)
    return {**receipt, "delivery": "website_delivery", "transfer_seconds": round(time.monotonic() - started, 2)}




