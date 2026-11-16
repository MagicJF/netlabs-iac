#!/usr/bin/env python3
# PROPÓSITO:   probar el detector de choque de vmid —*texto → booleano*—, la decisión
#              que hace que `apply` reintente Y re-derive en vez de morir cuando dos
#              `apply` eligen el mismo vmid a la vez (informe §6.7).
# INVARIANTES: los casos que TIENEN que cumplirse, y que son el contrato del detector:
#              1. los cuerpos REALES de Proxmox para un vmid ocupado (VM y contenedor)
#                 dicen SÍ;
#              2. un «already exists» de OTRA cosa (un pool, un bridge, una migración)
#                 dice NO: reintentar no lo arregla y lo escondería;
#              3. un error cualquiera (401, timeout, un fallo de red) dice NO;
#              4. la detección no depende del orden de las palabras ni de mayúsculas.
# LÍMITES:     no prueba el reintento de verdad (eso es un `apply` en paralelo contra
#              el VPS): aquí sólo se prueba la DECISIÓN de reintentar, que es lo que
#              no se puede leer a ojo en un bloque de Jinja.
# VER:         deployment_engine/filter_plugins/colision.py; tasks/converger.yml

# Uso:  python3 test/test_colision.py     (código de salida != 0 si algo falla)

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import colision  # noqa: E402

FALLOS = []


def comprobar(condicion, descripcion):
    print(("  OK   " if condicion else "  FALLA") + f" {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)


# El cuerpo va EXACTAMENTE como lo devuelve Proxmox: el error vive en `errors`, no en el
# mensaje de Ansible, y por eso el detector mira el cuerpo.
SI = [
    ("cuerpo de Proxmox al crear una VM con un vmid ocupado",
     '{"data":null,"errors":{"vmid":"VM 108 already exists on node \'pve\'"}}'),
    ("cuerpo de Proxmox al crear un contenedor con un vmid ocupado",
     '{"data":null,"errors":{"vmid":"CT 200 already exists"}}'),
    ("la misma idea con el orden de las palabras al revés",
     "the VM 108 already exists"),
    ("la misma idea en MAYÚSCULAS",
     "VMID 108 ALREADY EXISTS"),
    ("la formulación «already in use» de un ID",
     '{"errors":{"vmid":"ID 300 already in use"}}'),
]

NO = [
    ("vacío", ""),
    ("None", None),
    ("un pool que ya existe (reintentar NO lo arregla)",
     '{"errors":{"poolid":"pool-04_lab-red-routeros already exists"}}'),
    ("un bridge que ya existe", '{"errors":{"iface":"vmbr7 already exists"}}'),
    ("un 401 (el token, no el vmid)", "la API rechazó el token (401)"),
    ("un 403", "el token no tiene permiso para esta llamada (403)"),
    ("un timeout sin cuerpo", "no se pudo conectar con https://54.36.168.83:8006"),
    ("la palabra vmid sin un «already exists»", '{"errors":{"vmid":"invalid format"}}'),
]

print("1. lo que ES un choque de vmid")
for descripcion, texto in SI:
    comprobar(colision.es_colision_de_vmid(texto) is True, descripcion)

print("\n2. lo que NO es un choque de vmid (y por eso no se reintenta)")
for descripcion, texto in NO:
    comprobar(colision.es_colision_de_vmid(texto) is False, descripcion)

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el detector sólo dice SÍ a un vmid ocupado.")
