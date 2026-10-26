#!/usr/bin/env python3
"""Prueba qué datos públicos de perfil y videos entrega TikTok (uso de diagnóstico)."""
import json
import re
import sys
import urllib.parse

from monitor import http_get, limpiar_usuario


def corto(x, n=600):
    return json.dumps(x, ensure_ascii=False)[:n]


def rehidratacion(html):
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


for u in [limpiar_usuario(x) for x in sys.argv[1:]]:
    print("=" * 20, u)
    # 1) api-live: bloque stats
    try:
        q = urllib.parse.urlencode({"aid": "1988", "sourceType": "54", "uniqueId": u})
        _, t = http_get("https://www.tiktok.com/api-live/user/room/?" + q)
        d = json.loads(t).get("data") or {}
        print("[api-live] stats:", corto(d.get("stats")))
        print("[api-live] user keys:", sorted((d.get("user") or {}).keys()))
        sec = (d.get("user") or {}).get("secUid")
    except Exception as e:
        print("[api-live] ERROR", e); sec = None

    # 2) perfil HTML
    try:
        st, html = http_get("https://www.tiktok.com/@" + u)
        print("[perfil] http", st, "len", len(html))
        r = rehidratacion(html)
        if r:
            sc = r.get("__DEFAULT_SCOPE__", {})
            print("[perfil] scopes:", list(sc.keys()))
            ud = sc.get("webapp.user-detail", {})
            ui = ud.get("userInfo", {})
            print("[perfil] stats:", corto(ui.get("stats")), corto(ui.get("statsV2")))
            print("[perfil] itemList?", "itemList" in ud, len(ud.get("itemList") or []))
            sec = sec or (ui.get("user") or {}).get("secUid")
        else:
            print("[perfil] sin datos de rehidratación; contiene 'videoCount'?", "videoCount" in html)
        ids = list(dict.fromkeys(re.findall(r'/video/(\d{15,})', html)))
        print("[perfil] ids de video en HTML:", ids[:5])
    except Exception as e:
        print("[perfil] ERROR", e); ids = []

    # 3) embed del creador
    try:
        st, emb = http_get("https://www.tiktok.com/embed/@" + u)
        eids = list(dict.fromkeys(re.findall(r'(\d{18,20})', emb)))
        print("[embed] http", st, "len", len(emb), "ids:", eids[:8])
        m = re.search(r'<script id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', emb, re.S)
        if m:
            fs = json.loads(m.group(1))
            src = fs.get("source", {}).get("data", {})
            k = next(iter(src), None)
            dat = src.get(k, {}) if k else {}
            print("[embed] keys:", list(dat.keys())[:20])
            vl = dat.get("videoList") or []
            print("[embed] videoList:", len(vl), corto(vl[:1], 900))
            ids = ids or [str(v.get("id")) for v in vl if v.get("id")]
        ids = ids or eids
    except Exception as e:
        print("[embed] ERROR", e)

    # 4) item_list sin firma
    if sec:
        try:
            q = urllib.parse.urlencode({"aid": "1988", "secUid": sec, "count": "30", "cursor": "0"})
            st, t = http_get("https://www.tiktok.com/api/post/item_list/?" + q)
            print("[item_list] http", st, "len", len(t), t[:200])
        except Exception as e:
            print("[item_list] ERROR", e)

    # 5) página de un video
    for vid in ids[:2]:
        try:
            st, vh = http_get("https://www.tiktok.com/@%s/video/%s" % (u, vid))
            r = rehidratacion(vh)
            it = (r or {}).get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
            print("[video]", vid, "http", st, "createTime", it.get("createTime"), "stats", corto(it.get("stats")), corto(it.get("statsV2")))
        except Exception as e:
            print("[video] ERROR", vid, e)
