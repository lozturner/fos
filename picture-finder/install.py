#!/usr/bin/env python3
"""
Picture Finder — Self-Installer
================================
Run this once to set everything up. Like cPanel, but for your desktop.

Usage:
    python install.py

What it does:
    1. Checks Python version (3.8+ required)
    2. Installs pip dependencies (flask, anthropic)
    3. Checks for ANTHROPIC_API_KEY
    4. Creates a launch shortcut (start.bat on Windows)
    5. Prints the integration snippet for host apps
    6. Optionally starts the server right now
"""

import sys
import os
import subprocess
import shutil
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# ── Colours (ANSI, safe on Windows 10+) ───────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
AMBER  = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
PURPLE = "\033[95m"

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {AMBER}⚠{RESET}  {msg}")
def err(msg):   print(f"  {RED}✗{RESET}  {msg}")
def info(msg):  print(f"  {CYAN}→{RESET}  {msg}")
def head(msg):  print(f"\n{BOLD}{PURPLE}{msg}{RESET}")

def hr():
    print("─" * 58)

# ── Banner ─────────────────────────────────────────────────────────────────

def banner():
    print(f"""
{PURPLE}{BOLD}
  ██████╗ ██╗ ██████╗████████╗██╗   ██╗██████╗ ███████╗
  ██╔══██╗██║██╔════╝╚══██╔══╝██║   ██║██╔══██╗██╔════╝
  ██████╔╝██║██║        ██║   ██║   ██║██████╔╝█████╗
  ██╔═══╝ ██║██║        ██║   ██║   ██║██╔══██╗██╔══╝
  ██║     ██║╚██████╗   ██║   ╚██████╔╝██║  ██║███████╗
  ╚═╝     ╚═╝ ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝
  ███████╗██╗███╗   ██╗██████╗ ███████╗██████╗
  ██╔════╝██║████╗  ██║██╔══██╗██╔════╝██╔══██╗
  █████╗  ██║██╔██╗ ██║██║  ██║█████╗  ██████╔╝
  ██╔══╝  ██║██║╚██╗██║██║  ██║██╔══╝  ██╔══██╗
  ██║     ██║██║ ╚████║██████╔╝███████╗██║  ██║
  ╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═╝  ╚═╝
{RESET}
  {CYAN}Image hunting micro-tool — standalone + embeddable{RESET}
  {CYAN}v1.0.0  ·  Port 8776  ·  Claude Vision verified{RESET}
""")
    hr()

# ── Step 1: Python version ─────────────────────────────────────────────────

def check_python():
    head("Step 1 — Python version")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 8):
        err(f"Python 3.8+ required. You have {v.major}.{v.minor}")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")

# ── Step 2: pip dependencies ───────────────────────────────────────────────

DEPS = ["flask", "anthropic"]

def check_deps():
    head("Step 2 — Dependencies")
    missing = []
    for dep in DEPS:
        try:
            __import__(dep)
            ok(f"{dep} already installed")
        except ImportError:
            warn(f"{dep} not found — will install")
            missing.append(dep)
    if missing:
        info(f"Running: pip install {' '.join(missing)}")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *missing],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            err(f"pip install failed:\n{result.stderr}")
            sys.exit(1)
        ok(f"Installed: {', '.join(missing)}")

# ── Step 3: API key ────────────────────────────────────────────────────────

def check_api_key():
    head("Step 3 — Anthropic API key")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key and key.startswith("sk-"):
        ok("ANTHROPIC_API_KEY found in environment")
    else:
        warn("ANTHROPIC_API_KEY not set in environment")
        print()
        print("  Picture Finder uses Claude Vision to verify images match your search.")
        print("  Without a key, search still works but confidence scores won't appear.")
        print()
        print(f"  {AMBER}How to set it:{RESET}")
        print("  Windows:  setx ANTHROPIC_API_KEY sk-ant-...")
        print("  Then restart this terminal and re-run install.py")
        print()
        print("  Get a key at: https://console.anthropic.com")

# ── Step 4: Launch shortcut ────────────────────────────────────────────────

def create_shortcut():
    head("Step 4 — Launch shortcut")
    bat = HERE / "start.bat"
    content = f"""@echo off
title Picture Finder
echo.
echo   Starting Picture Finder on http://localhost:8776
echo.
cd /d "{HERE}"
python server.py
pause
"""
    bat.write_text(content)
    ok(f"Created: {bat}")

    # Also create a start-silent.bat (pythonw)
    silent = HERE / "start-silent.bat"
    content_s = f"""@echo off
cd /d "{HERE}"
start "" pythonw server.py
"""
    silent.write_text(content_s)
    ok(f"Created: {silent}  (runs without console window)")

# ── Step 5: Print integration snippet ─────────────────────────────────────

SNIPPET = """
<!-- ─────────── Picture Finder Integration ─────────── -->
<!-- Drop this into any web app to get the image picker -->

<script src="http://localhost:8776/pf-bridge.js"></script>
<script>
  // Open for a list of items:
  // items = [{ id, name, currentImg? }]
  // onImages = (map) => { 'item-id': 'https://...' }

  document.getElementById('my-btn').addEventListener('click', () => {
    PictureFinder.open(
      [{ id: 'item-1', name: 'Ergonomic Chair' }],
      (imageMap) => {
        console.log('Got images:', imageMap);
        // imageMap['item-1'] = 'https://...'
      }
    );
  });

  // Or wire to any existing button:
  // PictureFinder.attachButton('#btn', getItems, onImages);

  // Or add a floating FAB:
  // PictureFinder.fab(getItems, onImages);
</script>
"""

def print_snippet():
    head("Step 5 — Integration snippet")
    print(SNIPPET)
    print()
    info("Full docs: see README.md in this folder")

# ── Step 6: Verify files present ──────────────────────────────────────────

def verify_files():
    head("Step 6 — File check")
    required = ["server.py", "index.html", "pf-bridge.js"]
    all_ok = True
    for f in required:
        p = HERE / f
        if p.exists():
            ok(f"{f}  ({p.stat().st_size:,} bytes)")
        else:
            err(f"MISSING: {f}")
            all_ok = False
    if not all_ok:
        err("Some files are missing. Re-clone the repo.")
        sys.exit(1)

# ── Step 7: Offer to start now ─────────────────────────────────────────────

def offer_start():
    head("All done! 🎉")
    hr()
    print(f"\n  {GREEN}Picture Finder is ready.{RESET}")
    print(f"\n  Start the server:   {BOLD}python server.py{RESET}")
    print(f"  Or double-click:    {BOLD}start.bat{RESET}")
    print(f"\n  Open in browser:    {CYAN}http://localhost:8776{RESET}")
    print(f"  Embed in any app:   {CYAN}http://localhost:8776/pf-bridge.js{RESET}")
    print()
    hr()

    try:
        answer = input("\n  Start the server now? [y/N]  ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer == "y":
        print()
        info("Starting server.py — Ctrl+C to stop")
        print()
        os.chdir(HERE)
        os.execv(sys.executable, [sys.executable, str(HERE / "server.py")])
    else:
        print()
        info("Run  python server.py  whenever you're ready.")
        print()

# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    banner()
    check_python()
    check_deps()
    check_api_key()
    create_shortcut()
    print_snippet()
    verify_files()
    offer_start()
