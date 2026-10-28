#!/usr/bin/env python3
"""
Recolector de la encuesta de vendedores (encuesta/index.html).

- Las respuestas llegan a un buzón ntfy.sh (guarda 12 h); se copian a DATA_DIR/encuesta/respuestas.jsonl.
- Cada cuenta cuenta UNA sola vez: si un vendedor responde varias veces gana su última respuesta, y una
  cuenta de competencia reportada por varios vendedores es una sola fila.
- Eliminar: archivos en encuesta/excluir/*.txt (rama main) con una línea por cuenta (@usuario) o
  respuesta (id:XXXX). Se crean desde la pestaña Encuesta de SAPO.
- Genera en DATA_DIR/encuesta/:
    Encuesta_TikTok_Cresa.xlsx  (Cuentas Cresa · Competencia · Avance por agencia)
    datos.json                  (vista en vivo de SAPO)
    resumen.json
    cuentas_sapo.csv            (cuentas verificadas que SAPO monitorea, sin duplicar las puestas a mano)
"""
import csv
import difflib
import re
import unicodedata
import glob
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from monitor import http_get, leer_vendedores, log

BUZON = "https://ntfy.sh/sapo-cresa-encuesta-609141a776"
DATA_DIR = os.environ.get("DATA_DIR", "data")
CARPETA = os.path.join(DATA_DIR, "encuesta")
RESP = os.path.join(CARPETA, "respuestas.jsonl")
VALID = os.path.join(CARPETA, "validacion.json")
EXCEL = os.path.join(CARPETA, "Encuesta_TikTok_Cresa.xlsx")
RAIZ = os.path.dirname(os.path.abspath(__file__))
AGENCIAS = os.path.join(RAIZ, "encuesta", "agencias.json")
EXCLUIR = os.path.join(RAIZ, "encuesta", "excluir")
EC = timezone(timedelta(hours=-5))
MULTI = "INDEPENDIENTES (sin agencia)"
INDEP = ("Independientes", "Multinivel")   # Multinivel = nombre anterior
CADENAS = [("PAGA MENOS", "Pagamenos"), ("MOTOZONE", "Motozone"), ("SAMSUNG", "Samsung"),
           ("CRECOS", "Crecos"), ("ORVE", "Orve Hogar"), ("JAPON", "Japón")]


def leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def traer_respuestas():
    previas = []
    if os.path.exists(RESP):
        with open(RESP, encoding="utf-8") as f:
            previas = [json.loads(l) for l in f if l.strip()]
    vistas = {r["_id"] for r in previas}
    with urllib.request.urlopen(BUZON + "/json?poll=1&since=all", timeout=30) as r:
        lineas = r.read().decode("utf-8").splitlines()
    nuevas = []
    for l in lineas:
        ev = json.loads(l)
        if ev.get("event") != "message" or ev["id"] in vistas:
            continue
        try:
            d = json.loads(ev.get("message") or "{}")
        except ValueError:
            continue
        if d.get("cadena") == "Multinivel":
            d["cadena"] = "Independientes"
        if d.get("prueba") or not (d.get("agencia") or d.get("cadena") in INDEP):
            continue
        d["_id"], d["_t"] = ev["id"], ev["time"]
        nuevas.append(d)
    if nuevas:
        os.makedirs(CARPETA, exist_ok=True)
        with open(RESP, "a", encoding="utf-8") as f:
            for d in nuevas:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return previas + nuevas, len(nuevas)


def leer_exclusiones():
    """(@usuarios, ids de respuesta) eliminados desde SAPO."""
    usuarios, ids = set(), set()
    for ruta in glob.glob(os.path.join(EXCLUIR, "*.txt")):
        with open(ruta, encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#"):
                    continue
                if l.lower().startswith("id:"):
                    ids.add(l[3:].strip())
                else:
                    usuarios.add(l.lstrip("@").lower())
    return usuarios, ids


def verificar(usuario, cache):
    """Comprueba en TikTok que el usuario exista; guarda nombre visible y seguidores."""
    c = cache.get(usuario)
    ahora = time.time()
    if c and (c["existe"] and ahora - c["t"] < 7 * 86400 or c["existe"] is False and ahora - c["t"] < 6 * 3600):
        return c
    q = urllib.parse.urlencode({"aid": "1988", "sourceType": "54", "uniqueId": usuario})
    try:
        _, txt = http_get("https://www.tiktok.com/api-live/user/room/?" + q)
        d = json.loads(txt).get("data") or {}
        u, st = d.get("user") or {}, d.get("stats") or {}
        c = {"existe": bool(u), "nick": u.get("nickname", ""), "seguidores": st.get("followerCount"), "t": ahora}
    except Exception as e:
        if c:
            return c
        c = {"existe": None, "error": str(e)[:80], "t": ahora - 7 * 86400}
    cache[usuario] = c
    time.sleep(0.3)
    return c


def fecha(t):
    return datetime.fromtimestamp(t, EC).strftime("%Y-%m-%d %H:%M")


def existe_txt(v):
    c = v.get("corregido")
    if c:
        estado = {True: "sí existe", False: "TAMPOCO EXISTE – revisar", None: "sin verificar"}[c.get("existe")]
        return "Corregida → @%s (%s)" % (c["tiktok"], estado)
    return {True: "Sí", False: "NO EXISTE – revisar", None: "Sin verificar"}[v.get("existe")]


def _ag_norm(a):
    a = re.sub(r"\s+", " ", str(a or "").upper().replace("ALMACENES ", "")).strip()
    return re.sub(r"^ORVE HOGAR\b", "ORVE", a)


def _alnum(t):
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())


