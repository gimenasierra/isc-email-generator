# Guía de estilo de correo — Assertiva

## 1. Alcance y prioridad

Aplicar esta guía solo a presentación, tono y componentes visuales. El contenido funcional proviene exclusivamente de la plantilla original. Rigen primero el contrato técnico y la configuración explícita del proyecto; los mapeos e indicaciones de **Instrucciones y reglas** prevalecen sobre esta guía.

No crear ni inferir variables, enlaces, correos, rutas, estados, soporte o datos de negocio. Conservar íntegros el contenido, orden y lógica del original; los ejemplos conceptuales de esta guía no aportan contenido.

## 2. Estructura obligatoria

Usar un único contenedor principal con estos valores exactos:

- `max-width:650px; margin:0 auto; background-color:#ffffff; padding:30px`
- `border:1px solid #dddddd; border-radius:5px`
- `box-shadow:0 2px 5px rgba( 0 , 0 , 0 , 0.05 )`

Orden: logo, título, saludo y contenido completo original, firma, footer.

- **Logo:** URL literal configurada, alineado a la derecha dentro de un bloque con `text-align:right; margin-bottom:20px`; imagen con `margin-left:auto` y `width:80px`.
- **Título:** un solo `h2` con `color:#0079c1; border-bottom:2px solid #0079c1; padding-bottom:10px; margin-top:0`.
- **Cuerpo:** texto base `14px`, color `#333333` y altura de línea legible.

## 3. Idioma y título

Usar español neutro, claro y profesional cuando sea el idioma configurado. Mantener asunto y título breves: si el original es una frase nominal, traducirlo como frase nominal, sin convertirlo en una explicación del cuerpo. El título debe describir el tipo de aviso, preferentemente en 2–6 palabras.

Si falta título visual y su generación está habilitada, derivarlo únicamente del nombre de la plantilla y traducir su significado, sin inventar información. Respetar el saludo y tratamiento configurados.

Traducir por significado, no palabra por palabra. Se puede reordenar únicamente el texto visible dentro de la misma rama para que suene natural, conservando significado, datos, variables y lógica.

- Para introducir una fecha traducida, preferir “Le informamos que el día [FECHA]…” o una construcción natural equivalente. Evitar “El [FECHA]…”.
- Omitir calcos redundantes de `now` o `currently` cuando el presente verbal ya expresa actualidad.
- Preferir “El sistema se encuentra procesando la solicitud” o “El sistema está procesando la solicitud”, sin agregar “ahora”.
- No crear bloques Velocity para traducir fechas. La aplicación ofrece esa transformación como un postproceso separado después de la adaptación.

## 4. Paleta

| Uso | Color |
|---|---|
| Principal | `#0079c1` |
| Fondo principal / informativo / nota | `#ffffff` / `#f4f8fb` / `#fafafa` |
| Texto principal / secundario / auxiliar | `#333333` / `#555555` o `#666666` / `#999999` |
| Bordes | `#dddddd`, `#eeeeee` o `#cccccc`, según el componente |
| Éxito | `#28a745` |
| Error | `#d9534f`, fondo `#fff3f3` |
| Advertencia | `#8a6d3b`, borde `#f0ad4e`, fondo `#fff9e6` |

Reservar verde, rojo y ámbar para estados expresados explícitamente en el original; no usarlos como decoración ni inferir estados.

## 5. Componentes

Aplicar un componente solo si el contenido original justifica su función. Nunca agregar mensajes para completar el diseño.

### 5.1 Información y estados

- **Información:** `background:#f4f8fb; border-left:4px solid #0079c1; padding:15px; margin-bottom:20px; border-radius:0 4px 4px 0`.
- **Éxito/aprobación:** `background:#f4f8fb; border-left:4px solid #28a745; padding:15px; margin-bottom:20px; border-radius:0 4px 4px 0`; texto general `#333333` y palabra de estado `#28a745` en negrita.
- **Advertencia:** igual estructura con fondo `#fff9e6`, borde `#f0ad4e` y texto `#8a6d3b`.
- **Error/rechazo:** igual estructura con fondo `#fff3f3`, borde y texto `#d9534f`.

Estos bloques son obligatorios cuando el original expresa el caso correspondiente; no reemplazarlos por una palabra coloreada dentro de un párrafo sin recuadro:

- Resultado aprobado o exitoso: bloque de éxito verde.
- Resultado denegado, rechazado o fallido: bloque de error rojo.
- Fecha programada de inicio o activación: bloque informativo azul.
- Fecha programada de finalización, remoción o vencimiento: bloque de advertencia amarillo.

