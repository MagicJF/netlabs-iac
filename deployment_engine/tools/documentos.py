#!/usr/bin/env python3
# PROPÓSITO:   generar y comprobar la REGIÓN GENERADA del documento de un lab.
#              Es el único escritor de lo que va entre `<!-- generado:inicio -->` y
#              `<!-- generado:fin -->`: las tablas se derivan de la declaración,
#              nunca se redactan.
# INVARIANTES: la salida es DETERMINISTA: sin fechas, sin rutas absolutas y sin
#              orden de fichero (el orden lo fija la declaración). Si el render no
#              es determinista, `check docs` daría falsos positivos, y un check que
#              grita cuando no pasa nada se desactiva -- y entonces no protege.
#              Si los marcadores faltan o están duplicados, FALLA: no adivina y no
#              trunca, porque un documento a medias es peor que un error.
# LÍMITES:     no opina sobre la prosa de fuera de los marcadores, y no conoce
#              ningún lab concreto: el lab es siempre un argumento.
# VER:         README.md §Documentación; AGENTS.md §Documentación
#
# Uso (lo normal es a través de `./lab check docs`):
#     python3 deployment_engine/tools/documentos.py render   <dir-del-lab>
#     python3 deployment_engine/tools/documentos.py comprobar <dir-del-lab>
#     python3 deployment_engine/tools/documentos.py actualizar <dir-del-lab>

import os
import sys

import yaml

# Raíz del repositorio: este fichero vive en deployment_engine/tools/.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLANTILLA = os.path.join(RAIZ, "deployment_engine", "templates", "lab-region.md.j2")
VARS_MOTOR = os.path.join(RAIZ, "deployment_engine", "vars", "engine.yml")

MARCA_INICIO = "<!-- generado:inicio -->"
MARCA_FIN = "<!-- generado:fin -->"

# Los tipos de invitado, tal como se leen en el documento. El nombre de la API
# (`qemu`) no es lo que un humano espera ver; se traduce en un solo sitio.
ETIQUETA_TIPO = {"qemu": "VM (qemu)", "lxc": "LXC"}


def _leer_yaml(ruta):
    with open(ruta, encoding="utf-8") as fichero:
        return yaml.safe_load(fichero)


def _vars_del_motor():
    return _leer_yaml(VARS_MOTOR)


def _filas(filas, columnas):
    """Las filas de una tabla markdown, sin cabecera: la cabecera vive en la
    plantilla, que es la parte rígida del documento. Sin filas -> una fila que lo
    dice, para que no quede una tabla con cabecera y nada debajo."""
    if not filas:
        return "| " + " | ".join(["—"] * columnas) + " |"
    return "\n".join("| " + " | ".join(str(celda) for celda in fila) + " |" for fila in filas)


def _invitados_normalizados(declaracion):
    """Misma normalización que el motor, sin depender de él.

    Se repite a propósito: `documentos.py` es una herramienta y no debe cargar el
    filtro de Ansible para leer un YAML. La duplicación es de 6 líneas y está aquí
    a la vista; la alternativa (importar el filtro) ataría la documentación a
    Ansible, que es justo lo que se quiere evitar.
    """
    invitados = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        for invitado in declaracion.get(seccion) or []:
            invitados.append({**invitado, "tipo": tipo})
    invitados.sort(key=lambda i: (i["escalon"], i["rol"]))
    return invitados


def _localizar_region(texto, ruta_documento):
    """Devuelve (inicio, fin) de los marcadores, o falla explicando el porqué."""
    posiciones_inicio = [
        i for i in range(len(texto)) if texto.startswith(MARCA_INICIO, i)
    ]
    posiciones_fin = [i for i in range(len(texto)) if texto.startswith(MARCA_FIN, i)]
    if len(posiciones_inicio) != 1 or len(posiciones_fin) != 1:
        raise SystemExit(
            f"{ruta_documento}: se esperaba exactamente un `{MARCA_INICIO}` y un "
            f"`{MARCA_FIN}`; hay {len(posiciones_inicio)} y {len(posiciones_fin)}. "
            "No se adivina qué región generar: arréglalo a mano."
        )
    fin = posiciones_fin[0] + len(MARCA_FIN)
    if fin <= posiciones_inicio[0]:
        raise SystemExit(f"{ruta_documento}: `{MARCA_FIN}` aparece antes de `{MARCA_INICIO}`")
    return posiciones_inicio[0], fin


