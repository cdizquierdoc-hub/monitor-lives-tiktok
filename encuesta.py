#!/usr/bin/env python3
"""
Recolector de la encuesta de vendedores (encuesta/index.html).

- Las respuestas llegan a un buzón ntfy.sh (guarda 12 h); este script las copia a
  DATA_DIR/encuesta/respuestas.jsonl, verifica en TikTok que cada usuario exista
  y genera DATA_DIR/encuesta/Encuesta_TikTok_Cresa.xlsx con:
    · "Cuentas Cresa"  · "Competencia"  · "Avance por agencia"
"""
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
AGENCIAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "encuesta", "agencias.json")
EC = timezone(timedelta(hours=-5))


def leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def traer_respuestas():
    vistas = set()
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
        if d.get("prueba") or not (d.get("agencia") or d.get("cadena") == "Multinivel"):
            continue
        d["_id"], d["_t"] = ev["id"], ev["time"]
        nuevas.append(d)
    if nuevas:
        os.makedirs(CARPETA, exist_ok=True)
        with open(RESP, "a", encoding="utf-8") as f:
            for d in nuevas:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return previas + nuevas, len(nuevas)


def verificar(usuario, cache):
    """Comprueba en TikTok que el usuario exista; guarda nombre visible y seguidores."""
    c = cache.get(usuario)
    ahora = time.time()
    if c and (c["existe"] and ahora - c["t"] < 7 * 86400 or not c["existe"] and ahora - c["t"] < 6 * 3600):
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


def fecha(r):
    return datetime.fromtimestamp(r["_t"], EC).strftime("%Y-%m-%d %H:%M")


def existe_txt(v):
    return {True: "Sí", False: "NO EXISTE – revisar", None: "Sin verificar"}[v.get("existe")]


