"""Diagnóstico 6: cómo cargan productos los sitios con sistema propio."""
import json, re, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


def get(url, accept="text/html,application/json;q=0.9,*/*;q=0.8", headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"}
    h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode("utf-8", "replace"), url
    except Exception as e:
        return 0, f"ERROR {e}", url


def flat(s, n):
    return re.sub(r"\s+", " ", s)[:n]


def dump(nombre, url, extra=()):
    out = [f"\n===== {nombre} {url}"]
    s, b, fin = get(url)
    out.append(f"{s} len={len(b)} final={fin}")
    nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', b, re.S)
    if nd:
        try:
            d = json.loads(nd.group(1))
            out.append("NEXT buildId=" + str(d.get("buildId")) + " page=" + str(d.get("page")) + " query=" + json.dumps(d.get("query"))[:200])
            pp = d.get("props", {}).get("pageProps", {})
            out.append("pageProps keys=" + str(list(pp.keys())[:20]))
            out.append("pageProps=" + json.dumps(pp, ensure_ascii=False)[:1500])
        except Exception as e:
            out.append(f"NEXT parse {e}")
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', b)
    out.append("scripts: " + str([x for x in srcs if not any(k in x for k in ("google", "facebook", "gtm", "hotjar", "clarity", "tiktok"))][:14]))
    eps = set(re.findall(r'["\'](https?://[^"\']*(?:api|graphql|search|catalog|product)[^"\']*)["\']', b, re.I))
    eps |= set(re.findall(r'["\'](/(?:api|wp-json|ajax|graphql|search|productos?|catalog)[^"\' ]{0,120})["\']', b, re.I))
    out.append("endpoints: " + str(sorted(eps)[:25]))
    m = re.search(r"\$\s?\d{1,3}(?:[.,]\d{3})*[.,]\d{2}", b)
    if m:
        out.append("PRICE CTX: " + flat(b[max(0, m.start() - 1200):m.end() + 300], 1500))
    links = re.findall(r'href="([^"]*(?:producto|product|/p/|item|articulo|detalle)[^"]*)"', b, re.I)
    out.append("product links: " + str(list(dict.fromkeys(links))[:8]))
    cats = re.findall(r'href="([^"]*(?:categor|electro|linea-blanca|/c/)[^"]*)"', b, re.I)
    out.append("cat links: " + str(list(dict.fromkeys(cats))[:25]))
    for e in extra:
        s2, b2, f2 = get(e, "application/json,text/html;q=0.8", {"X-Requested-With": "XMLHttpRequest"})
        out.append(f"  EXTRA {s2} {e} -> {flat(b2, 700)}")
    return "\n".join(out)


TAREAS = [
    ("aki", "https://www.aki.com.ec/product-category/electrodomesticos-cocina-electrodomesticos/", ["https://www.aki.com.ec/wp-json/wc/v3/products?per_page=1", "https://www.aki.com.ec/wp-json/", "https://www.aki.com.ec/?wc-ajax=get_refreshed_fragments"]),
    ("megamaxi", "https://www.megamaxi.com/product-category/electrodomesticos/", ["https://www.megamaxi.com/wp-json/"]),
    ("mibodega", "https://mibodega.ec/", ["https://mibodega.ec/9-refrigeracion?from-xhr", "https://mibodega.ec/22-refrigeradora?from-xhr"]),
    ("tia", "https://www.tia.com.ec/electrodomesticos", []),
    ("etafashion", "https://www.etafashion.com/es_EC/HOGAR/c/109", ["https://www.etafashion.com/es_EC/HOGAR/LINEA-BLANCA/c/1090221/results?q=%3Arelevance&page=0", "https://www.etafashion.com/es_EC/search/results?q=refrigeradora&page=0"]),
    ("frecuento", "https://www.frecuento.com/categorias/electrodomesticos/14620/", []),
    ("todohogar", "https://www.todohogar.com/departamentos/electrodomesticos/bfbb988b-a49e-11f0-8898-06bcb14b83b7", []),
    ("point", "https://point.com.ec/", ["https://point.com.ec/search?q=refrigeradora"]),
    ("boyaca", "https://www.boyaca.com/electrodomesticos", ["https://www.boyaca.com/wp-json/"]),
    ("kissu", "https://kissu.com.ec/categoria.php?cat=electrodomesticos", []),
    ("granhogar", "https://granhogar.com.ec/electrodomesticos", ["https://granhogar.com.ec/api/products?category=electrodomesticos"]),
    ("computron", "https://www.computron.com.ec/wp-json/wc/store/v1/products?per_page=2&category=electrodomesticos", []),
]

with ThreadPoolExecutor(6) as ex:
    for r in ex.map(lambda t: dump(*t), TAREAS):
        print(r, flush=True)
