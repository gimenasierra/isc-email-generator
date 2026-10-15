# ISC Email Generator

Aplicación web local para adaptar notificaciones exportadas de SailPoint ISC de un cliente a otro sin alterar sus metadatos y con controles específicos para Apache Velocity.

La aplicación permite elegir entre **Gemini, Groq, Anthropic / Claude, OpenAI, un servidor local compatible con OpenAI** (por ejemplo LM Studio u Ollama) y un proveedor **simulado**. Los proveedores con IA pueden interpretar branding, indicaciones de color, instrucciones generales y la guía Markdown del proyecto. El modo simulado no llama a una IA: aplica solamente reemplazos explícitos de cliente, logo, colores, correos y URLs.

## Inicio normal en Windows

Haga doble clic en **`Iniciar app.cmd`**. El lanzador:

- usa directamente `backend\.venv`, sin activar el entorno;
- inicia FastAPI solo en `127.0.0.1:8000`;
- espera a que la aplicación responda y abre el navegador;
- mantiene FastAPI ejecutándose como proceso local en segundo plano, sin depender de que una consola permanezca abierta;
- si ya existe una instancia de ISC Email Generator, abre esa instancia sin iniciar otra;
- si encuentra una versión anterior que perdió su archivo PID, identifica de forma segura el proceso exacto que escucha en `localhost:8000`, valida que corresponda a `backend\run.py` y lo reemplaza;
- deja los errores visibles y los registra en `logs\app.log`.

Puede cerrar la ventana del lanzador después de que se abra el navegador; FastAPI continúa en segundo plano. Para detener solamente esa instancia, haga doble clic en **`Detener app.cmd`**. El detenedor valida el PID —o recupera el proceso exacto por el puerto local cuando falta el PID—, el ejecutable del entorno virtual y `backend\run.py`; no finaliza otros procesos de Python.

## Preparación inicial o reparación

El arranque normal no instala ni compila dependencias. La forma más simple es ejecutar **`Preparar entorno.cmd`** una sola vez: crea `backend\.venv`, instala las dependencias y, si hace falta, compila el frontend (requiere Node.js 20 o superior solo en ese caso).

Alternativamente, desde la raíz:

```powershell
py -3 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm.cmd install
npm.cmd run build
```

Requiere Python 3.11 o superior para crear el entorno y Node.js 20 o superior para instalar o recompilar el frontend. Una vez preparado, el uso normal no necesita Node.js ni dos terminales.

## Distribución a otra PC Windows

Para compartir la aplicación sin instalar herramientas de desarrollo en el destino:

