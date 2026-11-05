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
import gzip, html, json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
OUT = os.path.join(os.environ.get("DATA_DIR", "data"), "precios")
AHORA = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

TIENDAS = [
    {"id": "crecos",    "nombre": "Crecos",          "grupo": "cresa", "tipo": "vtex",    "host": "www.crecos.com"},
    {"id": "orve",      "nombre": "Orve Hogar",      "grupo": "cresa", "tipo": "vtex",    "host": "www.orvehogar.com"},
    {"id": "japon",     "nombre": "Almacenes Japón", "grupo": "cresa", "tipo": "vtex",    "host": "www.almacenesjapon.com"},
    {"id": "artefacta", "nombre": "Artefacta",       "grupo": "comp",  "tipo": "magento", "host": "www.artefacta.com", "store": 16},
    {"id": "marcimex",  "nombre": "Marcimex",        "grupo": "comp",  "tipo": "vtex",    "host": "www.marcimex.com"},
    {"id": "comandato", "nombre": "Comandato",       "grupo": "comp",  "tipo": "vtex",    "host": "www.comandato.com"},
    # --- sitios agregados en COTI ---
    {"id": "pycca",     "nombre": "Pycca",           "grupo": "comp",  "tipo": "vtex",    "host": "www.pycca.com", "cats": r"electro|linea blanca|l[ií]nea blanca|climatiza|refrigera|lavad|cocina"},
    {"id": "estuardo",  "nombre": "Estuardo Sánchez","grupo": "comp",  "tipo": "vtex",    "host": "www.estuardosanchez.com", "cats": r"electro|linea blanca|l[ií]nea blanca|climatiza|refrigera|lavad|cocina|tv|televis|audio"},
    {"id": "unity",     "nombre": "Unity Stores",    "grupo": "comp",  "tipo": "vtex",    "host": "www.unitystores.com"},
    {"id": "bodeguita", "nombre": "Bodeguita del Ahorro", "grupo": "comp", "tipo": "woo", "host": "bodeguitadelahorro.com"},
    {"id": "bestpc",    "nombre": "BestPC",          "grupo": "comp",  "tipo": "woo",     "host": "bestpc.ec"},
    {"id": "computron", "nombre": "Computron",       "grupo": "comp",  "tipo": "woo",     "host": "www.computron.com.ec"},
    {"id": "eljuri",    "nombre": "El Juri",         "grupo": "comp",  "tipo": "presta",  "host": "eljuri.store", "rutas": ["3-electrodomesticos"]},
    {"id": "mibodega",  "nombre": "Mi Bodega",       "grupo": "comp",  "tipo": "presta",  "host": "mibodega.ec", "rutas": ["2-inicio"]},
    {"id": "tia",       "nombre": "Tía",             "grupo": "comp",  "tipo": "magehtml","host": "www.tia.com.ec", "rutas": ["electrodomesticos"]},
    {"id": "coral",     "nombre": "Coral Hipermercados", "grupo": "comp", "tipo": "magehtml", "host": "coralhipermercados.com", "rutas": ["electrodomesticos.html"]},
    {"id": "etafashion","nombre": "Etafashion",      "grupo": "comp",  "tipo": "hybris",  "host": "www.etafashion.com", "rutas": ["es_EC/HOGAR/c/109"], "solo": r"/(LINEA-BLANCA|ELECTRO|TECNOLOG|CLIMATIZ|AUDIO|TV)"},
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
                raw = r.read()
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return r.status, raw.decode("utf-8", "replace")
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

    if re.match(r"\s*combo\b", nombre or "", re.I):  # un combo no es el mismo producto que su componente
        return None
    if ref and valido(ref) and not ref.isdigit():
        return limpio(ref)
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/.]*[A-Za-z0-9]", nombre or "")
    cands = [limpio(t) for t in toks if valido(t)]
    return max(cands, key=len) if cands else None


