# ISC Email Generator

Aplicación web local para adaptar notificaciones de email de SailPoint ISC para reutilizarlas con otro branding, otro idioma o la configuración por defecto del proyecto. Ajusta asunto, cuerpo HTML y estilo mediante un modelo de IA o sustitución directa de valores y conserva intactos los metadatos y toda la sintaxis Apache Velocity.

Funciona en su propia PC o servidor, escucha únicamente en `127.0.0.1` (puerto `8000` por defecto) y no modifica nada en SailPoint salvo cuando se publica una notificación en ISC.

<img width="1911" height="901" alt="image" src="https://github.com/user-attachments/assets/fb44b8b7-d579-43c5-bab7-8217a445fc8b" />

## Qué hace

1. **Importa** una notificación original desde SailPoint ISC (o desde un JSON exportado, sin conexión).
2. **Genera una versión adaptada** al cliente destino: cambia únicamente el asunto y el cuerpo HTML. El resto de los campos y todas las variables y directivas de Apache Velocity quedan intactos.
3. **Puede usar IA** (Gemini, Groq, Anthropic/Claude, OpenAI o un servidor local compatible con OpenAI como LM Studio u Ollama) para traducir y aplicar branding, o un **modo simulado** que no llama a ninguna IA y solo aplica reemplazos explícitos de cliente, logo, colores, correos y URLs.
4. **Permite revisar y editar** con validaciones: compara original y adaptación, ofrece edición visual protegida y bloquea la descarga o publicación si un cambio rompió las validaciones.
5. **Entrega el resultado** como JSON descargable o, de forma opcional y confirmada, lo publica de vuelta en ISC.

El idioma de destino predeterminado es español neutro. El original importado nunca se altera.

## Servidor multiusuario en Ubuntu

El modo servidor es adicional al uso local y portable. Aísla los datos y secretos de cada usuario y se despliega con PostgreSQL y Nginx:

1. Copie `.env.server.example` a `.env.server` y reemplace las dos claves.
2. Coloque el certificado corporativo en `deploy/certs/server.crt` y su clave en `deploy/certs/server.key`.
3. Inicie los servicios con `docker compose --env-file .env.server up -d --build`.
4. Cree el primer administrador de forma interactiva:

```bash
docker compose --env-file .env.server exec app python -m app.admin_cli create-admin --username administrador
```

La contraseña inicial es temporal. Hasta cambiarla, esa cuenta solamente puede consultar su sesión, cambiar la contraseña o cerrar sesión. Las cuentas posteriores se crean desde los endpoints administrativos; no existe autorregistro.

FastAPI no se publica directamente: Nginx es el único servicio expuesto y requiere HTTPS. La VM debe quedar limitada a la red o VPN corporativa. Los proyectos, guías, conexiones y publicaciones pertenecen al usuario autenticado. Las API keys y credenciales ISC se cifran antes de guardarse y nunca regresan al navegador.

### Clave maestra y respaldos

`ISC_EMAIL_GENERATOR_MASTER_KEY` debe generarse una vez y guardarse fuera de la VM y fuera del respaldo de PostgreSQL, en el gestor de secretos corporativo. Puede generarse con:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

El servidor conserva un verificador cifrado. Si se inicia con otra clave, bloquea el acceso a los secretos y no los sobrescribe. Para que un respaldo sea recuperable se necesitan conjuntamente:

- el dump de PostgreSQL;
- la misma clave maestra;
- el certificado HTTPS y su clave, custodiados según la política corporativa.

Ejemplo de respaldo de base:

```bash
docker compose --env-file .env.server exec -T db pg_dump -U isc_email_generator isc_email_generator > respaldo.sql
```

La rotación de la clave debe implementarse como una operación administrativa controlada de descifrado y recifrado; nunca se cambia directamente en `.env.server` con secretos existentes.

### Migración del proyecto local

Copie temporalmente `default.json` y, si corresponde, `default.md` dentro de `migration/`. Esa carpeta se monta como solo lectura. La simulación es obligatoria y no escribe datos:

```bash
docker compose --env-file .env.server exec app python -m app.admin_cli migrate-local \
  --source /migracion/default.json --guide /migracion/default.md --username usuario
```

El reporte muestra cantidades, exclusiones y un `confirmation_hash`. Después de revisarlo, monte los archivos como solo lectura y repita con:

