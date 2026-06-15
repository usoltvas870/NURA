import urllib.request, json, base64, re

env = open("C:/Users/Bayzel/AppData/Local/hermes/.env").read()
m = re.search(r"GOOGLE_API_KEY=(.*)", env)
key = m.group(1).strip() if m else ""

img_b64 = base64.b64encode(open(
    "C:/Users/Bayzel/AppData/Roaming/Hermes/composer-images/composer_2026-06-15_06-42-05-264_bc48ac.png",
    "rb"
).read()).decode()

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
payload = {
    "contents": [{
        "parts": [
            {"text": "Describe this screenshot briefly in Russian. What interface is this?"},
            {"inline_data": {"mime_type": "image/png", "data": img_b64}}
        ]
    }]
}

req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
        txt = data["candidates"][0]["content"]["parts"][0]["text"]
        print(txt)
except urllib.error.HTTPError as e:
    print(f"ERROR {e.code}:")
    print(e.read().decode()[:1000])
