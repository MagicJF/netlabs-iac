#!/usr/bin/env python3
# PROPÓSITO:   la ÚNICA forma sancionada de bloquearse a esperar: sondea una condición
#              cada pocos segundos y sale EN EL INSTANTE en que se cumple, con un tope
#              de tiempo. La condición es el evento (el ciclo terminó, una marca
#              apareció en un diario, un proceso murió), no una duración a ciegas.
# INVARIANTES: no hay `sleep` de duración fija: se duerme el intervalo de SONDEO y se
#              vuelve a preguntar. Si la condición ya se cumple en la primera vuelta,
#              no se duerme nada. Si el tope se agota, se dice qué se estaba esperando
#              y qué se vio al final; nunca se finge que se cumplió.
#              El tope existe siempre (por defecto 1800s): una espera sin tope es un
#              cuelgue con otro nombre.
# LÍMITES:     sólo mira cosas locales: un fichero de estado, un fichero de texto y un
#              PID. No habla con Proxmox ni con ningún invitado (eso es el motor), y no
#              reintenta lo que se estaba esperando.
# VER:         AGENTS.md §El agente no espera: se le avisa; README.md §Cómo se usa
#
# Uso:
#   python3 scripts/esperar.py --lab 04_lab-red-routeros          # hasta que el ciclo cierre
#   python3 scripts/esperar.py --pid 12345                        # hasta que el proceso muera
#   python3 scripts/esperar.py --fichero /tmp/x.log --patron '^PLAY RECAP'
#
# Sale con 0 si la condición se cumplió (ciclo en verde), 1 si se cumplió en rojo
# (ciclo fallido o proceso muerto), 3 si se agotó el tope y 2 si la invocación no vale.

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ciclo  # noqa: E402  (el formato del estado y la vida de un PID son los mismos: una sola definición)

VERDE, ROJO, TOPE, USO = 0, 1, 3, 2


def veredicto(datos):
    """(código, texto) del estado de un ciclo. código None = todavía no se sabe.

    Un estado «corriendo» con el proceso muerto NO es «corriendo»: es un ciclo que se
    cortó (un /stop, un cierre de sesión). Se distingue a propósito, porque esperar a un
    muerto es esperar para siempre.
    """
    if datos is None:
        return USO, "no hay ningún ciclo registrado para ese lab: lánzalo con scripts/ciclo.py"
    estado = datos.get("estado")
    reparto = " ".join(f"{fase['nombre']}={int(fase.get('segundos', 0))}s"
                       for fase in datos.get("fases", []))
    if estado == "corriendo":
        if datos.get("pid") and not ciclo.proceso_vivo(datos["pid"]):
            return ROJO, (f"el ciclo se cortó sin cerrar (pid {datos['pid']} ya no existe) "
                          f"en la fase '{datos.get('fase_actual')}'; el diario dice hasta dónde llegó: "
                          f"{datos.get('log')}")
        return None, f"corriendo · fase={datos.get('fase_actual')} · {reparto}".strip()
    if estado == "ok":
        return VERDE, f"ciclo en VERDE · total={int(datos.get('total_s', 0))}s · {reparto}"
    return ROJO, (f"ciclo en ROJO · rc={datos.get('rc')} · {reparto} · "
                  f"mira {datos.get('log')}")


def main():
    analizador = argparse.ArgumentParser(
        description="Espera con condición y tope: sale en cuanto el evento ocurre.",
    )
    grupo = analizador.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--lab", help="espera a que cierre el ciclo de ese lab")
    grupo.add_argument("--pid", type=int, help="espera a que ese proceso muera")
    grupo.add_argument("--fichero", help="espera a que aparezca un patrón en ese fichero")
    analizador.add_argument("--patron", help="expresión regular a buscar (con --fichero)")
    analizador.add_argument("--tope", type=int, default=1800, help="segundos de tope (por defecto 1800)")
    analizador.add_argument("--intervalo", type=float, default=2.0, help="segundos entre sondeos (por defecto 2)")
    analizador.add_argument("--latido", type=int, default=60,
                            help="cada cuántos segundos decir que sigue esperando (0 = callar; por defecto 60)")
    argumentos = analizador.parse_args()

    if argumentos.fichero and not argumentos.patron:
        return _fallo("--fichero necesita --patron")
    if argumentos.patron and not argumentos.fichero:
        return _fallo("--patron necesita --fichero")

    patron = re.compile(argumentos.patron) if argumentos.patron else None
    ruta_estado = None
    if argumentos.lab:
        ruta_estado = os.path.join(ciclo.RAIZ, "labs", argumentos.lab, "logs", ciclo.ESTADO)

    inicio = time.time()
    ultimo_latido = inicio
    ultimo_texto = ""
    while True:
        # 1) ¿Se cumple ya la condición? (primera vuelta incluida: si ya está, no se duerme)
        if argumentos.pid:
            if not ciclo.proceso_vivo(argumentos.pid):
                print(f"OK    esperar: el proceso {argumentos.pid} ya no existe "
                      f"({round(time.time() - inicio)}s)", flush=True)
                return VERDE
            ultimo_texto = f"proceso {argumentos.pid} vivo"
        elif argumentos.fichero:
            encontrado = False
            try:
                with open(argumentos.fichero, encoding="utf-8", errors="replace") as fichero:
                    encontrado = any(patron.search(linea) for linea in fichero)
            except OSError:
                encontrado = False
            if encontrado:
                print(f"OK    esperar: '{argumentos.patron}' apareció en {argumentos.fichero} "
                      f"({round(time.time() - inicio)}s)", flush=True)
                return VERDE
            ultimo_texto = f"sin '{argumentos.patron}' en {argumentos.fichero}"
        else:
            codigo, texto = veredicto(ciclo.leer_estado(ruta_estado))
            if codigo is not None:
                etiqueta = {VERDE: "OK   ", ROJO: "FALLA"}.get(codigo, "FALLA")
                print(f"{etiqueta} esperar: {texto} ({round(time.time() - inicio)}s)", flush=True)
                return codigo
            ultimo_texto = texto

        # 2) Tope: se dice qué se esperaba y qué se vio, y se sale en ROJO. Nunca se
        #    devuelve verde por haber aguantado mucho rato.
        transcurrido = time.time() - inicio
        if transcurrido >= argumentos.tope:
            return _fallo(f"tope de {argumentos.tope}s agotado esperando; lo último que se vio: {ultimo_texto}")

        if argumentos.latido and (time.time() - ultimo_latido) >= argumentos.latido:
            print(f"...  esperar: {ultimo_texto} · {round(transcurrido)}s de {argumentos.tope}s", flush=True)
            ultimo_latido = time.time()

        # 3) El intervalo de SONDEO, recortado para no pasarse del tope.
        time.sleep(max(0.2, min(argumentos.intervalo, argumentos.tope - transcurrido)))


def _fallo(mensaje):
    print(f"FALLA esperar: {mensaje}", file=sys.stderr, flush=True)
    return TOPE


if __name__ == "__main__":
    sys.exit(main())
