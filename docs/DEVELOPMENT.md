# Guía del código y desarrollo

## Por dónde empezar

Lee primero `README.md` para probar el producto. Para entender la implementación sigue este orden:

| Ubicación | Responsabilidad |
|---|---|
| `backend/app/main.py` | Construir la aplicación, configurar dependencias, conectar routers y cerrar el pool SQL al apagar |
| `backend/app/api/` | Rutas por recurso, sesiones por petición, límites HTTP, errores y proyecciones de informes |
| `backend/app/schemas/api.py` | Validar requests con Pydantic y documentar Swagger |
| `backend/app/services/specifications.py` | Parsear JSON/YAML, validar OpenAPI y calcular hash sin perder el original |
| `backend/app/core/json_input.py` | Parser JSON estricto compartido: claves duplicadas y no finitos son errores |
| `backend/app/adapters/oasdiff.py` | Ejecutar el motor fijado sin shell y normalizar sus reglas/metadatos |
| `backend/app/services/comparisons.py` | Resumir severidades, utilizado por HTTP y CLI |
| `backend/app/services/response_validation.py` | Seleccionar schemas de respuesta y evaluar datos en workers con timeout |
| `backend/app/domain/models.py` | Protocolo de motor, hallazgos y errores, sin FastAPI ni SQL |
| `backend/app/db/` y `repositories/` | Modelos/conexiones SQL y punto de sustitución del acceso a proyectos |
| `backend/alembic/` | Historial de migraciones; no depende del metadata actual para crear tablas antiguas |
| `backend/app/cli.py` | Comparación de ficheros sin servidor ni base |
| `tools/` | Instalación, lanzador Windows y comprobación HTTP sin dependencias externas |
| `examples/` y `backend/tests/` | Entradas reproducibles y regresiones de funcionamiento/seguridad |

`main.py` es la composición, no el lugar para añadir validaciones de negocio. `api/dependencies.py` obtiene configuración, motor y sesiones de la aplicación; evita globals compartidos entre instancias de pruebas. Las rutas mantienen el mismo contrato HTTP al reorganizarse.

## Flujo de una comparación

1. Se crea el proyecto y se importan versiones. El parser comprueba límites, refs y OpenAPI antes de guardar original/hash.
2. La ruta de comparación busca ambos contratos dentro del mismo proyecto. Se aplica otra vez la política de parsing vigente; si es el mismo contrato, se parsea una sola vez.
3. El adaptador verifica la versión del ejecutable y obtiene el changelog semántico. Solo ejecuta el diff suplementario cuando difiere alguna configuración de servidores soportada. El inventario previo es una optimización, no una clasificación de compatibilidad propia.
4. Se resumen los hallazgos y se guardan ejecución/hallazgos en una transacción.
5. Leer/exportar el informe consulta los resultados guardados y metadatos de versiones, no vuelve a ejecutar el motor ni carga sus textos completos.

Para listados se usa `defer(specification_content)` y una proyección explícita de campos. No reemplaces esa proyección por serializar la entidad entera y borrar después el contenido: eso cargaría contratos potencialmente grandes en memoria. Las pruebas comprueban que no se selecciona esa columna ni se accede a ella al serializar.

## Flujo de una validación de respuesta

1. El middleware limita el request y aplica parsing JSON estricto antes de Pydantic; los ficheros se cierran también en errores.
2. El servicio selecciona ruta/status/media/schema de OpenAPI o recibe un JSON Schema independiente. No hace llamadas al servidor ni persiste datos reales.
3. El worker usa un registro sin recuperación remota. El proceso puede terminarse si una regex o referencia recursiva consume demasiado tiempo. Dos slots por proceso API acotan la concurrencia; el `finally` libera procesos, pipes y slots.
4. El resultado distingue cuerpo ausente de JSON null y evaluación de schema de presencia de cuerpo. Los mensajes evitan valores reales; las ubicaciones son JSON Pointer.

Los comentarios explican límites y decisiones: replay del cuerpo de Starlette, refs de campos writeOnly, nombres de propiedades iguales a keywords, orden de borrado y fechas de SQLite. No se comentan operaciones obvias línea por línea.

## Preparar un entorno de desarrollo