# ---------------------------------------------------------------- VTEX
def vtex_hojas(t):
    st, b = get(f"https://{t['host']}/api/catalog_system/pub/category/tree/4")
    arbol = json.loads(b)
    filtro = re.compile(t["cats"], re.I) if t.get("cats") else None
    hojas = []

    def rec(nodos, ruta, nombres, dentro):
        for n in nodos:
            r = ruta + [str(n["id"])]
            nom = nombres + [n.get("name", "")]
            ok = dentro or not filtro or bool(filtro.search(n.get("name", "")))
            if n.get("children"):
                rec(n["children"], r, nom, ok)
            if ok:
                hojas.append(r)  # también los padres: atrapa productos colgados directo de ellos
    rec(arbol, [], [], False)
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
    hojas = vtex_hojas(t)
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
# Su GraphQL está apagado; el listado público "products-render-info" sí responde.
MAG_PAG = 200


def mag_pagina(host, store, pag):
    q = (f"searchCriteria[pageSize]={MAG_PAG}&searchCriteria[currentPage]={pag}"
         "&searchCriteria[filterGroups][0][filters][0][field]=status"
         "&searchCriteria[filterGroups][0][filters][0][value]=1"
         f"&storeId={store}&currencyCode=USD")
    st, b = get(f"https://{host}/rest/V1/products-render-info?{q}", timeout=90)
    return json.loads(b)


def escanear_magento(t):
    host, store = t["host"], t.get("store", 16)
    d = mag_pagina(host, store, 1)
    if d.get("items"):
        ej = dict(d["items"][0]); ej.pop("price_info", None)
        log(f"[{t['id']}] campos: {sorted(ej.keys())} ejemplo: {json.dumps({k: ej[k] for k in ej if k in ('name','url','images','is_salable','type','id')}, ensure_ascii=False)[:700]}")
    lotes = [d.get("items") or []]
    pag = 2
    while len(lotes[-1]) >= MAG_PAG and pag < 600:  # sin total: avanza de 4 en 4 páginas hasta que una venga incompleta
        with ThreadPoolExecutor(4) as ex:
            nuevas = list(ex.map(lambda n: mag_pagina(host, store, n).get("items") or [], range(pag, pag + 4)))
        lotes.extend(nuevas)
        pag += 4
        if any(len(x) < MAG_PAG for x in nuevas):
            break
    log(f"[{t['id']}] {sum(len(x) for x in lotes)} registros en {pag - 1} páginas")
    vistos = {}
    for lote in lotes:
        for p in lote:
            pid = str(p.get("id"))
            if pid in vistos or str(p.get("is_salable", "1")) in ("0", "False", "false"):
                continue
            if p.get("type") in ("warranty", "virtual", "giftcard"):
                continue
            pi = p.get("price_info") or {}
            precio = pi.get("final_price") or pi.get("minimal_price") or 0
            lista = pi.get("regular_price") or pi.get("max_regular_price") or 0
            if precio < 1:
                continue
            fotos = p.get("images") or []
            foto = next((f.get("url") for f in fotos if f.get("url") and "placeholder" not in f.get("url")), None)
            nombre = re.sub(r"\s+", " ", p.get("name") or "").strip()
            if not nombre:
                continue
            vistos[pid] = {
                "t": t["id"], "n": nombre, "m": "", "mo": modelo_de(nombre),
                "p": round(precio, 2), "l": round(lista, 2) if lista > precio + 0.5 else None,
                "i": foto, "u": p.get("url") or "", "c": "", "_id": pid,
            }
    return list(vistos.values())


