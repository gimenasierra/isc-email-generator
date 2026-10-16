# AGENTS.md

## Propósito

Este repositorio contiene una aplicación local para adaptar notificaciones exportadas de SailPoint ISC entre clientes, preservando metadatos y sintaxis Apache Velocity.

## Reglas obligatorias

- No modificar `key`, `medium`, `locale`, IDs ni otros metadatos durante una adaptación.
- Mantener el original y cada resultado como datos separados.
- Tratar cualquier contenido importado como no confiable.
- No ejecutar scripts de una plantilla ni interpretar Velocity en la vista previa.
- No presentar la validación sintáctica como prueba de equivalencia funcional.
- Los campos vacíos de branding significan “conservar original”.
- Los proveedores con IA pueden adaptar colores a partir de indicaciones de color, instrucciones adicionales o la guía Markdown del proyecto. Los mapeos exactos de color tienen prioridad; sin ninguna guía de color, conservar el original. El proveedor simulado solo aplica pares explícitos.
- No reemplazar correos ni URLs salvo que exista un mapeo explícito.
- No inventar variables de ISC ni datos de negocio.
- La guía Markdown aporta estructura, apariencia y políticas editoriales. Sus ejemplos nunca autorizan variables, directivas, URLs ni datos de negocio nuevos; el contenido funcional debe provenir de la plantilla original.
- Enviar `name`, `key` y `locale` a la IA solo como contexto. Nunca permitir que la adaptación modifique esos metadatos.
- Si hay idioma de destino, traducir únicamente el texto visible y conservar intactos los tokens Velocity. Si se solicita un título visual faltante, derivarlo del nombre de la plantilla sin inventar contenido de negocio.
- Las claves y llamadas de proveedores de IA pertenecen exclusivamente al backend.
- Las API keys ingresadas por UI se persisten únicamente en `backend/.env`, codificadas y fuera de Git. Nunca devolverlas al frontend ni incluirlas en proyectos, exportaciones o logs; un campo vacío conserva la clave actual.
- Las credenciales PAT de ISC se guardan únicamente en `backend/.env`; nunca se devuelven secretos o access tokens al frontend, logs, exportaciones o proveedores de IA.
- Toda llamada ISC debe usar exclusivamente la URL base validada de la conexión, sin seguir redirecciones a otros hosts.
- Mantener la interfaz de proveedor desacoplada para futuras integraciones.
- El contrato técnico común vive en `backend/prompts/adaptation_rules.md` y siempre se aplica. La guía de estilo editable de cada proyecto vive en `backend/prompts/projects/<project_id>.md` y se agrega como una segunda capa; nunca reemplaza el contrato ni debe hardcodearse en los adaptadores.
- La consulta e importación ISC son de solo lectura. La única escritura remota admitida es la publicación explícitamente confirmada de una adaptación revisada mediante `POST /notification-templates/v1`.
- Antes de publicar, resolver el destino exacto por `key + medium + locale`, preparar un payload separado, guardar respaldo local, volver a consultar el destino y verificar el resultado después del POST.
- Nunca eliminar plantillas en ISC, usar bulk-delete, enviar emails de prueba ni regenerar contenido durante una publicación.

## Desarrollo

- Frontend: React, TypeScript y Vite en `frontend/`.
- Backend: FastAPI en `backend/`.
- En uso normal, FastAPI sirve `frontend/dist`; Vite queda reservado para desarrollo.
- El inicio usa `backend/.venv` sin activación manual y escucha solo en localhost: en Windows con `Iniciar app.cmd`/`Detener app.cmd` y `scripts/stop_app.ps1`; en Linux con `Iniciar app.sh`/`Detener app.sh` y `scripts/stop_app.sh`, que comparten `backend/run.py`.
- Persistencia local: JSON por proyecto bajo `backend/data/` (ignorado por Git).
- Ejecutar los checks del frontend y las pruebas del backend antes de entregar cambios.
- Actualizar `README.md` cuando cambien comandos, configuración o comportamiento observable.

