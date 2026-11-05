"""
Radar de Precios CRESA — escáner de catálogos.

Recorre el catálogo completo de cada tienda y guarda, por tienda, un JSON con
nombre, marca, modelo, precio, precio normal, foto y enlace de cada producto.
Corre en GitHub Actions (ver .github/workflows/precios.yml) y escribe en
$DATA_DIR/precios/ (rama "data"). La página precios/index.html lee esos archivos.

Formato de cada producto (claves cortas para que los archivos pesen poco):
  t  tienda            n  nombre             m  marca
  mo modelo            p  precio actual      l  precio normal (tachado)
  i  foto              u  enlace             c  categoría
  pa precio anterior   cf fecha del último cambio de precio
"""
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
OUT = os.path.join(os.environ.get("DATA_DIR", "data"), "precios")
AHORA = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

TIENDAS = [
    {"id": "crecos",    "nombre": "Crecos",          "grupo": "cresa", "tipo": "vtex",    "host": "www.crecos.com"},
    {"id": "orve",      "nombre": "Orve Hogar",      "grupo": "cresa", "tipo": "vtex",    "host": "www.orvehogar.com"},
    {"id": "japon",     "nombre": "Almacenes Japón", "grupo": "cresa", "tipo": "vtex",    "host": "www.almacenesjapon.com"},
    # Artefacta (Magento) se agrega cuando se confirme cómo leer su catálogo
    {"id": "marcimex",  "nombre": "Marcimex",        "grupo": "comp",  "tipo": "vtex",    "host": "www.marcimex.com"},
    {"id": "comandato", "nombre": "Comandato",       "grupo": "comp",  "tipo": "vtex",    "host": "www.comandato.com"},
]


def log(*a):
    print(*a, flush=True)


def get(url, data=None, headers=None, timeout=40, intentos=3):
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Language": "es-EC,es;q=0.9"}
    h.update(headers or {})
    ultimo = None
    for n in range(intentos):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code in (400, 404):
                return e.code, ""
            time.sleep(2 + n * 3)
        except Exception as e:  # timeouts, conexión
            ultimo = e
            time.sleep(2 + n * 3)
    raise RuntimeError(f"{url[:90]} → {ultimo}")


# ---------------------------------------------------------------- modelo
UNIDADES = re.compile(r"^\d+(?:[.,]\d+)?(L|LT|LTS|LITROS|KG|KGS|LB|LBS|W|V|BTU|HZ|PULG|IN|CM|MM|M|GB|TB|MB|MAH|ML|OZ|K|P|HP|CC|PIES|FT|QT|G|MP|X\d+)$")


def modelo_de(nombre, ref=None):
    """Código de modelo del fabricante: el RefId si lo parece, si no el token más largo del nombre que mezcle letras y números."""
    def limpio(t):
        return re.sub(r"[^A-Z0-9]", "", t.upper())

    def valido(t):
        c = limpio(t)
        return (len(c) >= 5 or (len(c) == 4 and "-" in t)) and re.search(r"[A-Z]", c) and re.search(r"\d", c) and not UNIDADES.match(c) and not re.match(r"^(19|20)\d\d[A-Z]?$", c)

    if ref and valido(ref) and not ref.isdigit():
        return limpio(ref)
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/.]*[A-Za-z0-9]", nombre or "")
    cands = [limpio(t) for t in toks if valido(t)]
    return max(cands, key=len) if cands else None


# ---------------------------------------------------------------- VTEX
def vtex_hojas(host):
    st, b = get(f"https://{host}/api/catalog_system/pub/category/tree/4")
    arbol = json.loads(b)
    hojas = []

    def rec(nodos, ruta):
        for n in nodos:
            r = ruta + [str(n["id"])]
            if n.get("children"):
                rec(n["children"], r)
            hojas.append(r)  # también los padres: atrapa productos colgados directo de ellos
    rec(arbol, [])
    return hojas


def vtex_foto(url):
    # pide la foto en 300x300 para que la página cargue rápido
    return re.sub(r"/arquivos/ids/(\d+)(-\d+-\d+)?/", r"/arquivos/ids/\1-300-300/", url) if url else None


