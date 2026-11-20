# 0036 · NetBox como servicio: el inventario, y su web publicada por el túnel

- **Fecha:** 20-nov-2026
- **Estado:** aceptada
- **Contexto:** el lab necesita un **inventario** (NetBox) y que sea **alcanzable desde
  fuera** del lab. Hasta hoy el vocabulario cerrado de servicios de un Linux tenía dos
  miembros (`caddy` y `netxms`, ADR 0027/0028), y el túnel del bastión sólo sabía publicar la
  consola del propio bastión y el REST (80) de cada RouterOS.

## La decisión

1. **`netbox` entra en el vocabulario cerrado de `servicio:`.** El lab escribe
   `servicio: netbox` y nada más: ni paquete, ni base, ni puerto, ni versión (regla 7). La
   validación sigue rechazando cualquier nombre que no esté en la lista.
2. **En su propio invitado, no en el bastión.** NetBox es Django + PostgreSQL + Redis +
   gunicorn + nginx: meterlo al lado de NetXMS en 2 GB es pedirle al kernel que elija a quién
   matar. Se declara un `srv` más (2 núcleos, 4 GB, 16 GB de disco).
3. **Instalación nativa, no Docker.** La vía cómoda sería `netbox-docker`, y está prohibida
   por la misma razón que todo lo demás: un contenedor dentro de un LXC pide *nesting* y un
   invitado privilegiado, que este motor no crea (ADR 0004). El preparador instala el
   andamiaje con APT, clona la versión fija en `/opt/netbox`, monta su entorno virtual,
   escribe la configuración, crea la base y el administrador, y levanta gunicorn y nginx.
   **Cada pieza deja su marca** (`/var/lib/netlabs-netbox/`): repetir una pasada no reinstala.
4. **Sirve en el 8080 del invitado, y `sirve` es ENTRAR.** La comprobación del área pide
   `http://127.0.0.1:8080/login/` y exige cuerpo: un gunicorn vivo al que no se puede entrar
   no es un servicio que sirva (la lección del WAR de NetXMS, ADR 0034).
5. **La web se publica por el túnel del bastión, con el puerto DERIVADO del vmid.** Es la
   misma mecánica que ya reenvía el REST de cada RouterOS (ADR 0010): el bastión abre
   `-R <puerto>:<equipo>:8080` y el sshd del nodo de control lo autoriza con `permitlisten`.
   La banda es **22000+**, que no pisa la del túnel (20000+) ni la del REST (21000+). El lab
   **no guarda puertos** (regla 11): se vuelven a derivar leyendo la declaración.

## Por qué así

- **Porque un servicio que no se puede visitar no cumple lo que promete.** Publicar la web
  no es un extra: es la diferencia entre «está instalado» y «se usa». Se reutiliza el túnel
  que ya existe --el que hace que el motor no necesite entrar por SSH al hipervisor-- en vez
  de abrir otro camino, y con la misma disciplina: el puerto se deriva, no se declara.
- **Porque la publicación es HACIA CASA, no hacia Internet.** Lo que el motor garantiza es
  que la web contesta en el nodo de control del hogar. Ponerle un nombre público es asunto
  del proxy que ya vive ahí (`caddy`, ADR 0009), no del motor, y esta ADR no lo promete.
- **Frente a meter NetBox a mano en un invitado**: se descarta. Lo que no está en la
  declaración no lo puede reproducir nadie, y `destroy` no sabría de quién es.

## El nombre público: `NN.netbox.matadepera.eu`

El lab 04 se visita en **https://04.netbox.matadepera.eu**. La cadena, para que se pueda
repetir con otro número:

1. `*.matadepera.eu` resuelve al nodo (54.36.168.83) — es el DNS que ya existe, no lo toca el motor.
2. En el nodo, un DNAT manda :80 y :443 a **10.10.10.2**, el proxy de la zona (infraestructura
   de casa, fuera del repo). Ese proxy termina el TLS con su certificado y **añade un bloque
   por lab**: `04.netbox.matadepera.eu { reverse_proxy 10.40.0.20:8080 }`.
3. Para que el proxy pueda hablar con el invitado, el **nodo** tiene dirección en el bridge de
   gestión (`10.40.0.254/24` en `vmb_gestion`), que es lo único que le faltaba: sin ella,
   salía a la calle y volvía. Lo garantiza la unidad `netlabs-publicacion` (idempotente).

Lo que el motor garantiza es lo suyo: que NetBox **sirve** y que Django se entera de que la
petición viene por https (`SECURE_PROXY_SSL_HEADER` + `X-Forwarded-Proto` en el nginx del
invitado). Sin eso, la página se ve y el **login falla por CSRF** sin decir por qué.

Publicar un lab nuevo es, entonces, dos líneas fuera del motor (un bloque en el Caddy de la
zona) y ninguna en la declaración. Se deja dicho porque no es magia: es un proxy que hay que
tocar, y quien despliegue en otro sitio tendrá que hacer el equivalente.

## Dos cosas que costaron, y por qué quedan escritas

- **Publicar un puerto NUEVO sobre un túnel ya construido no hacía nada.** `systemctl enable
  --now` no reinicia un servicio que ya corre: el guion nuevo se quedaba en el disco y la
  sesión vieja seguía con los reenvíos de antes. Se cambió por `systemctl restart` (el
  arranque del túnel sólo se manda cuando el túnel no responde o no reenvía lo que promete,
  así que la idempotencia no se rompe). Medido: el túnel publicaba 21103/21106 y no 22110, y
  el motor decía que había convergido.
- **La sonda del túnel ahora mira TODOS los reenvíos, no sólo la consola y el REST.** Antes,
  un túnel al que le faltaba un reenvío se daba por bueno (`tunnel_probe.yml` sondeaba
  20000+vmid y 21000+vmid). Añadir una web publicada a un lab ya desplegado se quedaba sin
  publicar y ningún check se quejaba.

## Límites, dichos

- **La versión está fijada** (`v4.4.1`). Actualizar NetBox no es un `apt upgrade`: es cambiar
  la constante, volver a clonar y correr migraciones. El preparador no borra `/opt/netbox`, así
  que un cambio de versión pide `destroy` del invitado o una pasada a mano — y se dice.
- **Las credenciales son del banco de pruebas** (administrador `admin`/`netlabs`, base
  `netbox`/`netlabs`), como las del vigilante: viven dentro del invitado y el API no sale de
  loopback. No es un secreto de producción y no pretende serlo.
- **Redis y PostgreSQL escuchan sólo en loopback** dentro del invitado; el 8080 es el único
  puerto que se publica, y sólo por el túnel.
