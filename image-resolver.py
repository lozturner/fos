"""
Image Resolver v2 — multi-source parallel image hunter.
Port 8774.

Sources (all run in parallel):
  ddg       — DuckDuckGo Images scrape
  bing      — Bing Images scrape
  amazon    — Amazon UK product search images
  wikipedia — Wikipedia + Wikimedia Commons
  unsplash  — Unsplash photo search
  og        — Open Graph scrape from item's own product URL

Endpoints:
  GET  /api/hunt     — run all sources in parallel, return all candidates
  GET  /api/verify   — AI-verify one URL against an item name
  GET  /api/resolve  — full auto pipeline (best winner only)
  POST /api/batch    — batch resolve
  GET  /api/verified — dump cache
  GET  /api/health
"""

import os, re, sys, json, base64, urllib.request, urllib.parse, urllib.error
import threading, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, Response

import anthropic

BASE_DIR      = Path(__file__).parent.resolve()
VERIFIED_FILE = BASE_DIR / "spend_data" / "verified_images.json"
(BASE_DIR / "spend_data").mkdir(exist_ok=True)

app    = Flask(__name__)
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

# ── Verified image cache ───────────────────────────────────────────────────

def load_verified():
    if VERIFIED_FILE.exists():
        try:
            return json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_verified(db):
    VERIFIED_FILE.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")

verified_db = load_verified()
verify_cache: dict[str, dict] = {}   # url → result, in-memory only

# ── Source: DuckDuckGo Images ─────────────────────────────────────────────

def search_duckduckgo(query: str) -> list[str]:
    out = []
    try:
        q       = urllib.parse.quote(query)
        init    = f"https://duckduckgo.com/?q={q}&iax=images&ia=images"
        req     = urllib.request.Request(init, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="replace")

        vqd = (re.search(r'vqd=([^&"\'<>\s]+)', html) or
               re.search(r'"vqd"\s*:\s*"([^"]+)"', html))
        if not vqd:
            return out
        vqd = vqd.group(1)

        img_url = (
            f"https://duckduckgo.com/i.js"
            f"?l=uk-en&o=json&q={q}&vqd={vqd}&f=,,,,,&p=1"
        )
        req2 = urllib.request.Request(img_url, headers={
            **HEADERS,
            "Referer":          "https://duckduckgo.com/",
            "X-Requested-With": "XMLHttpRequest",
        })
        with urllib.request.urlopen(req2, timeout=12) as r2:
            data = json.loads(r2.read())

        for item in data.get("results", [])[:8]:
            u = item.get("image") or item.get("thumbnail")
            if u and u not in out:
                out.append(u)
    except Exception as e:
        print(f"  [DDG] {e}")
    return out

# ── Source: Bing Images ───────────────────────────────────────────────────

def search_bing(query: str) -> list[str]:
    out = []
    try:
        q   = urllib.parse.quote(query)
        url = f"https://www.bing.com/images/search?q={q}&form=HDRSC2&first=1"
        req = urllib.request.Request(url, headers={**HEADERS, "Referer": "https://www.bing.com/"})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="replace")

        for u in re.findall(r'"murl"\s*:\s*"([^"]+)"', html)[:8]:
            if u not in out:
                out.append(u)

        if not out:
            for u in re.findall(r'<img[^>]+src="(https://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', html)[:6]:
                if "bing.com" not in u and u not in out:
                    out.append(u)
    except Exception as e:
        print(f"  [Bing] {e}")
    return out

# ── Source: Amazon UK product search ──────────────────────────────────────