1. En este equipo, con `frontend\dist` ya compilado, ejecute:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "Empaquetar distribución.ps1"
   ```

2. Se genera `dist\isc-email-generator.zip` con el backend, el frontend compilado, los lanzadores y esta documentación. El ZIP **no** incluye `.venv`, `.env`, datos locales ni `node_modules`.
3. En la PC destino (solo requiere Windows y Python 3.11+): descomprima, ejecute **`Preparar entorno.cmd`** una vez y luego **`Iniciar app.cmd`**.

Cada usuario configura sus propias conexiones ISC y claves de IA desde la interfaz; esas credenciales se guardan en su `backend\.env` local y nunca se distribuyen.

## Modo de desarrollo

Para conservar recarga automática del frontend, use dos terminales solamente durante desarrollo:

```powershell
# Terminal 1, desde la raíz
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend
npm.cmd run dev
```

Abra [http://localhost:5173](http://localhost:5173). Vite redirige `/api` a FastAPI. El inicio normal usa [http://localhost:8000](http://localhost:8000) y sirve el build desde FastAPI.

## Flujo sugerido

1. Cargue `examples/notifications-with-velocity.json` o use **Cargar desde ISC**.
2. Abra el menú del engranaje y elija **Instrucciones y reglas**; indique el idioma de destino, el branding, la paleta o los mapeos compartidos que necesite y guárdelos.
3. Abra **Configuración de IA**, elija proveedor y modelo, guarde y pruebe la conexión.
4. Filtre y seleccione una notificación.
5. Genere la adaptación desde la barra de acciones.
6. Alterne entre la vista previa original y la adaptada; edite el resultado en modo **Visual** o **HTML** y revise diferencias, validaciones y referencias pendientes.
7. Descargue el objeto JSON personalizado.

Si las instrucciones y reglas cambian después de generar una adaptación, la aplicación marca ese resultado como desactualizado. No lo regenera ni sobrescribe automáticamente.

El idioma de destino predeterminado es **Español neutro**. La IA traduce únicamente el texto visible y conserva intactas las variables y directivas Velocity. Puede desactivar **Generar título visual si falta** o dejarlo activo para que la IA cree un único encabezado a partir del nombre de la plantilla, usando también el asunto y el contenido como contexto. `name`, `key`, `locale` y los demás metadatos nunca se modifican.

En **Instrucciones y reglas** también se habilitan las cuatro variables de fecha cuyo formato fue validado en ISC: `expires`, `dateRequested`, `startDate` y `removeDate`. No se pueden agregar nombres arbitrarios. Cuando el idioma de destino es español, el backend inserta junto a cada aparición visible un bloque Velocity determinista con 19 reemplazos de texto para los siete días y los doce meses. La llamada parte siempre de la referencia sin llaves —por ejemplo, `$expires.replace(...)`— y muestra el resultado mediante una variable descriptiva como `${fechaExpiracionEs}`. No usa `spTools`, no interpreta la fecha y conserva el día numérico, año, hora y `GMT`; por ejemplo, `Thursday 15 October 2026 (18:10:38 GMT)` se convierte en `jueves 15 octubre 2026 (18:10:38 GMT)` al ejecutarse en ISC.

El original importado nunca se altera. La adaptación se valida contra un cuerpo base preparado que se guarda por separado. La IA debe conservar literalmente cada bloque de fecha; una edición manual que lo modifique o elimine aparece en **Validación** y bloquea descarga y publicación hasta corregirla. Las adaptaciones creadas antes de esta función siguen validándose contra su original.

En **Aplicar guía de estilo**, la guía Markdown guardada se utiliza solamente para definir estructura visual, jerarquía, espaciado, colores, componentes y políticas editoriales. Sus ejemplos no autorizan contenido de negocio, variables ni enlaces nuevos. En **Conservar diseño actual**, se mantiene la estructura original salvo los cambios configurados y el título faltante cuando esa opción está activa.

El archivo descargado conserva todos los campos originales y cambia únicamente los campos editables de asunto y cuerpo. La vista previa se ejecuta en un `iframe` aislado, elimina scripts y atributos peligrosos, no ejecuta Velocity y no garantiza el render final en Outlook o Gmail.

### Edición visual segura

La pestaña **Editar asunto y HTML** abre inicialmente el modo **Visual**. Permite cambiar texto, negrita, cursiva, subrayado, tamaño, colores, alineación y la URL de enlaces existentes. No inserta imágenes, tablas, enlaces nuevos ni componentes estructurales. Variables, directivas y bloques deterministas de Velocity se muestran como etiquetas azules bloqueadas; el backend vuelve a validar el asunto y el cuerpo al guardar. Si una edición visual altera la lógica protegida, responde con un error sin sobrescribir la adaptación ni invalidar una preparación de publicación existente.

El modo **HTML** conserva el textarea avanzado y puede guardar con advertencias para reparar manualmente un resultado inseguro. Cuando el contenido contiene scripts, iframes, formularios, manejadores `on*` o URLs activas inseguras, el modo visual se deshabilita y debe usarse HTML. Ambos modos editan la misma copia adaptada; el original importado permanece inmutable.

## Cargar plantillas desde SailPoint ISC

La aplicación puede consultar plantillas **estándar** y **personalizadas** directamente desde ISC, siempre en modo de solo lectura:

1. Abra el menú del engranaje, elija **Conexiones ISC** y cree una conexión con nombre, entorno, URL base de API y credenciales PAT.
2. Use una URL exacta como `https://tenant.api.identitynow.com` o `https://tenant.api.identitynow-demo.com`. No se aceptan HTTP, puertos, rutas adicionales, parámetros, fragmentos ni credenciales dentro de la URL.
3. Guarde y pulse **Probar conexión**. Esta prueba autentica y verifica por separado el acceso de lectura a plantillas estándar y personalizadas.
4. En el panel izquierdo, pulse **Cargar desde ISC**, elija la conexión y el tipo de plantilla, consulte, filtre, seleccione e importe.

Las consultas usan OAuth 2.0 `client_credentials`, recorren todas las páginas con `limit=250` y `offset` y no envían filtros al endpoint de ISC. ISC puede devolver registros `EMAIL`, `SLACK` y `TEAMS` en la misma colección; la aplicación selecciona localmente únicamente `EMAIL` antes de mostrarlos. La selección por identidad también se realiza localmente sobre la respuesta completa. Ante un 401 se renueva el token una vez; los 429 respetan `Retry-After` con reintentos limitados.

