"""Diagnóstico 7: detalles finales de sitios con sistema propio."""
import json, re, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


def get(url, accept="text/html,application/json;q=0.9,*/*;q=0.8", headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"}
    h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode("utf-8", "replace")
    except Exception as e:
        return 0, f"ERROR {e}"


def f(s, n=900):
    return re.sub(r"\s+", " ", s)[:n]


def ctx(b, pat, antes=700, despues=900):
    m = re.search(pat, b)
    return f(b[max(0, m.start() - antes):m.end() + despues], antes + despues) if m else "(no aparece)"


def t_todohogar():
    o = []
    for u in ["https://www.todohogar.com/api/catalog/export?page=1", "https://www.todohogar.com/api/v1/products?categoryId=bfbb988b-a49e-11f0-8898-06bcb14b83b7&page=1",
              "https://www.todohogar.com/api/v1/products"]:
        s, b = get(u, "application/json"); o.append(f"{s} {u} -> {f(b, 900)}")
    s, b = get("https://www.todohogar.com/_next/static/chunks/pages/departamentos/%5Bcategory%5D/%5Bid%5D-9cdb9e619bd2c986.js", "*/*")
    o.append("chunk urls: " + str(sorted(set(re.findall(r'["`](/api/[^"`]{0,120}|https://[^"`]*api[^"`]{0,120})["`]', b)))[:20]))
    return "todohogar\n" + "\n".join(o)


def t_frecuento():
    o = []
    s, b = get("https://www.frecuento.com/categorias/electrodomesticos/14620/")
    chunks = re.findall(r'src="(/_next/static/chunks/[^"]+)"', b)
    urls = set()
    for c in chunks:
        s2, b2 = get("https://www.frecuento.com" + c, "*/*")
        urls |= set(re.findall(r'["`](https?://[a-z0-9.\-]+(?:/[^"`\s]{0,80})?)["`]', b2))
        urls |= set(x for x in re.findall(r'["`](/[a-z0-9_\-/]*(?:product|categor|search|api)[a-z0-9_\-/]*)["`]', b2, re.I))
    o.append("urls: " + str(sorted(u for u in urls if not any(k in u for k in ("google", "facebook", "w3.org", "reactjs", "nextjs", "cookieyes")))[:40]))
    return "frecuento\n" + "\n".join(o)


def t_point():
    s, b = get("https://point.com.ec/")
    o = ["links: " + str(list(dict.fromkeys(re.findall(r'href="(/[^"]+)"', b)))[:40])]
    o.append("price ctx: " + ctx(b, r"\$\s?\d+"))
    chunks = re.findall(r'src="(/_next/static/chunks/[^"]+)"', b)
    urls = set()
    for c in chunks[:25]:
        s2, b2 = get("https://point.com.ec" + c, "*/*")
        urls |= set(re.findall(r'["`](https?://[a-z0-9.\-]+[^"`\s]{0,80})["`]', b2))
    o.append("urls: " + str(sorted(u for u in urls if not any(k in u for k in ("google", "facebook", "w3.org", "react", "nextjs")))[:30]))
    return "point\n" + "\n".join(o)


def t_html(nombre, url, pat):
    s, b = get(url)
    return f"{nombre} {s} len={len(b)}\nctx: " + ctx(b, pat, 900, 1500)


def t_granhogar():
    s, b = get("https://granhogar.com.ec/bundles/js/app_lista.js?version=1.b.27", "*/*")
    o = [f"js {s} len={len(b)}", "urls: " + str(sorted(set(re.findall(r'["`\'](/[a-zA-Z0-9_\-/]{3,80})["`\']', b)))[:50])]
    o.append("fetch ctx: " + ctx(b, r"(ajax|fetch)\(", 200, 600))
    s, b = get("https://granhogar.com.ec/electrodomesticos")
    o.append("html prod ctx: " + ctx(b, r'class="[^"]*(?:product|card)[^"]*"', 200, 1200))
    return "granhogar\n" + "\n".join(o)


def t_eta():
    s, b = get("https://www.etafashion.com/es_EC/HOGAR/c/109/results?q=%3Arelevance&page=0", "application/json", {"X-Requested-With": "XMLHttpRequest"})
    o = [f"HOGAR results {s} {f(b, 300)}"]
    try:
        d = json.loads(b); o.append("pagination: " + json.dumps(d.get("pagination"))); o.append("item: " + json.dumps(d["results"][0], ensure_ascii=False)[:1500])
    except Exception as e:
        o.append(f"parse {e}")
    return "etafashion\n" + "\n".join(o)


def t_mibodega():
    o = []
    for c in ["2-inicio", "2-home", "3-electrodomesticos", "9-refrigeracion"]:
        s, b = get(f"https://mibodega.ec/{c}?from-xhr", "application/json", {"X-Requested-With": "XMLHttpRequest"})
        try:
            d = json.loads(b); o.append(f"{c}: total={d.get('pagination', {}).get('total_items')} item={json.dumps((d.get('products') or [{}])[0], ensure_ascii=False)[:700]}")
        except Exception:
            o.append(f"{c}: {s} {f(b, 120)}")
    s, b = get("https://eljuri.store/3-electrodomesticos?from-xhr", "application/json", {"X-Requested-With": "XMLHttpRequest"})
    d = json.loads(b); o.append(f"eljuri total={d.get('pagination', {}).get('total_items')} pages={d.get('pagination', {}).get('pages_count')}")
    return "prestashop\n" + "\n".join(o)


def t_tia_coral():
    o = []
    for n, u in [("tia", "https://www.tia.com.ec/electrodomesticos?p=2&product_list_limit=36"), ("coral", "https://coralhipermercados.com/electrodomesticos.html?p=1&product_list_limit=36")]:
        s, b = get(u)
        items = re.findall(r'<li class="item product product-item"', b)
        o.append(f"{n} {s} items={len(items)} toolbar={re.findall(r'toolbar-number\">(\d+)<', b)[:3]} prices={re.findall(r'class=\"price\">([^<]+)<', b)[:6]}")
        o.append(" img: " + str(re.findall(r'class="product-image-photo[^"]*"[^>]*src="([^"]+)"', b)[:2]))
    return "magento html\n" + "\n".join(o)


TAREAS = [t_todohogar, t_frecuento, t_point, t_granhogar, t_eta, t_mibodega, t_tia_coral,
          lambda: t_html("boyaca", "https://www.boyaca.com/electrodomesticos", r"\$\s?\d+[.,]\d\d"),
          lambda: t_html("boyaca-precio", "https://www.boyaca.com/electrodomesticos", r"(?i)precio"),
          lambda: t_html("kissu", "https://kissu.com.ec/categoria.php?cat=electrodomesticos", r"producto\.php\?ver="),
          lambda: t_html("aki", "https://www.aki.com.ec/product-category/electrodomesticos-cocina-electrodomesticos/", r"/producto/"),
          lambda: t_html("megamaxi-precio", "https://www.megamaxi.com/product-category/electrodomesticos/", r"(?i)woocommerce-Price-amount|precio|\bPVP\b")]

with ThreadPoolExecutor(6) as ex:
    for r in ex.map(lambda t: t(), TAREAS):
        print("\n=====", r, flush=True)