```bash
docker compose --env-file .env.server exec app python -m app.admin_cli migrate-local \
  --source /migracion/default.json --guide /migracion/default.md --username usuario \
  --apply --confirm-hash HASH_DEL_REPORTE
```

No se importan `.env`, API keys, credenciales ISC, tokens, sesiones, preparaciones de publicación ni estados transitorios. La fuente local nunca se modifica.

## Distribución portable para Windows x64

El archivo `dist\isc-email-generator-windows-x64.zip` está pensado para usuarios finales: se descomprime completo y se inicia con doble clic en **`Iniciar app.cmd`**. Incluye Python 3.12 x64, todas las dependencias del backend y `frontend/dist`; no requiere instalar Python, Node.js, Rust ni usar permisos de administrador. **`Detener app.cmd`** cierra solamente la instancia validada de la aplicación.

En modo portable, los proyectos, guías, conexiones, credenciales codificadas, PID y logs se guardan en `%LOCALAPPDATA%\ISC Email Generator`. Esto mantiene el paquete libre de datos personales y permite ejecutarlo desde cualquier carpeta, incluso una ruta con espacios o una ubicación de solo lectura. El ZIP incluye `LEEME-PORTABLE.txt` con las instrucciones mínimas.

### Generar el ZIP

La generación se realiza en Windows x64 desde un checkout de desarrollo con Node.js/npm y acceso a internet:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\Empaquetar distribución.ps1"
```

El script ejecuta `npm ci` y el build del frontend, descarga artefactos fijados de Python 3.12.10 y pip con verificación SHA-256, instala el lock `backend/requirements-portable-win-x64.txt` dentro del runtime embebible y genera el ZIP. Antes de comprimir hace una prueba real desde una ruta con espacios y otro directorio de trabajo: arranca con el Python incluido, consulta `/api/health` y detiene la instancia. Para reutilizar un `frontend/dist` ya verificado puede agregarse `-SkipFrontendBuild`; `-SkipSmokeTest` existe solo para diagnóstico y no se recomienda para una entrega.

El equipo que genera el ZIP sí necesita Node.js y acceso a PyPI/Python.org. El equipo destinatario no descarga ni instala nada.

## Prerrequisitos

Los siguientes prerrequisitos corresponden al checkout de desarrollo, no al ZIP portable:

- **Python 3.11 o superior** (obligatorio).
- **Node.js 20 o superior**: necesario solo para la instalación inicial, para compilar el frontend. El repositorio no incluye `frontend/dist`; si copia esa carpeta desde otro equipo, no necesita Node.js.
- **Clave de un proveedor de IA** (opcional): solo para generar con IA. El modo simulado no requiere ninguna clave.
- **Credenciales de SailPoint ISC** (opcional): un PAT (Client ID y Client Secret) con scope `sp:scopes:all`, solo si va a cargar plantillas desde ISC o publicar en él.

## Instalación inicial

La primera vez que clona o copia el proyecto hay que crear el entorno virtual de Python y compilar el frontend. Después no se vuelve a hacer.

### Windows

Doble clic en **`Preparar entorno.cmd`**. Crea `backend\.venv`, instala las dependencias y, si falta `frontend\dist`, compila el frontend. Al terminar indica que ya puede iniciar la app.

Equivalente manual, desde la raíz del proyecto:

```powershell
py -3 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm.cmd install
npm.cmd run build
cd ..
```

### Linux

Desde la raíz del proyecto:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend
npm install
npm run build
cd ..
```

## Cómo ejecutar la app

### Windows

- **Iniciar:** doble clic en **`Iniciar app.cmd`**. Levanta la aplicación en segundo plano en `http://127.0.0.1:8000` y abre el navegador. Puede cerrar la ventana del lanzador: la app sigue corriendo. Si ya hay una instancia corriendo, reutiliza esa en lugar de levantar otra.
- **Detener:** doble clic en **`Detener app.cmd`**. Detiene solamente esa instancia, validando el proceso exacto (PID, Python del entorno y `run.py`); nunca finaliza otro proceso de Python.

En desarrollo, los eventos se registran en `logs\app.log`. En el paquete portable quedan en `%LOCALAPPDATA%\ISC Email Generator\logs`, incluidos `inicio.log`, `inicio-salida.log`, `inicio-error.log` y `app.log`.

Para usar otro puerto en una sesión de PowerShell, defínalo antes de iniciar. Use la misma variable al detener:

```powershell
$env:ISC_EMAIL_GENERATOR_PORT = "8010"
.\Iniciar app.cmd
# luego: .\Detener app.cmd
```

