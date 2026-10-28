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
    m = re.search(r"tiktok\.com/@([^/?#\s]+)", u, re.I) or re.search(r"instagram\.com/([^/?#\s]+)", u, re.I)
    if m:
        u = m.group(1)
    u = re.sub(r"^(ig|instagram|tt|tiktok):", "", u.strip(), flags=re.I)
    return re.sub(r"\s+", "", u.lstrip("@")).lower()


def plataforma_de(txt_plataforma, txt_usuario=""):
    p = str(txt_plataforma or "").strip().lower()
    u = str(txt_usuario or "").strip().lower()
    if p.startswith(("ig", "insta")) or "instagram.com" in u or u.startswith(("ig:", "instagram:")):
        return "instagram"
    return "tiktok"


def clave_cuenta(handle, plataforma):
    """Identificador interno: TikTok usa el usuario tal cual; Instagram lleva el prefijo ig:."""
    return ("ig:" + handle) if plataforma == "instagram" else handle


# Cadenas de Cresa: se reconocen por el inicio de la agencia (ej. "JAPON PARQUE CALIFORNIA")
CADENAS_CRESA = [
    ("ALMACENES JAPON", "Japón"), ("ALMACENES JAPÓN", "Japón"), ("JAPON", "Japón"), ("JAPÓN", "Japón"),
    ("CRECOS", "Crecos"), ("ORVE HOGAR", "Orve Hogar"), ("ORVE", "Orve Hogar"),
    ("MOTOZONE", "Motozone"), ("MOTO ZONE", "Motozone"), ("PAGA MENOS", "Pagamenos"), ("PAGAMENOS", "Pagamenos"),
    ("SAMSUNG", "Samsung"), ("INDEPENDIENTES", "Independientes"), ("INDEPENDIENTE", "Independientes"),
    ("MULTINIVEL", "Independientes"), ("MULTI NIVEL", "Independientes"),
]
# Independientes (antes "Multinivel"): venden para cualquier agencia → no llevan agencia
MULTINIVEL = "Independientes"
COLUMNAS = {
    "usuario": ("usuario", "usuario tiktok", "user", "username", "tiktok"),
    "agencia": ("agencia", "zona", "zona / agencia", "tienda", "almacen", "almacén"),
    "nombre": ("nombre", "vendedor", "name"),
    "activo": ("activo", "activo (si/no)", "estado"),
    "tipo": ("tipo", "nuestra/competencia"),
    "rol": ("rol", "cuenta", "tipo de cuenta", "perfil", "clase"),
    "plataforma": ("plataforma", "red", "red social", "app"),
}
ORDEN_POR_DEFECTO = ["usuario", "agencia", "nombre", "activo", "tipo", "rol", "plataforma"]


def tipo_de(txt):
    t = str(txt or "").strip().upper()
    return "competencia" if t == "C" or t.startswith("COMP") else "propio"


# Competidores conocidos: si la agencia empieza así, la cuenta es de competencia y se agrupa en esa empresa.
# Se pueden agregar más; cualquier otra empresa también funciona marcándola como competencia.
COMPETIDORES = [
    ("ALMACENES ESPAÑA", "Almacenes España"), ("ALMACENES ESPANA", "Almacenes España"), ("ESPAÑA", "Almacenes España"),
    ("ALMACENES AL PRECIO", "Almacenes Al Precio"), ("AL PRECIO", "Almacenes Al Precio"),
    ("ARTEFACTA", "Artefacta"), ("MARCIMEX", "Marcimex"), ("COMANDATO", "Comandato"), ("JAHER", "Jaher"),
    ("ALMACENES JAHER", "Jaher"), ("LA GANGA", "La Ganga"), ("ALMACENES LA GANGA", "La Ganga"),
    ("ALMACENES TIA", "Almacenes Tía"), ("ALMACENES TÍA", "Almacenes Tía"), ("TIA", "Almacenes Tía"), ("TÍA", "Almacenes Tía"),
    ("TVENTAS", "Tventas"),
    # agregadas: indicadas por Mercadeo y principales cadenas del gremio (Asadelec) y del mercado
    ("POINT", "Point"), ("BODEGA DEL AHORRO", "Bodega del Ahorro"), ("LA BODEGA DEL AHORRO", "Bodega del Ahorro"),
    ("CASA HOGAR", "Casa Hogar"), ("MAS MOTO", "Más Moto"), ("MÁS MOTO", "Más Moto"), ("MASMOTO", "Más Moto"),
    ("SUKASA", "Sukasa"), ("TODO HOGAR", "Todo Hogar"), ("TODOHOGAR", "Todo Hogar"), ("GRAN HOGAR", "Gran Hogar"),
    ("MI BODEGA", "Mi Bodega"), ("BESTPC", "BestPC"), ("BEST PC", "BestPC"), ("COMPUTRON", "Computron"),
    ("NOVICOMPU", "Novicompu"), ("MI MOTO", "Mi Moto"), ("ALMACENES MI MOTO", "Mi Moto"),
    ("MASTER MOTOS", "Master Motos"), ("MASTER MOTO", "Master Motos"), ("MASTERMOTO", "Master Motos"),
    ("SAMADI MOTOS", "Samadi Motos"), ("SAMADI", "Samadi Motos"), ("SAMANDI MOTOS", "Samadi Motos"), ("SAMANDI", "Samadi Motos"),
]

