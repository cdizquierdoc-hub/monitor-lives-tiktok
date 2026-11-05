"""Diagnóstico de sitios nuevos: plataforma y APIs de catálogo que responden."""
import json, re, sys, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
SITIOS = [
    ("deprati", "https://www.deprati.com.ec/electrodomesticos/c/11"),
    ("frecuento", "https://www.frecuento.com/categorias/electrodomesticos/14620/"),
    ("point", "https://point.com.ec/"),
    ("eljuri", "https://eljuri.store/3-electrodomesticos"),
    ("boyaca", "https://www.boyaca.com/electrodomesticos"),
    ("estuardo", "https://www.estuardosanchez.com/electro/electrohogar"),
    ("kissu", "https://kissu.com.ec/categoria.php?cat=electrodomesticos"),
    ("todohogar", "https://www.todohogar.com/departamentos/electrodomesticos/bfbb988b-a49e-11f0-8898-06bcb14b83b7"),
    ("tia", "https://www.tia.com.ec/electrodomesticos"),
    ("computron", "https://www.computron.com.ec/producto-categoria/electrodomesticos/"),
    ("aki", "https://www.aki.com.ec/product-category/electrodomesticos-cocina-electrodomesticos/"),
    ("pycca", "https://www.pycca.com/electrohogar/electrodomesticos-menores"),
    ("bodeguita", "https://bodeguitadelahorro.com/tienda/"),
    ("megamaxi", "https://www.megamaxi.com/product-category/electrodomesticos/"),
    ("coral", "https://coralhipermercados.com/electrodomesticos/electrodomestico-mayor.html"),
    ("bestpc", "https://bestpc.ec/"),
    ("granhogar", "https://granhogar.com.ec/electrodomesticos"),
    ("unity", "https://www.unitystores.com/electrodomesticos"),
    ("etafashion", "https://www.etafashion.com/es_EC/HOGAR/LINEA-BLANCA/REFRIGERADORAS/c/10902213999"),
    ("laganga", "https://laganga.com/"),
    ("mibodega", "https://mibodega.ec/"),
]
MARCAS = ["vtex", "wp-content", "woocommerce", "shopify", "prestashop", "mage/", "magento", "/_ui/", "hybris", "demandware",
          "__next_data__", "__nuxt", "wix", "jumpseller", "bsale", "odoo", "route=product", "opencart", "squarespace",
          "vue", "react", "angular", "graphql", "algolia", "salesforce", "occ/v2", "@type\":\"product", "\"@type\": \"product"]


def get(url, accept="application/json,text/html;q=0.9,*/*;q=0.8", headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"}
    h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode("utf-8", "replace"), url, dict(e.headers or {})
    except Exception as e:
        return 0, f"ERROR {type(e).__name__}: {e}", url, {}


def js(b):
    try:
        return json.loads(b)
    except Exception:
        return None


def probar(sitio):
    sid, url = sitio
    u = urllib.parse.urlparse(url)
    base = f"{u.scheme}://{u.netloc}"
    out = [f"\n===== {sid} {url}"]
    s, b, fin, hd = get(url, "text/html")
    low = b.lower()
    out.append(f"cat: {s} len={len(b)} final={fin} server={hd.get('Server') or hd.get('server')} powered={hd.get('X-Powered-By') or hd.get('x-powered-by')}")
    out.append("marcas: " + str([m for m in MARCAS if m in low]))
    out.append("precios html: " + str(re.findall(r"\$\s?[0-9][0-9.,]{1,9}", b)[:6]))
    lds = [x for x in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', b, re.S) if "roduct" in x]
    if lds:
        out.append("LD product: " + re.sub(r"\s+", " ", lds[0])[:300])
    gen = re.findall(r'<meta name="generator" content="([^"]+)"', b)
    if gen:
        out.append(f"generator: {gen}")
    pruebas = [
        ("vtex", f"{base}/api/catalog_system/pub/products/search?ft=refrigeradora&_from=0&_to=0"),
        ("woo", f"{base}/wp-json/wc/store/v1/products?per_page=1&search=refrigeradora"),
        ("shopify", f"{base}/products.json?limit=1"),
        ("magento", f"{base}/rest/V1/products-render-info?searchCriteria[pageSize]=1&storeId=1&currencyCode=USD"),
        ("presta", url + ("&" if "?" in url else "?") + "from-xhr"),
        ("hybris", url.rstrip("/") + "/results?q=%3Arelevance&page=0"),
    ]
    for nombre, pu in pruebas:
        hdr = {"X-Requested-With": "XMLHttpRequest"} if nombre in ("presta", "hybris") else None
        s2, b2, _, hd2 = get(pu, "application/json", hdr)
        d = js(b2)
        ok = d is not None and s2 == 200
        resumen = ""
        if ok:
            if isinstance(d, list):
                resumen = f"lista[{len(d)}] " + json.dumps(d[0], ensure_ascii=False)[:250] if d else "lista vacía"
            else:
                resumen = f"claves={list(d.keys())[:12]} " + json.dumps(d, ensure_ascii=False)[:250]
        out.append(f"  {nombre}: {s2} {'JSON ' + resumen if ok else (b2[:90].replace(chr(10), ' ') if s2 else b2[:90])}")
    return "\n".join(out)


with ThreadPoolExecutor(8) as ex:
    for r in ex.map(probar, SITIOS):
        print(r, flush=True)