def main(solo_si_hay_nuevas=False):
    """Genera el Excel. Con solo_si_hay_nuevas=True (uso desde el monitor, cada minuto) no hace nada si no llegó nada."""
    respuestas, n_nuevas = traer_respuestas()
    if solo_si_hay_nuevas and n_nuevas == 0 and os.path.exists(EXCEL):
        return 0
    cache = leer_json(VALID, {})
    en_sapo = {v["handle"] for v in leer_vendedores() if v["plataforma"] == "tiktok"}
    agencias = leer_json(AGENCIAS, [])

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    cab_fill = PatternFill("solid", fgColor="16A34A")
    rojo = PatternFill("solid", fgColor="FDE2E2")

    def hoja(ws, cab, filas, anchos, col_alerta=None):
        ws.append(cab)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), cab_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for f in filas:
            ws.append([x for x, _ in f] if isinstance(f[0], tuple) else f)
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 30
        if col_alerta:
            for row in ws.iter_rows(min_row=2):
                if str(row[col_alerta - 1].value).startswith("NO"):
                    for c in row:
                        c.fill = rojo

    def link(ws, col, url_fn):
        for row in ws.iter_rows(min_row=2):
            c = row[col - 1]
            if c.value:
                c.hyperlink, c.style = url_fn(c.value), "Hyperlink"

    # ---- Cuentas Cresa (la última respuesta de cada vendedor gana; se marcan repetidos)
    conteo = defaultdict(int)
    for r in respuestas:
        if r.get("tiktok"):
            conteo[r["tiktok"]] += 1
    filas = []
    for r in sorted(respuestas, key=lambda x: x["_t"]):
        tt = r.get("tiktok") or ""
        v = verificar(tt, cache) if tt else {}
        filas.append([fecha(r), r.get("nombre", ""), r.get("cadena", ""), r.get("agencia", "") or ("(sin agencia)" if r.get("cadena") == "Multinivel" else ""),
                      ("@" + tt) if tt else "(no tiene TikTok)", existe_txt(v) if tt else "",
                      v.get("nick", ""), v.get("seguidores"), r.get("lives", ""),
                      ("@" + r["instagram"]) if r.get("instagram") else "",
                      "Sí" if tt in en_sapo else ("No" if tt else ""),
                      ("Repetido x%d" % conteo[tt]) if tt and conteo[tt] > 1 else ""])
    ws = wb.active
    ws.title = "Cuentas Cresa"
    hoja(ws, ["Fecha", "Nombre", "Cadena", "Agencia", "Usuario TikTok", "¿Existe en TikTok?", "Nombre en TikTok",
              "Seguidores", "¿Hace lives?", "Instagram", "¿Ya está en SAPO?", "Observación"],
         filas, [17, 26, 12, 30, 24, 20, 24, 12, 13, 20, 14, 14], col_alerta=6)
    link(ws, 5, lambda u: "https://www.tiktok.com/" + u if u.startswith("@") else None)
    link(ws, 10, lambda u: "https://www.instagram.com/" + u.lstrip("@") + "/")

    # ---- Competencia (una fila por cuenta, con quién la reportó)
    comp = {}
    for r in sorted(respuestas, key=lambda x: x["_t"]):
        for c in r.get("competencia") or []:
            u = (c.get("usuario") or "").lower()
            if not u:
                continue
            x = comp.setdefault(u, {"empresas": defaultdict(int), "contenido": defaultdict(int), "por": [], "agencias": set(), "primera": fecha(r)})
            if c.get("empresa"):
                x["empresas"][c["empresa"]] += 1
            if c.get("contenido"):
                x["contenido"][c["contenido"]] += 1
            x["por"].append(r.get("nombre", ""))
            x["agencias"].add(r.get("agencia") or r.get("cadena", ""))
    filas = []
    for u, x in sorted(comp.items(), key=lambda kv: -len(kv[1]["por"])):
        v = verificar(u, cache)
        emp = max(x["empresas"], key=x["empresas"].get) if x["empresas"] else ""
        cont = max(x["contenido"], key=x["contenido"].get) if x["contenido"] else ""
        filas.append(["@" + u, emp, cont, existe_txt(v), v.get("nick", ""), v.get("seguidores"), len(x["por"]),
                      ", ".join(dict.fromkeys(p for p in x["por"] if p)), ", ".join(sorted(a for a in x["agencias"] if a)),
                      x["primera"], "Sí" if u in en_sapo else "No"])
    ws2 = wb.create_sheet("Competencia")
    hoja(ws2, ["Usuario TikTok", "Empresa", "Qué publica", "¿Existe en TikTok?", "Nombre en TikTok", "Seguidores",
               "Veces reportada", "Reportada por", "Agencias que la reportan", "Primer reporte", "¿Ya está en SAPO?"],
         filas, [24, 20, 13, 20, 24, 12, 10, 36, 40, 17, 14], col_alerta=4)
    link(ws2, 1, lambda u: "https://www.tiktok.com/" + u)

    # ---- Avance por agencia (para saber a quién insistir)
    por_ag = defaultdict(set)
    for r in respuestas:
        clave = "MULTINIVEL (sin agencia)" if r.get("cadena") == "Multinivel" else r.get("agencia", "")
        por_ag[clave].add((r.get("nombre") or "").strip().lower() or r["_id"])
    cad = lambda a: next((n for p, n in [("PAGA MENOS", "Pagamenos"), ("MOTOZONE", "Motozone"), ("SAMSUNG", "Samsung"),
                                          ("CRECOS", "Crecos"), ("ORVE", "Orve Hogar"), ("JAPON", "Japón")] if a.startswith(p)), "")
    filas = [[cad(a), a, len(por_ag.get(a, ())), "Sí" if por_ag.get(a) else "Sin respuestas"] for a in agencias]
    m = "MULTINIVEL (sin agencia)"
    filas.append(["Multinivel", m, len(por_ag.get(m, ())), "Sí" if por_ag.get(m) else "Sin respuestas"])
    filas.sort(key=lambda f: (f[2] > 0, f[0], f[1]))
    ws3 = wb.create_sheet("Avance por agencia")
    hoja(ws3, ["Cadena", "Agencia", "Vendedores que respondieron", "¿Respondió?"], filas, [12, 32, 14, 16])
    for row in ws3.iter_rows(min_row=2):
        if row[3].value == "Sin respuestas":
            row[3].fill = rojo

    os.makedirs(CARPETA, exist_ok=True)
    wb.save(EXCEL)
    with open(VALID, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    resumen = {"actualizado": int(time.time() * 1000), "respuestas": len(respuestas),
               "vendedores": len({r.get("tiktok") for r in respuestas if r.get("tiktok")}),
               "competencia": len(comp), "agencias_con_respuesta": sum(1 for a in agencias if por_ag.get(a)),
               "agencias_total": len(agencias)}
    with open(os.path.join(CARPETA, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f)
    log("Encuesta: %d respuestas (%d nuevas) · %d cuentas de competencia" % (len(respuestas), n_nuevas, len(comp)))
    return max(n_nuevas, 1)


if __name__ == "__main__":
    main()
