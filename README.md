# SAPO · Sistema de Análisis de Presencia Online

Monitor de lives y contenido de TikTok de los vendedores de Cresa (Crecos, Orve Hogar, Japón, Motozone, Pagamenos) y de la competencia.

**Dashboard:** https://cdizquierdoc-hub.github.io/monitor-lives-tiktok/

## Cómo funciona
- GitHub Actions revisa cada minuto si cada vendedor está en LIVE (`monitor.py`).
- Cada live queda registrado con inicio, fin y duración en la rama `data` (`data/data.json`).
- El dashboard (`index.html`, GitHub Pages) lee esos datos y se actualiza solo.

## Agregar vendedores
Desde el dashboard: botón **＋ Vendedores** → pega la lista (usuario y agencia, ej. `"@pepito" "JAPON PARQUE CALIFORNIA"`) → **Guardar en GitHub** → **Commit changes**.

También puedes editar directamente cualquier archivo de la carpeta `vendedores/` (CSV: `usuario,agencia,nombre,activo`, ej. `@pepito,JAPON PARQUE CALIFORNIA,Pepito Pérez,SI`).
Pon `NO` en la columna `activo` para dejar de monitorear a alguien. Para cuentas de la competencia usa `tipo` = `competencia` y en `agencia` pon la empresa (ej. `COMANDATO`).

El dashboard tiene tres páginas: **Resumen** de lives (filtro Nuestras / Competencia / Todas), **Nosotros vs Competencia** (`#competencia`) y **Contenido** (`#contenido`: seguidores, publicaciones, views, likes, comentarios, compartidos, guardados y engagement; se actualiza cada 4 h con `social.py`).

## Probar una cuenta
Actions → *Monitor de lives* → *Run workflow* (o localmente: `python3 monitor.py probar usuario1 usuario2`).