def buscar_correccion(fila, manuales_por_ag, ocupadas=()):
    """Cuenta puesta a mano (misma agencia) que corrige un usuario de la encuesta que no existe."""
    a = _alnum(fila["tiktok"])
    nombres = [_alnum(p) for p in unicodedata.normalize("NFD", fila["nombre"]).encode("ascii", "ignore").decode().split() if len(p) >= 4]
    mejor, puntaje = None, 0
    for h in manuales_por_ag.get(_ag_norm(fila["agencia"]), []):
        b = _alnum(h)
        if not b or h in ocupadas:
            continue
        p = 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()
        p += 0.5 * sum(1 for n in nombres if n and n in b)   # cada palabra del nombre que aparece en el usuario
        if p > puntaje:
            mejor, puntaje = h, p
    return mejor if puntaje >= 0.55 else None


def cadena_de(a):
    return next((n for p, n in CADENAS if a.startswith(p)), "")


def procesar(respuestas, cache):
    excl_u, excl_ids = leer_exclusiones()
    for r in respuestas:
        if r.get("cadena") == "Multinivel":
            r["cadena"] = "Independientes"
    validas = [r for r in respuestas if r["_id"] not in excl_ids]
    manuales = {(v["plataforma"], v["handle"]): v for v in leer_vendedores(incluir_encuesta=False)}

    # ---- Cuentas Cresa: una fila por usuario de TikTok (gana la última respuesta)
    cresa = {}
    for r in sorted(validas, key=lambda x: x["_t"]):
        tt = (r.get("tiktok") or "").lower()
        if tt and tt in excl_u:
            continue
        clave = tt or "sin-tiktok:" + (r.get("nombre") or "").strip().lower() + "|" + (r.get("agencia") or "")
        prev = cresa.get(clave)
        x = dict(r)
        x["_veces"] = (prev["_veces"] + 1) if prev else 1
        x["_ids"] = (prev["_ids"] if prev else []) + [r["_id"]]
        x["_primera"] = prev["_primera"] if prev else r["_t"]
        cresa[clave] = x
    filas_cresa = []
    for x in sorted(cresa.values(), key=lambda x: -x["_t"]):
        tt = (x.get("tiktok") or "").lower()
        v = verificar(tt, cache) if tt else {}
        man = manuales.get(("tiktok", tt))
        filas_cresa.append({
            "fecha": fecha(x["_t"]), "nombre": x.get("nombre", ""), "cadena": x.get("cadena", ""),
            "agencia": x.get("agencia") or ("(sin agencia)" if x.get("cadena") in INDEP else ""),
            "tiktok": tt, "existe": v.get("existe") if tt else None, "nick": v.get("nick", ""),
            "seguidores": v.get("seguidores"), "lives": x.get("lives", ""),
            "instagram": (x.get("instagram") or "").lower(), "veces": x["_veces"], "ids": x["_ids"],
            "ya_en_sapo": bool(man)})

    # Cuentas que no existen pero que alguien ya corrigió agregándolas a mano (misma agencia, usuario parecido)
    manuales_por_ag = defaultdict(list)
    for (plat, h), v in manuales.items():
        if plat == "tiktok" and v["tipo"] == "propio":
            manuales_por_ag[_ag_norm(v["agencia"] or "INDEPENDIENTE")].append(h)
    ocupadas = {f["tiktok"] for f in filas_cresa if f["tiktok"] and f["existe"]}   # cuentas válidas de otros vendedores
    for f in filas_cresa:
        if f["tiktok"] and f["existe"] is False:
            h = buscar_correccion(f, manuales_por_ag, ocupadas)
            if h:
                f["corregido"] = {"tiktok": h, "existe": verificar(h, cache).get("existe")}

    # ---- Competencia: una fila por cuenta (aunque la reporten varios)
    comp = {}
    for r in sorted(validas, key=lambda x: x["_t"]):
        for c in r.get("competencia") or []:
            u = (c.get("usuario") or "").lower()
            if not u or u in excl_u or u in cresa:
                continue
            x = comp.setdefault(u, {"empresas": defaultdict(int), "contenido": defaultdict(int), "por": [],
                                    "agencias": set(), "primera": r["_t"], "ultima": r["_t"]})
            if c.get("empresa"):
                x["empresas"][c["empresa"]] += 1
            if c.get("contenido"):
                x["contenido"][c["contenido"]] += 1
            quien = (r.get("nombre") or "").strip()
            if quien and quien not in x["por"]:
                x["por"].append(quien)
            x["agencias"].add(r.get("agencia") or r.get("cadena", ""))
            x["ultima"] = r["_t"]
    filas_comp = []
    for u, x in sorted(comp.items(), key=lambda kv: (-len(kv[1]["por"]), -kv[1]["ultima"])):
        v = verificar(u, cache)
        filas_comp.append({
            "tiktok": u, "empresa": max(x["empresas"], key=x["empresas"].get) if x["empresas"] else "",
            "contenido": max(x["contenido"], key=x["contenido"].get) if x["contenido"] else "",
            "existe": v.get("existe"), "nick": v.get("nick", ""), "seguidores": v.get("seguidores"),
            "veces": max(1, len(x["por"])), "por": x["por"], "agencias": sorted(a for a in x["agencias"] if a),
            "primera": fecha(x["primera"]), "ya_en_sapo": bool(manuales.get(("tiktok", u)))})

    # ---- Avance por agencia (vendedores únicos)
    agencias = leer_json(AGENCIAS, [])
    por_ag = defaultdict(set)
    for f in filas_cresa:
        clave = MULTI if f["cadena"] in INDEP else f["agencia"]
        por_ag[clave].add(f["tiktok"] or f["nombre"].lower())
    avance = [{"cadena": cadena_de(a), "agencia": a, "n": len(por_ag.get(a, ()))} for a in agencias]
    avance.append({"cadena": "Independientes", "agencia": MULTI, "n": len(por_ag.get(MULTI, ()))})
    return filas_cresa, filas_comp, avance, len(validas), len(respuestas) - len(validas)


