# 0034 · El API REST del vigilante: se carga, y se queda dentro

- **Fecha:** 19-nov-2026
- **Estado:** aceptada
- **Contexto:** `servicio: netxms` del área `servicio` (ADR 0028) y la vigilancia
  del lab 08.

## La decisión

1. **El servidor carga el módulo `webapi`** (`Module = webapi` en
   `/etc/netxmsd.conf`, con su sección `[WEBAPI]`: `Enable = yes`,
   `Address = loopback`, `Port = 8000`). Sin él, NetXMS sólo trae el **núcleo**
   del API —`/v1/login`, el que usa el motor para entrar— y los **recursos**
   (`/v1/objects`, `/v1/alarms`, `/v1/info`…) contestan **404**. Medido en el
   `ctl-2` del 08 antes de este cambio: `/v1/login` contestaba 405/403 (vivo) y
   `/v1/objects` daba 404 con el módulo presente en disco y sin cargar.
2. **El API se queda en loopback.** `Address = loopback` es explícito, no la
   ausencia de configuración: la única puerta del API es el token, y no se
   publica a Internet por eso. Quien lo use entra **por un túnel SSH**, que es lo
   que ya hace el motor con la consola del bastión (ADR 0010) y con el REST de
   los routers.
3. **La lectura prueba el API, no el fichero.** `estado` pregunta por
   `/v1/objects` y exige 401/403 (módulo cargado, pide token): 404 es «sin
   módulo» y `000` es «no contesta». El fichero dice lo que se **pidió**; la
   respuesta dice lo que el servidor **cargó**, y sólo la segunda es prueba.
   Hay un verbo nuevo, `api`, que imprime ese `si`/`no` sin tocar nada.
4. **El reinicio va donde tiene que ir, y detrás el arreglo de la clave.** El
   módulo se lee **sólo al arrancar**, así que si falta, `preparar` **reinicia**
   el servidor —una vez, sólo cuando falta—. Y detrás de un arranque está la
   trampa ya medida (ADR 0033): el paquete reescribe el hash del administrador a
   una forma que no verifica. Por eso el orden es siempre *reiniciar → preguntar
   → reponer la clave buena → volver a preguntar*, nunca al revés. Un arranque
   de más fue lo que dejaba la clave rota en cada pasada; ahora el arranque tiene
   motivo (falta el módulo) y cola (la clave se repone acto seguido).

## Por qué así

- **Cargar el módulo no es un extra: es lo que la documentación llama «el API
  REST».** La página de integración describe los recursos y dice cómo cargarlos;
  dejar el servidor sin el módulo deja un API de mentira, que contesta al
  `login` y nada más. Un servicio que se declara «netxms» tiene que quedar como
  la doc dice que se instala.
- **Loopback y túnel, no TLS expuesto** (y no `Address = any` + proxy TLS
  delante): el API mueve inventario, alarmas y DCIs de **todo** el lab, y su
  única credencial es un token de sesión. El túnel SSH aporta lo que el API no
  tiene — autenticación por clave, canal cifrado y **ningún puerto abierto** en
  la red del lab ni en la del nodo. Es la misma regla que ya gobierna la consola
  del bastión y el REST de los routers: se entra, no se publica.
- **El 401 como prueba** evita el fallo silencioso clásico: `estado` mirando el
  fichero diría «convergido» con el módulo sin cargar (el fichero está bien) y
  nadie volvería a preparar. Medido: pasó exactamente eso.
- **Los recursos del vigilante** suben a **4 GB de RAM y 20 GB de disco** en la
  declaración del 08. Los 4 GB no son un gusto: son el mínimo que publica la
  documentación de requisitos para un servidor de hasta 500 nodos; el contenedor
  había nacido con 1,5 GB y 6 GB, por debajo incluso para doce equipos (la base
  crece con el histórico). Los 50 GB de la doc son para 500 nodos: aquí no se
  copian, se dice por qué (ver la prosa del lab).

## Cómo se usa (receta, sin exponer nada)

Desde la máquina que tenga la clave de depuración del nodo:

```
# 1) el túnel: el 8000 del vigilante, en tu 8000 local. El `-L` se resuelve en el
#    SALTO FINAL, y el API escucha SÓLO en el loopback de ESE invitado: apuntar a su
#    dirección de gestión (`10.44.0.20:8000`) da conexión rechazada -- medido --. Por
#    eso el último salto termina DENTRO del vigilante y desde ahí se pide 127.0.0.1.
ssh -N -L 8000:127.0.0.1:8000 -J root@<nodo-de-proxmox> root@<vigilante>

# 2) el token (el login es el núcleo del API; las credenciales son las del
#    administrador del servicio, las mismas con las que el motor entra)
curl -s -X POST http://127.0.0.1:8000/v1/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"<admin>","password":"<clave>"}'

# 3) los recursos, con el token
curl -s -H "Authorization: Bearer <token>" http://127.0.0.1:8000/v1/objects
```

El token caduca (TTL por defecto de NetXMS): al caducar, se vuelve a pedir. La
receta no lleva credenciales escritas a propósito.

## Consecuencias

- El área `servicio` de NetXMS gobierna, además de la base y la web, **el
  módulo del API**: tres ficheros y cuatro preguntas (esquema, web, login y
  recursos).
- `netlabs-servicio-netxms` gana el verbo `api` (sólo lectura). `estado` lo usa
  y `preparar` reinicia cuando falta.
- Un `apply` sobre un invitado ya desplegado **reinicia el servidor una vez**
  (para cargar el módulo) y repone la clave en la misma pasada: el ciclo sigue
  cerrando en una sola vuelta.
- La web (`nxmc`) sigue siendo la puerta de la interfaz; el API no la sustituye
  ni la toca.
