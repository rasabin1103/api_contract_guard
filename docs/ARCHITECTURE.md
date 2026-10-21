# Arquitectura del servicio

Este repositorio entrega una API y una CLI. La presentación pertenece a ASE. Swagger es únicamente la consola de desarrollo y pruebas, sin frontend ni identidad visual de producto propia.

```text
ASE (presentación y backend/gateway) ─┐
Swagger / cliente HTTP ─────────────┴─> FastAPI /api/v1
                                          ├─ repositorios → SQLAlchemy → SQLite/PostgreSQL
                                          └─ parser estricto → ComparisonEngine → oasdiff
CLI ───────────────────────────────────────── parser estricto → ComparisonEngine
```

`domain` define hallazgos, errores y el protocolo del comparador sin dependencias HTTP/ORM. `services/specifications.py` realiza parsing y validación antes de cualquier comparación. `adapters/oasdiff.py` ejecuta el motor fijado sin depender de FastAPI ni SQLAlchemy. `services/comparisons.py` resume sus hallazgos. `repositories` contiene la interfaz inicial de ámbito de proyecto y su implementación local. `db` contiene los modelos relacionales; `schemas` valida solicitudes. `main.py` compone la aplicación y su ciclo de vida; `api/` separa rutas por recurso, dependencias por petición, límites HTTP y consultas.

Cuatro tablas guardan proyectos, contratos, ejecuciones y hallazgos. Se usan UUID y restricciones de unicidad por proyecto para etiquetas y hashes SHA-256 canónicos. Se conserva el texto original del contrato. Las comparaciones guardan versión/configuración del motor, resultado, resumen y hallazgos de forma transaccional. Borrar un proyecto exige confirmar su nombre y elimina sus datos relacionados en una transacción. Alembic gestiona el esquema, compatible con SQLite y PostgreSQL.

El adaptador utiliza `oasdiff changelog` con INFO, referencias externas deshabilitadas, configuración vacía explícita y actualización automática de dialecto. ERR se representa como breaking, WARN como potentially_breaking e INFO como non_breaking. Las clasificaciones desconocidas son informational. Solo cuando cambia el inventario de servidores se añade `oasdiff diff` para extraer cambios semánticos de `servers` que el changelog no clasifica, a nivel global, de ruta y de operación. La regla propia `acg-server-configuration-changed` clasifica cambios de configuración como potentially_breaking y cambios exclusivamente de descripción como informational. No supone una incompatibilidad confirmada; exige revisar URLs efectivas y herencia. Se conservan los deltas originales y los valores concretos de servers, con `source=oasdiff diff` y `value_scope=servers`. La configuración del informe registra `adapter_version=2` y la regla suplementaria para distinguirlo de los informes anteriores.

No se interpreta un diff textual como análisis semántico. Para las reglas originales se conservan su identificador y metadatos; los valores antes/después muestran la operación fuente (`value_scope=source_operation`), no deltas escalares inventados. La lista de hallazgos no es un inventario de todas las diferencias posibles del documento: se incluyen las reglas del changelog y los cambios suplementarios de servidores. `compatible` significa que no se han disparado reglas breaking ni potentially_breaking, no que ambos documentos sean idénticos.

Los identificadores y el orden de los hallazgos son estables para el mismo contenido/motor/configuración. Cada ejecución tiene su propio UUID y fecha. El historial conserva su versión del motor; cambiar el pin exige revisar las pruebas. Los endpoints de listas usan offset/limit. Las consultas de metadatos difieren la columna de texto del contrato y proyectan solo los campos necesarios, también al reconstruir informes.

La operación local es monousuario. La interfaz de repositorio de proyectos proporciona una primera separación para futuros ámbitos, pero las consultas directas de contratos/ejecuciones deben migrarse a repositorios con ámbito de organización antes de uso multiusuario. No se afirma que exista aislamiento de tenants ni autenticación. ASE consumirá el contrato HTTP versionado; no se compartirá su base de datos ni se importará su código.

## Validación de respuestas

`services/response_validation.py` es independiente de FastAPI, ORM y oasdiff. Selecciona la respuesta esperada del contrato o utiliza un JSON Schema 2020-12 independiente. Utiliza `openapi-schema-validator` 0.7.3 para OpenAPI 3.0/3.1 y `jsonschema` 4.24.1 para esquemas independientes, con `referencing` 0.37.0 y un registro sin recuperación remota. Se usa contexto de lectura en OpenAPI: los readOnly obligatorios siguen siendo obligatorios y los writeOnly no son necesarios y no deben aparecer en la respuesta, incluso mediante referencias locales. La validación JSON Schema independiente conserva sus semánticas estándar de anotaciones.

La evaluación de constraints y regex se realiza en un proceso descartable `spawn`, con dos slots por proceso API, timeout compartido de configuración y terminación forzada al agotar tiempo. En Linux se aplica un límite de espacio de direcciones de 512 MiB por worker; en Windows se utiliza el control del host junto al timeout. No se crean tablas ni migraciones: ni las respuestas ni los resultados se guardan. El consumidor puede almacenar un informe explícitamente fuera del servicio si su política lo permite.

Las referencias de Path Item/Response se siguen localmente antes de seleccionar el schema. Se conservan schemas recursivos para que el validador los evalúe sobre datos finitos; no se resuelven expandiendo estructuras sin límite. Las rutas concretas ambiguas se rechazan. Las respuestas sin cuerpo se distinguen de JSON null, y un schema ausente nunca se presenta como validado. Los informes tienen errores acotados y mensajes sin valores de datos. Las bibliotecas pueden ignorar formatos personalizados y keywords no definidos por su dialecto; no se presenta esto como una validación del comportamiento del servidor.

Referencias: [contexto de lectura OpenAPI](https://python-openapi.org/openapi-schema-validator/docs/latest/validation.html), [registro de referencias sin descargas implícitas](https://python-jsonschema.readthedocs.io/en/stable/referencing/).
