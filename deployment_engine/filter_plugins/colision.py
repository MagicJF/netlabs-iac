# PROPÓSITO:   decidir si un fallo de la API al CREAR un invitado es un choque de vmid
#              (otro `apply` se llevó ese número entre la lectura del mundo y la
#              creación), que es lo que `apply` reintenta re-derivando.
# INVARIANTES: es una función PURA de un texto a un booleano: sin red, sin Proxmox y
#              sin Ansible. Sólo dice SÍ a la forma con que Proxmox rechaza un vmid
#              ocupado («already exists» MÁS un indicio de vmid); cualquier otro error
#              dice NO, para no reintentar lo que no se arregla reintentando.
# LÍMITES:     no distingue de quién es el vmid que chocó --eso lo decide el plan, que
#              ya sabe qué es del lab y qué es ajeno--, ni reintenta: sólo mira el texto.
# VER:         docs/informe-estado-del-arte-2026-11.md §6.7; tasks/converger.yml
"""El vocabulario con que Proxmox dice «ese vmid ya está»."""

import re
# Proxmox contesta a un `POST /nodes/<nodo>/{qemu,lxc}` con un vmid ocupado con un 500 y
# un cuerpo del estilo `{"errors":{"vmid":"VM 108 already exists on node 'x'"}}` (una VM)
# o `{"errors":{"vmid":"CT 200 already exists"}}` (un contenedor). Se exige que el texto
# diga «already exists»/«already in use» Y que mencione un vmid: así un «already exists»
# de otra cosa (un pool, un bridge) NO se toma por un choque de vmid, y no se reintenta
# lo que reintentar no arregla.
_YA_EXISTE = re.compile(r"already\s+(?:exists|in\s+use)", re.IGNORECASE)
_ES_VMID = re.compile(r"vmid|\bVM\b|\bCT\b|\bLXC\b", re.IGNORECASE)


def es_colision_de_vmid(texto):
    """¿Este texto (el mensaje del fallo y/o el cuerpo de la API) es un vmid ocupado?"""
    if not texto:
        return False
    return bool(_YA_EXISTE.search(texto)) and bool(_ES_VMID.search(texto))


class FilterModule:
    def filters(self):
        return {"es_colision_de_vmid": es_colision_de_vmid}