Las APIs de notificaciones no publican scopes granulares llamados `idn:notification-*`. Para endpoints sin un scope granular definido, SailPoint indica usar `sp:scopes:all`; además, el usuario propietario del PAT debe tener un nivel de acceso que permita administrar notificaciones. Por eso, un 403 se informa como acceso denegado al endpoint correspondiente y no como la ausencia de un scope inventado.

Al importar, el original se guarda localmente junto con su procedencia: conexión, entorno, URL, tipo y fecha de lectura. Si ya existe la misma combinación `key + medium + locale`, puede:

- **Omitirla**, para conservar lo que ya está en el panel.
- **Reemplazar el original**, sin mezclar versiones y eliminando cualquier adaptación anterior después de mostrar una advertencia explícita.
- **Importar como copia**, para conservar ambas como elementos locales independientes. La copia recibe un identificador interno propio y queda marcada como **Copia local**, pero mantiene los metadatos ISC originales.

Las copias permiten comparar o adaptar variantes de una misma notificación sin perder trabajo. Como comparten el mismo destino ISC (`key + medium + locale`), la aplicación impide preparar o publicar dos copias del mismo destino dentro de un único lote; debe elegir cuál publicar.

La consulta e importación no realizan escrituras. La publicación es una operación separada, explícita y confirmada que se describe a continuación. La aplicación no contiene operaciones para eliminar plantillas en ISC, usar bulk-delete ni enviar emails de prueba.

## Preparar y publicar en ISC

Una adaptación vigente, revisada, sin referencias originales eliminadas, variables nuevas ni directivas modificadas habilita **Descargar JSON para ISC** y **Publicar en ISC**. Repetir una variable ya existente para mostrar la misma URL en un botón y en su enlace alternativo se informa para revisión, pero no bloquea estas acciones. Ambas comienzan eligiendo expresamente un tenant destino y consultando sus metadatos; la descarga principal ya no reutiliza los metadatos del tenant origen. La pantalla permite trabajar con una plantilla o seleccionar varias para un lote:

1. Elija expresamente la conexión destino; nunca se deduce a partir del tenant de origen.
2. Pulse **Preparar y comparar**. Esta etapa es de solo lectura: busca primero una personalización y luego el default mediante la combinación exacta `key + medium + locale`.
3. Revise tenant, ambiente, URL, identidad, contenido actual, contenido adaptado, validaciones y referencias pendientes.
4. Opcionalmente descargue **JSON para destino**. Este archivo contiene el payload de publicación y es distinto del JSON adaptado con metadatos de origen.
5. Confirme **Publicar en ISC**. La confirmación vuelve a mostrar el destino exacto.

El payload conserva `from`, `replyTo`, nombre y descripción del destino cuando existen; aplica únicamente `subject` y `body` de la adaptación revisada. Nunca copia el ID del tenant origen. Al reemplazar una personalización usa solamente el ID resuelto en el destino; al crear sobre un default omite el ID. También omite `created`, `modified`, propiedades internas, `header` y `footer`.

Antes de cada POST se vuelve a consultar el destino. Si cambió desde la preparación, se cancela y se exige preparar y revisar otra vez. Inmediatamente antes de escribir se guarda un respaldo local de la personalización actual o, si todavía no existe, del default de referencia junto con ese estado. Después del POST se consulta nuevamente el destino y se informa uno de estos resultados:

- **Publicada · verificación pendiente**: ISC aceptó el POST, pero la personalización todavía no apareció en la lectura posterior. Queda desmarcada y solo se ofrece volver a comprobar, sin repetir la escritura.
- **Publicada y verificada**: los campos publicados coinciden.
- **Publicada con diferencias**: ISC respondió pero la lectura posterior difiere.
- **Resultado no confirmado**: un timeout o problema de conexión impidió determinar el resultado.

Ante un timeout posterior al envío no se repite automáticamente el POST: primero se consulta el destino. Los lotes ejecutan un POST por plantilla, secuencialmente, no son transacciones y pueden quedar parcialmente completados. La interfaz conserva el resultado individual, desmarca y bloquea las publicaciones aceptadas, y permite reintentar únicamente las fallidas. Si luego cambia el asunto, el HTML o la configuración que produjo la adaptación, la nueva versión vuelve a habilitarse para preparación y publicación.

