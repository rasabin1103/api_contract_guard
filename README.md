# ASE API Contract Guard

API para **comparar contratos OpenAPI** y **validar datos JSON reales contra un esquema**. Incluye Swagger, persistencia de versiones/informes y una CLI para comparación. La interfaz de producto se integrará en ASE; este repositorio funciona de forma independiente, sin frontend ni cuentas cloud.

| Quiero… | Operación |
|---|---|
| Detectar cambios incompatibles entre dos OpenAPI | Importar versiones y ejecutar una comparación |
| Comprobar una respuesta real contra un OpenAPI | Seleccionar contrato, ruta, método, status y datos |
| Comprobar datos contra JSON Schema, sin proyecto | Pegar `schema` + `response_body`, o subir dos JSON |

**Modo actual: pruebas locales monousuario, sin autenticación. No exponer públicamente.** La integración real de identidad, permisos y organizaciones con ASE está pendiente.

## 1. Descargar y arrancar

Descarga o clona el repositorio y abre la carpeta que contiene `Iniciar.cmd`, `backend/` y `docker-compose.yml`. Elige **una** de estas opciones.

### Windows: doble clic, sin instalar Python ni Docker

Abre **`Iniciar.cmd`**. El lanzador:

1. Descarga uv con checksum verificado y prepara Python 3.13 localmente.
2. Instala las dependencias fijadas del backend.
3. Comprueba/instala oasdiff 1.34.0 y aplica las migraciones de la base de datos.
4. Arranca la API en loopback y abre Swagger cuando responde.

La primera vez necesita internet y puede tardar varios minutos. Requiere Windows 10/11 con PowerShell y `tar` disponibles. No modifica el PATH ni instala paquetes globales. Mantén la ventana abierta; **Ctrl+C** detiene el proceso que inició.

Opciones desde PowerShell:

```powershell
.\Iniciar.cmd -Port 8011
.\Iniciar.cmd -NoBrowser
.\Iniciar.cmd -Port 8011 -NoBrowser -Verify
```

`-Verify` necesita un puerto libre: arranca una instancia temporal, ejecuta pruebas HTTP de comparación/validación y la detiene. Si el puerto habitual ya contiene esta API, el arranque normal la reutiliza; no la sustituye ni la detiene. Los errores se muestran en la consola y los logs del servidor están en `.runtime/logs/`.

### Windows, Linux o macOS: Docker

Con Docker Engine/Desktop iniciado, Compose v2 disponible y el puerto 8000 libre, ejecuta desde la raíz:

```sh
docker compose up --build
```

Para dejarlo en segundo plano y esperar a que esté listo:

```sh
docker compose up --build --detach --wait
```

Solo se levanta un backend, sin Node/npm ni otro servidor. La primera construcción descarga dependencias y compila el motor fijado.