# ---------------------------------------------------------------- WooCommerce (Store API pública)
def escanear_woo(t):
    vistos, pag, total = {}, 1, 1
    while pag <= total and pag <= 200:
        url = f"https://{t['host']}/wp-json/wc/store/v1/products?per_page=100&page={pag}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("X-WP-TotalPages") or r.headers.get("x-wp-totalpages") or 1)
            lote = json.loads(r.read().decode("utf-8", "replace"))
        for p in lote:
            if not p.get("is_in_stock", True) or not p.get("is_purchasable", True):
                continue
            pr = p.get("prices") or {}
            dec = 10 ** int(pr.get("currency_minor_unit") or 0)
            try:
                precio = int(pr.get("price") or 0) / dec
                lista = int(pr.get("regular_price") or 0) / dec
            except ValueError:
                continue
            if precio < 1:
                continue
            nombre = html.unescape(re.sub(r"<[^>]+>", "", p.get("name") or "")).strip()
            img = (p.get("images") or [{}])[0]
            marca = ", ".join(b.get("name", "") for b in (p.get("brands") or []))
            vistos[p["id"]] = {"t": t["id"], "n": nombre, "m": html.unescape(marca), "mo": modelo_de(nombre + " " + (p.get("sku") or "")),
                               "p": round(precio, 2), "l": round(lista, 2) if lista > precio + 0.5 else None,
                               "i": img.get("thumbnail") or img.get("src"), "u": p.get("permalink") or "",
                               "c": html.unescape((p.get("categories") or [{}])[0].get("name", ""))}
        pag += 1
    log(f"[{t['id']}] {total} páginas")
    return list(vistos.values())


# ---------------------------------------------------------------- PrestaShop (listado con ?from-xhr)
def escanear_presta(t):
    vistos = {}
    for ruta in t["rutas"]:
        pag, total = 1, 1
        while pag <= total and pag <= 300:
            st, b = get(f"https://{t['host']}/{ruta}?page={pag}&resultsPerPage=48&from-xhr", headers={"X-Requested-With": "XMLHttpRequest"})
            d = json.loads(b or "{}")
            total = (d.get("pagination") or {}).get("pages_count") or 1
            for p in d.get("products") or []:
                if str(p.get("availability")) == "unavailable" and not p.get("quantity"):
                    continue
                precio = float(p.get("price_amount") or 0)
                lista = float(p.get("regular_price_amount") or 0)
                if precio < 1:
                    continue
                cover = p.get("cover") or {}
                foto = ((cover.get("bySize") or {}).get("home_default") or {}).get("url") or (cover.get("medium") or {}).get("url") or (cover.get("large") or {}).get("url")
                nombre = html.unescape(p.get("name") or "").strip()
                vistos[p.get("id_product")] = {"t": t["id"], "n": nombre, "m": p.get("manufacturer_name") or "",
                                               "mo": modelo_de(nombre + " " + (p.get("reference") or "")),
                                               "p": round(precio, 2), "l": round(lista, 2) if lista > precio + 0.5 else None,
                                               "i": foto, "u": p.get("url") or "", "c": p.get("category_name") or ""}
            pag += 1
        log(f"[{t['id']}] {ruta}: {total} páginas")
    return list(vistos.values())


# ---------------------------------------------------------------- Magento leyendo el listado HTML (Tía, Coral)
def num(txt):
    txt = re.sub(r"[^\d.,]", "", txt or "")
    if not txt:
        return None
    if txt.rfind(",") > txt.rfind("."):
        txt = txt.replace(".", "").replace(",", ".")
    else:
        txt = txt.replace(",", "")
    try:
        return float(txt)
    except ValueError:
        return None