def vtex_producto(t, p):
    mejor = None
    ref = None
    foto = None
    for it in p.get("items", []):
        for s in it.get("sellers", []):
            o = s.get("commertialOffer") or {}
            if (o.get("AvailableQuantity") or 0) > 0 and (o.get("Price") or 0) > 0:
                if not mejor or o["Price"] < mejor["Price"]:
                    mejor = o
                    ref = next((r.get("Value") for r in it.get("referenceId") or [] if r.get("Value")), None)
                    foto = (it.get("images") or [{}])[0].get("imageUrl")
    if not mejor:
        return None
    cats = p.get("categories") or []
    cat = cats[0].strip("/").split("/")[-1] if cats else ""
    lista = mejor.get("ListPrice") or 0
    precio = round(mejor["Price"], 2)
    return {
        "t": t["id"], "n": re.sub(r"\s+", " ", p.get("productName", "")).strip(), "m": p.get("brand") or "",
        "mo": modelo_de(p.get("productName", ""), ref if t["grupo"] == "cresa" else None),
        "p": precio, "l": round(lista, 2) if lista > precio + 0.5 else None,
        "i": vtex_foto(foto), "u": p.get("link") or "", "c": cat, "_id": str(p.get("productId")),
    }


def vtex_categoria(t, ruta):
    fq = urllib.parse.quote("C:/" + "/".join(ruta) + "/")
    out = []
    for desde in range(0, 2500, 50):
        st, b = get(f"https://{t['host']}/api/catalog_system/pub/products/search?fq={fq}&_from={desde}&_to={desde + 49}")
        if st not in (200, 206):
            break
        lote = json.loads(b or "[]")
        out.extend(lote)
        if len(lote) < 50:
            break
    return out


def escanear_vtex(t):
    hojas = vtex_hojas(t["host"])
    log(f"[{t['id']}] {len(hojas)} categorías")
    vistos = {}
    with ThreadPoolExecutor(4) as ex:
        for lote in ex.map(lambda r: vtex_categoria(t, r), hojas):
            for p in lote:
                pid = str(p.get("productId"))
                if pid in vistos:
                    continue
                x = vtex_producto(t, p)
                if x:
                    vistos[pid] = x
    return list(vistos.values())


# ---------------------------------------------------------------- Magento (Artefacta)
MAG_Q = """{ products(filter: {category_uid: {eq: "%s"}}, pageSize: 100, currentPage: %d, sort: {name: ASC}) {
  total_count page_info { total_pages }
  items { uid sku name url_key url_suffix canonical_url
    small_image { url } categories { name }
    price_range { minimum_price { regular_price { value } final_price { value } } }
    stock_status
    ... on SimpleProduct { manufacturer }
  } } }"""


def mag(host, q):
    st, b = get(f"https://{host}/graphql?query=" + urllib.parse.quote(q), headers={"Content-Type": "application/json"})
    d = json.loads(b)
    if d.get("errors") and not d.get("data"):
        raise RuntimeError(str(d["errors"])[:200])
    return d["data"]