El valor debe ser un entero entre `1` y `65535`. La aplicación no elige automáticamente otro puerto para evitar abrir o detener una instancia equivocada.

### Linux

```bash
./Iniciar app.sh    # levanta la app en segundo plano y abre el navegador si hay escritorio
./Detener app.sh    # detiene solo esa instancia, con la misma validación que en Windows
```

El lanzador verifica que existan el entorno virtual, el frontend compilado y las dependencias (y le indica qué comando falta si algo no está). Deja la app corriendo con `nohup`, espera hasta 40 segundos a que responda y muestra la dirección `http://127.0.0.1:8000`. El log queda en `logs/app.log`.

En Linux puede elegir otro puerto para iniciar y detener la misma instancia:

```bash
export ISC_EMAIL_GENERATOR_PORT=8010
./Iniciar\ app.sh
# luego: ./Detener\ app.sh
```

En un servidor sin escritorio gráfico no se abre ningún navegador: use port-forwarding SSH y abra la dirección en su equipo:

```bash
ssh -L 8000:127.0.0.1:8000 usuario@servidor
# luego, en su equipo local: http://127.0.0.1:8000
```

## Cómo usar la app

1. Cargue uno o varios archivos JSON, o pulse **Cargar desde ISC**. Cada archivo puede contener una única notificación o un array de notificaciones.
2. Menú del engranaje → **Instrucciones y reglas**: indique idioma de destino, branding, colores o mapeos, y guárdelos.
3. **Configuración de IA**: elija proveedor y modelo, guarde y pruebe la conexión (o deje el proveedor simulado si no quiere usar IA).
4. Filtre y seleccione una notificación en el panel izquierdo.
5. Genere la adaptación desde la barra de acciones.
6. Compare original y adaptación; edite en modo **Visual** o **HTML** y revise validaciones y referencias pendientes.
7. Si la plantilla contiene una fecha compatible, use **Traducir fechas** para convertir sus días y meses después de la adaptación, sin volver a llamar a la IA.
8. Descargue el JSON adaptado, o prepárelo para publicarlo en ISC.

Si las instrucciones o la guía de estilo cambian después de generar, la adaptación queda marcada como desactualizada: no se regenera ni se sobrescribe sola.

### Carga de archivos JSON locales

La carga local es acumulativa: agregar otro archivo no borra las notificaciones que ya están en el panel. Antes de confirmar se muestran los archivos válidos, los rechazados y las coincidencias por `key + medium + locale`. Si hay duplicados, puede omitirlos o importarlos como **Copia local** independiente. Un archivo inválido se rechaza completo, pero no impide cargar los demás archivos válidos seleccionados al mismo tiempo.

### Protecciones de la edición

- Solo se modifican asunto y cuerpo; `name`, `key`, `locale` y los demás metadatos nunca cambian.
- Las referencias Velocity nunca se sustituyen por nombres literales aunque parezcan equivalentes; en particular, `${PRODUCT_NAME}` se conserva como valor dinámico de ISC incluso dentro de la firma.
- El modo **Visual** permite texto, negrita, cursiva, tamaño, colores, alineación y la URL de enlaces existentes. Las variables y directivas de Velocity se muestran como etiquetas azules bloqueadas; si el backend detecta que una edición alteró esa lógica, responde con un error sin sobrescribir la adaptación.
- Si el contenido contiene scripts, iframes u otros elementos inseguros, el modo visual se deshabilita y hay que editar en modo **HTML**.
- La vista previa se muestra en un `iframe` aislado que elimina scripts; no ejecuta Velocity ni garantiza el render final de Outlook o Gmail.
- Cuando el destino es español, **Traducir fechas** detecta las referencias validadas `expires`, `dateRequested`, `startDate`, `removeDate`, `detail.startDate` y `detail.removeDate`. Las dos últimas se admiten específicamente dentro de los detalles iterados de solicitudes de acceso; no se generaliza la transformación a otras propiedades anidadas. La acción inserta después de la adaptación un bloque Velocity determinista que traduce días y meses completos o abreviados, conservando número, año, hora y zona horaria (por ejemplo, `Thursday 15 October 2026 (18:10:38 GMT)` → `jueves 15 octubre 2026 (18:10:38 GMT)` y `Fri Oct 23 03:00:00 UTC 2026` → `viernes octubre 23 03:00:00 UTC 2026`). La IA no recibe ni genera esos bloques. La acción se puede revertir con **Quitar traducción de fechas**; una edición manual que rompa un bloque protegido aparece en **Validación** y bloquea descarga y publicación hasta corregirla.