# ---- Separar "CADENA + UBICACIÓN" cuando la cadena no está en las listas (ej. "POINT MALL DEL NORTE")
CIUDADES = """GUAYAQUIL QUITO CUENCA MACHALA MANTA PORTOVIEJO AMBATO LOJA ESMERALDAS IBARRA RIOBAMBA LATACUNGA BABAHOYO
QUEVEDO MILAGRO DURAN DURÁN DAULE SALINAS LIBERTAD PLAYAS CHONE SAMBORONDON SAMBORONDÓN TULCAN TULCÁN NUEVA LOJA LAGO AGRIO
COCA TENA PUYO MACAS ZAMORA AZOGUES GUARANDA OTAVALO CAYAMBE SANGOLQUI SANGOLQUÍ PASAJE HUAQUILLAS JIPIJAPA MONTECRISTI
BAHIA BAHÍA PEDERNALES NARANJAL NARANJITO EMPALME TRONCAL VINCES VENTANAS BALZAR NOBOL PIÑAS PINAS ROSA SANTO DOMINGO
CONCORDIA QUININDE QUININDÉ CALCETA SUCRE MACHACHI TUMBACO CUMBAYA CUMBAYÁ CALDERON CALDERÓN CARAPUNGO CONOCOTO
GUAMANI GUAMANÍ CHILLOGALLO QUITUMBE SUR NORTE CENTRO ESTE OESTE MATRIZ SUCURSAL AGENCIA LOCAL MALL
SHOPPING CC C.C. CENTRO COMERCIAL PASEO RIOCENTRO QUICENTRO POLICENTRO SAN MARINO RECREO CONDADO SCALA BOMBOLI
PORTAL ALBORADA URDESA GUASMO PORTETE PROSPERINA SAUCES AV AV. AVENIDA CALLE KM KM. VIA VÍA""".split()


def _lugares_aprendidos():
    """Ubicaciones completas aprendidas de las agencias de Cresa (ej. 'MALL DEL NORTE', 'NUEVA AURORA', 'EL RECREO')."""
    frases = set()
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "encuesta", "agencias.json"), encoding="utf-8") as f:
            for a in json.load(f):
                for p, _ in sorted(CADENAS_CRESA, key=lambda x: -len(x[0])):
                    if a.startswith(p + " "):
                        resto = re.sub(r"(\s+\d+)+$", "", a[len(p) + 1:].strip())   # sin el número de local
                        if resto:
                            frases.add(resto)
                        break
    except Exception:
        pass
    return frases


LUGARES = set(CIUDADES)
LUGAR_FRASES = sorted(_lugares_aprendidos(), key=len, reverse=True)


def separar_cadena(agencia):
    """'POINT MALL DEL NORTE' → ('Point', 'MALL DEL NORTE'). Si no encuentra ubicación, todo es la cadena."""
    palabras = agencia.split()
    for i in range(1, len(palabras)):
        resto = " ".join(palabras[i:])
        w = palabras[i].strip(".,-")
        if w in LUGARES or w.isdigit() or any(resto == f or resto.startswith(f + " ") for f in LUGAR_FRASES):
            return " ".join(palabras[:i]).title(), resto
    return agencia.title(), ""


def _prefijo(agencia, lista):
    """(nombre, coincide_exacto) del primer prefijo que calce, o (None, False)."""
    a = agencia.upper()
    for prefijo, nombre in lista:
        if a == prefijo:
            return nombre, True
        if a.startswith(prefijo + " "):
            return nombre, False
    return None, False