def renderizar_region(directorio_lab):
    """Devuelve la región generada (con marcadores) como texto."""
    nombre_lab = os.path.basename(os.path.normpath(directorio_lab))
    archivo_declaracion = f"{nombre_lab}.yml"
    declaracion = _leer_yaml(os.path.join(directorio_lab, archivo_declaracion))
    motor = _vars_del_motor()

    invitados = _invitados_normalizados(declaracion)
    bridges = declaracion["lab"]["bridges"]
    escalones = sorted(set(declaracion["lab"]["escalones"]))

    tabla_invitados = _filas(
        [
            [
                i["rol"],
                ETIQUETA_TIPO[i["tipo"]],
                i["escalon"],
                i["cores"],
                i["memoria"],
                i["disco"],
                # Las patas del invitado, en orden. Un invitado de varias (`bridges`) las
                # enseña todas: la tabla es la lectura rápida de la topología.
                " + ".join(i.get("bridges") or [i.get("bridge") or ""]),
                i["direccion"],
            ]
            for i in invitados
        ],
        8,
    )

    tabla_bridges = _filas(
        [[b["nombre"], b.get("direccion") or "—"] for b in bridges],
        2,
    )

    # El orden de arranque, derivado: qué roles caen en cada escalón.
    tabla_escalones = _filas(
        [
            [
                escalon,
                ", ".join(i["rol"] for i in invitados if i["escalon"] == escalon) or "—",
            ]
            for escalon in escalones
        ],
        2,
    )

    # Identidad: el nombre canónico SÍ es derivable sin Proxmox (lab + rol). El vmid
    # y la MAC no lo son hasta que se lee el clúster, y por eso salen como guion en
    # vez de inventarse.
    tabla_identidad = _filas(
        [
            [
                i["rol"],
                ETIQUETA_TIPO[i["tipo"]],
                motor["engine_plantilla_nombre"]
                .replace("{lab}", declaracion["lab"]["nombre"])
                .replace("{rol}", i["rol"]),
                "—",
                "—",
            ]
            for i in invitados
        ],
        5,
    )

    with open(PLANTILLA, encoding="utf-8") as fichero:
        plantilla = fichero.read()

    # Sustitución simple y explícita: un marcador despistado se ve en el render.
    sustituciones = {
        "archivo_declaracion": archivo_declaracion,
        "prefijo_mac": motor["engine_prefijo_mac"],
        "tabla_invitados": tabla_invitados,
        "tabla_bridges": tabla_bridges,
        "tabla_escalones": tabla_escalones,
        "tabla_identidad": tabla_identidad,
    }
    resultado = plantilla
    # El comentario de cabecera de la plantilla no es parte de la región: se quita
    # ANTES de buscar marcadores sin sustituir, porque en él aparece `{{ clave }}`
    # como ejemplo y no es un marcador de verdad.
    if resultado.lstrip().startswith("<!-- PROPÓSITO"):
        resultado = resultado[resultado.index(MARCA_INICIO):]
    for clave, valor in sustituciones.items():
        resultado = resultado.replace("{{ " + clave + " }}", str(valor))

    sobrantes = [linea for linea in resultado.splitlines() if "{{" in linea]
    if sobrantes:
        raise SystemExit(
            "la plantilla tiene marcadores sin sustituir: " + "; ".join(sobrantes)
        )
    return resultado.strip("\n")


def leer_como_esta(ruta_documento):
    """La región generada tal y como está escrita ahora mismo en el .md."""
    with open(ruta_documento, encoding="utf-8") as fichero:
        texto = fichero.read()
    inicio, fin = _localizar_region(texto, ruta_documento)
    return texto, (inicio, fin), texto[inicio:fin].strip("\n")


def comprobar(directorio_lab):
    """0 si disco == render; 1 y un mensaje claro si no."""
    nombre_lab = os.path.basename(os.path.normpath(directorio_lab))
    ruta_documento = os.path.join(directorio_lab, f"{nombre_lab}.md")
    if not os.path.exists(ruta_documento):
        print(f"FALLA docs: falta el documento {os.path.relpath(ruta_documento, RAIZ)}")
        return 1
    _, _, en_disco = leer_como_esta(ruta_documento)
    esperado = renderizar_region(directorio_lab)
    if en_disco.strip("\n") != esperado:
        print(f"FALLA docs: la región generada de {os.path.relpath(ruta_documento, RAIZ)} no coincide con su render.")
        print("            Arréglalo con: ./lab check docs --actualizar")
        return 1
    return 0


def actualizar(directorio_lab):
    """Reescribe la región generada y devuelve True si cambió algo."""
    nombre_lab = os.path.basename(os.path.normpath(directorio_lab))
    ruta_documento = os.path.join(directorio_lab, f"{nombre_lab}.md")
    texto, (inicio, fin), en_disco = leer_como_esta(ruta_documento)
    esperado = renderizar_region(directorio_lab)
    if en_disco.strip("\n") == esperado:
        return False
    with open(ruta_documento, "w", encoding="utf-8") as fichero:
        fichero.write(texto[:inicio] + esperado + texto[fin:])
    return True


def main(argumentos):
    if len(argumentos) < 2:
        print(__doc__)
        return 2
    orden, directorio_lab = argumentos[0], argumentos[1]
    if orden == "render":
        print(renderizar_region(directorio_lab))
        return 0
    if orden == "comprobar":
        return comprobar(directorio_lab)
    if orden == "actualizar":
        cambiado = actualizar(directorio_lab)
        print(("región actualizada: " if cambiado else "sin cambios: ")
              + os.path.relpath(directorio_lab, RAIZ))
        return 0
    print(f"orden desconocida: {orden}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