def search_amazon(query: str) -> list[str]:
    out = []
    try:
        q   = urllib.parse.quote(query)
        url = f"https://www.amazon.co.uk/s?k={q}&ref=nb_sb_noss"
        req = urllib.request.Request(url, headers={
            **HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=14) as r:
            html = r.read().decode("utf-8", errors="replace")

        # Primary: class="s-image" src attrs
        imgs = re.findall(r'<img[^>]+class="[^"]*s-image[^"]*"[^>]+src="([^"]+)"', html)
        if not imgs:
            # Fallback: data-image-source-density
            imgs = re.findall(r'data-image-source-density="1"[^>]*src="([^"]+)"', html)
        if not imgs:
            # JSON blobs Amazon sometimes embeds
            imgs = re.findall(r'"hiRes"\s*:\s*"(https://[^"]+\.jpg[^"]*)"', html)

        for u in imgs[:8]:
            # Upgrade to higher-res version if Amazon CDN URL
            u = re.sub(r'\._[A-Z]{2}\d+_\.', '._SX600_SY600_.', u)
            if u not in out:
                out.append(u)
    except Exception as e:
        print(f"  [Amazon] {e}")
    return out

# ── Source: Unsplash ──────────────────────────────────────────────────────

def search_unsplash(query: str) -> list[str]:
    out = []
    try:
        slug = urllib.parse.quote(query.replace(" ", "-").lower())
        url  = f"https://unsplash.com/s/photos/{slug}"
        req  = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read(300_000).decode("utf-8", errors="replace")

        raws = re.findall(r'"urls"\s*:\s*\{[^}]*"raw"\s*:\s*"([^"]+)"', html)
        for raw in raws[:6]:
            u = raw.replace("\\u0026", "&").split("?")[0] + "?w=600&q=80&fm=jpg"
            if u not in out:
                out.append(u)
    except Exception as e:
        print(f"  [Unsplash] {e}")
    return out

# ── Source: Wikipedia + Wikimedia Commons ─────────────────────────────────

def search_wikipedia(query: str) -> list[str]:
    out = []
    try:
        q   = urllib.parse.quote(query)
        url = (f"https://en.wikipedia.org/w/api.php?action=query"
               f"&titles={q}&prop=pageimages&format=json&pithumbsize=800&pilimit=3")
        req = urllib.request.Request(url, headers={"User-Agent": "LozWishlist/2.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        for page in data.get("query", {}).get("pages", {}).values():
            t = page.get("thumbnail", {}).get("source")
            if t and t not in out:
                out.append(t)
    except Exception:
        pass
    try:
        q   = urllib.parse.quote(query)
        url = (f"https://commons.wikimedia.org/w/api.php?action=query"
               f"&list=search&srsearch={q}&srnamespace=6&srlimit=5&format=json")
        req = urllib.request.Request(url, headers={"User-Agent": "LozWishlist/2.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        for result in data.get("query", {}).get("search", [])[:4]:
            title = result.get("title", "")
            if title.startswith("File:"):
                u = _wikimedia_url(title)
                if u and u not in out:
                    out.append(u)
    except Exception:
        pass
    return out

def _wikimedia_url(file_title: str) -> str | None:
    try:
        t   = urllib.parse.quote(file_title)
        url = (f"https://commons.wikimedia.org/w/api.php?action=query"
               f"&titles={t}&prop=imageinfo&iiprop=url&format=json")
        req = urllib.request.Request(url, headers={"User-Agent": "LozWishlist/2.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        for page in data.get("query", {}).get("pages", {}).values():
            info = page.get("imageinfo", [{}])
            u = info[0].get("url") if info else None
            if u:
                return u
    except Exception:
        pass
    return None

# ── Source: Open Graph from product page URL ──────────────────────────────

def scrape_og_image(page_url: str) -> str | None:
    try:
        req  = urllib.request.Request(page_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read(65_536).decode("utf-8", errors="replace")
        m = (re.search(r'<meta[^>]+(?:og:image|twitter:image)[^>]+content=["\']([^"\']+)["\']', html, re.I) or
             re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:og:image|twitter:image)', html, re.I))
        return m.group(1) if m else None
    except Exception:
        return None

# ── Image download + Claude Vision verify ────────────────────────────────

def fetch_image_b64(img_url: str):
    try:
        req = urllib.request.Request(img_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as r:
            data = r.read(8 * 1024 * 1024)
        ct = "image/jpeg"
        if img_url.lower().endswith(".png") or data[:4] == b'\x89PNG':
            ct = "image/png"
        elif img_url.lower().endswith(".webp"):
            ct = "image/webp"
        return base64.standard_b64encode(data).decode(), ct
    except Exception:
        return None, None

def verify_image(img_url: str, item_name: str) -> dict:
    """AI-verify one URL. Returns {match, confidence, description, reason}."""
    if img_url in verify_cache:
        return verify_cache[img_url]

    b64, ct = fetch_image_b64(img_url)
    if not b64:
        result = {"match": False, "confidence": 0, "description": "", "reason": "Could not download image"}
        verify_cache[img_url] = result
        return result

    prompt = (
        f'You are verifying whether an image correctly shows: "{item_name}"\n\n'
        'Look at the image carefully and respond with ONLY this JSON (no markdown):\n'
        '{"match": true/false, "confidence": 0-100, '
        '"description": "what you see in the image", '
        '"reason": "why it does or does not match"}\n\n'
        'Be strict: if you can clearly see the specific product/item named, '
        'match=true with high confidence. If wrong, generic, or unclear, match=false.'
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": ct, "data": b64}},
                {"type": "text",  "text": prompt},
            ]}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
    except Exception as e:
        result = {"match": False, "confidence": 0, "description": "", "reason": str(e)}

    verify_cache[img_url] = result
    return result

# ── Hunt: run all sources in parallel ────────────────────────────────────

def run_all_sources(query: str, item_url: str = "") -> dict:
    """Run all image sources in parallel. Returns {source: {status, candidates}}."""
    tasks = {
        "ddg":       lambda: search_duckduckgo(query),
        "bing":      lambda: search_bing(query),
        "amazon":    lambda: search_amazon(query),
        "wikipedia": lambda: search_wikipedia(query),
        "unsplash":  lambda: search_unsplash(query),
    }
    if item_url and item_url.startswith("http"):
        def _og():
            u = scrape_og_image(item_url)
            return [u] if u else []
        tasks["og"] = _og

    out = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                urls = [u for u in (future.result() or []) if u and u.startswith("http")]
                out[name] = {"status": "ok" if urls else "empty", "candidates": urls[:8]}
            except Exception as e:
                out[name] = {"status": "error", "candidates": [], "error": str(e)}

    return out

# ── Auto-resolve pipeline (winner only) ───────────────────────────────────

def resolve_item(item_name: str, item_id: str, item_url: str = "", force: bool = False) -> dict:
    if not force and item_id in verified_db and verified_db[item_id].get("verified"):
        return {**verified_db[item_id], "cached": True}

    result = {"item_id": item_id, "item_name": item_name,
              "img_url": None, "confidence": 0, "description": "",
              "verified": False, "attempts": [], "source": None}

    sources = run_all_sources(item_name, item_url)
    all_candidates = []
    for src_name, src_data in sources.items():
        for url in src_data.get("candidates", []):
            all_candidates.append((src_name, url))

    if not all_candidates:
        result["reason"] = "No candidates found from any source"
        verified_db[item_id] = result
        save_verified(verified_db)
        return result

    print(f"  {len(all_candidates)} total candidates across all sources, verifying…")
    best_attempt = None

    for source, url in all_candidates[:12]:
        v = verify_image(url, item_name)
        attempt = {"source": source, "url": url,
                   "match": v.get("match", False),
                   "confidence": v.get("confidence", 0),
                   "description": v.get("description", ""),
                   "reason": v.get("reason", "")}
        result["attempts"].append(attempt)

        if best_attempt is None or v.get("confidence", 0) > best_attempt["confidence"]:
            best_attempt = attempt

        if v.get("match") and v.get("confidence", 0) >= 55:
            result.update(img_url=url, confidence=v["confidence"],
                          description=v.get("description", ""),
                          verified=True, source=source)
            print(f"  ✓ {source}: {v['confidence']}% — {v.get('description','')[:60]}")
            break

    if not result["verified"] and best_attempt:
        result.update(img_url=best_attempt["url"],
                      confidence=best_attempt["confidence"],
                      description=best_attempt.get("description", ""),
                      source=best_attempt["source"])

    verified_db[item_id] = result
    save_verified(verified_db)
    return result

# ── Flask API ─────────────────────────────────────────────────────────────

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return r


@app.route("/api/hunt", methods=["GET", "OPTIONS"])
def api_hunt():
    """Run all sources in parallel, return every candidate from every source."""
    if request.method == "OPTIONS":
        return "", 204
    q    = request.args.get("q", "").strip()
    id_  = request.args.get("id", q).strip()
    iurl = request.args.get("url", "").strip()
    if not q:
        return jsonify({"error": "Missing q parameter"}), 400

    print(f"\n🔍 Hunt: {q}")
    sources = run_all_sources(q, iurl)
    total   = sum(len(v["candidates"]) for v in sources.values())
    print(f"  Found {total} total candidates")

    return jsonify({"item_id": id_, "item_name": q, "sources": sources})


@app.route("/api/verify", methods=["GET", "OPTIONS"])
def api_verify():
    """AI-verify a single image URL against an item name."""
    if request.method == "OPTIONS":
        return "", 204
    img_url   = request.args.get("url", "").strip()
    item_name = request.args.get("q", "").strip()
    if not img_url or not item_name:
        return jsonify({"error": "Missing url or q"}), 400
    result = verify_image(img_url, item_name)
    return jsonify(result)


@app.route("/api/resolve", methods=["GET", "OPTIONS"])
def api_resolve():
    if request.method == "OPTIONS":
        return "", 204
    q     = request.args.get("q", "").strip()
    id_   = request.args.get("id", q).strip()
    iurl  = request.args.get("url", "").strip()
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    if not q:
        return jsonify({"error": "Missing q"}), 400
    return jsonify(resolve_item(q, id_, item_url=iurl, force=force))


@app.route("/api/batch", methods=["POST", "OPTIONS"])
def api_batch():
    if request.method == "OPTIONS":
        return "", 204
    items = request.json or []
    if not items:
        return jsonify([])
    def stream():
        yield "["
        for i, item in enumerate(items):
            r = resolve_item(item.get("name", ""), item.get("id", ""), item.get("url", ""))
            yield ("," if i else "") + json.dumps(r)
            time.sleep(0.2)
        yield "]"
    return Response(stream(), mimetype="application/json")


@app.route("/api/verified")
def api_verified():
    return jsonify(verified_db)


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "image-resolver-v2", "cached": len(verified_db)})


if __name__ == "__main__":
    print("=" * 60)
    print("  Image Resolver v2  →  http://127.0.0.1:8774")
    print(f"  Cached: {len(verified_db)} items")
    print("  Sources: DDG · Bing · Amazon · Wikipedia · Unsplash · OG")
    print("  Endpoints: /api/hunt  /api/verify  /api/resolve  /api/batch")
    print("=" * 60)
    app.run(host="127.0.0.1", port=8774, debug=False, threaded=True)
