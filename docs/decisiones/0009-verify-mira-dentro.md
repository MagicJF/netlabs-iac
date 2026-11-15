# ADR 0009 — `verify` mira DENTRO: el driver del interior aprende un modo «sólo leer»

<!-- PROPÓSITO: dejar escrito por qué `verify` relee el interior de cada invitado con el
     MISMO driver que `apply` (en modo sólo lectura) en vez de con un código aparte, y por
     qué la garantía de «verify no escribe» vive en la PUERTA, no en la memoria del driver.
     Nace de una pared MEDIDA: la primera versión de `verify` saltó el interior entero y
     aun así dio CORRECTO, porque el túnel no respondía y no había nada que leer.
     INVARIANTES: comprobar no cambia el mundo (regla 6): en `solo_leer` el driver corta
     antes de su sección de escribir y la vía de acceso de RouterOS SÓLO atiende GET — y si algo
     pide escribir, PARA diciendo que es un bug del driver. La decisión de qué falta la
     toma la MISMA función pura que usa `apply` (`pasos_de_convergencia`): no hay dos
     verdades sobre qué es «estar convergido». No se aprueba lo que no se ha mirado: un
     invitado que no se pudo leer (o con el túnel caído) cuenta como NO conforme.
     LÍMITES: `verify` NO construye el túnel (eso es de `apply`); si el túnel no responde,
     los invitados quedan «no comprobable» y el veredicto CAE, no se levanta nada aquí.
     Sólo se mira dentro de quien declara áreas que piden visita: a un puesto dinámico no
     hay nada que preguntarle. No cubre todavía el interior de los invitados de la fase 1
     (no declaran `config`).
     VER: deployment_engine/playbooks/verify.yml,
     deployment_engine/tasks/interior_verificar.yml,
     deployment_engine/tasks/configurar_linux.yml (interior_solo_leer, interior_seguir),
     deployment_engine/tasks/configurar_routeros.yml, deployment_engine/tasks/ros_api.yml
     (la red de seguridad), deployment_engine/filter_plugins/interior.py
     (invitados_a_verificar, informe_ok, sin_comprobar),
     deployment_engine/filter_plugins/estado.py (estado_informe_texto) -->

**Estado:** aceptada; medida contra el VPS (lab de aceptación: `verify` CORRECTO con «3/3
invitado(s) leído(s) por dentro y coincidente(s)» y **cero** escrituras en el diario).

**Contexto.** `apply` convergía el interior (RouterOS por su REST, Linux por SSH) y lo
comprobaba releyendo al final, pero `verify` sólo miraba el **mundo de la API**: el pool, la
configuración del hipervisor, si el invitado está arrancado. Un invitado podía existir,
coincidir por fuera y estar mal por dentro, y `verify` daba CORRECTO. «Lo de dentro
comprobado dentro» no estaba cubierto.

**Decisión.** `verify` **relee el interior** de cada invitado que declara `config` con áreas
que piden visita, usando el **mismo driver** que `apply` con una variable nueva,
`interior_solo_leer` (por defecto `false`). No es un código aparte a propósito: si hubiera
dos lecturas, habría dos verdades sobre qué es «estar convergido». Los tramos de **lectura**
de los dos drivers ya eran puros (GETs del REST; comandos de lectura por SSH) — las
escrituras empiezan después—, así que el modo sólo lectura **corta** las secciones de
escribir y releer, y deja la decisión (`pasos_de_convergencia`, la misma función pura) en
manos de `verify`.

**Por qué la garantía vive en la PUERTA.** La primera implementación puso la guarda en el
driver y **`verify` escribió**: el `when` usaba `interior_seguir` (cierto cuando la lectura
FUNCIONA) en vez de «no estar en sólo lectura». Una guarda olvidada en un driver volvería a
escribir. Por eso la frontera se movió a la gateway: en `solo_leer`, `ros_api.yml` **sólo
atiende GET** y cualquier otra cosa **PARA** con un mensaje que dice, en claro, que es un bug
del driver y no de la declaración. Un invariante que depende de que alguien se acuerde no es
un invariante.

**Consecuencias.** `verify` da un veredicto **único** (un solo `ok`) que mezcla los dos
mundos: si el interior no se pudo leer —túnel caído, invitado inalcanzable— cada rol queda
**«no comprobable»** con su motivo y el veredicto **cae**: no se aprueba lo que no se ha
mirado. El resumen humano gana la sección `EL INTERIOR (n/m …)`. Coste: `verify` ahora
necesita el túnel en pie (lo levanta `apply`) y tarda un poco más; a cambio, deja de poder
dar CORRECTO sobre un lab que por dentro está mal.