| Acción | Comando / dirección |
|---|---|
| Probar operaciones | [Swagger: localhost:8000/docs](http://localhost:8000/docs) |
| Obtener contrato de esta API | [localhost:8000/openapi.json](http://localhost:8000/openapi.json) |
| Comprobar salud | [localhost:8000/health](http://localhost:8000/health) |
| Consultar contenedor/logs | `docker compose ps` / `docker compose logs backend` |
| Parar conservando datos | `docker compose down` |

La raíz `/` también redirige a Swagger. Sus recursos estáticos usan el CDN predeterminado de FastAPI, por lo que el navegador necesita acceso a ese CDN.

## 2. Primera prueba: esquema frente a datos

No necesita crear proyecto. En Swagger abre **Response validation → POST `/api/v1/validations/schema` → Try it out**. Copia **todo** el contenido de [request-schema-invalid.json](examples/request-schema-invalid.json) y pulsa **Execute**:

```json
{
  "schema": {
    "type": "object",
    "required": ["id", "nombre", "saldo"],
    "properties": {
      "id": {"type": "integer"},
      "nombre": {"type": "string"},
      "saldo": {"type": "number", "minimum": 0}
    },
    "additionalProperties": false
  },
  "response_body": {"id": "123", "nombre": "Ana", "saldo": -50}
}
```

Resultado esperado: **`valid: false`, `error_count: 2`**, con errores en `/id` y `/saldo`. Ahora copia [request-schema-valid.json](examples/request-schema-valid.json): conserva el mismo esquema y usa `id: 123` y `saldo: 50.25`. Debe devolver **`valid: true`, `error_count: 0`**.

**HTTP 200 significa que la evaluación terminó; no significa que los datos sean válidos. Consulta `valid`.** `schema` contiene las reglas y `response_body` los datos. Un esquema `{}` o `true` no impone restricciones y acepta cualquier JSON; no lo uses para esta prueba.

Para subir archivos en vez de pegar el request, abre **POST `/api/v1/validations/schema/files`**:

| Campo | Archivo |
|---|---|
| `schema_file` | [response-schema.json](examples/response-schema.json) |
| `response_file`, caso inválido | [response-invalid.json](examples/response-invalid.json) |
| `response_file`, caso válido | [response-valid.json](examples/response-valid.json) |

Estos últimos archivos usan los campos `id` y `name`: el caso inválido tiene **un** error de tipo en `/id`. Son partes separadas, no los requests completos del ejemplo anterior.

También puedes ejecutar los requests completos desde PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/validations/schema -ContentType application/json -Body (Get-Content -Raw examples/request-schema-invalid.json)
```

## 3. Comparar dos contratos OpenAPI

En cada operación de Swagger utiliza **Try it out → Execute**.

1. **POST `/api/v1/projects`**: crea un proyecto con `{"name":"Inventory API","description":"Prueba local"}` y copia su `id`.
2. **POST `/api/v1/projects/{project_id}/contracts`**: introduce ese ID, `version_label=v1` y selecciona [openapi-v1.yaml](examples/openapi-v1.yaml). Guarda el `id` del contrato devuelto.
3. Repite la importación con `version_label=v2` y [openapi-v2-breaking.yaml](examples/openapi-v2-breaking.yaml). Guarda su `id`.
4. **POST `/api/v1/projects/{project_id}/comparisons`**: envía:

   ```json
   {
     "baseline_id": "UUID_REAL_DEL_CONTRATO_V1",
     "candidate_id": "UUID_REAL_DEL_CONTRATO_V2"
   }
   ```

   Sustituye los valores por UUID reales, no por etiquetas ni por el ID del proyecto. **Baseline es el contrato actual y candidate la propuesta; invertirlos cambia el análisis.**

5. El resultado esperado del ejemplo es `overall_result: "breaking"` con cuatro cambios incompatibles. [openapi-v2-compatible.yaml](examples/openapi-v2-compatible.yaml) sirve para probar una adición opcional compatible.
6. Consulta el historial con **GET `/api/v1/projects/{project_id}/comparisons`**. Recupera el informe con **GET `/api/v1/comparisons/{comparison_id}`** o descarga JSON añadiendo `/export`.

`compatible` indica que no se dispararon reglas breaking ni de revisión, no que los documentos sean idénticos. Los cambios de configuración de servidores se muestran como `potentially_breaking`; los de su descripción son informativos. El historial conserva el resultado/configuración original: vuelve a comparar para aplicar reglas nuevas.

## 4. Validar una respuesta contra un OpenAPI importado

Usa **POST `/api/v1/projects/{project_id}/contracts/{version_id}/validate-response`** con el proyecto y el ID del contrato `v1` anterior:

```json
{
  "path": "/items",
  "method": "GET",
  "status_code": 200,
  "content_type": "application/json",
  "response_body": {"id": "123", "name": "Ana"},
  "body_present": true
}
```

Devuelve `valid: false` y un error en `/id`. Cambia `"123"` por `123` para una respuesta válida. `path` admite la plantilla del contrato o una ruta concreta no ambigua. Se busca el status exacto, su rango y después `default`.

`response_body: null` representa JSON null. Para indicar que no hay cuerpo, añade `body_present: false`. Los informes distinguen la evaluación de un schema de la comprobación exclusiva de presencia de cuerpo.

Esta función **no llama al servidor de origen, no utiliza sus tokens/headers y no guarda los cuerpos ni sus informes**. Valida datos capturados previamente; no comprueba headers, cookies, tiempos ni comportamiento del servidor.

## 5. Datos y configuración

| Forma de arranque | Base SQLite | Herramientas / cachés |
|---|---|---|
| `Iniciar.cmd` | `backend/data/guard.db` | `.runtime/` y `tools/bin/` |
| Docker | Volumen `guard-data` | Dentro de la imagen |

**Son instalaciones con datos independientes.** Cambiar entre ellas no mueve proyectos automáticamente. Parar el servicio conserva la base. No borres `data/` ni uses `docker compose down -v` salvo que quieras eliminar todos los registros de esa instalación.

Para Python, copia `.env.example` a `backend/.env` o exporta las variables. En Docker, revisa el bloque `environment` de Compose; la URL SQLite está fijada allí y debe cambiarse explícitamente para usar PostgreSQL.

| Variable | Función / valor por defecto |
|---|---|
| `ACG_DATABASE_URL` | `sqlite:///./data/guard.db`; PostgreSQL admite `postgresql+psycopg://…` |
| `ACG_MAX_UPLOAD_BYTES` | 2097152 bytes; límites de ficheros/JSON y framing multipart aparte |
| `ACG_COMPARISON_TIMEOUT` | 30 segundos por proceso del motor/validador |
| `ACG_OASDIFF_PATH` | `oasdiff`; el lanzador configura su ruta absoluta |
| `ACG_CORS_ORIGINS` | `[]`; allowlist JSON si ASE accede desde otro origen de navegador |

## 6. CLI, desarrollo y pruebas

La instalación Python registra `contract-guard`. Con el entorno activado y oasdiff configurado, desde la raíz:

```sh
contract-guard compare --base examples/openapi-v1.yaml --target examples/openapi-v2-breaking.yaml --format json
```

No requiere API ni base de datos. Admite `--format text`; códigos: **0** sin breaking (puede haber avisos), **1** breaking, **2** error. La CLI actual compara contratos; la validación de respuestas se usa por HTTP.

Con la API arrancada y Python disponible, `python tools/smoke_api.py` comprueba los ejemplos del README y el recorrido completo, creando y borrando únicamente su proyecto temporal. El lanzador Windows ofrece la misma comprobación con `-Verify`.

Para instalar el entorno de desarrollo, ejecutar Pytest/Ruff/Mypy o modificar el código, sigue **[Guía del código y desarrollo](docs/DEVELOPMENT.md)**. El resultado real de las comprobaciones está en [VALIDATION.md](docs/VALIDATION.md).

## Problemas habituales y límites

- **`valid: true` en ambos casos:** comprueba el endpoint, que el request incluye el `schema` completo y que no has sustituido las reglas al cambiar los datos. Copia los dos requests completos de `examples/`. Revisa el bloque **Curl** de Swagger para ver lo que enviaste.
- **422 por UUID:** usa el ID devuelto por cada importación. Puedes recuperarlo con GET de contratos del proyecto.
- **409 al importar:** etiqueta o contenido canónico ya existentes en ese proyecto.
- **413:** supera el límite de tamaño. **422:** JSON/OpenAPI/schema inválido o selección no declarada.
- **Puerto ocupado:** usa `Iniciar.cmd -Port 8011` o detén conscientemente la instancia anterior. El lanzador no mata procesos ajenos.
- **Falla una descarga:** comprueba internet, proxy/certificados de tu organización y el mensaje de consola.
- **Swagger no carga:** comprueba acceso a su CDN; `/openapi.json` sigue disponible.
- **Motor no disponible:** debe indicar exactamente `oasdiff version 1.34.0`; fuera del lanzador configura `ACG_OASDIFF_PATH`.
- **Tabla inexistente:** aplica `alembic upgrade head` usando la misma configuración de base que el servicio.

Se admiten OpenAPI 3.0/3.1 y JSON Schema independiente 2020-12. Se rechazan referencias externas/dinámicas y construcciones fuera de cobertura; en validación no se admiten `$id`, anchors o dialectos personalizados. Los formatos desconocidos son anotaciones. Los errores se limitan a 100, con `truncated` si hay más. Ningún resultado demuestra toda la compatibilidad funcional de un servidor. Consulta los detalles en [API](docs/API.md) y [Seguridad](docs/SECURITY.md).

La aplicación no depende de ASE. Su integración, autenticación, permisos y aislamiento multiusuario están descritos en [ASE_INTEGRATION.md](docs/ASE_INTEGRATION.md), pero aún no implementados. No hay publicación automática ni despliegue de producción.

[Arquitectura](docs/ARCHITECTURE.md) · [Despliegue](docs/DEPLOYMENT.md) · [Motor y licencias](LICENSE-DECISION.md)

oasdiff es Apache-2.0 y su licencia se conserva en `third-party`. El propietario debe decidir la licencia de distribución del código original antes de publicarlo.
