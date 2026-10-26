#!/usr/bin/env python3
"""Diagnóstico: qué datos públicos entrega Instagram sin sesión."""
import json, sys, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
def get(url, extra=None):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-ES,es;q=0.9", "X-IG-App-ID": "936619743392459",
         "Referer": "https://www.instagram.com/", "X-Requested-With": "XMLHttpRequest"}
    h.update(extra or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return 0, str(e)
for u in sys.argv[1:]:
    print("=" * 10, u)
    for base in ("https://i.instagram.com", "https://www.instagram.com"):
        st, t = get(base + "/api/v1/users/web_profile_info/?username=" + u)
        print(base, st, len(t))
        if st == 200:
            try:
                usr = json.loads(t)["data"]["user"]
                print("  seguidores", usr["edge_followed_by"]["count"], "posts", usr["edge_owner_to_timeline_media"]["count"],
                      "is_live?", {k: usr.get(k) for k in usr if "live" in k.lower() or "broadcast" in k.lower()})
                ed = usr["edge_owner_to_timeline_media"]["edges"]
                print("  posts recientes", len(ed))
                for e in ed[:3]:
                    n = e["node"]
                    print("   ", n.get("shortcode"), n.get("taken_at_timestamp"), "likes", n.get("edge_liked_by", n.get("edge_media_preview_like", {})).get("count"),
                          "coms", n.get("edge_media_to_comment", {}).get("count"), "views", n.get("video_view_count"), "plays", n.get("video_play_count"), "video", n.get("is_video"))
                print("  user keys:", sorted(k for k in usr.keys())[:80])
            except Exception as e:
                print("  parse", e, t[:200])
        else:
            print("  ", t[:200].replace("\n", " "))
    st, t = get("https://www.instagram.com/" + u + "/", {"Accept": "text/html"})
    print("html", st, len(t), "og:description" in t, t[t.find('og:description'):t.find('og:description')+200] if 'og:description' in t else '')
