# PROPÓSITO:   decidir dos cosas sobre la CREACIÓN de un invitado, sin red y sin Proxmox:
#              (1) si un fallo de la API al crearlo es un choque de vmid (otro `apply`
#              se llevó ese número entre la lectura del mundo y la creación), que es lo
#              que `apply` reintenta re-derivando; y (2) si el vmid que ya existe es un
#              invitado NUESTRO (mismo lab y mismo rol), en cuyo caso el paso ya está
#              dado y NO se vuelve a crear.
# INVARIANTES: son funciones PURAS de textos a un booleano. (1) dice SÍ sólo a la forma
#              con que Proxmox rechaza un vmid ocupado («already exists» MÁS un indicio
#              de vmid); cualquier otro error dice NO, para no reintentar lo que no se
#              arregla reintentando. (2) dice SÍ sólo si la descripción del invitado
#              lleva NUESTRA marca (lab y rol): un invitado ajeno --o sin marca-- dice
#              NO, y entonces crear es una colisión de verdad y el reintento es correcto.
# LÍMITES:     (1) no distingue de quién es el vmid que chocó: eso lo dice (2) mirando la
#              descripción, no el texto del error. Ninguna de las dos reintenta ni crea:
#              sólo deciden. La marca se compara literal (`lab=<lab> rol=<rol>`), que es
#              la misma que escribe el plan al crear.
# VER:         docs/informe-estado-del-arte-2026-11.md §6.7; tasks/converger.yml;
#              tasks/paso.yml (la guarda que usa `es_guest_del_lab` antes de crear)
"""El vocabulario con que Proxmox dice «ese vmid ya está», y con el que el plan marca lo suyo."""

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


def es_guest_del_lab(descripcion, lab, rol):
    """¿Ese invitado --por su descripción-- es de ESTE lab y de ESTE rol?

    Es la guarda que impide el gemelo: si el vmid que íbamos a crear ya lo ocupa un
    invitado NUESTRO, el paso está dado y no se crea otra vez. Con `lab` y `rol` vacíos
    (una declaración sin rol) dice NO a propósito: sin marca no se adopta nada.

    La comparación es por PALABRA completa (no un `in` a pelo): si no, `lab=01` casaría
    dentro de `lab=011`, y el motor se creería dueño de un invitado ajeno.
    """
    if not descripcion or not lab or not rol:
        return False
    marca = r"(?:^|\s)lab=%s\s+rol=%s(?:\s|$)" % (re.escape(str(lab)), re.escape(str(rol)))
    return bool(re.search(marca, descripcion))


class FilterModule:
    def filters(self):
        return {
            "es_colision_de_vmid": es_colision_de_vmid,
            "es_guest_del_lab": es_guest_del_lab,
        }