La publicación por lote utiliza el endpoint batch del backend, que deduplica `key + medium + locale`. Mientras prepara, publica, comprueba o descarga, el diálogo no puede cerrarse. La descarga se realiza dentro de la aplicación: si la preparación quedó desactualizada, se muestra el error 409 sin navegar a una página JSON.

Las preparaciones se invalidan si cambia la adaptación, el branding o la conexión correspondiente. La IA nunca recibe credenciales ni participa en la publicación, y el contenido no se regenera durante este proceso.

Autorización para preparar y publicar:

- Configurá el PAT con `sp:scopes:all`, ya que SailPoint no define actualmente scopes granulares para estos endpoints de notificaciones.
- El usuario propietario del PAT debe tener un nivel de acceso adecuado para consultar plantillas estándar y personalizadas y para crear personalizaciones.

**Probar conexión** valida la autenticación y consulta por separado ambos endpoints de lectura sin realizar una escritura. Un token puede autenticarse correctamente y aun así recibir un 403 si el usuario propietario no tiene acceso al recurso. La autorización de escritura se comprueba efectivamente cuando se confirma una publicación.

### Credenciales ISC

Los metadatos de cada conexión se guardan en el proyecto local. El PAT Client ID y Client Secret se escriben únicamente en `backend/.env`, codificados para evitar texto plano accidental, y nunca se devuelven al frontend, se agregan al JSON exportado ni se incluyen en logs. Dejar un campo de credencial vacío al editar conserva el valor actual. El archivo `.env` está ignorado por Git y se actualiza sin borrar otras variables existentes.

Puede usar [backend/.env.example](backend/.env.example) como referencia. No copie credenciales reales al repositorio. El access token vive solo en memoria, se reutiliza hasta poco antes de expirar y se invalida cuando cambia la configuración de la conexión.

Desde **Conexiones ISC** puede eliminar un tenant guardado. Esto quita únicamente la conexión y sus credenciales locales; las notificaciones ya importadas permanecen en el proyecto y no se modifica nada en SailPoint.

En el panel izquierdo, cada notificación muestra una **×** al pasar el cursor para eliminarla del proyecto local. El botón con icono de papelera, ubicado en el extremo inferior derecho del panel, elimina todos los originales y adaptaciones locales, pero conserva las conexiones y las configuraciones. Ambas acciones solicitan confirmación y nunca eliminan plantillas en SailPoint.

## Configuración de IA y claves

El proveedor, el identificador de modelo y la URL del servidor local se guardan en el JSON local del proyecto. Las API keys ingresadas desde la interfaz se conservan entre reinicios exclusivamente en `backend/.env`, codificadas y fuera de Git. **No se guardan en el proyecto, no se devuelven al frontend y no se escriben en logs ni exportaciones**. Un campo vacío conserva la clave actual; ingresar otra la reemplaza. También puede configurarlas manualmente mediante variables de entorno:

```powershell
$env:GEMINI_API_KEY = "..."
$env:GROQ_API_KEY = "..."
$env:ANTHROPIC_API_KEY = "..."
$env:OPENAI_API_KEY = "..."
$env:LOCAL_OPENAI_API_KEY = "..." # opcional
```

La interfaz solo informa si existe una clave; nunca permite leer la guardada. Las conexiones ISC se comportan igual: sus metadatos permanecen en el proyecto y su Client ID/Secret en `backend/.env`.

Para un servidor local, indique la URL OpenAI-compatible incluyendo `/v1`, por ejemplo `http://127.0.0.1:1234/v1` para LM Studio o `http://localhost:11434/v1` para Ollama. Si se ingresa solamente el host y puerto, la aplicación agrega `/v1` automáticamente. En LM Studio no use `/api/v1`: esa ruta corresponde a su API nativa, cuyo formato es diferente. El modelo se escribe como identificador configurable; la aplicación no fija un modelo único.

La URL base configurable se utiliza exclusivamente con **Servidor local compatible con OpenAI**. Groq, OpenAI, Gemini y Anthropic siempre usan sus endpoints oficiales; al cambiar desde un servidor local a un proveedor remoto, la URL local se descarta.

Las conexiones HTTPS de los proveedores remotos usan el almacén de certificados confiables del sistema operativo mediante `truststore`. Esto permite respetar certificados raíz administrados por TI en redes corporativas sin desactivar la validación SSL. Si un certificado corporativo no está instalado como confiable en Windows, la aplicación muestra un error específico y no continúa de forma insegura.

