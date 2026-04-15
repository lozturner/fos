# 🖼 Picture Finder

> **Standalone image-hunting micro-tool with Claude Vision verification.**
> Drop one `<script>` tag into any web app and get a slick modal image picker.
> Works solo *or* embedded. Like a cPanel plugin — install once, use everywhere.

---

## What it does

You've got a list of things — wishlist items, products, project assets — and you need real images for them. Picture Finder searches **Bing, Amazon, Argos, and Google** simultaneously, shows you thumbnails, lets you click to select, then asks **Claude Vision** to verify the image actually matches what you searched for. Confidence score included.

When you're done, it fires a callback to your host app with a clean `{ id: imageUrl }` map — or copies JSON to clipboard if you're running standalone.

---

## Quick start

### 1. Install

```bash
cd picture-finder
python install.py
```

The installer checks Python 3.8+, installs Flask + Anthropic, creates `start.bat`, and prints your integration snippet.

### 2. Run

```bash
python server.py
```

Then open → **http://localhost:8776**

---

## Embed in any web app

Drop one line in your HTML:

```html
<script src="http://localhost:8776/pf-bridge.js"></script>
```

Then call it from your JS:

```js
// Open the picker for a list of items
PictureFinder.open(
  [
    { id: 'chair-1',  name: 'Herman Miller Aeron' },
    { id: 'desk-1',   name: 'Standing desk oak',  currentImg: 'https://...' },
  ],
  (imageMap) => {
    // imageMap = { 'chair-1': 'https://...', 'desk-1': 'https://...' }
    console.log('User picked:', imageMap);
    applyImagesToMyApp(imageMap);
  }
);
```

### Wire to a button

```js
PictureFinder.attachButton('#find-images-btn', getMyItems, handleImages);
```

### Add a floating action button

```js
PictureFinder.fab(getMyItems, handleImages);
// → floating 🖼 button appears bottom-left, opens picker on click
```

---

## API reference (server endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves `index.html` (standalone UI) |
| `GET` | `/pf-bridge.js` | Host-app integration bridge |
| `GET` | `/api/search?q=&source=` | Single-source image search |
| `GET` | `/api/hunt?q=` | All sources in parallel |
| `GET` | `/api/verify?url=&q=` | Claude Vision confidence check |
| `GET` | `/api/health` | Server status JSON |

### `/api/hunt` response shape

```json
{
  "q": "Herman Miller Aeron chair",
  "sources": {
    "bing":   { "status": "ok",    "urls": ["https://...", ...] },
    "amazon": { "status": "ok",    "urls": ["https://...", ...] },
    "argos":  { "status": "empty", "urls": [] },
    "google": { "status": "ok",    "urls": ["https://...", ...] }
  }
}
```

### `/api/verify` response shape

```json
{
  "match": true,
  "confidence": 87,
  "description": "Ergonomic office chair with mesh back and aluminium base",
  "reason": "Image clearly shows Herman Miller Aeron matching the search query"
}
```

---

## pf-bridge.js — PostMessage protocol

The bridge uses `window.postMessage` for safe cross-origin iframe communication.

### Messages sent TO Picture Finder (parent → iframe)

| Type | Payload | When |
|------|---------|------|
| `pf:load-items` | `{ items: [{id, name, currentImg?}] }` | After iframe ready |

### Messages sent FROM Picture Finder (iframe → parent)

| Type | Payload | When |
|------|---------|------|
| `pf:ready` | `{}` | iframe fully loaded |
| `pf:images-saved` | `{ 'item-id': 'https://...' }` | User clicked Apply |
| `pf:close` | `{}` | User dismissed modal |

---

## Architecture

```
Host App (any domain)
  │
  │   <script src="http://localhost:8776/pf-bridge.js">
  │
  ▼
pf-bridge.js                          ← runs in host app context
  │  window.PictureFinder.open()
  │  postMessage: pf:load-items
  │
  ▼
[iframe] index.html (port 8776)       ← sandboxed, full Picture Finder UI
  │
  │  fetch /api/hunt?q=...
  │
  ▼
server.py (Flask, port 8776)          ← search proxy + Claude Vision
  │
  ├── Bing Images scraper
  ├── Amazon.co.uk scraper
  ├── Argos.co.uk scraper
  └── Google Images scraper
        │
        └── /api/verify → Anthropic Claude Haiku 4.5 Vision
```

Data flows back:
```
user clicks thumbnail → sidebar preview → AI verify → confidence badge
  → user clicks "Apply to project"
  → postMessage: pf:images-saved { id: url, ... }
  → pf-bridge.js fires your callback
  → modal closes
```

---

## Files

```
picture-finder/
├── server.py       Flask backend — search proxy + Claude Vision (port 8776)
├── index.html      Full standalone UI — 3-column: items | results | preview
├── pf-bridge.js    Host-app integration bridge — drop-in <script> tag
├── install.py      Self-installer — deps, shortcut, API key check
├── start.bat       Windows launch shortcut (created by install.py)
├── start-silent.bat  Runs without console window (created by install.py)
└── screenshots/    UI screenshots for docs
```

---

## Requirements

- Python 3.8+
- `flask` — `pip install flask`
- `anthropic` — `pip install anthropic`
- `ANTHROPIC_API_KEY` environment variable (for Claude Vision verification)

Without the API key, search still works but confidence scores won't appear.

---

## Integration example — Laurence Wishlist

The wishlist app at port 8773 integrates Picture Finder like this:

```html
<!-- In woop-wishlist.html head -->
<script src="http://localhost:8776/pf-bridge.js"></script>
```

```js
// Collect all items (wishes + owned) and open the picker
function openPictureFinder() {
  const allItems = [
    ...wishes.map(w => ({ id: w.id, name: w.name, currentImg: w.img })),
    ...owned.map(o  => ({ id: o.id, name: o.name, currentImg: o.img })),
  ];

  PictureFinder.open(allItems, (imageMap) => {
    // Apply images back to the relevant list
    Object.entries(imageMap).forEach(([id, url]) => {
      const wish = wishes.find(w => w.id === id);
      if (wish) { wish.img = url; }
      const own = owned.find(o => o.id === id);
      if (own) { own.img = url; }
    });
    saveWish(wishes);
    saveOwned(owned);
    render();
  });
}
```

---

## Troubleshooting

**Server won't start**
```bash
pip install flask anthropic
python server.py
```

**No images appearing**
- Check the server is running: http://localhost:8776/api/health
- Some sources (Google, Bing) occasionally block server-side requests. Try Amazon or Argos.
- Paste an image URL directly in the URL bar in the preview sidebar.

**Claude Vision not working**
- Set `ANTHROPIC_API_KEY` in your environment (see install.py output).
- Verify: `echo %ANTHROPIC_API_KEY%` (Windows) or `echo $ANTHROPIC_API_KEY` (Mac/Linux)

**Bridge script not loading**
- Confirm Picture Finder server is running on port 8776.
- Check browser console for CORS or mixed-content errors.
- The bridge script sets `Access-Control-Allow-Origin: *` on all endpoints.

---

## Roadmap

- [ ] Drag-and-drop image upload
- [ ] Local file browser as an image source
- [ ] Pinterest / Unsplash / Pexels source plugins
- [ ] Bulk hunt mode (auto-pick best image for all items)
- [ ] Hosted version (no local server needed)

---

## Credits

Built for the **Laurence Bring** personal productivity suite.
Claude Vision powered by [Anthropic](https://anthropic.com).
Search via Bing, Amazon, Argos, Google Images.

---

*Picture Finder is a local tool. No data leaves your machine except image URLs sent to Claude Vision for verification.*
