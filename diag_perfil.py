"""Diagnóstico: qué devuelve TikTok en la página de perfil (para cuentas restringidas)."""
import json, re, sys, urllib.parse
from monitor import http_get
for u in sys.argv[1:]:
    print("==", u)
    try:
        code, html = http_get("https://www.tiktok.com/@" + urllib.parse.quote(u), timeout=25)
    except Exception as e:
        print("ERROR", e); continue
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        print("sin datos", len(html)); continue
    det = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {})
    ui = det.get("userInfo") or {}
    print("statusCode", det.get("statusCode"), det.get("statusMsg"), "keys", list(det.keys()))
    usr = ui.get("user") or {}
    print("user", {k: usr.get(k) for k in ("id", "uniqueId", "nickname", "privateAccount", "secret", "isUnderAge18", "ftc", "commerceUserInfo") if k in usr})
    print("stats", ui.get("statsV2") or ui.get("stats"))
    for k in ("needFix", "shareMeta"):
        if k in det: print(k, str(det[k])[:200])
    print()
