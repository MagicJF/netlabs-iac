# ADR 0007 — Las patas se declaran, y lo que se configura tiene que existir

<!-- PROPÓSITO: dejar escrito por qué un invitado declara sus patas (`bridges:`) y por qué
     el validador rechaza configurar una interfaz que el invitado no tendrá. Nace de una
     pared medida, no de una idea: RouterOS contestó
     `400 input does not match any value of interface` A MITAD de una convergencia.
     INVARIANTES: el orden de `bridges` ES la numeración de las interfaces (`eth0`/`ether1`
     la primera); la MAC de cada pata se DERIVA del vmid (regla 11, `identidad_mac_de_pata`)
     y no se declara; las patas se deciden al CREAR el invitado (cambiarlas en caliente
     obliga a reiniciar, y aquí no se reinicia la máquina que trabaja); el motor no conoce
     ninguna topología: sólo sabe que `net<i>` se corresponde con `eth<i>`.
     LÍMITES: esto no cubre añadir o quitar patas a un invitado en marcha (el motor se para
     y dice el remedio: `destroy` de ese invitado y `apply`), ni las patas del PUESTO DE
     CONTROL, que son otra cosa (`_red_del_invitado`: una por bridge del lab más la de
     gestión del nodo, la última).
     VER: filter_plugins/declaracion.py (patas_declaradas, _validar_interior),
     tools/plan.py (_redes_del_invitado), test/test_declaracion.py,
     labs/lab-red-routeros/lab-red-routeros.yml -->

**Estado:** aceptada; medida contra el VPS (CHR 108, RouterOS 7.25.1).

**Contexto.** El lab de aceptación declara, para su primer CHR (`borde`), que quiere
configurar `ether2` (la LAN que sirve: `10.40.1.1/24`, su servidor DHCP y su red). Pero el
invitado declaraba **una sola** pata (`bridge: vmb_gestion`), y el motor creaba la máquina
con una sola interfaz. La convergencia llegó hasta ahí y se paró en seco:

```
POST /ip/address/add  {"address":"10.40.1.1/24","interface":"ether2"}
  -> 400  Bad Request  input does not match any value of interface
```

No fue un fallo de RouterOS ni de la puerta: fue una **promesa imposible**. El motor estaba
en mitad del intercambio de la dirección de gestión (ADR 0006 §5) y el router se quedó a
medias, con parte del trabajo hecho y sin manera de saber de dónde. Y lo peor: la declaración
se aceptó sin decir nada, así que el fallo apareció **después de gastar el ciclo entero**,
con dos máquinas ya creadas.

**Decisión.** Tres cosas, y las tres son del motor (ninguna es un valor de un lab):

1. **Un invitado declara sus patas, en orden**: `bridges: [vmb_gestion, vmb_lan1]`. El orden
   ES la numeración: la primera pata es `eth0` (en RouterOS, `ether1`), la segunda
   `eth1`/`ether2`. Un invitado de una sola pata puede seguir declarando `bridge:` como
   siempre (todo lo de la fase 1 queda igual); las dos formas dicen lo mismo y
   `patas_declaradas()` es el único sitio que las lee.
2. **El plan crea una pata por bridge declarado** (`net0`, `net1`...) con la MAC de cada
   pata derivada del vmid (`identidad_mac_de_pata`), exactamente igual que la de una pata.
   Nada se le deja a Proxmox: si la MAC la eligiera él, el plan vería una identidad distinta
   en cada pasada y la idempotencia se caería.
3. **El validador rechaza configurar lo que no existirá.** Si el interior nombra `etherN` y
   el invitado no declara N patas, la declaración es incoherente y `plan` no llega ni a
   empezar. La misma regla vale para Linux (`eth0`, `eth1`): la primitiva es la misma, y por
   eso vive en `_validar_interior` y no en el validador de RouterOS.

**Por qué así.** Podría haberse hecho al revés: que el motor dedujera las patas de las
interfaces que la declaración configura. Se descartó porque inventaría topología donde el lab
no la declara (regla 7: el motor conoce reglas, no valores) y porque el orden de las patas
decide la numeración de las interfaces, que es justo lo que el lab necesita poder nombrar.
Lo que sí se hizo es **no dejar pasar la promesa imposible**: un fallo de declaración cuesta
un ciclo entero y dos máquinas mal creadas, y eso se ve en el validador en milisegundos.

**Consecuencias.**

- El lab de aceptación declara dos patas en cada CHR (`borde`: gestión + su LAN; `nucleo`:
  la del escalón anterior + la suya), y `./lab check declaracion` lo comprueba sin
  credenciales.
- Cambiar las patas de un invitado en marcha no se hace en caliente: el plan lo dice y para
  (`destroy` de ese invitado y `apply`), porque el motor no reinicia la máquina que trabaja.
- El motor sigue sin saber nada de ningún lab: `eth<i>` ↔ `net<i>` es una regla, y los
  nombres de los bridges los pone la declaración.