Requiere Python 3.12+ (probado en 3.13). Los comandos se ejecutan desde la raíz salvo que se indique otra carpeta.

Windows PowerShell, con Python disponible:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.lock
.venv/Scripts/python.exe -m pip install --no-deps -e backend
./tools/install-oasdiff.ps1
$env:ACG_OASDIFF_PATH = (Resolve-Path tools/bin/oasdiff.exe).Path
cd backend
../.venv/Scripts/alembic.exe upgrade head
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si ya utilizaste `Iniciar.cmd`, puedes usar su uv local para preparar `.venv` sin Python global:

```powershell
.runtime/uv/uv.exe venv .venv --python 3.13
.runtime/uv/uv.exe pip install --python .venv/Scripts/python.exe -r backend/requirements-dev.lock
.runtime/uv/uv.exe pip install --python .venv/Scripts/python.exe --no-deps -e backend
```

Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.lock
pip install --no-deps -e backend
sh tools/install-oasdiff.sh
export ACG_OASDIFF_PATH="$PWD/tools/bin/oasdiff"
cd backend
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Para configurar variables revisa `.env.example`; el loader Python busca `.env` en el directorio de trabajo. El arranque documentado usa `backend/`. No reutilices una base real como `TEST_POSTGRES_URL`.

## Ejecutar comprobaciones

En Windows, desde `backend`:

```powershell
../.venv/Scripts/python.exe -m pytest -q
../.venv/Scripts/ruff.exe check . ../tools/smoke_api.py
../.venv/Scripts/ruff.exe format --check . ../tools/smoke_api.py
../.venv/Scripts/mypy.exe app
../.venv/Scripts/alembic.exe check
../.venv/Scripts/pip-audit.exe --progress-spinner off
```

Con el entorno activado en Linux/macOS, utiliza `pytest`, `ruff`, `mypy`, `alembic` y `pip-audit` directamente. La suite usa bases SQLite temporales migradas y el oasdiff real. El test PostgreSQL se omite sin `TEST_POSTGRES_URL`. Para ejecutar un subconjunto usa, por ejemplo, `pytest tests/test_response_validation.py -q`.

Con una API ya arrancada, desde la raíz:

```sh
python tools/smoke_api.py
```

El smoke usa solo la biblioteca estándar, prueba los requests del README y crea y borra su proyecto temporal sin tocar los existentes. No ejecutes el smoke con Python `-O`, ya que utiliza asserts de comprobación. CI aplica lint/format/tipos/pruebas/auditoría, PostgreSQL y smoke con Docker. Los resultados ejecutados localmente se registran en `VALIDATION.md`; una configuración de CI no equivale a una ejecución remota correcta.

## Cambiar el código sin romper sus contratos

- Nueva ruta: elige un router de `api/`, define entrada/salida en `schemas/` y añade la operación reutilizable a `services/`. Usa `DB` y exige ámbito de proyecto para sus versiones.
- Nueva regla del motor: mantén identificador/metadatos originales. Si la regla es propia del adaptador, identifícala como tal y registra su configuración. Usa un fixture real y revisa clasificación/determinismo.
- Nuevo campo persistente: modelo + migración Alembic + prueba de upgrade/consulta. No alteres `0001_initial.py` ni uses `create_all` para actualizar instalaciones.
- Nueva dependencia: fija versión y actualiza ambos locks con `uv pip compile backend/pyproject.toml -o backend/requirements.lock` y la variante `--extra dev -o backend/requirements-dev.lock`. Revisa auditoría/licencias.
- Actualizar oasdiff: coordina `ENGINE_VERSION`, instaladores, Dockerfile, fixtures esperadas y `LICENSE-DECISION.md`. El runtime y el build comprueban la versión, por lo que no basta con cambiar un solo pin.
- Optimizar: mide el caso pertinente o demuestra trabajo evitado (queries/columnas/procesos). Mantén las pruebas antes de ampliar la limpieza; no añadas caches ilimitadas de contratos/respuestas.

La carpeta `.runtime/` y `.venv/` son entornos locales ignorados, no código muerto. No se eliminan al limpiar fuentes: pueden contener herramientas y estado que el usuario necesita para arrancar.
