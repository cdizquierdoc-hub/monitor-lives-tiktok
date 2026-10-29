"""Diagnóstico: ¿las portadas de TikTok se pueden mostrar desde otra web (CORS / hotlink)?"""
import json, subprocess, urllib.request
subprocess.run(["git", "fetch", "-q", "origin", "data"], check=True)
d = json.loads(subprocess.run(["git", "show", "FETCH_HEAD:data/social.json"], capture_output=True, check=True).stdout)
urls = [p["portada"] for p in d["posts"].values() if p.get("portada")][:3]
for u in urls:
    for hdr in ({"Origin": "https://cdizquierdoc-hub.github.io", "Referer": "https://cdizquierdoc-hub.github.io/"}, {}):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", **hdr}), timeout=20)
            print(r.status, r.headers.get("content-type"), "ACAO=", r.headers.get("access-control-allow-origin"), "con origin" if hdr else "sin origin", len(r.read()))
        except Exception as e:
            print("ERROR", e, "con origin" if hdr else "sin origin")
