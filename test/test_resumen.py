#!/usr/bin/env python3
# PROPÓSITO:   probar el informe de los diarios (deployment_engine/tools/resumen.py) contra
#              diarios de mentira, en un directorio temporal: sin Proxmox y sin lab.
# INVARIANTES: lo que se prueba es lo que el informe PROMETE: cuenta lo que hay, dice A QUÉ
#              EQUIPO se le hizo cada cosa (derivando el vmid del propio diario, sin fichero
#              de estado), los pasos van EN SU ORDEN, cita la explicación de cada escritura,
#              dice las llamadas que no responden 2xx, trae el veredicto, y NO se calla lo que
#              falta (un diario ausente se avisa; una línea ilegible se cuenta). Un informe
#              que se inventa lo que no está es peor que no tenerlo.
# LÍMITES:     no prueba el texto exacto (mejora a propósito): prueba que estén los datos, la
#              atribución y las ausencias. No comprueba el ancho de las columnas.
# VER:         docs/decisiones/0014 §3; deployment_engine/tools/resumen.py

import importlib.util
import json
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERRAMIENTA = os.path.join(RAIZ, "deployment_engine", "tools", "resumen.py")

fallos = []


def comprobar(condicion, queja):
    if not condicion:
        fallos.append(queja)


def escribir(ruta, lineas):
    with open(ruta, "w", encoding="utf-8") as fichero:
        for linea in lineas:
            fichero.write(json.dumps(linea, ensure_ascii=False) + "\n")


def cargar():
    spec = importlib.util.spec_from_file_location("resumen", HERRAMIENTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def main():
    resumen = cargar()
    temporal = tempfile.mkdtemp(prefix="resumen-prueba-")
    try:
        # Un lab con las vías de acceso que hay: un paso del plan que crea un invitado (de ahí sale
        # el mapa vmid->rol), una escritura DENTRO de un router, una lectura, una llamada
        # torcida, una línea ilegible y un veredicto.
        escribir(os.path.join(temporal, "api.jsonl"), [
            {"ts": "2026-01-01T10:00:00", "verb": "apply", "lab": "prueba", "method": "GET",
             "path": "/cluster/resources", "status": "200", "etiqueta": "leer el mundo"},
            {"ts": "2026-01-01T10:00:01", "verb": "apply", "lab": "prueba", "method": "POST",
             "path": "/nodes/n/qemu", "status": "200",
             "etiqueta": "paso 6: crear_invitado -- el rol 'borde' no está desplegado: se crea con el vmid 111"},
            {"ts": "2026-01-01T10:00:02", "verb": "apply", "lab": "prueba", "method": "POST",
             "path": "/nodes/n/qemu/111/status/start", "status": "200",
             "etiqueta": "paso 12: arrancar_invitado -- el rol 'borde' pertenece a la etapa 1"},
            {"ts": "2026-01-01T10:00:03", "verb": "apply", "lab": "prueba", "api": "routeros",
             "guest": "nucleo", "method": "POST", "path": "/ip/address/add", "status": "200",
             "etiqueta": "escribir addresses: poner la dirección 10.42.1.1/24 en ether2"},
            {"ts": "2026-01-01T10:00:04", "verb": "apply", "lab": "prueba", "api": "routeros",
             "guest": "nucleo", "method": "POST", "path": "/ip/service/set", "status": "400",
             "etiqueta": "escribir ip_services: deshabilitar el servicio 'api'"},
        ])
        escribir(os.path.join(temporal, "interior.jsonl"), [
            {"ts": "2026-01-01T10:00:05", "verb": "apply", "lab": "prueba", "guest": "borde",
             "area": "addresses", "accion": "escribir", "resultado": "ok"},
            {"ts": "2026-01-01T10:00:06", "verb": "apply", "lab": "prueba", "guest": "control",
             "area": "sonda", "accion": "leer", "rc": "1", "resultado": "fallo"},
        ])
        escribir(os.path.join(temporal, "console.jsonl"), [
            {"ts": "2026-01-01T10:00:07", "verb": "apply", "lab": "prueba", "access": "console",
             "accion": "enviar la línea", "vmid": "112", "tipo": "lxc",
             "etiqueta": "arranque del túnel del rol control (intento 1)"},
        ])
        with open(os.path.join(temporal, "api.jsonl"), "a", encoding="utf-8") as fichero:
            fichero.write("{esto no es json\n")
        with open(os.path.join(temporal, "ultimo-verify.txt"), "w", encoding="utf-8") as fichero:
            fichero.write("VERIFICACIÓN del lab 'prueba' — CORRECTO\n  6 invitado(s), 0 fallo(s)\n")

        texto, _ = resumen.resumen_de_lab(temporal)

        # Lo que hay: las vías de acceso, la cuenta, y sobre todo A QUIÉN y EN QUÉ ORDEN.
        comprobar("| Proxmox" in texto and "| RouterOS" in texto,
                  "no lista las vías de acceso en la tabla del vistazo")
        comprobar("apply (converger)" in texto, "no dice de qué verbo es la pasada")
        comprobar("no 2xx" in texto, "no avisa de la columna de las que no responden bien")
        comprobar("## A qué equipos se les tocó algo" in texto, "no hay sección de a quién se tocó")
        comprobar("| borde " in texto and "111" in texto, "no dice a qué vmid pertenece 'borde'")
        comprobar("| nucleo" in texto, "no atribuye la escritura del router a su invitado")
        comprobar("| 6 " in texto and "| 12 " in texto, "no lista los pasos con su número")
        comprobar(texto.index("| 6 ") < texto.index("| 12 "), "los pasos no van en su orden")
        comprobar("poner la dirección 10.42.1.1/24 en ether2" in texto,
                  "no cita la explicación de una escritura")
        comprobar("leer el mundo" not in texto, "mete una LECTURA en el informe de lo escrito")
        comprobar("1 línea(s) ilegible(s)" in texto, "no avisa de la línea ilegible")
        comprobar("CORRECTO" in texto, "no trae el veredicto de la última comprobación")

        # Lo que falta: un diario ausente se avisa, no se da por vacío (la regla del invariante).
        os.unlink(os.path.join(temporal, "console.jsonl"))
        texto, _ = resumen.resumen_de_lab(temporal)
        comprobar("No hay diario de" in texto and "console.jsonl" in texto,
                  "no avisa de un diario que falta")

        # Y un lab sin diarios: lo dice, y no revienta.
        vacio = tempfile.mkdtemp(prefix="resumen-vacio-")
        try:
            texto, _ = resumen.resumen_de_lab(vacio)
            comprobar("No hay ninguna pasada" in texto, "no dice que no hay pasada")
            comprobar("No hay diario de" in texto, "no dice que no hay ningún diario")
        finally:
            shutil.rmtree(vacio, ignore_errors=True)
    finally:
        shutil.rmtree(temporal, ignore_errors=True)

    for queja in fallos:
        print(f"  FALLA {queja}")
    print(f"RESULTADO: {len(fallos)} fallo(s)")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
