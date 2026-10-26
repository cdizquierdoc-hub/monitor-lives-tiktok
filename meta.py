#!/usr/bin/env python3
"""
Instagram vía la API oficial de Meta (Instagram Graph API). Gratis, sin bloqueos.

Necesita el secreto IG_TOKEN (token de usuario del sistema o de usuario de larga duración) con permisos:
  instagram_basic, instagram_manage_insights, pages_show_list, pages_read_engagement, business_management

Qué se puede obtener:
  - Cuentas propias (las que administra el token): seguidores, publicaciones, likes, comentarios,
    views, guardados, compartidos y si están EN VIVO.
  - Otras cuentas de empresa o creador (vendedores, competencia), con Business Discovery: seguidores,
    publicaciones, likes y comentarios. Instagram no entrega views, guardados, compartidos ni lives de cuentas ajenas.
  - Cuentas personales: Instagram no entrega nada por la API.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

VERSION = "v21.0"
TOKEN = os.environ.get("IG_TOKEN", "").strip()


class MetaError(Exception):
    pass


def disponible():
    return bool(TOKEN)


def api(ruta, **params):
    params["access_token"] = TOKEN
    url = "https://graph.facebook.com/%s/%s?%s" % (VERSION, ruta.lstrip("/"), urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", {})
            msg = err.get("error_user_msg") or err.get("message") or str(e)
        except Exception:
            msg = str(e)
        raise MetaError(msg[:200])


_propias = None


def cuentas_propias():
    """{usuario_instagram: ig_user_id} de las cuentas de empresa que administra el token."""
    global _propias
    if _propias is not None:
        return _propias
    _propias = {}
    if not TOKEN:
        return _propias
    ruta, params = "me/accounts", {"fields": "instagram_business_account{id,username}", "limit": "100"}
    while ruta:
        r = api(ruta, **params)
        for p in r.get("data", []):
            ig = p.get("instagram_business_account")
            if ig and ig.get("username"):
                _propias[ig["username"].lower()] = ig["id"]
        nxt = (r.get("paging") or {}).get("next")
        if not nxt:
            break
        q = urllib.parse.urlparse(nxt)
        ruta = q.path.split("/", 2)[-1]
        params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items() if k != "access_token"}
    # también cuentas de Instagram asignadas directamente al usuario del sistema
    try:
        r = api("me", fields="instagram_accounts{id,username}")
        for ig in (r.get("instagram_accounts") or {}).get("data", []):
            if ig.get("username"):
                _propias.setdefault(ig["username"].lower(), ig["id"])
    except MetaError:
        pass
    return _propias


def en_vivo(ig_id):
    """True/False si una cuenta propia está transmitiendo en vivo."""
    r = api("%s/live_media" % ig_id, fields="id,media_product_type,timestamp")
    vivos = r.get("data") or []
    return (vivos[0].get("id") if vivos else None)


CAMPOS_MEDIA = "id,caption,like_count,comments_count,timestamp,media_type,media_product_type,permalink"


def perfil_propio(ig_id, limite=25):
    r = api(ig_id, fields="username,name,followers_count,follows_count,media_count,media.limit(%d){%s}" % (limite, CAMPOS_MEDIA))
    media = (r.get("media") or {}).get("data", [])
    for m in media:
        m.update(insights_media(m))
    return r, media


def insights_media(m):
    """views, guardados, compartidos y alcance de una publicación propia (si Instagram los entrega)."""
    out = {}
    metricas = "views,saved,shares,reach"
    try:
        r = api("%s/insights" % m["id"], metric=metricas)
    except MetaError:
        try:
            r = api("%s/insights" % m["id"], metric="saved,reach")
        except MetaError:
            return out
    for item in r.get("data", []):
        vals = item.get("values") or [{}]
        out[item.get("name")] = (item.get("total_value") or {}).get("value", vals[0].get("value"))
    return out


def perfil_ajeno(ig_id_propio, usuario, limite=25):
    """Business Discovery: datos públicos de otra cuenta de empresa o creador."""
    campos = "business_discovery.username(%s){username,name,followers_count,follows_count,media_count,media.limit(%d){%s}}" % (
        usuario, limite, CAMPOS_MEDIA)
    try:
        r = api(ig_id_propio, fields=campos).get("business_discovery") or {}
    except MetaError as e:
        if "business" in str(e).lower() or "invalid user" in str(e).lower() or "cannot be found" in str(e).lower():
            raise MetaError("cuenta personal o inexistente: Instagram solo comparte datos de cuentas de empresa o creador")
        raise
    return r, (r.get("media") or {}).get("data", [])
