#!/usr/bin/env python3
# PROPÓSITO:   probar el VALIDADOR de la declaración sin Ansible ni Proxmox: el caso
#              válido es un lab de verdad del repo, y cada prueba rompe ese caso en
#              un sitio para exigir que el validador lo cace y lo diga. Un validador
#              que no se ha visto fallar no es un validador.
# INVARIANTES: ninguna prueba toca la API ni escribe nada. Todas parten de una copia
#              del lab de aceptación (`labs/lab-red-routeros`), así que si el lab de
#              aceptación deja de ser coherente, esta batería lo dice en su primera
#              línea en vez de esconderlo.
# LÍMITES:     prueba la coherencia INTERNA de una declaración; NO prueba que la API
#              acepte lo declarado (eso lo dice `plan`/`apply`) ni la disjunción de
#              vmids entre labs (necesita credenciales).
# VER:         labs/lab-red-routeros/lab-red-routeros.yml; AGENTS.md §Reglas duras;
#              deployment_engine/filter_plugins/declaracion.py

import copy
import os
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import declaracion as modulo  # noqa: E402

RUTA_LAB = os.path.join(RAIZ, "labs", "lab-red-routeros", "lab-red-routeros.yml")
CARPETA = "lab-red-routeros"

FALLOS = []


def comprobar(condicion, texto):
    if condicion:
        print(f"  OK    {texto}")
    else:
        FALLOS.append(texto)
        print(f"  FALLA {texto}")


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado, f"{texto}  (obtenido {obtenido!r}, esperado {esperado!r})")


def errores_de(mutar):
    """Los errores del lab de aceptación con un cambio aplicado encima."""
    declaracion = copy.deepcopy(BASE)
    mutar(declaracion)
    return modulo.declaracion_validar(declaracion, CARPETA)


def dice(errores, fragmento):
    return any(fragmento in error for error in errores)


# ---------------------------------------------------------------------------

print("\nEL CASO VÁLIDO: EL LAB DE ACEPTACIÓN\n")

with open(RUTA_LAB, encoding="utf-8") as fichero:
    BASE = yaml.safe_load(fichero)

BASICOS = modulo.declaracion_validar(BASE, CARPETA)
comprobar(not BASICOS, f"el lab de aceptación es coherente (si no: {BASICOS})")
igual(
    modulo.declaracion_validar(BASE, CARPETA),
    [],
    "validar dos veces da lo mismo: el validador no depende del orden ni del azar",
)
igual(
    modulo.declaracion_validar(BASE, "lab-dos-redes")[:1] != [],
    True,
    "un nombre que no es el de la carpeta se caza (el pool se llama como la carpeta)",
)
comprobar(
    dice(modulo.declaracion_validar(BASE, "otra-carpeta"), "carpeta"),
    "y el error nombra la carpeta, para que se pueda arreglar sin buscar",
)

# ---------------------------------------------------------------------------

print("\nLA SUPERNET: DENTRO, NO FUERA\n")

comprobar(modulo._ip_en_supernet("10.40.1.5/24", "10.40.0.0/16"), "10.40.1.5/24 cae en 10.40.0.0/16")
comprobar(modulo._ip_en_supernet("10.40.0.11", "10.40.0.0/16"), "sin máscara también")
comprobar(not modulo._ip_en_supernet("10.41.0.11/24", "10.40.0.0/16"), "10.41.0.11/24 NO cae")
comprobar(
    not modulo._ip_en_supernet("10.40.5.5/24", "10.40.0.0/24"),
    "un /24 dentro de otro: coincidir en los tres primeros octetos no basta",
)
comprobar(
    modulo._ip_en_supernet("10.40.0.11/24", "10.40.0.0/24"), "y sí basta cuando coinciden todos"
)
comprobar(
    modulo._ip_en_supernet("10.40.0.11/24", "10.40.0.0/17"),
    "un prefijo que no cae en un octeto no se vigila (no se opina, no se adivina)",
)

