# 0033 — La clave se deja al CREAR, y si falta se para

## La decisión

El motor deja su clave pública dentro de un contenedor **sólo al crearlo**
(`ssh-public-keys`). Si se encuentra un invitado que existía de antes sin esa clave, **no lo
rodea: para y lo dice**, con lo que hay que hacer — destruir el lab y volver a desplegarlo.

## Por qué

Porque no hay otra forma **por la API**, y está comprobado en el código de Proxmox, no
supuesto: `ssh-public-keys` está entre los parámetros del endpoint de **creación**
(`PVE/API2/LXC.pm`, junto a `ostemplate` y `restore`) y **no** aparece en el esquema de
configuración (`PVE/LXC/Config.pm`), así que un `PUT .../config` con esa clave no la admite.
Las demás vías están prohibidas por diseño: `snippets`, `hookscripts`, `pct exec` y SSH al
hipervisor (regla 1), y la consola existe para poner el arranque del bastión, no para
configurar equipos (regla 19).

Sin clave, sshd contesta **«Permission denied (publickey)»**, un error que no dice nada de lo
que pasa de verdad. Antes, el motor lo dejaba pasar como un «no pude preguntar» más y el lab se
quedaba a medias sin decir por qué. Ahora reconoce esa firma exacta —`rc` 255 **con** ese
texto, que es «llegué al sshd y me rechazó», no «no hay camino»— y para con la causa y el
remedio. Es la regla 16 aplicada al interior: se para diciendo qué pieza falta y cómo se
arregla, nunca se rodea.

## El coste, dicho en claro

Obliga a destruir y volver a desplegar un lab que ya estaba desplegado con una versión
anterior. Es feo, y es lo honesto: la alternativa era rodear la API, y eso no se hace aquí.

## Cómo se comprueba

- La guarda vive en la **única** vía de acceso al interior (`tasks/interior_ssh.yml`), después
  del diario: el intento queda escrito, que es la evidencia, y el verbo para con el motivo.
- `./lab check access` sigue verde: la guarda no abre ninguna conexión nueva, sólo interpreta
  el resultado de la que ya se hace.
- El ciclo real de un lab: `destroy → apply → verify` en verde.

## VER

- [deployment_engine/tasks/interior_ssh.yml](../../deployment_engine/tasks/interior_ssh.yml)
  (la guarda de la llave y por qué va ahí)
- [deployment_engine/tools/plan.py](../../deployment_engine/tools/plan.py) (`ssh-public-keys`
  al crear, que es la única mitad que la API admite)
- [docs/decisiones/0010-el-rest-por-el-tunnel.md](0010-el-rest-por-el-tunnel.md)