def competidor_de(agencia):
    return _prefijo(agencia, COMPETIDORES)[0]


def rol_de(txt_rol, agencia):
    """'oficial' = cuenta de la cadena/empresa; 'vendedor' = cuenta personal de un vendedor.
    Si no se indica, es oficial cuando la agencia es solo el nombre de la cadena (ej. CRECOS, JAPON, ARTEFACTA)."""
    t = str(txt_rol or "").strip().upper()
    if t.startswith(("OFI", "MARCA", "CADENA", "CORP")):
        return "oficial"
    if t.startswith(("VEN", "PERS", "ASES")):
        return "vendedor"
    for lista in (CADENAS_CRESA, COMPETIDORES):
        nombre, exacto = _prefijo(agencia, lista)
        if nombre == MULTINIVEL:
            return "vendedor"
        if nombre:
            return "oficial" if exacto else "vendedor"
    return "vendedor"


def clasificar(agencia, tipo_txt):
    """Devuelve (cadena, tipo). Cadenas Cresa por 1.ª palabra; competidores conocidos por prefijo."""
    comp = competidor_de(agencia)
    if comp:
        return comp, "competencia"
    tipo = tipo_de(tipo_txt)
    return cadena_de(agencia, tipo), tipo


def cadena_de(agencia, tipo="propio"):
    """Cadenas Cresa por prefijo conocido; si no se conoce, se separa la cadena de la ubicación."""
    if agencia == "SIN AGENCIA":
        return "Competencia" if tipo == "competencia" else "Otra"
    conocida = _prefijo(agencia, CADENAS_CRESA)[0]
    if conocida and tipo != "competencia":
        return conocida
    return separar_cadena(agencia)[0]


ENCUESTA_CSV = os.path.join(DATA_DIR, "encuesta", "cuentas_sapo.csv")


def leer_vendedores(incluir_encuesta=True):
    """Cuentas a monitorear: primero las que llegaron por la encuesta (verificadas) y luego las
    agregadas a mano en vendedores/*.csv. Si una cuenta está en ambos lados cuenta una sola vez
    y ganan los datos puestos a mano."""
    vistos, salida = {}, []
    rutas = sorted(glob.glob(os.path.join(VENDEDORES_DIR, "*.csv")))
    if incluir_encuesta and os.path.exists(ENCUESTA_CSV):
        rutas = [ENCUESTA_CSV] + rutas
    for ruta in rutas:
        archivo = "encuesta" if ruta == ENCUESTA_CSV else os.path.basename(ruta)
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
            handle = limpiar_usuario(datos.get("usuario"))
            if not handle:
                continue
            plataforma = plataforma_de(datos.get("plataforma"), datos.get("usuario"))
            usuario = clave_cuenta(handle, plataforma)
            agencia = re.sub(r"\s+", " ", datos.get("agencia", "")).strip().upper() or "SIN AGENCIA"
            cadena, tipo = clasificar(agencia, datos.get("tipo"))
            if cadena == MULTINIVEL:
                agencia, tipo = "", "propio"          # los independientes no pertenecen a una agencia
            v = {
                "usuario": usuario,
                "handle": handle,
                "plataforma": plataforma,
                "rol": rol_de(datos.get("rol"), agencia),
                "nombre": datos.get("nombre") or "@" + handle,
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


_perfiles = {}


def perfil_tiktok(usuario, max_edad=6 * 3600):
    """Existencia real de una cuenta según su página de perfil (la API de lives solo conoce
    cuentas con lives habilitados). Devuelve {existe, nick, seguidores, videos} o None si no se pudo consultar."""
    c = _perfiles.get(usuario)
    if c and time.time() - c["_t"] < max_edad:
        return c
    try:
        _, html = http_get("https://www.tiktok.com/@" + urllib.parse.quote(usuario), timeout=25)
    except Exception:
        return c
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return c
    det = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {})
    ui = det.get("userInfo") or {}
    u, st = ui.get("user") or {}, ui.get("statsV2") or ui.get("stats") or {}
    existe = det.get("statusCode", 0) == 0 and bool(u.get("uniqueId") or u.get("id"))
    c = {"existe": existe, "nick": u.get("nickname", ""), "seguidores": int(st["followerCount"]) if st.get("followerCount") is not None else None,
         "videos": int(st["videoCount"]) if st.get("videoCount") is not None else None, "codigo": det.get("statusCode"), "_t": time.time()}
    _perfiles[usuario] = c
    return c


