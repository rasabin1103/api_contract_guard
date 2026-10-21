# Verificación de la entrega

Fecha: 2026-10-20. Versión 0.2.0, tras reorganizar y limpiar el código.

## Comprobaciones ejecutadas

| Comprobación | Resultado |
|---|---|
| Pytest con SQLite y oasdiff real | 92 passed, 1 skipped: PostgreSQL opcional |
| Ruff: lint y formato | Correctos, incluido tools/smoke_api.py |
| Mypy | Sin errores en 23 ficheros fuente |
| Docker Compose: reconstrucción y arranque | Backend saludable en loopback, puerto 8000 |
| Smoke HTTP contra Docker | Correcto: Swagger, proyectos, importación, comparación, historial, exportación, tres modos de validación y borrado del proyecto temporal |
| Lanzador Windows -Port 8011 -NoBrowser -Verify | Instala dependencias, migra, arranca, supera el smoke y detiene su servidor temporal |
| Alembic check en Docker | Sin operaciones de migración nuevas |

El smoke también envía los dos requests completos del README: el inválido devuelve valid:false con dos errores y el válido valid:true. Los ejemplos multipart usan sus propios ficheros de esquema/datos. HTTP 200 indica que se realizó la comprobación, no que los datos sean válidos.

Las nuevas regresiones comprueban que listar contratos no selecciona su texto completo, que serializar metadatos no accede a esa columna y que solo se ejecuta el diff suplementario cuando cambia la configuración de servidores. También protegen nombres de propiedades iguales a keywords JSON Schema y el rechazo controlado de dialectos mal formados.

La suite cubre comparación semántica, servidores, determinismo, persistencia, CLI, ámbitos de proyecto, parsing estricto, referencias locales, formatos y tipos, selección de respuesta, readOnly/writeOnly, ausencia de cuerpo, privacidad de errores y terminación de workers por timeout. La primera repetición dentro del sandbox encontró permisos denegados sobre temporales de Windows; se repitió fuera de esa restricción. Permanece un aviso de deprecación de Starlette TestClient sobre httpx.

## Alcance y límites

- No se ha vuelto a ejecutar PostgreSQL ni una auditoría de dependencias/contenedores en esta revisión. Las versiones fijadas y el esquema de base no han cambiado.
- CI contiene lint, formato, tipos, pruebas, auditoría y smoke con Docker/PostgreSQL; no se ha ejecutado remotamente ni se ha hecho push.
- El servicio sigue siendo local monousuario. Identidad, permisos, organizaciones y aislamiento de ASE quedan pendientes.
- La validación de respuestas recibe JSON capturado: no llama al servidor ni valida headers, cookies o latencia. JSON Schema independiente usa 2020-12; las referencias externas/dinámicas y dialectos personalizados se rechazan.
- Los hallazgos corresponden a reglas soportadas y a la regla suplementaria de servidores; compatible no significa documentos idénticos ni garantiza comportamiento del servidor.
- Swagger sirve sus assets desde el CDN predeterminado de FastAPI. Se ha verificado su respuesta HTTP y el flujo de API, sin interacción manual con sus controles ni prueba de doble clic del lanzador.

La API queda disponible en [Swagger local](http://localhost:8000/docs). docker compose down la detiene conservando el volumen SQLite.
