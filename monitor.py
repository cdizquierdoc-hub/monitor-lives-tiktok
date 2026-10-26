#!/usr/bin/env python3
"""
Monitor de lives de TikTok de vendedores.

- Lee los vendedores de vendedores/*.csv (usuario,agencia,nombre,activo)
- Revisa cada INTERVALO segundos si cada uno está en LIVE
- Registra inicio, fin y duración de cada live en data/data.json
- Lo corre GitHub Actions; el dashboard (index.html) lee data/data.json

Variables de entorno:
  DATA_DIR        carpeta donde se guarda data.json (default: data)
  VENDEDORES_DIR  carpeta con los CSV de vendedores (default: vendedores)
  INTERVALO       segundos entre revisiones (default: 120)
  DURACION_MIN    minutos que corre el bucle antes de salir (default: 0 = una sola revisión)
  AL_GUARDAR      comando a ejecutar después de guardar (ej. commit + push)
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", "data")
VENDEDORES_DIR = os.environ.get("VENDEDORES_DIR", "vendedores")
INTERVALO = int(os.environ.get("INTERVALO", "120"))
DURACION_MIN = float(os.environ.get("DURACION_MIN", "0"))
AL_GUARDAR = os.environ.get("AL_GUARDAR", "")
REVISIONES_PARA_CERRAR = 3      # revisiones seguidas sin live para dar por terminado (evita cortes por señal)
DIAS_EN_DASHBOARD = 120         # historial que se publica en data.json
LATIDO_SEG = 600                # guarda aunque no haya cambios, para mostrar "última revisión"
HILOS = 8

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.tiktok.com/",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def ahora_ms():
    return int(time.time() * 1000)


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ vendedores

def limpiar_usuario(txt):
    u = str(txt or "").strip()
    m = re.search(r"tiktok\.com/@([^/?#\s]+)", u, re.I)
    if m:
        u = m.group(1)
    return re.sub(r"\s+", "", u.lstrip("@")).lower()


# Cadenas de Cresa: se reconocen por la 1.ª palabra de la agencia (ej. "JAPON PARQUE CALIFORNIA")
CADENAS = {"CRECOS": "Crecos", "ORVE": "Orve Hogar", "JAPON": "Japón", "JAPÓN": "Japón",
           "MOTOZONE": "Motozone", "PAGAMENOS": "Pagamenos", "PAGA": "Pagamenos"}
COLUMNAS = {
    "usuario": ("usuario", "usuario tiktok", "user", "username", "tiktok"),
    "agencia": ("agencia", "zona", "zona / agencia", "tienda", "almacen", "almacén"),
    "nombre": ("nombre", "vendedor", "name"),
    "activo": ("activo", "activo (si/no)", "estado"),
    "tipo": ("tipo", "cuenta", "tipo de cuenta"),
}
ORDEN_POR_DEFECTO = ["usuario", "agencia", "nombre", "activo", "tipo"]


def tipo_de(txt):
    t = str(txt or "").strip().upper()
    return "competencia" if t == "C" or t.startswith("COMP") else "propio"


# Competidores conocidos: si la agencia empieza así, la cuenta es de competencia y se agrupa en esa empresa.
# Se pueden agregar más; cualquier otra empresa también funciona marcándola como competencia.
COMPETIDORES = [
    ("ALMACENES ESPAÑA", "Almacenes España"), ("ALMACENES ESPANA", "Almacenes España"), ("ESPAÑA", "Almacenes España"),
    ("ALMACENES AL PRECIO", "Almacenes Al Precio"), ("AL PRECIO", "Almacenes Al Precio"),
    ("ARTEFACTA", "Artefacta"), ("MARCIMEX", "Marcimex"), ("COMANDATO", "Comandato"), ("JAHER", "Jaher"),
    ("LA GANGA", "La Ganga"), ("ALMACENES TIA", "Almacenes Tía"), ("TVENTAS", "Tventas"),
]


def competidor_de(agencia):
    a = agencia.upper()
    for prefijo, nombre in COMPETIDORES:
        if a == prefijo or a.startswith(prefijo + " "):
            return nombre
    return None


def clasificar(agencia, tipo_txt):
    """Devuelve (cadena, tipo). Cadenas Cresa por 1.ª palabra; competidores conocidos por prefijo."""
    comp = competidor_de(agencia)
    if comp:
        return comp, "competencia"
    tipo = tipo_de(tipo_txt)
    return cadena_de(agencia, tipo), tipo


def cadena_de(agencia, tipo="propio"):
    """Nuestras: Japón / Crecos / Orve según la 1.ª palabra. Competencia: la empresa completa."""
    if tipo == "competencia":
        return agencia.title() if agencia != "SIN AGENCIA" else "Competencia"
    primera = (agencia.split() or [""])[0].upper()
    return CADENAS.get(primera, "Otra")


def leer_vendedores():
    vistos, salida = {}, []
    for ruta in sorted(glob.glob(os.path.join(VENDEDORES_DIR, "*.csv"))):
        archivo = os.path.basename(ruta)
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            texto = f.read()
        if not texto.strip():
            continue
        sep = ";" if texto.count(";") > texto.count(",") else ("\t" if "\t" in texto else ",")
        orden = ORDEN_POR_DEFECTO
        for i, fila in enumerate(csv.reader(texto.splitlines(), delimiter=sep)):
            if not fila or not fila[0].strip() or fila[0].strip().startswith("#"):
                continue
            cab = [c.strip().lower() for c in fila]
            if i == 0 and cab[0] in COLUMNAS["usuario"]:
                orden = [next((k for k, alias in COLUMNAS.items() if c in alias), "") for c in cab]
                continue
            datos = {k: (fila[j].strip() if j < len(fila) else "") for j, k in enumerate(orden) if k}
            usuario = limpiar_usuario(datos.get("usuario"))
            if not usuario:
                continue
            agencia = re.sub(r"\s+", " ", datos.get("agencia", "")).strip().upper() or "SIN AGENCIA"
            cadena, tipo = clasificar(agencia, datos.get("tipo"))
            v = {
                "usuario": usuario,
                "nombre": datos.get("nombre") or "@" + usuario,
                "agencia": agencia,
                "cadena": cadena,
                "tipo": tipo,
                "activo": datos.get("activo", "").upper() not in ("NO", "N", "0", "FALSE", "INACTIVO"),
                "archivo": archivo,
            }
            # si el mismo usuario aparece varias veces, gana la última aparición
            if usuario in vistos:
                salida[vistos[usuario]] = v
            else:
                vistos[usuario] = len(salida)
                salida.append(v)
    return salida


# ------------------------------------------------------------------ TikTok

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def consultar_api(usuario):
    q = urllib.parse.urlencode({
        "aid": "1988", "app_name": "tiktok_web", "device_platform": "web_pc",
        "app_language": "es", "browser_language": "es-ES", "sourceType": "54",
        "uniqueId": usuario,
    })
    _, txt = http_get("https://www.tiktok.com/api-live/user/room/?" + q)
    j = json.loads(txt)
    d = j.get("data") or {}
    user = d.get("user") or {}
    room = d.get("liveRoom") or {}
    if not user:
        raise LookupError("TikTok: %s (¿usuario correcto?)" % (j.get("message") or j.get("statusCode")))
    st = room.get("status", user.get("status"))
    en_vivo = str(st) == "2"
    inicio = None
    if en_vivo and room.get("startTime"):
        t = int(room["startTime"]) * 1000
        if 0 <= ahora_ms() - t < 24 * 3600 * 1000:
            inicio = t
    stats = room.get("liveRoomStats") or {}
    return {"enVivo": en_vivo, "roomId": str(user.get("roomId") or ""),
            "inicio": inicio, "titulo": room.get("title") or "",
            "espectadores": int(stats.get("userCount") or 0) if en_vivo else None,
            "vistas": int(stats.get("enterCount") or 0) if en_vivo else None}


def consultar_html(usuario):
    """Plan B: lee la página del live y confirma con check_alive."""
    _, html = http_get("https://www.tiktok.com/@%s/live" % urllib.parse.quote(usuario))
    m = re.search(r'"roomId":"(\d{6,})"', html) or re.search(r"room_id=(\d{6,})", html)
    if not m:
        if re.search(r'"statusCode":\s*10221|user doesn|couldn.t find this account', html, re.I):
            raise LookupError("TikTok: la cuenta no existe")
        return {"enVivo": False, "roomId": "", "inicio": None, "titulo": "", "espectadores": None, "vistas": None}
    room_id = m.group(1)
    _, txt = http_get("https://webcast.tiktok.com/webcast/room/check_alive/?aid=1988&region=CH"
                      "&user_is_login=false&room_ids=" + room_id)
    data = (json.loads(txt).get("data") or [{}])[0]
    titulo = ""
    mt = re.search(r'"title":"([^"]{0,200})"', html)
    if mt:
        titulo = mt.group(1)
    return {"enVivo": bool(data.get("alive")), "roomId": room_id, "inicio": None, "titulo": titulo,
            "espectadores": None, "vistas": None}


def consultar(usuario):
    errores = []
    for fn in (consultar_api, consultar_html):
        try:
            r = fn(usuario)
            r["metodo"] = fn.__name__
            return r
        except LookupError as e:
            return {"error": str(e)}
        except Exception as e:  # red, bloqueo, JSON inválido
            errores.append("%s: %s" % (fn.__name__, str(e)[:120]))
    return {"error": " | ".join(errores)}


# ------------------------------------------------------------------ datos

def cargar_datos():
    ruta = os.path.join(DATA_DIR, "data.json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {}
    d.setdefault("lives", [])
    d.setdefault("estado", {})
    if isinstance(d["estado"], list):
        d["estado"] = {e["usuario"]: e for e in d["estado"]}
    return d


def guardar_datos(d, vendedores):
    os.makedirs(DATA_DIR, exist_ok=True)
    lim = ahora_ms() - DIAS_EN_DASHBOARD * 86400000
    archivo_hist = os.path.join(DATA_DIR, "historial.csv")
    viejos = [l for l in d["lives"] if l["estado"] != "EN VIVO" and l["inicio"] < lim]
    if viejos:
        nuevo = not os.path.exists(archivo_hist)
        with open(archivo_hist, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["id", "usuario", "nombre", "agencia", "inicio_utc", "fin_utc", "min", "vistas", "pico", "promedio", "titulo"])
            for l in viejos:
                iso = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else ""
                w.writerow([l["id"], l["usuario"], l["nombre"], l.get("agencia", ""), iso(l["inicio"]), iso(l.get("fin")), l.get("min"), l.get("vistas"), l.get("pico"), l.get("promedio"), l.get("titulo", "")])
        d["lives"] = [l for l in d["lives"] if l not in viejos]

    salida = {
        "generado": ahora_ms(),
        "intervalo": max(1, round(INTERVALO / 60)),
        "vendedores": vendedores,
        "lives": d["lives"],
        "estado": sorted(d["estado"].values(), key=lambda e: e["usuario"]),
    }
    tmp = os.path.join(DATA_DIR, "data.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(DATA_DIR, "data.json"))


def registrar_audiencia(live, r):
    """Vistas = entradas acumuladas al live; pico y promedio de espectadores simultáneos."""
    esp, vis = r.get("espectadores"), r.get("vistas")
    if vis is not None:
        live["vistas"] = max(live.get("vistas") or 0, vis)
    if esp is not None:
        live["actual"] = esp
        live["pico"] = max(live.get("pico") or 0, esp)
        live["sumaEsp"] = (live.get("sumaEsp") or 0) + esp
        live["muestras"] = (live.get("muestras") or 0) + 1
        live["promedio"] = round(live["sumaEsp"] / live["muestras"])


def cerrar_live(live, fin):
    live["fin"] = fin
    live["min"] = max(1, round((fin - live["inicio"]) / 60000))
    live["estado"] = "FINALIZADO"
    live["actual"] = None


def revisar(d):
    """Una ronda de revisión. Devuelve (vendedores, hubo_cambios)."""
    vendedores = leer_vendedores()
    activos = [v for v in vendedores if v["activo"]]
    por_id = {l["id"]: l for l in d["lives"]}
    cambios = False
    t = ahora_ms()

    # cierra lives abiertos de vendedores que ya no se monitorean
    monitoreados = {v["usuario"] for v in activos}
    for u, e in list(d["estado"].items()):
        if u not in monitoreados:
            if e.get("liveId") in por_id and por_id[e["liveId"]]["estado"] == "EN VIVO":
                cerrar_live(por_id[e["liveId"]], por_id[e["liveId"]].get("visto") or t)
            del d["estado"][u]
            cambios = True

    with ThreadPoolExecutor(HILOS) as ex:
        resultados = list(ex.map(lambda v: consultar(v["usuario"]), activos))

    en_vivo = 0
    for v, r in zip(activos, resultados):
        e = d["estado"].setdefault(v["usuario"], {
            "usuario": v["usuario"], "enVivo": False, "roomId": "", "liveId": "", "sinLive": 0})
        e["ultimaRev"] = t
        live = por_id.get(e.get("liveId"))

        if "error" in r:
            if e.get("error") != r["error"]:
                cambios = True
            e["error"] = r["error"]
            continue
        if e.get("error"):
            cambios = True
        e["error"] = ""

        if r["enVivo"]:
            en_vivo += 1
            e["sinLive"] = 0
            otro_live = e["enVivo"] and r["roomId"] and e.get("roomId") and r["roomId"] != e["roomId"]
            if not e["enVivo"] or otro_live or not live:
                if otro_live and live:
                    cerrar_live(live, t)
                inicio = r["inicio"] or t
                lid = "%s-%s" % (v["usuario"], datetime.fromtimestamp(inicio / 1000, timezone.utc).strftime("%Y%m%d%H%M"))
                live = por_id.get(lid)
                if not live:
                    live = {"id": lid, "usuario": v["usuario"], "nombre": v["nombre"], "agencia": v["agencia"], "cadena": v["cadena"],
                            "inicio": inicio, "fin": None, "min": None, "titulo": r["titulo"],
                            "estado": "EN VIVO", "visto": t}
                    d["lives"].append(live)
                    por_id[lid] = live
                    log("🔴 INICIO", v["usuario"], r.get("metodo", ""))
                live["estado"], live["visto"] = "EN VIVO", t
                registrar_audiencia(live, r)
                e.update(enVivo=True, roomId=r["roomId"], liveId=lid)
                cambios = True
            else:
                live["visto"] = t
                registrar_audiencia(live, r)
                cambios = True
                if r["titulo"] and not live.get("titulo"):
                    live["titulo"] = r["titulo"]
        elif e["enVivo"]:
            e["sinLive"] = e.get("sinLive", 0) + 1
            if e["sinLive"] >= REVISIONES_PARA_CERRAR:
                if live:
                    visto = live.get("visto") or t
                    cerrar_live(live, visto + INTERVALO * 1000 // 2)
                    log("⚪ FIN", v["usuario"], "%s min" % live["min"])
                e.update(enVivo=False, roomId="", liveId="", sinLive=0)
                cambios = True

    errores = sum(1 for v in activos if d["estado"][v["usuario"]].get("error"))
    log("Revisados %d · en vivo %d · errores %d" % (len(activos), en_vivo, errores))
    return vendedores, cambios


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "crudo":
        for u in sys.argv[2:]:
            try:
                q = urllib.parse.urlencode({"aid": "1988", "app_name": "tiktok_web", "device_platform": "web_pc",
                                            "sourceType": "54", "uniqueId": limpiar_usuario(u)})
                _, txt = http_get("https://www.tiktok.com/api-live/user/room/?" + q)
                d = json.loads(txt).get("data") or {}
                room = d.get("liveRoom") or {}
                print(u, "status", room.get("status"), (d.get("user") or {}).get("status"))
                print("  liveRoom keys:", sorted(room.keys()))
                print("  stats:", json.dumps(room.get("liveRoomStats"), ensure_ascii=False)[:400])
                for k in ("userCount", "enterCount", "viewerCount", "likeCount", "totalUser"):
                    if k in room:
                        print("  ", k, room[k])
                print("  data keys:", sorted(d.keys()))
            except Exception as e:
                print(u, "ERROR", e)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "probar":
        for u in sys.argv[2:]:
            print(u, json.dumps(consultar(limpiar_usuario(u)), ensure_ascii=False))
        return

    fin_bucle = time.time() + DURACION_MIN * 60
    ultimo_guardado = 0
    d = cargar_datos()
    while True:
        inicio_ronda = time.time()
        if AL_GUARDAR:
            subprocess.run(["git", "pull", "-q", "--ff-only"], check=False)  # toma vendedores nuevos
        vendedores, cambios = revisar(d)
        if cambios or time.time() - ultimo_guardado >= LATIDO_SEG:
            guardar_datos(d, vendedores)
            ultimo_guardado = time.time()
            if AL_GUARDAR:
                subprocess.run(AL_GUARDAR, shell=True, check=False)
        if time.time() + INTERVALO > fin_bucle:
            break
        time.sleep(max(5, INTERVALO - (time.time() - inicio_ronda)))
    guardar_datos(d, leer_vendedores())
    if AL_GUARDAR:
        subprocess.run(AL_GUARDAR, shell=True, check=False)


if __name__ == "__main__":
    main()
