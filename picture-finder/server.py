"""
Picture Finder — standalone image hunting server.
Port 8776.

Endpoints:
  GET  /              → serves index.html
  GET  /pf-bridge.js  → serves the host-app integration bridge
  GET  /api/search    → proxies image search (bing/amazon/argos/google)
  GET  /api/verify    → Claude Vision confidence check
  GET  /api/health    → status

Usage:
  python server.py
  → open http://localhost:8776

Standalone or embedded via pf-bridge.js in any host app.
"""

import re, json, base64, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

import anthropic

HERE   = Path(__file__).parent.resolve()
app    = Flask(__name__, static_folder=str(HERE))
client = anthropic.Anthropic()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

verify_cache: dict[str, dict] = {}

# ── CORS ──────────────────────────────────────────────────────────────────

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return r

# ── Static files ───────────────────────────────────────────────────────────

@app.route("/")
def root():
    return send_from_directory(HERE, "index.html")

@app.route("/pf-bridge.js")
def bridge():
    return send_from_directory(HERE, "pf-bridge.js")

# ── Search proxy ───────────────────────────────────────────────────────────

def _fetch(url, extra_headers=None):
    h = {**HEADERS, **(extra_headers or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", errors="replace")

def search_bing(q):
    urls = []
    try:
        html = _fetch(f"https://www.bing.com/images/search?q={urllib.parse.quote(q)}&form=HDRSC2",
                      {"Referer": "https://www.bing.com/"})
        for m in re.findall(r'"murl"\s*:\s*"([^"]+)"', html)[:10]:
            if m not in urls: urls.append(m)
    except Exception as e:
        print(f"[Bing] {e}")
    return urls

def search_amazon(q):
    urls = []
    try:
        html = _fetch(f"https://www.amazon.co.uk/s?k={urllib.parse.quote(q)}")
        imgs = re.findall(r'<img[^>]+class="[^"]*s-image[^"]*"[^>]+src="([^"]+)"', html)
        for u in imgs[:8]:
            u = re.sub(r'\._[A-Z]{2}\d+_\.', '._SX600_SY600_.', u)
            if u not in urls: urls.append(u)
    except Exception as e:
        print(f"[Amazon] {e}")
    return urls

def search_argos(q):
    urls = []
    try:
        html = _fetch(f"https://www.argos.co.uk/search/{urllib.parse.quote(q)}/",
                      {"Referer": "https://www.argos.co.uk/"})
        # Argos embeds product data as JSON in script tags
        blobs = re.findall(r'"imageUrl"\s*:\s*"([^"]+)"', html)
        for u in blobs[:8]:
            u = u.replace("\\u0026", "&")
            if u.startswith("http") and u not in urls:
                urls.append(u)
        if not urls:
            imgs = re.findall(r'<img[^>]+src="(https://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', html)
            for u in imgs[:6]:
                if "argos.co.uk" in u and u not in urls:
                    urls.append(u)
    except Exception as e:
        print(f"[Argos] {e}")
    return urls

def search_google(q):
    """Scrape Google Images (less reliable but useful fallback)."""
    urls = []
    try:
        html = _fetch(
            f"https://www.google.com/search?q={urllib.parse.quote(q)}&tbm=isch",
            {"Referer": "https://www.google.com/"}
        )
        # Google embeds image data in AF_initDataCallback blobs
        blobs = re.findall(r'https?://[^\s"\'\\]+\.(?:jpg|jpeg|png|webp)', html)
        seen = set()
        for u in blobs:
            if len(u) > 50 and "google" not in u and u not in seen:
                urls.append(u); seen.add(u)
            if len(urls) >= 8: break
    except Exception as e:
        print(f"[Google] {e}")
    return urls

SOURCES = {
    "bing":   search_bing,
    "amazon": search_amazon,
    "argos":  search_argos,
    "google": search_google,
}

@app.route("/api/search", methods=["GET", "OPTIONS"])
def api_search():
    if request.method == "OPTIONS": return "", 204
    q      = request.args.get("q", "").strip()
    source = request.args.get("source", "bing").lower()
    if not q: return jsonify({"error": "Missing q"}), 400
    fn = SOURCES.get(source, search_bing)
    print(f"[Search] {source}: {q}")
    urls = fn(q)
    return jsonify({"source": source, "q": q, "urls": urls})

# ── Batch search all sources ───────────────────────────────────────────────

@app.route("/api/hunt", methods=["GET", "OPTIONS"])
def api_hunt():
    if request.method == "OPTIONS": return "", 204
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"error": "Missing q"}), 400

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fn, q): name for name, fn in SOURCES.items()}
        for f in as_completed(futures):
            name = futures[f]
            try:
                urls = [u for u in (f.result() or []) if u.startswith("http")]
                results[name] = {"status": "ok" if urls else "empty", "urls": urls[:8]}
            except Exception as e:
                results[name] = {"status": "error", "urls": [], "error": str(e)}

    return jsonify({"q": q, "sources": results})

# ── Claude Vision verify ───────────────────────────────────────────────────

@app.route("/api/verify", methods=["GET", "OPTIONS"])
def api_verify():
    if request.method == "OPTIONS": return "", 204
    img_url = request.args.get("url", "").strip()
    q       = request.args.get("q", "").strip()
    if not img_url or not q: return jsonify({"error": "Missing url or q"}), 400

    cache_key = f"{img_url}|{q}"
    if cache_key in verify_cache:
        return jsonify({**verify_cache[cache_key], "cached": True})

    try:
        req = urllib.request.Request(img_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as r:
            data = r.read(8 * 1024 * 1024)
        ct = "image/jpeg"
        if img_url.lower().endswith(".png") or data[:4] == b'\x89PNG': ct = "image/png"
        elif img_url.lower().endswith(".webp"): ct = "image/webp"
        b64 = base64.standard_b64encode(data).decode()
    except Exception as e:
        return jsonify({"match": False, "confidence": 0, "description": "", "reason": str(e)})

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "image",  "source": {"type": "base64", "media_type": ct, "data": b64}},
                {"type": "text",   "text": (
                    f'Does this image show: "{q}"?\n'
                    'Reply ONLY with JSON: {"match":true/false,"confidence":0-100,'
                    '"description":"what you see","reason":"why match or not"}'
                )},
            ]}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"): text = text.split("\n",1)[1].rsplit("```",1)[0].strip()
        result = json.loads(text)
    except Exception as e:
        result = {"match": False, "confidence": 0, "description": "", "reason": str(e)}

    verify_cache[cache_key] = result
    return jsonify(result)

# ── Health ─────────────────────────────────────────────────────────────────

@app.route("/api/health")
def api_health():
    return jsonify({
        "ok":      True,
        "service": "picture-finder",
        "version": "1.0.0",
        "sources": list(SOURCES.keys()),
        "port":    8776,
    })

# ── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 58)
    print("  🖼  Picture Finder  →  http://localhost:8776")
    print("  Sources: Bing · Amazon · Argos · Google")
    print("  Bridge:  http://localhost:8776/pf-bridge.js")
    print("  Embed:   <script src='http://localhost:8776/pf-bridge.js'>")
    print("=" * 58)
    app.run(host="0.0.0.0", port=8776, debug=False, threaded=True)