def escanear_magehtml(t):
    vistos = {}
    for ruta in t["rutas"]:
        primero = None
        for pag in range(1, 200):
            st, b = get(f"https://{t['host']}/{ruta}?p={pag}&product_list_limit=36", headers={"Accept": "text/html"})
            bloques = re.split(r'<li[^>]*class="[^"]*\bproduct-item\b[^"]*"', b)[1:]
            if not bloques:
                break
            enlaces = re.findall(r'class="product-item-link"\s+href="([^"]+)"', b)
            if enlaces and enlaces[0] == primero:  # Magento repite la última página si se pide una de más
                break
            primero = enlaces[0] if enlaces else None
            for bl in bloques:
                bl = bl[:20000]
                m = re.search(r'class="product-item-link"\s+href="([^"]+)"[^>]*>\s*([^<]+)<', bl)
                if not m:
                    continue
                url, nombre = m.group(1), html.unescape(m.group(2)).strip()
                fp = re.search(r'data-price-type="finalPrice"[^>]*>\s*<span class="price">([^<]+)<', bl)
                op = re.search(r'data-price-type="oldPrice"[^>]*>\s*<span class="price">([^<]+)<', bl)
                precio = num(fp.group(1)) if fp else None
                if not precio or precio < 1:
                    continue
                lista = num(op.group(1)) if op else None
                img = re.search(r'class="product-image-photo[^"]*"[^>]*?src="([^"]+)"', bl) or re.search(r'<img[^>]+src="([^"]+/media/catalog/product/[^"]+)"', bl)
                marca = re.search(r'product-item-brand"><strong><span>Marca</span>\s*([^<]+)<', bl)
                vistos[url] = {"t": t["id"], "n": nombre, "m": (marca.group(1).strip() if marca else ""), "mo": modelo_de(nombre),
                               "p": round(precio, 2), "l": round(lista, 2) if lista and lista > precio + 0.5 else None,
                               "i": html.unescape(img.group(1)) if img else None, "u": url, "c": ""}
        log(f"[{t['id']}] {ruta}: {pag - 1} páginas")
    return list(vistos.values())


# ---------------------------------------------------------------- SAP Hybris (Etafashion)
def precio_hybris(x):
    if isinstance(x, dict):
        return x.get("value")
    return x


def escanear_hybris(t):
    vistos, ejemplo = {}, False
    solo = re.compile(t["solo"], re.I) if t.get("solo") else None
    for ruta in t["rutas"]:
        pag, total = 0, 1
        while pag < total and pag < 200:
            st, b = get(f"https://{t['host']}/{ruta}/results?q=%3Arelevance&page={pag}", headers={"X-Requested-With": "XMLHttpRequest"})
            d = json.loads(b or "{}")
            total = (d.get("pagination") or {}).get("numberOfPages") or 1
            for p in d.get("results") or []:
                if not ejemplo:
                    ejemplo = True
                    log(f"[{t['id']}] campos: {sorted(p.keys())} precio: {json.dumps({k: p.get(k) for k in p if 'rice' in k.lower() or 'discount' in k.lower()}, ensure_ascii=False)[:800]} imagenes: {json.dumps(p.get('images'), ensure_ascii=False)[:300]}")
                url = p.get("url") or ""
                if solo and not solo.search(url):
                    continue
                if ((p.get("stock") or {}).get("stockLevelStatus") or {}).get("code") == "outOfStock":
                    continue
                cands = [precio_hybris(p.get(k)) for k in ("discountPrice", "priceDiscount", "price") if p.get(k) is not None]
                cands = [float(c) for c in cands if isinstance(c, (int, float)) and c > 0]
                if not cands:
                    continue
                precio = min(cands)
                lista = max(cands)
                foto = None
                for im in p.get("images") or []:
                    if im.get("format") in ("product", "thumbnail", "zoom") or not foto:
                        foto = im.get("url")
                if foto and foto.startswith("/"):
                    foto = f"https://{t['host']}{foto}"
                nombre = html.unescape(p.get("name") or "").strip()
                vistos[p.get("code")] = {"t": t["id"], "n": nombre, "m": (p.get("manufacturer") or ""), "mo": modelo_de(nombre),
                                         "p": round(precio, 2), "l": round(lista, 2) if lista > precio + 0.5 else None,
                                         "i": foto, "u": f"https://{t['host']}/es_EC{url}" if url.startswith("/") else url, "c": ""}
            pag += 1
        log(f"[{t['id']}] {ruta}: {total} páginas")
    return list(vistos.values())


ESCANERES = {"vtex": escanear_vtex, "magento": escanear_magento, "woo": escanear_woo, "presta": escanear_presta, "magehtml": escanear_magehtml, "hybris": escanear_hybris}


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