def escribir_excel(filas_cresa, filas_comp, avance):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    cab_fill = PatternFill("solid", fgColor="16A34A")
    rojo = PatternFill("solid", fgColor="FDE2E2")

    def hoja(ws, cab, filas, anchos, col_alerta=None, links=()):
        ws.append(cab)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), cab_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for f in filas:
            ws.append(f)
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 30
        for row in ws.iter_rows(min_row=2):
            if col_alerta and (str(row[col_alerta - 1].value).startswith(("NO", "Sin r"))):
                for c in row:
                    c.fill = rojo
            for col, url in links:
                c = row[col - 1]
                if c.value and str(c.value).startswith("@"):
                    c.hyperlink, c.style = url(str(c.value)[1:]), "Hyperlink"

    ws = wb.active
    ws.title = "Cuentas Cresa"
    hoja(ws, ["Última respuesta", "Nombre", "Cadena", "Agencia", "Usuario TikTok", "¿Existe en TikTok?", "Nombre en TikTok",
              "Seguidores", "¿Hace lives?", "Instagram", "¿Ya estaba en SAPO?", "Veces que respondió"],
         [[f["fecha"], f["nombre"], f["cadena"], f["agencia"], ("@" + f["tiktok"]) if f["tiktok"] else "(no tiene TikTok)",
           existe_txt(f) if f["tiktok"] else "", f["nick"], f["seguidores"], f["lives"],
           ("@" + f["instagram"]) if f["instagram"] else "", "Sí" if f["ya_en_sapo"] else "No", f["veces"]] for f in filas_cresa],
         [17, 26, 12, 30, 24, 20, 24, 12, 13, 20, 14, 12], col_alerta=6,
         links=[(5, lambda u: "https://www.tiktok.com/@" + u), (10, lambda u: "https://www.instagram.com/" + u + "/")])
    ws2 = wb.create_sheet("Competencia")
    hoja(ws2, ["Usuario TikTok", "Empresa", "Qué publica", "¿Existe en TikTok?", "Nombre en TikTok", "Seguidores",
               "Vendedores que la reportaron", "Reportada por", "Agencias que la reportan", "Primer reporte", "¿Ya estaba en SAPO?"],
         [["@" + f["tiktok"], f["empresa"], f["contenido"], existe_txt(f), f["nick"], f["seguidores"], f["veces"],
           ", ".join(f["por"]), ", ".join(f["agencias"]), f["primera"], "Sí" if f["ya_en_sapo"] else "No"] for f in filas_comp],
         [24, 20, 13, 20, 24, 12, 12, 36, 40, 17, 14], col_alerta=4, links=[(1, lambda u: "https://www.tiktok.com/@" + u)])
    ws3 = wb.create_sheet("Avance por agencia")
    orden = sorted(avance, key=lambda a: (a["n"] > 0, a["cadena"], a["agencia"]))
    hoja(ws3, ["Cadena", "Agencia", "Vendedores que respondieron", "¿Respondió?"],
         [[a["cadena"], a["agencia"], a["n"], "Sí" if a["n"] else "Sin respuestas"] for a in orden], [12, 32, 14, 16], col_alerta=4)
    wb.save(EXCEL)


