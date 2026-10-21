# Ejecución y despliegue

Desde la raíz, `docker compose up --build` construye y ejecuta únicamente el servicio `backend`. Aplica migraciones antes de iniciar FastAPI, expone `127.0.0.1:8000`, mantiene SQLite en `guard-data` y dispone de health check, usuario no root y límites de memoria/CPU. Abre `http://localhost:8000/docs`; la raíz redirige a Swagger. No se utiliza el puerto 3000.

Comprueba el estado con `docker compose ps` y los logs con `docker compose logs backend`. Detén el servicio con `docker compose down`; el volumen permanece. `docker compose down -v` elimina deliberadamente todos los datos y solo debe usarse si se desean descartar. Para copias de seguridad, detén el servicio antes de copiar SQLite o utiliza su API de backup online. Restaura con el servicio detenido y conserva los permisos del volumen.

El primer build descarga dependencias Python y compila el módulo fijado de oasdiff. El Dockerfile comprueba que el ejecutable declara 1.34.0. El procesamiento de contratos no utiliza servicios cloud. Swagger utiliza los recursos CDN predeterminados de FastAPI; si se necesita una consola completamente offline, se deben empaquetar sus assets estáticos. La API y la CLI no dependen de esa consola.

Para PostgreSQL configura `ACG_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/guard` y ejecuta `alembic upgrade head`. El servidor y la base deben existir. Compose utiliza SQLite por defecto; cambia explícitamente la URL de su servicio para usar PostgreSQL. Las pruebas de compatibilidad utilizan una base PostgreSQL dedicada, no datos reales. SQLite conserva fechas sin offset; los valores se interpretan como UTC.

La integración en ASE consiste en desplegar esta API en una red privada y configurar su URL en el backend/gateway de ASE. ASE presenta la funcionalidad dentro de su propia interfaz. No expongas esta configuración local sin autenticación públicamente. Antes de habilitar acceso remoto se requieren identidad verificable, permisos, aislamiento organizativo, TLS y controles de abuso. Consulta ASE_INTEGRATION.md.

Antes de distribución pública: fija digests de imágenes base, revisa vulnerabilidades de contenedores y Go, genera un inventario de licencias/SBOM y valida restauraciones. No se publica ni despliega automáticamente desde CI.
