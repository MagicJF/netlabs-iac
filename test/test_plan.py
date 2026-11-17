#!/usr/bin/env python3
# PROPÓSITO:   probar la parte del plan que decide si un invitado está DONDE dice la
#              declaración --*declaración + lo que el nodo dice → diferencias*--, sin
#              Proxmox y sin Ansible. Es la decisión que separa «no hay nada que hacer» de
#              «este invitado hay que rehacerlo», y por eso se prueba aparte.
# INVARIANTES: los casos que TIENEN que cumplirse, y que son el contrato:
#              1. un invitado con sus interfaces donde la declaración pide NO tiene
#                 diferencias -- la comparación no inventa trabajo;
#              2. si la SEGUNDA pata está en otro bridge, SÍ las tiene: es el caso que se
#                 colaba, porque el plan sólo miraba la primera (`bridge`), y un invitado
#                 con la segunda en otro sitio seguía diciendo «no hay nada que hacer»
#                 mientras el interior configuraba una interfaz que ya no está donde debe;
#              3. se comparan las interfaces que declaró CREAR: la misma función
#                 (`_redes_del_guest`) que las escribe, para que crear y comparar digan lo
#                 mismo. Una copia que se desincronice daría diferencias que no existen;
#              4. la pata de FUERA (la salida del lab) cuenta como cualquier otra: es la
#                 última y también tiene que estar en el bridge que toca.
# LÍMITES:     prueba la DECISIÓN, no el remedio: que el plan pare en vez de arreglarlo en
#              marcha (§5, no se reinicia lo que está trabajando) lo dice quien llama. No
#              toca la API ni escribe nada.
# VER:         deployment_engine/tools/plan.py (interfaces_que_difieren, _redes_del_guest);
#              docs/decisiones/0026-un-equipo-una-responsabilidad... y el §5 del README

import copy
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "tools"))

import plan as modulo  # noqa: E402

FALLOS = []


def comprobar(condicion, texto):
    if condicion:
        print(f"  OK    {texto}")
    else:
        FALLOS.append(texto)
        print(f"  FALLA {texto}")


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado, f"{texto}  (obtenido {obtenido!r}, esperado {esperado!r})")


# El prefijo de las MAC del motor: sin él no se puede derivar la de cada interfaz, y el
# invariante es que venga de `vars/engine.yml`, no que se invente aquí. Se pasa como dato.
PARAMETROS = {"mac_prefijo": "BC:24:11", "bridge_gestion": "vmbr1"}

# Un invitado de DOS patas, sin interior: `ether1` sirve la red de gestión, `ether2` la LAN.
# Es la forma de un CHR que sirve una zona, y la que se colaba al comparar sólo la primera.
DOS_PATAS = {
    "rol": "borde",
    "tipo": "qemu",
    "vmid": 301,
    "stage": 1,
    "bridges": ["vmb_gestion", "vmb_lan"],
}


def actual_de(guest, puentes):
    """Lo que el ESTADO dice que tiene puesto el invitado.

    `interfaces` es {índice: bridge} con las claves en TEXTO, porque el estado viaja por
    variables de Ansible y ahí las claves siempre son texto. Se escribe así a propósito: la
    versión anterior de esta prueba pasaba la config cruda del nodo (`net0=...`) y por eso no
    vio que el estado no guardaba más que la PRIMERA interfaz.
    """
    return {"interfaces": {str(indice): bridge for indice, bridge in enumerate(puentes)}}


def difieren(guest, puentes):
    return modulo.interfaces_que_difieren(
        copy.deepcopy(guest), actual_de(guest, puentes), {}, {}, PARAMETROS
    )


# ---------------------------------------------------------------------------

print("\nUN INVITADO DONDE LA DECLARACIÓN PIDE NO DA TRABAJO\n")

igual(
    difieren(DOS_PATAS, ["vmb_gestion", "vmb_lan"]), {},
    "las interfaces están donde la declaración pide: no hay ni una diferencia",
)

# ---------------------------------------------------------------------------

print("\nUNA SEGUNDA PATA EN OTRO BRIDGE SÍ\n")

# El caso que Greptile cazó: `campos_que_difieren` mira `bridge` -- la primera -- y con la
# primera igual daba el invitado por bueno, aunque la segunda hubiera cambiado de sitio.
diferencia = difieren(DOS_PATAS, ["vmb_gestion", "vmb_troncal"])
igual(
    list(diferencia), [1],
    "con la primera igual y la segunda en otro bridge, la diferencia sale en la SEGUNDA",
)
igual(
    diferencia[1], {"esperado": "vmb_lan", "encontrado": "vmb_troncal"},
    "y se dice qué se pidió y qué hay: un motivo que se puede arreglar",
)

