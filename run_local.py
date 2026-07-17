import os

import server


if __name__ == "__main__":
    os.makedirs(server.DATA_DIR, exist_ok=True)
    os.makedirs(server.EXPORTS_DIR, exist_ok=True)
    os.makedirs(server.EMAILS_DIR, exist_ok=True)
    os.makedirs(server.ENRICHMENT_DIR, exist_ok=True)
    print("OutreachIQ at http://localhost:5001", flush=True)
    server.app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
