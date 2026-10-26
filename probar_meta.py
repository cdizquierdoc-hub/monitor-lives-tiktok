#!/usr/bin/env python3
"""Diagnóstico de la conexión con la API de Meta (Instagram)."""
import sys
import meta

if not meta.disponible():
    print("Falta el secreto IG_TOKEN en GitHub (Settings → Secrets and variables → Actions).")
    sys.exit(0)
try:
    propias = meta.cuentas_propias()
    print("Cuentas de Instagram propias conectadas:", propias or "ninguna")
except Exception as e:
    print("ERROR al leer cuentas propias:", e); sys.exit(0)
base = next(iter(propias.values()), None)
for u in sys.argv[1:]:
    u = u.lstrip("@").lower()
    try:
        if u in propias:
            p, media = meta.perfil_propio(propias[u], 3)
            print(u, "PROPIA · seguidores", p.get("followers_count"), "· posts", p.get("media_count"), "· vivo:", meta.en_vivo(propias[u]))
        else:
            p, media = meta.perfil_ajeno(base, u, 3)
            print(u, "AJENA · seguidores", p.get("followers_count"), "· posts", p.get("media_count"))
        for m in media[:3]:
            print("   ", m.get("timestamp"), "likes", m.get("like_count"), "coment", m.get("comments_count"), "views", m.get("views"), "guard", m.get("saved"))
    except Exception as e:
        print(u, "ERROR:", e)
