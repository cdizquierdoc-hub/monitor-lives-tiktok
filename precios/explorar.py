"""Diagnóstico 2: Artefacta (Magento), Jaher y Almacenes España."""
import json, re, sys, urllib.request, urllib.error, urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
Q = sys.argv[1] if len(sys.argv) > 1 else "refrigeradora"

def get(url, accept="application/json,text/html;q=0.9,*/*;q=0.8", data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), (e.read() or b"").decode("utf-8", "replace"), url
    except Exception as e:
        return 0, {}, f"ERROR {type(e).__name__}: {e}", url

print("===== ARTEFACTA")
gql = '{ products(search: "%s", pageSize: 3, currentPage: 1) { total_count page_info { total_pages } items { sku name url_key url_suffix manufacturer small_image { url } price_range { minimum_price { regular_price { value } final_price { value } } } } } }' % Q
for url in ["https://www.artefacta.com/graphql?query=" + urllib.parse.quote(gql)]:
    s, hd, b, _ = get(url, headers={"Store": "default"})
    print("graphql GET:", s, b[:1500])
s, hd, b, _ = get("https://www.artefacta.com/graphql", data=json.dumps({"query": gql}).encode(), headers={"Content-Type": "application/json"})
print("graphql POST:", s, b[:600])
gql2 = '{ products(filter: {price: {from: "1"}}, pageSize: 2, currentPage: 1) { total_count items { sku name } } }'
s, hd, b, _ = get("https://www.artefacta.com/graphql?query=" + urllib.parse.quote(gql2))
print("graphql all:", s, b[:400])
s, hd, b, u = get(f"https://www.artefacta.com/catalogsearch/result/?q={Q}", accept="text/html")
print("catalogsearch:", s, len(b), u)
print("  data-price-amount:", re.findall(r'data-price-amount="([\d.]+)"', b)[:8])
print("  product names:", [re.sub(r"\s+"," ",x).strip() for x in re.findall(r'class="product-item-link"[^>]*>(.*?)</a>', b, re.S)[:5]])
print("  imgs:", re.findall(r'class="product-image-photo[^"]*"[^>]*src="([^"]+)"', b)[:3])
print("  amount/toolbar:", re.findall(r'toolbar-number">(\d+)<', b)[:4])
s, hd, b, u = get("https://www.artefacta.com/sitemap.xml", accept="*/*")
print("sitemap:", s, len(b), b[:300])

print("\n===== JAHER")
s, hd, b, u = get("https://www.jaher.com.ec/", accept="text/html")
print("home:", s, len(b), u)
links = sorted(set(re.findall(r'href="([^"#]+)"', b)))
print("links:", links[:80])
print("scripts:", re.findall(r'<script[^>]+src="([^"]+)"', b)[:15])
print("text:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b))[:1200])
for path in ["/sitemap.xml", "/robots.txt", "/productos/", "/catalogo/", "/tienda/", "/api/productos/", "/api/products/"]:
    s, hd, b, u = get("https://www.jaher.com.ec" + path, accept="*/*")
    print(f" {path}: {s} {len(b)} {re.sub(chr(10),' ',b[:200])!r}")

print("\n===== ALMACENES ESPAÑA")
for url in ["https://almacenesespana.com.ec/", "http://almacenesespana.com.ec/", "https://www.almacenesespana.com.ec/", "https://almacenesespana.ec/"]:
    s, hd, b, u = get(url, accept="text/html", timeout=40)
    print(url, s, len(b), u, b[:120].replace("\n", " "))
