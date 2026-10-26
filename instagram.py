#!/usr/bin/env python3
"""
Métricas de contenido de Instagram vía la API oficial de Meta (ver meta.py).
Se suma a DATA_DIR/social.json junto a TikTok. Sin IG_TOKEN solo marca las cuentas como pendientes.
"""
import json
import os
import time
from datetime import datetime, timezone

import meta
from monitor import leer_vendedores, log

DATA_DIR = os.environ.get("DATA_DIR", "data")
ARCHIVO = os.path.join(DATA_DIR, "social.json")


def ms(ts):
    # "2026-10-26T14:03:11+0000"
    return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").timestamp() * 1000)


def main():
    datos = {"cuentas": {}, "posts": {}}
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding="utf-8") as f:
            datos = json.load(f)
    cuentas = [v for v in leer_vendedores() if v["activo"] and v["plataforma"] == "instagram"]
    if not cuentas:
        log("Instagram: no hay cuentas cargadas")
        return
    t = int(time.time() * 1000)
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    propias, base, error_general = {}, None, ""
    if not meta.disponible():
        error_general = "Instagram: falta conectar la API de Meta (IG_TOKEN)"
    else:
        try:
            propias = meta.cuentas_propias()
            base = next(iter(propias.values()), None)
            if not base:
                error_general = "Instagram: el token no administra ninguna cuenta de empresa de Instagram"
        except Exception as e:
            error_general = "Instagram: %s" % str(e)[:150]

    ok = 0
    for v in cuentas:
        c = datos["cuentas"].setdefault(v["usuario"], {"historial": []})
        c["revisado"], c["plataforma"] = t, "instagram"
        if error_general:
            c["error"] = error_general
            continue
        try:
            propia = v["handle"] in propias
            if propia:
                perfil, media = meta.perfil_propio(propias[v["handle"]])
            else:
                perfil, media = meta.perfil_ajeno(base, v["handle"])
            ok += 1
            c.update(error="", seguidores=perfil.get("followers_count"), siguiendo=perfil.get("follows_count"),
                     videos=perfil.get("media_count"), nick=perfil.get("name") or "", propia=propia,
                     alcance="completo" if propia else "público (sin views, guardados ni compartidos)")
            h = [p for p in c["historial"] if p["d"] != hoy]
            h.append({"d": hoy, "seguidores": c["seguidores"], "likes": None, "videos": c["videos"]})
            c["historial"] = h[-400:]
            for m in media:
                if not m.get("timestamp"):
                    continue
                datos["posts"].setdefault(m["id"], {}).update({
                    "usuario": v["usuario"], "plataforma": "instagram", "creado": ms(m["timestamp"]),
                    "desc": (m.get("caption") or "")[:300], "permalink": m.get("permalink"),
                    "formato": (m.get("media_product_type") or m.get("media_type") or "").lower(),
                    "vistas": m.get("views"), "likes": m.get("like_count"), "comentarios": m.get("comments_count"),
                    "compartidos": m.get("shares"), "guardados": m.get("saved"), "alcance": m.get("reach"),
                    "actualizado": t})
        except Exception as e:
            c["error"] = "Instagram: %s" % str(e)[:150]
        time.sleep(0.3)

    datos["generado"] = t
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = ARCHIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ARCHIVO)
    log("Instagram: cuentas %d · ok %d%s" % (len(cuentas), ok, (" · " + error_general) if error_general else ""))


if __name__ == "__main__":
    main()