def escanear_magento(t):
    host = t["host"]
    cats = mag(host, "{ categories(filters: {}) { items { uid name children { uid name children { uid name } } } } }")
    uids = []

    def rec(items):
        for c in items or []:
            uids.append(c["uid"])
            rec(c.get("children"))
    rec(cats["categories"]["items"])
    log(f"[{t['id']}] {len(uids)} categorías")
    vistos = {}

    def una(uid):
        out = []
        pag, total = 1, 1
        while pag <= total and pag <= 60:
            d = mag(host, MAG_Q % (uid, pag))["products"]
            total = d["page_info"]["total_pages"] or 1
            out.extend(d["items"])
            pag += 1
        return out

    with ThreadPoolExecutor(3) as ex:
        for lote in ex.map(una, uids):
            for p in lote:
                if p["uid"] in vistos or p.get("stock_status") == "OUT_OF_STOCK":
                    continue
                mp = p["price_range"]["minimum_price"]
                precio = mp["final_price"]["value"] or 0
                lista = mp["regular_price"]["value"] or 0
                if precio <= 0:
                    continue
                url = p.get("canonical_url") or f"{p.get('url_key')}{p.get('url_suffix') or ''}"
                if url and not url.startswith("http"):
                    url = f"https://{host}/" + url.lstrip("/")
                foto = (p.get("small_image") or {}).get("url")
                if foto and "placeholder" in foto:
                    foto = None
                vistos[p["uid"]] = {
                    "t": t["id"], "n": re.sub(r"\s+", " ", p["name"]).strip(), "m": str(p.get("manufacturer") or ""),
                    "mo": modelo_de(p["name"]), "p": round(precio, 2), "l": round(lista, 2) if lista > precio + 0.5 else None,
                    "i": foto, "u": url, "c": ((p.get("categories") or [{}])[-1] or {}).get("name", ""), "_id": p["uid"],
                }
    return list(vistos.values())


ESCANERES = {"vtex": escanear_vtex, "magento": escanear_magento}


# ---------------------------------------------------------------- principal
def previo(tid):
    try:
        with open(os.path.join(OUT, f"{tid}.json"), encoding="utf-8") as f:
            return {(p.get("u") or p["n"]): p for p in json.load(f)}
    except Exception:
        return {}


def con_historial(nuevos, antes):
    for p in nuevos:
        a = antes.get(p.get("u") or p["n"])
        if a and abs((a.get("p") or 0) - p["p"]) >= 0.01:
            p["pa"], p["cf"] = a["p"], AHORA
        elif a and a.get("pa") is not None:
            p["pa"], p["cf"] = a["pa"], a.get("cf")
    return nuevos


def correr(t):
    ini = time.time()
    antes = previo(t["id"])
    try:
        prods = ESCANERES[t["tipo"]](t)
        if not prods:
            raise RuntimeError("no devolvió productos")
        prods = con_historial(prods, antes)
        for p in prods:
            p.pop("_id", None)
            for k in [k for k, v in p.items() if v in (None, "")]:
                del p[k]
        prods.sort(key=lambda p: p["n"])
        with open(os.path.join(OUT, f"{t['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(prods, f, ensure_ascii=False, separators=(",", ":"))
        cambios = sum(1 for p in prods if p.get("cf") == AHORA)
        log(f"[{t['id']}] {len(prods)} productos, {cambios} cambios de precio, {time.time() - ini:.0f}s")
        return {"total": len(prods), "actualizado": AHORA, "cambios": cambios}
    except Exception as e:
        log(f"[{t['id']}] ERROR {e}")
        if antes:  # conserva el último escaneo bueno
            viejo = previo_resumen().get(t["id"], {})
            return {"total": len(antes), "actualizado": viejo.get("actualizado"), "aviso": "No respondió en el último escaneo; se muestran los datos anteriores."}
        return {"error": "Esta tienda no respondió al escaneo."}


def previo_resumen():
    try:
        with open(os.path.join(OUT, "resumen.json"), encoding="utf-8") as f:
            return {t["id"]: t for t in json.load(f)["tiendas"]}
    except Exception:
        return {}


def main():
    os.makedirs(OUT, exist_ok=True)
    solo = set(sys.argv[1:])
    tiendas = [t for t in TIENDAS if not solo or t["id"] in solo]
    with ThreadPoolExecutor(len(tiendas)) as ex:
        res = dict(zip([t["id"] for t in tiendas], ex.map(correr, tiendas)))
    viejo = previo_resumen()
    resumen = {"actualizado": AHORA, "tiendas": []}
    for t in TIENDAS:
        r = res.get(t["id"]) or {k: v for k, v in viejo.get(t["id"], {}).items() if k not in ("id", "nombre", "grupo")}
        resumen["tiendas"].append({"id": t["id"], "nombre": t["nombre"], "grupo": t["grupo"], **r})
    with open(os.path.join(OUT, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)
    log(json.dumps(resumen, ensure_ascii=False))


if __name__ == "__main__":
    main()