# ------------------------------------------------------------------ Instagram (API oficial de Meta)

IG_CADA_MIN = 5            # la API de Meta tiene límite de llamadas: los lives de Instagram se revisan cada 5 min
_ig_ultima = {"t": 0, "res": {}}


def consultar_instagram(v):
    """Lives de Instagram: solo para cuentas propias conectadas a la API de Meta."""
    import meta
    if not meta.disponible():
        return {"omitir": True, "nota": "Instagram: falta conectar la API de Meta (IG_TOKEN)"}
    try:
        propias = meta.cuentas_propias()
    except Exception as e:
        return {"omitir": True, "nota": "Instagram: %s" % str(e)[:120]}
    ig_id = propias.get(v["handle"])
    if not ig_id:
        return {"omitir": True, "nota": "Instagram: lives solo para cuentas propias conectadas a Meta (las métricas de contenido sí se registran)"}
    t = time.time()
    if t - _ig_ultima["res"].get(v["usuario"], {}).get("_t", 0) < IG_CADA_MIN * 60 - 5:
        return {"omitir": True}
    try:
        live_id = meta.en_vivo(ig_id)
        r = {"enVivo": bool(live_id), "roomId": live_id or "", "inicio": None, "titulo": "", "espectadores": None, "vistas": None, "metodo": "meta"}
    except Exception as e:
        r = {"error": "Instagram: %s" % str(e)[:120]}
    _ig_ultima["res"][v["usuario"]] = dict(r, _t=t)
    return r


def consultar(usuario):
    errores = []
    for fn in (consultar_api, consultar_html):
        try:
            r = fn(usuario)
            r["metodo"] = fn.__name__
            return r
        except LookupError as e:
            p = perfil_tiktok(usuario)
            if p and p["existe"]:   # existe, pero sin lives habilitados → no es un error
                return {"enVivo": False, "roomId": "", "inicio": None, "titulo": "", "espectadores": None, "vistas": None,
                        "metodo": "perfil", "nota": "sin lives habilitados"}
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
        resultados = list(ex.map(lambda v: consultar(v["handle"]) if v["plataforma"] == "tiktok" else None, activos))
    resultados = [r if r is not None else consultar_instagram(v) for v, r in zip(activos, resultados)]

    en_vivo = 0
    for v, r in zip(activos, resultados):
        e = d["estado"].setdefault(v["usuario"], {
            "usuario": v["usuario"], "enVivo": False, "roomId": "", "liveId": "", "sinLive": 0})
        e["ultimaRev"] = t
        live = por_id.get(e.get("liveId"))

        if r.get("omitir"):               # Instagram fuera de turno o sin datos de lives disponibles
            if "nota" in r and e.get("error") != r["nota"]:
                e["error"] = r["nota"]
                cambios = True
            continue
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
                            "plataforma": v["plataforma"],
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
            if e["sinLive"] >= (1 if v["plataforma"] == "instagram" else REVISIONES_PARA_CERRAR):
                if live:
                    visto = live.get("visto") or t
                    paso = IG_CADA_MIN * 60000 if v["plataforma"] == "instagram" else INTERVALO * 1000
                    cerrar_live(live, visto + paso // 2)
                    log("⚪ FIN", v["usuario"], "%s min" % live["min"])
                e.update(enVivo=False, roomId="", liveId="", sinLive=0)
                cambios = True

    errores = sum(1 for v in activos if d["estado"][v["usuario"]].get("error") and v["plataforma"] == "tiktok")
    log("Revisados %d · en vivo %d · errores %d" % (len(activos), en_vivo, errores))
    return vendedores, cambios


def revisar_encuesta():
    """Revisa el buzón de la encuesta en cada vuelta; regenera el Excel solo si llegaron respuestas."""
    try:
        import encuesta
        return encuesta.main(solo_si_hay_nuevas=True)
    except Exception as e:
        log("Encuesta: error", str(e)[:150])
        return 0


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

    if len(sys.argv) > 1 and sys.argv[1] == "perfil":
        for u in sys.argv[2:]:
            print(u, json.dumps(perfil_tiktok(limpiar_usuario(u)), ensure_ascii=False))
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
        if revisar_encuesta():
            cambios = True
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
