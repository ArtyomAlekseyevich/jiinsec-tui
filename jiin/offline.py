# Practice mode (./jiinsec --offline): runs the mock server in-process with a throwaway config dir.
# Nothing hits the real site; the mock dies with the app.
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import mock_server

    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_server.H)      # port 0 = pick a free one
    srv.daemon_threads = True
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix="jiinsec-offline-") as cfg:
        Path(cfg, "session.json").write_text(json.dumps(
            {"base": base, "cookies": [{"name": "sid", "value": "offline", "domain": "127.0.0.1", "path": "/"}]}))
        os.environ["JIIN_BASE"] = base            # set before importing the app
        os.environ["JIIN_CONFIG_DIR"] = cfg
        from jiin.app import main as run_app
        run_app()


if __name__ == "__main__":
    main()
