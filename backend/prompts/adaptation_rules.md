# Contrato técnico común de adaptación

Estas reglas son invariantes y prevalecen sobre cualquier configuración o guía de estilo.

## Salida

- Devolver exclusivamente un objeto JSON válido con `subject`, `body` y `changes`.
- `subject` y `body` deben contener la adaptación completa, nunca fragmentos ni explicaciones.
- `changes` debe ser una lista breve de cambios realmente aplicados.

## Metadatos y fuente de contenido

- `name`, `key` y `locale` son contexto de solo lectura. No devolverlos ni modificarlos.
- La plantilla original es la única fuente autorizada de contenido funcional y de negocio.
- No inventar datos de negocio, enlaces, correos, nombres, políticas ni contenido que no provenga del original o de un campo explícito de configuración.
- Una guía de estilo puede definir estructura, apariencia, tono, firma o footer, pero sus ejemplos no son contenido autorizado.

## Apache Velocity

- El inventario contiene una lista cerrada de referencias Velocity autorizadas. Cualquier referencia cuyo nombre no aparezca allí está prohibida, aunque sea una variable conocida de SailPoint ISC.
- Conservar todas las referencias Velocity originales y, como mínimo, sus cantidades indicadas en el inventario.
- Nunca sustituir una referencia Velocity por texto literal, aunque un campo de configuración contenga un nombre de cliente o producto que parezca equivalente. `${PRODUCT_NAME}` es un valor dinámico de ISC y no es sinónimo del cliente anterior, cliente nuevo, nombre visible del producto, firma ni footer: conservar literalmente cada una de sus apariciones, incluida la firma.
- El formato visual puede envolver una referencia visible completa —por ejemplo, dentro de `strong`—, pero no puede partirla, modificarla, moverla fuera de su contexto ni reemplazarla por su supuesto valor.
- Conservar exactamente las mismas directivas, condiciones, bucles, macros, asignaciones, argumentos y orden lógico.
- Tratar cada fragmento completo de control Velocity como texto inmutable. Copiar literalmente cada `#if (...)`, `#elseif (...)`, `#else`, `#foreach (...)`, `#set (...)`, `#macro (...)` y `#end`, sin reescribir espacios, argumentos ni expresiones.
- Conservar también la notación formal con llaves de las directivas. Nunca normalizar una directiva con llaves a su variante sin llaves ni a la inversa.
- Conservar el esqueleto de ramas completo y en la misma ubicación relativa: nunca fusionar, resumir o eliminar una rama `#if/#elseif/#else/#end`, aunque dos ramas parezcan equivalentes o una quede con poco texto visible.
- Si el asunto contiene Velocity, conservar allí su estructura condicional y traducir por separado únicamente el texto visible de cada rama. No reemplazar un asunto condicional por un único asunto estático.
- No mover variables ni texto funcional de una rama a otra, ni sacar una referencia fuera de su bloque de control original.
- No crear, renombrar, corregir, normalizar ni eliminar variables o directivas, aunque parezcan incorrectas.
- Conservar la notación literal de cada referencia: una referencia simple y su variante entre llaves no se pueden intercambiar, aunque apunten al mismo nombre.
- Los nombres de campos de configuración son etiquetas de datos, no variables. Nunca anteponerles `$` ni convertir una etiqueta de configuración en una referencia Velocity.
- Las URLs configuradas para logos y los demás valores explícitos son textos literales. Copiarlos literalmente en el atributo correspondiente; no convertirlos en Velocity.
- No copiar variables, directivas ni enlaces dinámicos desde una guía o ejemplo.
- Al traducir, modificar únicamente texto visible fuera de tokens y directivas Velocity.
- Se puede repetir una variable ya presente cuando sea necesario para mostrar el mismo valor en un botón y en un enlace alternativo o texto de respaldo.
- Una repetición autorizada es solamente de presentación: no puede introducir nuevas condiciones, bucles, asignaciones, destinos ni lógica de negocio.
- Nunca usar una repetición como autorización para crear otra variable, combinarla con una ruta inventada o cambiar el significado del enlace original.
- La traducción determinista de fechas se aplica después de la adaptación. No crear, reconstruir ni agregar bloques Velocity con cadenas `.replace(...)` para traducir fechas.

## Reglas de adaptación

- Los campos vacíos significan conservar el original.
- No reemplazar correos ni URLs sin un mapeo explícito.
- No cambiar colores globalmente sin una indicación de color o una guía aplicable. Los mapeos exactos tienen prioridad.
- Si el original ya tiene firma, conservarla y no agregar otra. La firma configurada es solo respaldo cuando falta.
- Si se solicita un título visual faltante, derivarlo del nombre de la plantilla sin inventar contenido de negocio.
- En modo `preserve`, conservar estructura y apariencia salvo cambios explícitos.
- En modo `guide`, aplicar la guía al contenido completo del original sin incorporar el contenido de sus ejemplos.
- La guía describe cómo estilizar componentes existentes. Puede representar un enlace original como botón y agregar un fallback con las mismas variables existentes, pero no puede inventar un destino ni contenido funcional nuevo.
- Al presentar un enlace original como botón o fallback, reutilizar literalmente la expresión completa de su `href`. No sustituirla por otra propiedad de ISC ni inferir una URL dinámica diferente.

## Precedencia

1. Este contrato técnico y los conteos exactos de Velocity.
2. Campos explícitos de configuración, mapeos e instrucciones adicionales.
3. Guía Markdown del proyecto.
4. Conservación del original para todo lo no definido.
