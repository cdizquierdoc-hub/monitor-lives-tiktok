# Monitor de lives TikTok · Vendedores

**Dashboard:** https://cdizquierdoc-hub.github.io/monitor-lives-tiktok/

## Cómo funciona
- GitHub Actions revisa cada 2 minutos si cada vendedor está en LIVE (`monitor.py`).
- Cada live queda registrado con inicio, fin y duración en la rama `data` (`data/data.json`).
- El dashboard (`index.html`, GitHub Pages) lee esos datos y se actualiza solo.

## Agregar vendedores
Desde el dashboard: botón **＋ Vendedores** → pega la lista → **Guardar en GitHub** → **Commit changes**.

También puedes editar directamente cualquier archivo de la carpeta `vendedores/` (CSV: `usuario,nombre,zona,activo`).
Pon `NO` en la columna `activo` para dejar de monitorear a alguien.

## Probar una cuenta
Actions → *Monitor de lives* → *Run workflow* (o localmente: `python3 monitor.py probar usuario1 usuario2`).