### Guías de estilo

En **Instrucciones y reglas** puede elegir **Conservar diseño actual** o **Aplicar guía de estilo**. La guía es un Markdown propio del proyecto (guardado en `backend/prompts/projects/`) que define únicamente estructura visual, jerarquía, colores y políticas editoriales: sus ejemplos no autorizan contenido de negocio, variables ni enlaces nuevos. El repositorio incluye `backend/prompts/projects/default.md` como guía inicial reproducible del proyecto predeterminado; las demás guías y sus metadatos permanecen locales y fuera de Git. El contrato técnico de `backend/prompts/adaptation_rules.md` siempre se aplica y ninguna guía lo reemplaza. Cambiar o eliminar una guía marca las adaptaciones existentes como desactualizadas.

## Cargar plantillas desde SailPoint ISC

1. Menú del engranaje → **Conexiones ISC**: cree una conexión con nombre, entorno, URL base de API y credenciales PAT. Use una URL exacta como `https://tenant.api.identitynow.com` o `https://tenant.api.identitynow-demo.com` (sin HTTP, puertos, rutas ni parámetros).
2. Guarde y pulse **Probar conexión**: autentica y verifica por separado la lectura de plantillas estándar y personalizadas, sin escribir nada.
3. Panel izquierdo → **Cargar desde ISC**: elija conexión y tipo de plantilla, consulte, filtre, seleccione e importe.

La consulta es de solo lectura: usa OAuth 2.0 `client_credentials`, recorre todas las páginas, filtra localmente solo el medio `EMAIL` y respeta los límites de tasa de ISC. Si la misma `key + medium + locale` ya existe localmente, puede **omitirla**, **reemplazar el original** o **importar como copia local** independiente.

Las APIs de notificaciones no definen scopes granulares; use PAT con `sp:scopes:all` y un usuario propietario con acceso a administrar notificaciones. Un 403 se informa como acceso denegado al endpoint correspondiente.

La aplicación no contiene operaciones para eliminar plantillas en ISC ni enviar emails de prueba.

### Credenciales y datos locales

- Los metadatos de la conexión se guardan en el proyecto local.
- El PAT Client ID y Client Secret se escriben únicamente en `backend/.env`, codificados; nunca se devuelven al frontend, ni se agregan a exportaciones ni a logs. Dejar un campo vacío al editar conserva el valor actual. Vea [backend/.env.example](backend/.env.example).
- Desde **Conexiones ISC** puede eliminar una conexión: quita solo la conexión y sus credenciales locales, sin tocar nada en SailPoint. Las notificaciones importadas permanecen en el proyecto; cada una puede eliminarse del panel con la **×**, y la papelera inferior derecha limpia todos los locales. Ambas acciones piden confirmación.

## Configurar proveedores de IA

- El proveedor, el modelo y la URL del servidor local se guardan en el proyecto. Las API keys ingresadas desde la interfaz se guardan solo en `backend/.env`, codificadas, y nunca se muestran, exportan ni registran.
- También puede definirlas por variables de entorno: `GEMINI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` y `LOCAL_OPENAI_API_KEY` (opcional).
- Servidor local: indique la URL compatible con OpenAI incluyendo `/v1`, por ejemplo `http://127.0.0.1:1234/v1` (LM Studio) o `http://localhost:11434/v1` (Ollama). Si ingresa solo host y puerto, la app agrega `/v1` automáticamente. Los proveedores remotos siempre usan sus endpoints oficiales.
- **Probar conexión** hace una solicitud mínima al modelo y puede consumir cuota.
- Límites: 90 segundos para proveedores remotos y 5 minutos para servidores locales.
- Las conexiones HTTPS usan el almacén de certificados del sistema mediante `truststore`, por lo que los certificados raíz corporativos instalados se respetan sin desactivar la validación SSL.
- Una respuesta de IA que borre referencias originales, invente variables, modifique directivas de Velocity o aparezca truncada se rechaza antes de guardarse. El backend valida además que la respuesta contenga `subject`, `body` y `changes`.

## Preparar y publicar en ISC

Una adaptación vigente y validada habilita **Descargar JSON para ISC** y **Publicar en ISC**. Ambas acciones comienzan eligiendo expresamente un tenant destino (nunca se deduce del origen):

