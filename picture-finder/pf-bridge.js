/**
 * Picture Finder — Host App Bridge v1.0.0
 *
 * Drop this script into any web app to get a floating "🖼 Find Pictures"
 * button that opens Picture Finder in a sandboxed modal, then fires
 * a callback with the chosen image URLs when the user is done.
 *
 * Usage:
 *   <script src="http://localhost:8776/pf-bridge.js"></script>
 *
 * Then in your app JS:
 *   PictureFinder.open(items, onImages);
 *
 *   // items: [{ id, name, currentImg? }]
 *   // onImages: (imageMap) => { 'item-id': 'https://...', ... }
 *
 * Or use the auto-trigger button:
 *   PictureFinder.attachButton('#my-btn', getItems, onImages);
 */

(function (global) {
  'use strict';

  const PF_URL    = 'http://localhost:8776';
  const PF_ORIGIN = 'http://localhost:8776';
  const Z         = 99999;

  let _modal = null;
  let _iframe = null;
  let _overlay = null;
  let _callback = null;
  let _pendingItems = null;

  /* ── Inject modal styles once ── */
  function injectStyles() {
    if (document.getElementById('pf-bridge-styles')) return;
    const s = document.createElement('style');
    s.id = 'pf-bridge-styles';
    s.textContent = `
      #pf-overlay {
        display:none; position:fixed; inset:0; z-index:${Z};
        background:rgba(0,0,0,0.72); backdrop-filter:blur(4px);
        align-items:center; justify-content:center;
      }
      #pf-overlay.open { display:flex; }
      #pf-modal {
        width:min(960px,96vw); height:min(720px,92vh);
        border:none; border-radius:14px;
        box-shadow:0 24px 80px rgba(0,0,0,0.7);
        overflow:hidden;
      }
      #pf-fab {
        position:fixed; bottom:24px; left:24px; z-index:${Z - 1};
        width:52px; height:52px; border-radius:50%;
        background:#7c6fdd; border:none; color:#fff;
        font-size:1.3rem; cursor:pointer;
        box-shadow:0 4px 16px rgba(124,111,221,0.5);
        transition:transform 0.15s, box-shadow 0.15s;
        display:flex; align-items:center; justify-content:center;
      }
      #pf-fab:hover {
        transform:scale(1.08);
        box-shadow:0 6px 24px rgba(124,111,221,0.7);
      }
      #pf-fab title { display:none; }
    `;
    document.head.appendChild(s);
  }

  /* ── Build modal DOM ── */
  function buildModal() {
    if (_modal) return;
    injectStyles();

    _overlay = document.createElement('div');
    _overlay.id = 'pf-overlay';
    _overlay.addEventListener('click', (e) => {
      if (e.target === _overlay) close();
    });

    _iframe = document.createElement('iframe');
    _iframe.id  = 'pf-modal';
    _iframe.src = PF_URL;
    _iframe.allow = 'clipboard-write';

    _overlay.appendChild(_iframe);
    document.body.appendChild(_overlay);
    _modal = _overlay;

    /* Listen for messages back from Picture Finder */
    window.addEventListener('message', (e) => {
      if (e.origin !== PF_ORIGIN) return;
      const { type, data } = e.data || {};
      if (type === 'pf:ready' && _pendingItems) {
        /* iframe loaded — send items */
        _iframe.contentWindow.postMessage({
          type: 'pf:load-items',
          items: _pendingItems,
        }, PF_ORIGIN);
        _pendingItems = null;
      }
      if (type === 'pf:images-saved') {
        /* User clicked "Apply to project" */
        if (_callback) _callback(data);
        close();
      }
      if (type === 'pf:close') {
        close();
      }
    });
  }

  /* ── Open with items ── */
  function open(items, callback) {
    buildModal();
    _callback = callback || null;
    _pendingItems = items;

    /* If iframe already loaded, send immediately */
    try {
      if (_iframe.contentDocument && _iframe.contentDocument.readyState === 'complete') {
        _iframe.contentWindow.postMessage({ type: 'pf:load-items', items }, PF_ORIGIN);
        _pendingItems = null;
      }
    } catch (_) { /* cross-origin not yet loaded, will send on pf:ready */ }

    /* Reset src to force fresh load each open */
    _iframe.src = PF_URL + '?t=' + Date.now();
    _modal.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  /* ── Close ── */
  function close() {
    if (_modal) _modal.classList.remove('open');
    document.body.style.overflow = '';
    _callback = null;
  }

  /* ── Attach to a button ── */
  function attachButton(selector, getItems, onImages) {
    const el = typeof selector === 'string'
      ? document.querySelector(selector)
      : selector;
    if (!el) return console.warn('[PictureFinder] button not found:', selector);
    el.addEventListener('click', () => open(getItems(), onImages));
  }

  /* ── Auto FAB (optional, call PictureFinder.fab(getItems, onImages)) ── */
  function fab(getItems, onImages) {
    injectStyles();
    const btn = document.createElement('button');
    btn.id = 'pf-fab';
    btn.title = 'Picture Finder';
    btn.textContent = '🖼';
    btn.addEventListener('click', () => open(getItems(), onImages));
    document.body.appendChild(btn);
  }

  /* ── Export ── */
  global.PictureFinder = { open, close, attachButton, fab };

})(window);
