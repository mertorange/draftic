"""Draftić launcher: starts the server and opens the game in the browser."""

import os
import sys
import threading
import time
import webbrowser

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("DRAFTIC_PORT", "8010"))


def main():
    import uvicorn

    def open_browser():
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"Draftić running at http://localhost:{PORT}  (Ctrl+C to stop)")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=PORT, reload=True)


if __name__ == "__main__":
    main()