errores = errores_de(lambda d: d["lab"].__setitem__("supernet", "10.50.0.0/16"))
comprobar(dice(errores, "se sale de la supernet"), "un lab fuera de su supernet se caza")
comprobar(
    len([error for error in errores if "se sale de la supernet" in error]) >= 5,
    "y se caza TODO lo que se sale (bridges, direcciones, rangos y pasarelas), no sólo lo primero",
)
errores = errores_de(lambda d: d["lab"].__setitem__("supernet", "10.40.0.0/24"))
comprobar(
    dice(errores, "se sale de la supernet"),
    "una supernet que no contiene las LANs que el lab sirve se caza igual: es el error contrario",
)

# ---------------------------------------------------------------------------

print("\nLO QUE NO SE DECLARA NUNCA: MACs Y CREDENCIALES\n")

errores = errores_de(lambda d: d["vms"][0].__setitem__("mac", "BC:24:11:00:00:01"))
comprobar(dice(errores, "MAC"), "una MAC en la declaración es un bug (regla 14)")
errores = errores_de(lambda d: d["vms"][0].__setitem__("mac", "aa-bb-cc-dd-ee-ff"))
comprobar(dice(errores, "MAC"), "también si se escribe en otro formato")
errores = errores_de(lambda d: d["vms"][0].__setitem__("password", "hunter2"))
comprobar(dice(errores, "password"), "una contraseña en la declaración es un bug")
errores = errores_de(lambda d: d["lab"].__setitem__("camino_clave", "ssh-ed25519 AAAA"))
comprobar(dice(errores, "clave") or dice(errores, "credencial"), "y una clave privada, también")

# ---------------------------------------------------------------------------

print("\nEL VOCABULARIO ES CERRADO\n")

errores = errores_de(lambda d: d["vms"][0]["config"]["routeros"].__setitem__("cortafuegos", {}))
comprobar(
    dice(errores, "cortafuegos") and (dice(errores, "no") or dice(errores, "pendiente")),
    "un área que el motor todavía no converge se RECHAZA con su motivo: aquí no se finge",
)
errores = errores_de(lambda d: d["vms"][0]["config"]["routeros"].__setitem__("inventado", {}))
comprobar(dice(errores, "inventado"), "un área que no existe se caza con su nombre")
errores = errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("docker", {}))
comprobar(dice(errores, "docker"), "y una primitiva que el lab se inventa, también (regla 15)")

errores = errores_de(lambda d: d["containers"][0]["config"].__setitem__("routeros", {}))
comprobar(dice(errores, "tipo"), "un invitado con dos tipos de interior se caza: el tipo elige driver")
errores = errores_de(lambda d: d["vms"][0].__setitem__("config", {}))
comprobar(dice(errores, "config"), "un `config:` vacío no declara nada y se dice")

errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["servicios"].__setitem__("deshabilitar", ["www"])
)
comprobar(
    dice(errores, "www") and dice(errores, "camino de vuelta"),
    "deshabilitar `www` (donde vive REST) se caza: dejaría el equipo sin poder configurarlo nunca",
)

errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["direcciones"].append(
        {"interfaz": "ether3", "direccion": "10.40.3.1"}
    )
)
comprobar(dice(errores, "direccion"), "una dirección sin máscara se caza")
errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["dhcp"][0].__setitem__(
        "reservas", [{"rol": "servidor", "mac": "BC:24:11:00:00:01"}]
    )
)
comprobar(
    dice(errores, "MAC") or dice(errores, "reserva"),
    "una reserva con MAC se caza: las reservas se derivan del vmid",
)
errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["dhcp"][0].__setitem__("reservas", "derivada")
)
comprobar(dice(errores, "reservas"), "`reservas: derivada` (en singular) tampoco es la forma correcta")

# ---------------------------------------------------------------------------

print("\nUN INVITADO CON INTERIOR TIENE QUE SER ALCANZABLE\n")

errores = errores_de(lambda d: d["containers"][0].__setitem__("direccion", None))
comprobar(
    dice(errores, "direccion"),
    "un invitado con `config:` sin dirección se caza: no se puede converger lo que no se alcanza",
)


# ---------------------------------------------------------------------------

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el validador caza lo que tiene que cazar y deja pasar el lab de aceptación.")
