# Conectar Instagram a SAPO (API oficial de Meta, gratis)

Instagram bloquea las consultas automáticas sin sesión, así que SAPO usa la **API oficial de Meta**.
Solo hay que crear un token una vez (≈15 min) con alguien que sea **administrador del portafolio comercial (Business Manager) de Cresa**.

## Qué se obtiene
| Cuentas | Datos |
|---|---|
| Oficiales de Cresa (Crecos, Orve Hogar, Japón, Motozone, Pagamenos) conectadas a Meta | Seguidores, publicaciones, likes, comentarios, **views, guardados, compartidos, alcance** y **lives** |
| Vendedores y competencia con cuenta de **empresa o creador** | Seguidores, publicaciones, likes y comentarios |
| Cuentas **personales** | Nada (Instagram no lo permite) |

## Pasos
1. **Requisito:** cada cuenta de Instagram de las cadenas debe ser *profesional* y estar vinculada a su página de Facebook dentro del portafolio comercial de Cresa.
2. **Crear la app:** entra a <https://developers.facebook.com/apps> → *Crear app* → caso de uso *Otro* → tipo *Empresa* → vincúlala al portafolio de Cresa.
3. En la app, agrega el producto **Instagram** → *API con inicio de sesión de Facebook*.
4. **Token permanente (usuario del sistema):** <https://business.facebook.com/settings> → *Usuarios* → *Usuarios del sistema* → *Agregar* (rol Administrador).
   - *Asignar activos*: las **páginas de Facebook** y **cuentas de Instagram** de las 5 cadenas (control total) y la **app** creada.
   - *Generar token* → elige la app → caducidad **Nunca** → permisos:
     `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`, `business_management`.
   - Copia el token.
5. **Guardarlo en GitHub (nunca en el código):** <https://github.com/cdizquierdoc-hub/monitor-lives-tiktok/settings/secrets/actions> → *New repository secret* → Name: `IG_TOKEN` → pega el token → *Add secret*.
6. Listo: en la siguiente hora aparecen las métricas. Para probar al momento: *Actions* → *Probar cuentas* → *Run workflow* → modo `meta` y los usuarios de Instagram.

> Si Meta pide pasar la app a modo *Activo/Live*, usa como URL de política de privacidad el link del dashboard.

## Agregar cuentas de Instagram
En el dashboard: **＋ Cuentas** → elige **Instagram** → pega `usuario, agencia` (o el link `instagram.com/usuario`).