# Al revés también, y no sólo por el último: en cualquier posición.
diferencia = difieren(DOS_PATAS, ["vmb_otro", "vmb_lan"])
igual(list(diferencia), [0], "si la que cambió de sitio es la primera, la diferencia sale en la primera")

# Y si le FALTA una interfaz entera (el nodo sólo tiene una pata), también.
comprobar(
    list(diferencia) and difieren(DOS_PATAS, [])[0]["encontrado"] is None,
    "una interfaz que el invitado pide y el nodo no tiene es una diferencia, no un hueco mudo",
)

# Y por qué hizo falta una comprobación nueva en vez de añadir `netN` a la lista de campos:
# `campos_que_difieren` compara `bridge` (en singular, el de `net0`), así que con la segunda
# pata en otro sitio NO ve nada -- el invitado se daba por bueno. Aquí se ve el agujero tal
# cual era, contra el MISMO estado que ahora se conserva entero.
igual(
    modulo.campos_que_difieren(
        modulo._esperado_del_guest(copy.deepcopy(DOS_PATAS)),
        dict(actual_de(DOS_PATAS, ["vmb_gestion", "vmb_troncal"]), bridge="vmb_gestion"),
    ),
    {},
    "la comparación de campos por sí sola NO ve la segunda pata: es el agujero que esto cierra",
)

# Y la otra mitad del contrato, la que se coló y se vio en un `plan --api` de verdad: el
# estado TIENE que traer las interfaces. Si no las trajera, este mismo invitado perfecto
# saldría con todas sus patas «en ningún bridge» y el plan daría por roto un lab entero.
comprobar(
    actual_de(DOS_PATAS, ["vmb_gestion", "vmb_lan"]).get("interfaces") ==
    {"0": "vmb_gestion", "1": "vmb_lan"},
    "el estado dice el bridge de CADA interfaz (si sólo dijera el de la primera, la "
    "comparación vería huecos donde no los hay)",
)

# ---------------------------------------------------------------------------

print("\nLA PATA DE FUERA CUENTA COMO CUALQUIER OTRA\n")


def actual_con_salida(guest, puentes, salida):
    return actual_de(guest, list(puentes) + [salida])


# Un invitado con `uplink` sale al bridge del nodo: esa interfaz es la ÚLTIMA y también tiene
# que estar donde toca. Se calcula con la declaración delante, como en el plan de verdad.
CON_SALIDA = {
    "rol": "nucleo",
    "tipo": "qemu",
    "vmid": 302,
    "stage": 1,
    "bridges": ["vmb_gestion", "vmb_troncal"],
    "config": {"routeros": {"uplink": {"resolver": "1.1.1.1"}}},
}

igual(
    modulo.interfaces_que_difieren(
        copy.deepcopy(CON_SALIDA),
        actual_con_salida(CON_SALIDA, ["vmb_gestion", "vmb_troncal"], "vmbr1"),
        {}, {}, PARAMETROS,
    ),
    {},
    "con la salida en el bridge de gestión del nodo, el invitado está donde la declaración pide",
)
igual(
    list(
        modulo.interfaces_que_difieren(
            copy.deepcopy(CON_SALIDA),
            actual_con_salida(CON_SALIDA, ["vmb_gestion", "vmb_troncal"], "vmbr9"),
            {}, {}, PARAMETROS,
        )
    ),
    [2],
    "y si la salida quedó en otro bridge, la diferencia sale en la ÚLTIMA interfaz",
)

# ---------------------------------------------------------------------------

print("\nLA MISMA FUNCIÓN QUE CREA ES LA QUE COMPARA\n")

# El invariante que impide diferencias fantasma: lo que se compara es lo que escribiría
# `_redes_del_guest`, no una copia que se pueda desincronizar. Si esto se rompiera, el plan
# pediría rehacer invitados que están perfectos.
comprobado = True
for guest, puentes in ((DOS_PATAS, ["vmb_gestion", "vmb_lan"]),):
    escrito = modulo._redes_del_guest(copy.deepcopy(guest), {}, {}, PARAMETROS)
    comprobado = comprobado and (
        modulo._puentes_de(escrito) == modulo._puentes_de_estado(actual_de(guest, puentes))
    )
comprobar(
    comprobado,
    "los bridges que crear escribe y los que comparar espera son los MISMOS: una sola fuente",
)

if FALLOS:
    print(f"RESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("RESULTADO: el plan no da por bueno un invitado que está en otro sitio.")
