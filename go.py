import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

servers = [
    ("Wishlist",        8773, ["python", "-m", "http.server", "8773"]),
    ("Picture Finder",  8776, ["python", "picture-finder/server.py"]),
    ("Spend Watch",     8780, ["pythonw", "spend-watch.pyw"]),
    ("Whisper",         8781, ["python", "whisper-server.py"]),
    ("Circuit",         8771, ["python", "-m", "http.server", "8771"]),
    ("Spend Chat",      8767, ["python", "-m", "http.server", "8767"]),
]

for name, port, cmd in servers:
    ans = input(f"Start {name} (:{port})? [y/N] ").strip().lower()
    if ans == "y":
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform=="win32" else 0)
        print(f"  → http://localhost:{port}")