1. **Preparar y comparar** (solo lectura): busca en el destino la personalización o el default correspondiente a `key + medium + locale` y muestra contenido actual, contenido adaptado, validaciones y referencias pendientes.
2. Opcionalmente descargue el JSON de publicación.
3. Confirme **Publicar en ISC**. Antes del POST se vuelve a consultar el destino: si cambió desde la preparación, se cancela. Justo antes de escribir se guarda un respaldo local del contenido actual del destino.
4. Después del POST se relee el destino y se informa el resultado: **publicada y verificada**, **publicación · verificación pendiente**, **publicada con diferencias** o **resultado no confirmado**.

El payload conserva `from`, `replyTo`, nombre y descripción del destino, aplica únicamente `subject` y `body` de la adaptación y omite IDs del tenant origen, fechas internas, `header` y `footer`. Nunca se reintenta un POST automáticamente tras un timeout: primero se consulta el destino. Los lotes son secuenciales, no transaccionales, y permiten reintentar solo las plantillas fallidas. La IA nunca recibe credenciales ni participa en la publicación.

Si cambia la adaptación, el branding o la conexión, las preparaciones existentes se invalidan y hay que preparar de nuevo.

## Modo de desarrollo

Use dos terminales solo mientras desarrolla. El backend debe arrancar desde `backend/` para que Python encuentre el paquete `app`:

```powershell
# Windows — Terminal 1
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend
npm.cmd run dev
```

```bash
# Linux — Terminal 1
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Abra [http://localhost:5173](http://localhost:5173); Vite redirige `/api` a FastAPI. El uso normal no usa Vite: FastAPI sirve el build compilado en [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Checks

Las dependencias de ejecución están en `backend/requirements.txt`. Para desarrollo y pruebas instale además `backend/requirements-dev.txt`:

```powershell
# Windows
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest --basetemp=.pytest_tmp
cd ..
cd frontend
npm.cmd run test
npm.cmd run typecheck
npm.cmd run build
```

En Linux use `.venv/bin/python` en lugar de `.venv\Scripts\python.exe` y `npm` en lugar de `npm.cmd`.

El lock `backend/requirements-portable-win-x64.txt` se usa exclusivamente al construir el ZIP y fija también las dependencias transitivas. No reemplaza `backend/requirements.txt` en desarrollo.

## Estructura del proyecto

- `backend/app/` — API FastAPI; cliente ISC (`isc.py`), publicación (`publication.py`), secretos (`isc_secrets.py`) y proveedores de IA (`providers/`).
- `backend/prompts/` — contrato técnico de adaptación y guías de estilo por proyecto.
- `backend/run.py` — arranque compartido por Windows y Linux. En desarrollo usa `logs/` y `.run/`; el lanzador portable los redirige a la ubicación de datos del usuario.
- `frontend/` — interfaz Vite + React; el build compilado queda en `frontend/dist` (ignorado por Git).
- `Iniciar app.cmd` / `Detener app.cmd` — usan `runtime/python.exe` cuando existe (portable) y `backend/.venv` en desarrollo; `Preparar entorno.cmd` prepara el checkout de Windows. Los scripts `.sh` mantienen el flujo Linux.
- `Empaquetar distribución.ps1` — construye y valida el ZIP portable Windows x64 sin copiar el `.venv` de desarrollo.
- `examples/` — notificaciones de ejemplo para probar sin conexión.

## Documentación de referencia

- Gemini: https://ai.google.dev/api y https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- Groq: https://console.groq.com/docs/api-reference y https://console.groq.com/docs/structured-outputs
- Anthropic / Claude: https://platform.claude.com/docs/en/api/messages/create y https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- OpenAI: https://developers.openai.com/api/docs/guides/structured-outputs
- LM Studio: https://lmstudio.ai/docs/developer/openai-compat
- Ollama: https://docs.ollama.com/api/openai-compatibility
- SailPoint, autenticación: https://developer.sailpoint.com/docs/api/authentication/
- SailPoint, parámetros de colecciones: https://developer.sailpoint.com/docs/api/standard-collection-parameters/
- SailPoint, rutas v1 de notificaciones: https://developer.sailpoint.com/docs/api/api-versioning-migration/
- SailPoint, `TemplateDto`: https://developer.sailpoint.com/docs/tools/sdk/python/notifications/models/templatedto/
- SailPoint, crear/personalizar una plantilla: https://developer.sailpoint.com/docs/tools/sdk/python/notifications/methods/notifications/#create-notification-template-v1
