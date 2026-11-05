"""Diagnóstico: cómo responde cada tienda (APIs de catálogo y páginas)."""
import json, re, sys, urllib.request, urllib.error, ssl

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
Q = sys.argv[1] if len(sys.argv) > 1 else "refrigeradora"

def get(url, accept="application/json,text/html;q=0.9,*/*;q=0.8"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), (e.read() or b"").decode("utf-8", "replace")
    except Exception as e:
        return 0, {}, f"ERROR {type(e).__name__}: {e}"

HOSTS = ["www.crecos.com", "www.orvehogar.com", "www.almacenesjapon.com", "www.artefacta.com",
         "www.marcimex.com", "www.comandato.com", "almacenesespana.com.ec", "www.jaher.com.ec"]

def vtex(h):
    s, hd, b = get(f"https://{h}/api/catalog_system/pub/products/search?ft={Q}&_from=0&_to=1")
    print(f"  vtex legacy: {s} resources={hd.get('resources') or hd.get('Resources')} len={len(b)}")
    if s in (200, 206):
        try:
            d = json.loads(b)
            if d:
                p = d[0]; it = p["items"][0]; so = it["sellers"][0]["commertialOffer"]
                print("   ", p.get("productName"), "|", p.get("brand"), "|", p.get("link"))
                print("    img:", it["images"][0]["imageUrl"] if it.get("images") else None)
                print("    price:", so.get("Price"), "list:", so.get("ListPrice"), "avail:", so.get("AvailableQuantity"))
                print("    cats:", p.get("categories", [])[:2], "ref:", it.get("referenceId"), "ean:", it.get("ean"))
        except Exception as e:
            print("    parse", e, b[:200])
    else:
        print("   ", b[:200].replace("\n", " "))
    s, hd, b = get(f"https://{h}/api/io/_v/api/intelligent-search/product_search/?query={Q}&count=2")
    print(f"  vtex IS: {s} len={len(b)} {b[:160]!r}")

def woo(h):
    s, hd, b = get(f"https://{h}/wp-json/wc/store/v1/products?search={Q}&per_page=2")
    print(f"  woo store api: {s} total={hd.get('X-WP-Total') or hd.get('x-wp-total')} {b[:300]!r}")

def home(h):
    s, hd, b = get(f"https://{h}/", accept="text/html")
    marks = [m for m in ["vtex", "__NEXT_DATA__", "shopify", "woocommerce", "wp-content", "prestashop", "magento", "faststore", "vtexassets", "jumpseller", "bigcommerce", "wix"] if m in b.lower()]
    print(f"  home: {s} len={len(b)} server={hd.get('Server') or hd.get('server')} marks={marks}")
    forms = re.findall(r'<form[^>]*>.{0,400}?</form>', b, re.S | re.I)
    for f in forms[:3]:
        if "search" in f.lower() or "busc" in f.lower() or 'name="s"' in f or "q" in f:
            print("   form:", re.sub(r"\s+", " ", f)[:300])
    return b

for h in HOSTS:
    print(f"\n===== {h}")
    home(h)
    vtex(h)
    if h in ("almacenesespana.com.ec", "www.jaher.com.ec"):
        woo(h)
        for path in [f"/?s={Q}&post_type=product", f"/busqueda?search_query={Q}", f"/index.php?controller=search&s={Q}", f"/buscar?q={Q}", f"/search?q={Q}"]:
            s, hd, b = get(f"https://{h}{path}", accept="text/html")
            prices = re.findall(r"\$\s?\d[\d.,]*", b)
            print(f"  {path}: {s} len={len(b)} precios={prices[:5]}")
    if h == "www.artefacta.com":
        for path in [f"/s?q={Q}", f"/{Q}?_q={Q}&map=ft", f"/api/graphql"]:
            s, hd, b = get(f"https://{h}{path}", accept="text/html")
            print(f"  {path}: {s} len={len(b)} precios={re.findall(r'[$]\s?[0-9][0-9.,]*', b)[:5]}")
