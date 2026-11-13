# ADR 0003 — El documento de un lab tiene dos regiones, y los punteros se vigilan

<!-- PROPÓSITO: resolver la fricción entre una plantilla rígida y un documento libre.
     INVARIANTES: un solo escritor por región. Los datos se regeneran; la prosa se
     revisa.
     LÍMITES: ningún check opina sobre el contenido de la prosa.
     VER: README.md §Documentación; AGENTS.md §Documentación -->

**Estado:** aceptada.

**Contexto.** El intento anterior metía la prosa dentro de una plantilla Jinja: el
documento no era ni libre ni comprobable, y tenía dos escritores. La tentación
contraria --una wiki sin estructura-- es peor: nadie la mantiene al día.

**Decisión.** Un documento, dos regiones. Entre los marcadores `generado:inicio` y
`generado:fin`, sólo tablas derivadas de la declaración, escritas por
`deployment_engine/tools/documentos.py`: **prohibido escribirlas a mano**, y el check
`docs` falla si el fichero difiere de su render. Fuera de los marcadores, prosa
libre, y **ningún check opina sobre ella**.

**Por qué.** Lo que chocaba no era "plantilla contra libertad": eran **dos escritores
sobre el mismo fichero**. Separados, cada uno puede ser estricto a su manera. Los
datos no envejecen porque se regeneran; la prosa no envejecen porque se revisa con un
aviso de caducidad (el sellado por hash), no con un render.

**Consecuencia.** Tres guardas mecánicas, y una frase que las justifica: *una
afirmación de comportamiento que puede ser un check, no se queda en prosa*. Los
enlaces del documento al código se comprueban (`links`); el sellado dice qué prosa ha
dejado de estar revisada (`refs`); y el hook `pre-commit` **bloquea** lo que es un
hecho mecánico (región generada desincronizada) y sólo **avisa** de lo que exige
criterio (caducidad).