def escribir_cuentas_sapo(filas_cresa, filas_comp):
    """Cuentas verificadas para que SAPO las monitoree. Las que ya están puestas a mano se omiten (no se duplican)."""
    filas = []
    for f in filas_cresa:
        if f["tiktok"] and f["existe"] and not f["ya_en_sapo"]:
            agencia = "INDEPENDIENTE" if f["cadena"] in INDEP else f["agencia"]
            filas.append([f["tiktok"], agencia, f["nombre"], "SI", "propio", "vendedor", "tiktok"])
        if f["instagram"]:
            agencia = "INDEPENDIENTE" if f["cadena"] in INDEP else f["agencia"]
            filas.append([f["instagram"], agencia, f["nombre"], "SI", "propio", "vendedor", "instagram"])
    for f in filas_comp:
        if f["existe"] and not f["ya_en_sapo"]:
            filas.append([f["tiktok"], (f["empresa"] or "COMPETENCIA").upper(), "", "SI", "competencia", "vendedor", "tiktok"])
    with open(os.path.join(CARPETA, "cuentas_sapo.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["usuario", "agencia", "nombre", "activo", "tipo", "rol", "plataforma"])
        w.writerows(filas)
    return len(filas)


def main(solo_si_hay_nuevas=False):
    """Con solo_si_hay_nuevas=True (desde el monitor, cada minuto) regenera solo si llegó algo o cambiaron las eliminaciones."""
    respuestas, n_nuevas = traer_respuestas()
    firma = json.dumps(sorted(leer_exclusiones()[0]) + sorted(leer_exclusiones()[1]))
    previo = leer_json(os.path.join(CARPETA, "resumen.json"), {})
    if solo_si_hay_nuevas and n_nuevas == 0 and os.path.exists(EXCEL) and previo.get("firma") == firma \
            and time.time() * 1000 - previo.get("actualizado", 0) < 3600 * 1000:
        return 0
    cache = leer_json(VALID, {})
    filas_cresa, filas_comp, avance, n_validas, n_eliminadas = procesar(respuestas, cache)
    os.makedirs(CARPETA, exist_ok=True)
    escribir_excel(filas_cresa, filas_comp, avance)
    n_sapo = escribir_cuentas_sapo(filas_cresa, filas_comp)
    with open(VALID, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    resumen = {"actualizado": int(time.time() * 1000), "respuestas": n_validas, "eliminadas": n_eliminadas,
               "vendedores": sum(1 for f in filas_cresa if f["tiktok"]), "competencia": len(filas_comp),
               "agencias_con_respuesta": sum(1 for a in avance if a["n"] and a["agencia"] != MULTI),
               "agencias_total": len(avance) - 1, "multinivel": next(a["n"] for a in avance if a["agencia"] == MULTI),
               "agregadas_a_sapo": n_sapo, "firma": firma}
    with open(os.path.join(CARPETA, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f)
    with open(os.path.join(CARPETA, "datos.json"), "w", encoding="utf-8") as f:
        json.dump({"resumen": resumen, "cresa": filas_cresa, "competencia": filas_comp, "avance": avance},
                  f, ensure_ascii=False, separators=(",", ":"))
    log("Encuesta: %d respuestas (%d nuevas) · %d vendedores únicos · %d de competencia · %d a SAPO" %
        (n_validas, n_nuevas, resumen["vendedores"], len(filas_comp), n_sapo))
    return max(n_nuevas, 1)


if __name__ == "__main__":
    main()