**Probar conexión** hace una solicitud mínima al modelo y puede consumir cuota. Un error no cambia automáticamente a otro proveedor. En servidores locales, el mensaje distingue problemas de conexión; los errores del servidor informan también si el modelo indicado no está disponible.

Las solicitudes a proveedores remotos tienen un límite de 90 segundos. Los servidores locales OpenAI-compatible disponen de hasta 5 minutos, porque el procesamiento inicial del prompt y la generación en CPU/GPU local pueden ser considerablemente más lentos. Si se alcanza ese límite, simplifique la guía de estilo o use un modelo más rápido.

Los adaptadores solicitan salida estructurada cuando el endpoint/modelo la admite. Si el proveedor responde que ese formato no está soportado, se solicita JSON normal al mismo proveedor y se valida localmente que contenga `subject`, `body` y `changes`. Las validaciones posteriores de Velocity, metadatos y referencias pendientes se aplican igual a todos los proveedores.

Para una adaptación con Gemini, el backend consulta `outputTokenLimit` del modelo seleccionado y reserva hasta 32K tokens de salida. También inspecciona `finishReason`: si Gemini informa `MAX_TOKENS` u otra interrupción, la respuesta parcial se rechaza con un motivo específico antes de validar o guardar el contenido. La aplicación sigue realizando una sola generación y no intenta reparaciones automáticas.

Para los modelos GPT-OSS servidos por Groq, la aplicación solicita razonamiento bajo y excluye el razonamiento de la respuesta. Así reserva la salida para el JSON final que necesita la adaptación; esta opción no se envía a modelos o proveedores que no la admiten.

Una respuesta de IA que elimine referencias originales, invente nombres de variables, modifique directivas Velocity o cuyo cuerpo parezca truncado se rechaza antes de guardarse. Las repeticiones adicionales de variables existentes se separan de las variables inventadas: quedan señaladas para revisión y aparecen como advertencia de publicación, pero se permiten para casos legítimos como un botón acompañado por la misma URL de respaldo. Esta protección sigue siendo una validación sintáctica, no una garantía de equivalencia funcional.

### Contrato técnico y guías de estilo

El contrato técnico común vive en `backend/prompts/adaptation_rules.md` y siempre se aplica. Define la conservación de metadatos y Velocity, la fuente autorizada del contenido y el formato JSON de salida; una guía de proyecto nunca lo reemplaza.

En **Instrucciones y reglas** puede elegir **Conservar diseño actual** o **Aplicar guía de estilo**. El segundo modo permite cargar, editar, guardar, reemplazar o limpiar una guía Markdown propia del proyecto. La guía se guarda como `backend/prompts/projects/<project_id>.md`, se relee en cada generación y tiene un límite de 100 KB. No debe contener claves ni credenciales.

Antes de enviarla a la IA, el backend neutraliza variables y directivas Velocity de ejemplo y retira URLs o correos. Conserva las reglas, el HTML estructural, los estilos inline, colores y textos de política. Los campos explícitos de **Instrucciones y reglas**, sus mapeos y las instrucciones adicionales prevalecen sobre la guía.

Cambiar o eliminar una guía no regenera ni sobrescribe resultados: marca las adaptaciones existentes como desactualizadas e invalida preparaciones de publicación. El modo guía no permite generar hasta que exista una guía guardada. La plantilla original continúa siendo la única fuente autorizada de contenido funcional.

Documentación oficial consultada:

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

Los adaptadores están verificados con respuestas simuladas. Las conexiones reales quedan pendientes hasta que exista una credencial válida o un servidor local iniciado con el modelo configurado.

## Checks

Las dependencias de ejecución están en `backend/requirements.txt`. Para desarrollar o ejecutar pruebas instale además `backend/requirements-dev.txt`:

```powershell
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest --basetemp=.pytest_tmp
cd ..

cd frontend
npm.cmd run test
npm.cmd run typecheck
npm.cmd run build
```

## Estructura extensible

`backend/app/providers/base.py` define el contrato común de IA y el resultado normalizado. Los adaptadores HTTP y el registro desacoplado están en `backend/app/providers/`. El cliente ISC, incluida la autenticación y los reintentos controlados, está aislado en `backend/app/isc.py`; la preparación, respaldo y verificación de publicaciones viven en `backend/app/publication.py`; y los secretos se manejan en `backend/app/isc_secrets.py`.

