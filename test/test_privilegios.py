#!/usr/bin/env python3
# PROPÓSITO:   probar la mitad LÓGICA de la guarda de mínimos privilegios sin Proxmox y
#              sin Ansible: la comparación entre lo que el nodo tiene concedido (lo que
#              devuelve `GET /access/roles`, escrito aquí a mano como fixture) y lo que
#              el motor exige, rol a rol, un rol por ruta.
# INVARIANTES: cada caso tiene que poder FALLAR de verdad, y el caso 2 es el que más
#              importa: un rol con los privilegios de OTRA ruta es exactamente el
#              defecto que se midió en el nodo (un solo rol en cinco rutas = la unión
#              en todas partes). Si el filtro lo dejara pasar, este test falla.
# LÍMITES:     no prueba nada contra la API real (eso es `preflight`, que además hace
#              la operación nula sobre cada rol y exige 403). Aquí sólo se compara
#              listas: el filtro no decide qué privilegios hacen falta.
# VER:         docs/decisiones/0004-*.md; tasks/guardia_privilegios.yml; vars/engine.yml
#
# Uso:  python3 test/test_privilegios.py     (código de salida != 0 si algo falla)

import os
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import estado as modulo_estado  # noqa: E402

FALLOS = []


def comprobar(condicion, descripcion):
    print(f"  {'OK  ' if condicion else 'FALLA'}  {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)


def igual(obtenido, esperado, descripcion):
    comprobar(obtenido == esperado, f"{descripcion}  (obtenido {obtenido!r}, esperado {esperado!r})")


# El mapa del motor NO se inventa: se lee el del repositorio. Si alguien lo cambia,
# este test prueba lo que el motor exige hoy, no lo que exigía ayer.
VARS = yaml.safe_load(open(os.path.join(RAIZ, "deployment_engine", "vars", "engine.yml")))
POR_ROL = VARS["engine_privilegios_por_rol"]
VEDADOS = VARS["engine_privilegios_vedados"]

# Lo que el nodo tiene concedido, tal cual lo devuelve `GET /access/roles`: una lista de
# `{roleid, privs}` con `privs` como cadena separada por comas.
def nodo_con(por_rol):
    return [{"roleid": rol, "privs": ",".join(privs)} for rol, privs in por_rol.items()]


def comparar(por_rol_en_el_nodo):
    return modulo_estado.estado_privilegios_roles(
        nodo_con(por_rol_en_el_nodo), POR_ROL, VEDADOS
    )


print("\nLA GUARDA DE PRIVILEGIOS, ROL A ROL\n")

# ---------------------------------------------------------------------------
print("1. El nodo tal y como debe estar")
resultado = comparar(POR_ROL)
igual(resultado["ok"], True, "cinco roles, uno por ruta, cada uno con lo suyo")
igual(resultado["ausentes"], [], "y ninguno ausente")
igual(resultado["faltan"], {}, "y a ninguno le falta un privilegio")
igual(resultado["sobran"], {}, "y a ninguno le sobra nada")
comprobar(
    str(len(POR_ROL)) in resultado["texto"] and "NetlabsMotorVms" in resultado["texto"],
    "el texto dice CUÁNTOS roles vigila y cuáles (un check que no se puede leer no sirve)",
)

# ---------------------------------------------------------------------------
print("\n2. El defecto que se midió en el nodo: los privilegios de otra ruta")
# Un solo rol concedido en las cinco rutas daba la UNIÓN en todas partes: aquí se
# reproduce concediendo al rol de `/vms` lo que es del rol del nodo.
unificado = {rol: list(privs) for rol, privs in POR_ROL.items()}
unificado["NetlabsMotorVms"] = unificado["NetlabsMotorVms"] + ["Sys.Modify", "Datastore.AllocateSpace"]
resultado = comparar(unificado)
igual(resultado["ok"], False, "un rol con privilegios de OTRA ruta NO pasa")
igual(
    sorted(resultado["sobran"]["NetlabsMotorVms"]),
    ["Datastore.AllocateSpace", "Sys.Modify"],
    "y se dice CUÁLES sobran, con su nombre",
)

# ---------------------------------------------------------------------------
print("\n3. Un privilegio vedado, aunque sea «poco»")
vedado = {rol: list(privs) for rol, privs in POR_ROL.items()}
vedado["NetlabsMotorVms"] = vedado["NetlabsMotorVms"] + ["VM.GuestAgent.FileRead"]
resultado = comparar(vedado)
igual(resultado["ok"], False, "un privilegio vedado en un rol NO pasa")
igual(
    resultado["sobran"]["NetlabsMotorVms"], ["VM.GuestAgent.FileRead"],
    "y se nombra el privilegio vedado",
)

# ---------------------------------------------------------------------------
print("\n4. Un rol que el nodo no tiene (el que se quedó huérfano al partir el rol único)")
sin_nodo = {rol: list(privs) for rol, privs in POR_ROL.items() if rol != "NetlabsMotorNodo"}
resultado = comparar(sin_nodo)
igual(resultado["ok"], False, "un rol ausente NO pasa")
igual(resultado["ausentes"], ["NetlabsMotorNodo"], "y se nombra el rol que falta")

# ---------------------------------------------------------------------------
print("\n5. A un rol le falta UN privilegio de los suyos")
corto = {rol: list(privs) for rol, privs in POR_ROL.items()}
corto["NetlabsMotorVms"] = [p for p in corto["NetlabsMotorVms"] if p != "VM.Console"]
resultado = comparar(corto)
igual(resultado["ok"], False, "a un rol sin VM.Console NO se le da por bueno")
igual(resultado["faltan"]["NetlabsMotorVms"], ["VM.Console"], "y se dice cuál falta")

# Y el caso que importa de verdad: ese privilegio que falta es el del camino. Si el
# token lo perdiera, el motor no podría entrar en la red de ningún lab, y la guarda
# lo dice ANTES de intentarlo.
comprobar(
    "VM.Console" in POR_ROL["NetlabsMotorVms"],
    "el rol de /vms lleva VM.Console: es la puerta del camino y sin él no hay lab",
)
comprobar(
    "Sys.Modify" not in POR_ROL["NetlabsMotorVms"] and "Sys.Modify" in POR_ROL["NetlabsMotorNodo"],
    "y Sys.Modify vive SÓLO en el rol de la red del nodo, no en el de los invitados",
)

print()
if FALLOS:
    print(f"RESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("RESULTADO: la guarda de privilegios caza lo que tiene que cazar y deja pasar lo correcto.")
