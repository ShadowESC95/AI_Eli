import os
from mitmproxy import http
import json
import requests

ELI_URL = f"http://127.0.0.1:{os.environ.get('ELI_PROXY_PORT', '18080')}/chat"

def request(flow: http.HTTPFlow):
    if flow.request.method != "POST":
        return

    if "chat" not in flow.request.pretty_url:
        return

    try:
        payload = json.loads(flow.request.get_text())

        r = requests.post(
            ELI_URL,
            json=payload,
            timeout=60
        )
        r.raise_for_status()

        reply = r.json().get("reply", "")

        flow.response = http.Response.make(
            200,
            json.dumps({
                "message": reply
            }),
            {"Content-Type": "application/json"}
        )

        print("ELI intercepted and responded")

    except Exception as e:
        flow.response = http.Response.make(
            500,
            f"ELI error: {e}"
        )
