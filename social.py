#!/usr/bin/env python3
"""
Métricas de contenido de TikTok por cuenta (seguidores, publicaciones y su desempeño).

- Perfil (https://www.tiktok.com/@usuario): seguidores, siguiendo, likes totales, videos.
- Publicaciones recientes (embed del creador): ~13 últimas, luego la página de cada
  video para views, likes, comentarios, compartidos, guardados y fecha de publicación.
- Guarda todo en DATA_DIR/social.json; el historial se va acumulando en cada corrida.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from monitor import http_get, leer_vendedores, log

DATA_DIR = os.environ.get("DATA_DIR", "data")
ARCHIVO = os.path.join(DATA_DIR, "social.json")
DIAS_ACTUALIZAR = 45        # se refrescan métricas de posts publicados en los últimos N días
HILOS = 4
DIAS_PORTADA = 120          # se mantiene vigente la portada de los posts de los últimos N días
MAX_VIEJOS = 25             # posts anteriores que se releen por cuenta en cada corrida (para no tardar demasiado)


def ahora_ms():
    return int(time.time() * 1000)


def rehidratacion(html):
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    return (json.loads(m.group(1)) if m else {}).get("__DEFAULT_SCOPE__", {})


def n(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def perfil(usuario):
    _, html = http_get("https://www.tiktok.com/@" + usuario, timeout=25)
    ui = rehidratacion(html).get("webapp.user-detail", {}).get("userInfo", {})
    st = ui.get("statsV2") or ui.get("stats") or {}
    if not st:
        raise LookupError("perfil sin datos")
    return {
        "seguidores": n(st.get("followerCount")),
        "siguiendo": n(st.get("followingCount")),
        "likesTotales": n(st.get("heartCount") or st.get("heart")),
        "videos": n(st.get("videoCount")),
        "nick": (ui.get("user") or {}).get("nickname") or "",
    }


def ids_recientes(usuario):
    _, emb = http_get("https://www.tiktok.com/embed/@" + usuario, timeout=25)
    m = re.search(r'<script id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', emb, re.S)
    if not m:
        return []
    src = json.loads(m.group(1)).get("source", {}).get("data", {})
    salida = []
    for dat in src.values():
        for v in dat.get("videoList") or []:
            if v.get("id"):
                salida.append((str(v["id"]), v.get("desc") or ""))
    return salida


def video(usuario, vid):
    _, html = http_get("https://www.tiktok.com/@%s/video/%s" % (usuario, vid), timeout=25)
    it = rehidratacion(html).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
    st = it.get("statsV2") or it.get("stats") or {}
    if not it.get("createTime"):
        raise LookupError("video sin datos")
    return {
        "creado": int(it["createTime"]) * 1000,
        "desc": (it.get("desc") or "")[:300],
        "vistas": n(st.get("playCount")),
        "likes": n(st.get("diggCount")),
        "comentarios": n(st.get("commentCount")),
        "compartidos": n(st.get("shareCount")),
        "guardados": n(st.get("collectCount")),
        "duracion": n((it.get("video") or {}).get("duration")),
        # portada real del video (URL firmada de TikTok; se renueva en cada actualización del post)
        "portada": (it.get("video") or {}).get("cover") or (it.get("video") or {}).get("originCover") or "",
    }


def procesar(v, posts_previos, t):
    u = v["handle"]
    res = {"usuario": v["usuario"], "error": "", "perfil": None, "posts": {}}
    try:
        res["perfil"] = perfil(u)
    except Exception as e:
        res["error"] = "perfil: %s" % str(e)[:100]
    try:
        recientes = ids_recientes(u)
    except Exception as e:
        recientes = []
        res["error"] += " embed: %s" % str(e)[:100]
    lim = t - DIAS_ACTUALIZAR * 86400000
    for vid, desc in recientes:
        prev = posts_previos.get(vid)
        if prev and prev.get("creado", 0) < lim:
            continue                       # post viejo: sus métricas ya casi no cambian
        try:
            d = video(u, vid)
            d.update(usuario=v["usuario"], plataforma="tiktok", actualizado=t)
            res["posts"][vid] = d
        except Exception as e:
            if not prev:
                res["error"] += " video %s: %s" % (vid, str(e)[:60])
        time.sleep(0.4)
    # Posts anteriores a los ~13 más recientes: se vuelven a leer cuando les falta la portada o ya va a vencer
    # (TikTok firma la URL de la portada por ~2 días). Así el top 5 siempre tiene portada y sus métricas siguen al día.
    vistos = {vid for vid, _ in recientes}
    viejos = sorted(((vid, p) for vid, p in posts_previos.items() if p.get("usuario") == v["usuario"] and vid not in vistos
                     and p.get("creado", 0) >= t - DIAS_PORTADA * 86400000 and portada_vence(p.get("portada"), t)),
                    key=lambda x: -(x[1].get("vistas") or 0))[:MAX_VIEJOS]
    for vid, prev in viejos:
        try:
            d = video(u, vid)
            d.update(usuario=v["usuario"], plataforma="tiktok", actualizado=t)
            res["posts"][vid] = d
        except Exception:
            pass
        time.sleep(0.4)
    return res


def portada_vence(url, t):
    """True si no hay portada o su firma vence en menos de 12 horas."""
    m = re.search(r"x-expires=(\d+)", url or "")
    return not m or int(m.group(1)) * 1000 < t + 12 * 3600 * 1000


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    datos = {"cuentas": {}, "posts": {}}
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding="utf-8") as f:
            datos = json.load(f)
    t = ahora_ms()
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vendedores = [v for v in leer_vendedores() if v["activo"] and v["plataforma"] == "tiktok"]

    with ThreadPoolExecutor(HILOS) as ex:
        resultados = list(ex.map(lambda v: procesar(v, datos["posts"], t), vendedores))

    ok = 0
    for r in resultados:
        c = datos["cuentas"].setdefault(r["usuario"], {"historial": []})
        c["error"] = r["error"].strip()
        c["revisado"] = t
        if r["perfil"]:
            ok += 1
            c.update(r["perfil"])
            # un punto por día (el último del día gana) para la curva de seguidores
            h = [p for p in c["historial"] if p["d"] != hoy]
            h.append({"d": hoy, "seguidores": r["perfil"]["seguidores"], "likes": r["perfil"]["likesTotales"],
                      "videos": r["perfil"]["videos"]})
            c["historial"] = h[-400:]
        for vid, p in r["posts"].items():
            datos["posts"].setdefault(vid, {}).update(p)
    datos["generado"] = t

    tmp = ARCHIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ARCHIVO)
    nuevos = sum(len(r["posts"]) for r in resultados)
    log("Cuentas %d · perfiles ok %d · posts actualizados %d · posts guardados %d" %
        (len(vendedores), ok, nuevos, len(datos["posts"])))
    for r in resultados:
        if r["error"]:
            log("⚠", r["usuario"], r["error"][:200])


if __name__ == "__main__":
    main()