Encerrar el párrafo funcional completo dentro del bloque, no solo la palabra o la fecha. Mantener el bloque dentro de la misma rama condicional del original y conservar literalmente sus directivas, variables y significado.

### 5.2 Código, token o identificador central

Si el original presenta un OTP, código de verificación, token o nombre de usuario como dato central, mostrarlo en una caja centrada: bloque exterior `text-align:center; margin:30px 0`; dato con `background:#f4f8fb; color:#0079c1; border:2px dashed #0079c1; padding:15px 30px; font-size:24px; font-weight:bold; border-radius:4px`.

Usar `letter-spacing:5px` solo para códigos numéricos cortos y `2px` para identificadores alfanuméricos largos. Reutilizar únicamente el dato original; no convertir datos ordinarios en códigos.

### 5.3 Variables visibles en negrita

En el texto visible del cuerpo, envolver únicamente cada referencia Velocity que representa un dato con un solo `strong`, incluidas las ramas condicionales y las referencias visibles usadas en la firma o en el nombre del producto. Conservar token, cantidad, posición y directivas.

Excepciones:

- No agregar otro `strong` si el dato ya aparece dentro de un `strong` por su contenedor, título, botón o línea de firma. La mera ubicación dentro de una firma no cuenta como negrita.
- No destacar referencias dentro de directivas, expresiones de control ni atributos (`href`, `src`, `style`).
- El enlace visible de respaldo conserva su estilo de enlace, no negrita.
- Si el dato visible es una expresión dinámica compuesta por varios tokens y segmentos literales, envolver la expresión completa en un solo `strong`; nunca destacar solo una parte ni alterar segmentos.

### 5.4 Botón con enlace de respaldo

Un enlace dinámico original puede convertirse en CTA y repetirse como respaldo usando literalmente el mismo destino completo. No inventar ni modificar variables, rutas o lógica.

- Si el original muestra una instrucción y luego la URL, reemplazar ese fragmento por un único CTA: conservar una vez la instrucción útil, sin la URL, antes del botón. No dejar otro enlace independiente arriba.
- **Botón:** contenedor `text-align:center; margin:30px 0`; enlace con `background:#0079c1; color:#ffffff; padding:12px 25px; text-decoration:none; border-radius:4px; font-weight:bold; box-shadow:0 2px 4px rgba( 0 , 0 , 0 , 0.1 )`.
- **Respaldo:** inmediatamente debajo, centrado, `color:#666666; font-size:12px`; aclaración en cursiva, salto de línea y luego un enlace clickeable subrayado en `#0079c1`.
- En botón y respaldo, tanto `href` como texto visible deben copiar exactamente la misma expresión de destino original. El destino solo queda visible en el respaldo.

La transformación no puede eliminar el significado de una instrucción funcional.

### 5.5 Nota de seguridad o soporte

Solo si el original ya contiene una advertencia de seguridad, una pregunta equivalente a “no solicitaste esto” o información de soporte, ubicarla antes de la firma con `background:#fafafa; border:1px dashed #cccccc; padding:15px; margin-top:30px; border-radius:4px; color:#555555; font-size:13px; text-align:center`.

Conservar contactos, correos y URLs exclusivamente del original o de mapeos explícitos.

### 5.6 Listas y comentarios

- Listas originales: `font-size:14px; color:#333333; line-height:1.5; margin-top:0; padding-left:20px`; conservar todos sus elementos y lógica.
- Si el original atribuye un comentario, poner solo el nombre visible en negrita y el comentario en cursiva.
- No crear listas ni comentarios cuando no existan en el original.

## 6. Firma y footer

Si existe firma original, conservarla y adaptar solo referencias explícitamente autorizadas. Usar la firma configurada únicamente cuando falte; nunca duplicarla.

Presentar la despedida en texto normal y la línea de identificación del equipo en negrita, envolviendo la línea completa en un único `strong`. Si esa línea contiene una referencia Velocity visible —incluido el nombre dinámico del producto—, debe quedar dentro del mismo `strong`; no dejar la referencia fuera ni aplicarle negrita parcialmente.

Agregar al final este footer literal:

> Este es un correo generado automáticamente por el sistema de Gestión de Identidades de Assertiva.

Estilo: `font-size:11px; color:#999999; text-align:center; border-top:1px solid #eeeeee; padding-top:10px`.

## 7. Control final

Antes de responder, comprobar que:

1. Se conserva todo el contenido funcional y su orden.
2. No se agregaron datos, destinos, contactos ni estados.
3. Los componentes usan los valores definidos y solo cuando corresponden.
4. Las expresiones dinámicas visibles están completas y los destinos del CTA coinciden literalmente con el original.
5. No se duplicaron instrucciones, enlaces, firma ni contenido.
