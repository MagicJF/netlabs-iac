# Registro de cambios

Lo que ha entrado en cada versión, de la más nueva a la más vieja. El formato es
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`.

Mientras la versión MAYOR sea `0`, el motor está **en desarrollo**: la declaración de un
lab y los verbos todavía pueden cambiar, y cualquier versión MENOR puede traer un cambio
que rompa. Es la regla de SemVer para la serie 0.x, y es la razón de que la primera
entrega sea `0.1.0` y no `1.0.0`: no hay nada estable que prometer todavía. La `1.0.0` se
publicará cuando lo haya —una declaración de lab que no queramos volver a tocar y
terceros usándola—.

El fichero `VERSION` lleva la **última versión publicada**, el tag `vX.Y.Z` la marca y
aquí está su entrada; los tres tienen que contar lo mismo, y eso es lo que vigila
`./lab check version`. Lo que entra en `main` sin publicarse se apunta bajo
`[No publicado]`, y se convierte en una versión el día que se publica.

## [No publicado]

## [0.1.0] - 2026-11-15

Primera entrega. Recoge lo que el motor es hoy, después de siete labs: un motor IaC en
Ansible que despliega topologías —VMs QEMU y contenedores LXC— en un nodo Proxmox **sólo
por su API REST**, pone él mismo la identidad de cada invitado, **configura el interior**
de cada equipo (RouterOS por su REST, Linux por SSH) y lo documenta.

### Añadido

**La declaración**
- Una carpeta por topología (`labs/NN_<nombre>/`) con su declaración, su documento y sus
  diarios. El motor **no conoce ninguna topología**: el lab es siempre un parámetro.
- El lab declara roles, el tipo de equipo (`rt`/`srv`/`ws`/`sw`/`ctl`), bridges,
  direcciones, etapas de arranque, recursos y —si quiere que el motor entre dentro— qué
  configurar y con qué imagen. **Nunca** declara vmids ni MACs.

**La identidad, derivada**
- vmid (el menor libre de todo el clúster), nombre `<tipo>-<alias>`, MAC `f(vmid)`,
  descripción y pool del lab. **Sin fichero de estado**: se re-deriva leyendo la API.

**Los verbos**
- `plan` (ordena y explica cada llamada REST que haría), `preflight` (sólo lectura: qué
  hay, qué falta, qué difiere), `apply` (converge y verifica), `verify` (¿existe de verdad
  lo declarado?) y `destroy` (el único que borra, y sólo lo que él creó).
- El plan es una **explicación**: dice por qué cada llamada, no sólo cuál.

**Las cuatro vías de acceso y los tres diarios**
- API de Proxmox y REST de RouterOS, siempre con `ansible.builtin.uri`, y cada llamada
  deja su línea en `logs/api.jsonl` (`api: proxmox` | `routeros`).
- El interior de un Linux, sólo por SSH, con una línea por paso en `logs/interior.jsonl`.
- La consola de la API —el único protocolo no-REST— para una sola cosa: el arranque del
  bastión. Su diario es `logs/console.jsonl`. Ninguna credencial se escribe en un diario.

**El interior de un invitado**
- Un driver por familia (RouterOS por REST, Linux por SSH) con la misma forma: leer dentro
  → decidir la diferencia en los dos sentidos → escribir lo que falta → releer y comprobar.
- DHCP con reservas derivadas de la MAC del invitado, direcciones estáticas por interfaz,
  rutas, cortafuegos, identidad y servicios. Dentro de un área declarada, lo que no está en
  la declaración se quita; fuera de las áreas declaradas no se toca nada.

**El túnel**
- Lo construye el motor y lo comprueba de punta a punta antes de seguir. Por él van el REST
  de RouterOS y el SSH al interior: el motor no necesita llegar solo a la red del lab.

**La red y el orden de arranque**
- Los bridges los crea el plan si faltan, con su marca de propiedad; `destroy` sólo borra
  los que llevan esa marca y no están usando invitados de fuera del lab.
- Cada etapa arranca sólo cuando la anterior está convergida y sirviendo: la carrera del
  DHCP que mató a la fase anterior se evita por construcción, no por suerte.
- El agente de invitado en toda VM, para poder LEER direcciones que la API no expone.

**Los checks y la documentación**
- Checks mecánicos (`./lab check`), sin credenciales y sin Proxmox, cada uno diciendo el
  fichero y el comando que lo arregla.
- El documento de un lab tiene dos regiones: la generada (nadie la escribe a mano) y la
  prosa libre. Los documentos que citan el motor se sellan por hash y **caducan avisando**.
- ADRs para lo que no se quiere re-litigar, un pre-commit que vigila docs↔código, y una
  suite de pruebas con fixtures para el asignador: el asignador se prueba sin Proxmox.
