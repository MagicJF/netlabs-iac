# 0025 — Los secretos pueden ir cifrados, y versionados

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: CÓMO pueden vivir las
credenciales del motor en el repositorio, sin variables de entorno*

## El problema

El ADR 0024 fijó QUÉ no puede estar en lo versionado (el token del nodo, una clave privada, el
propio `secrets.yml`) y lo vigiló con un check. Pero dejó las credenciales del host en **texto
plano 0600 en una máquina**: una decisión consciente y cómoda para un MVP, y también un punto
único: cambiar de nodo, o de portátil, es copiar un fichero a mano. El informe (§6.6) lo apunta
como la mejora natural, y señala que es **reversible sin tocar la arquitectura**.

La restricción dura de esta casa es otra (regla 3): el motor **no lee variables de entorno**. Eso
descarta el uso de sops «de manual», que espera la clave en `SOPS_AGE_KEY_FILE` o similar.

## La decisión

**1. Los secretos pueden vivir CIFRADOS y versionados en `deployment_engine/secrets.sops.yml`.**
Es sops/age: una clave pública cifra, una privada descifra. El fichero cifrado **sí** se versiona —
su contenido no abre nada—, y por eso `./lab check secretos` no lo bloquea: un valor `ENC[...]` es
texto cifrado, no un secreto en claro.

**2. El wrapper descifra, y el motor no se enteró.** `./lab`, que es el único punto de entrada,
mira si hay `secrets.sops.yml` y no hay un `secrets.yml` en claro más nuevo; si es así, lo
descifra al mismo `deployment_engine/secrets.yml` (gitignored, 0600) y sigue. **Ninguna tarea,
playbook ni filtro cambia**: el motor sigue leyendo un solo fichero, como siempre.

**3. Sin variables de entorno, de verdad.** La clave privada vive en
`deployment_engine/age.key` (gitignored, 0600) y se le pasa a sops con **`--age-key-file`, que es
una bandera**, no una variable. El motor no lee `os.environ`: la regla 3 se cumple igual que antes.

**4. Falla pronto y en claro.** Si hay `secrets.sops.yml` pero falta el binario `sops` o la clave,
el verbo **para** diciendo cuál de los dos falta y cómo se arregla. No hay descifrado a medias ni
un `secrets.yml` con basura.

**5. La clave privada también está vigilada.** `./lab check secretos` reconoce ahora la forma
`AGE-SECRET-KEY-1...`: la clave que abre lo cifrado es tan de nadie como el `secrets.yml` en
claro, y no entra en lo versionado.

## La trampa: un claro más nuevo manda, y el candado se fía de `ENC[`

Dos detalles que parecen menores y son deuda:

- **La precedencia es por fecha.** Si hay un `secrets.yml` en claro más nuevo que el cifrado, el
  wrapper **no lo pisa**: es el caso de «lo edité a mano hace un momento». La contrapartida es que
  un cifrado recién traído de otro sitio no refresca un claro viejo que esté al lado; se resuelve
  tocando el claro (borrarlo o `touch`earlo), y está escrito aquí para que no sorprenda.
- **`ENC[` es un patrón que alguien podría imitar.** El candado da por bueno un valor que empiece
  por `ENC[`. Escribir un secreto real con ese prefijo lo escondería. No se defiende de eso porque
  no hay nada que defender: quien escribe el secreto en `secrets.sops.yml` a mano está
  saltándose el mecanismo a propósito, y ninguna regex arregla eso — lo arregla no hacerlo.

## Qué NO decide

No obliga a cifrar: `secrets.yml` a mano sigue valiendo, y sigue siendo el camino por defecto. No
versiona ninguna clave ni elige un proveedor de KMS. Y no promete que la clave privada esté a
salvo: dice dónde vive y que no se versiona, que es distinto.
