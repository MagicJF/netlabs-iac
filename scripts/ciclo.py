#!/usr/bin/env python3
# PROPÓSITO:   lanzar un ciclo de desarrollo de un lab (`plan` → `destroy` → `apply`) en
#              UNA sola invocación, con un diario propio por ciclo, un estado
#              consultable en JSON y una marca de fin inequívoca (`=== CICLO FIN`), para
#              que quien orquesta no tenga que esperar a ojo ni adivinar cuándo acabó.
# INVARIANTES: el ciclo es la SUMA de los verbos de `./lab`, nunca una segunda vía: cada
#              fase es una invocación del wrapper, que es el único punto de entrada y el
#              único que habla con Ansible. Aquí no se llama a ninguna API y no se toca
#              el mundo por cuenta propia.
#              Una fase que falla CORTA el ciclo: no se sigue sobre un mundo a medias.
#              Nunca hay dos ciclos del mismo lab a la vez (dos labs no caben juntos en
#              el nodo): si ya hay uno en vuelo, se niega en vez de pisarlo.
# LÍMITES:     no decide qué desplegar (eso es la declaración) y no reintenta una fase
#              fallida: el motor es idempotente, se relanza y converge. No sustituye a
#              la pasada suelta de `verify` que se exige antes de publicar (aunque
#              `apply` ya importa `verify.yml` al final, ver `--fases`).
# VER:         AGENTS.md §El agente no espera: se le avisa; README.md §Cómo se usa
#
# Uso:
#   python3 scripts/ciclo.py --lab 04_lab-red-routeros
#   python3 scripts/ciclo.py --lab 04_lab-red-routeros --fases plan,destroy,apply,verify
#
# Quien lo lanza EN SEGUNDO PLANO se queda con la marca de fin como disparador:
#   terminal(background=true, notify=["=== CICLO FIN"])
# y el paso siguiente lo arranca el aviso, no el reloj. Para bloquearse de verdad
# existe `scripts/esperar.py`, que sale en el instante en que el ciclo termina.

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = os.path.join(RAIZ, "lab")

# Los mismos verbos que el wrapper. Un nombre que no esté aquí no es una fase: es una
# errata, y una errata que se descubre a los diez minutos de `destroy` es cara.
VERBOS = ("plan", "preflight", "apply", "verify", "test", "capture", "impair", "destroy")
FASES_POR_DEFECTO = "plan,destroy,apply"
MARCA_FIN = "=== CICLO FIN"
# Tope por fase. No es una espera: es el seguro de que un ciclo colgado (una tarea de
# Proxmox que nunca contesta) se convierte en un fallo con mensaje en vez de en un
# proceso que nadie mira. `--tope-fase 0` lo desactiva.
TOPE_FASE_POR_DEFECTO = 2700
# Segundos que se le dan a una fase para morir educadamente antes del SIGKILL.
GRACIA_AL_MATAR = 15

# La fase en curso y la señal recibida. Con la fase anotada, un SIGTERM al ciclo no deja
# huérfano el `ansible-playbook` de dentro: se mata su GRUPO (arranca con sesión propia) y el
# ciclo termina escribiendo su estado, en vez de morir dejando el mundo a medias sin decirlo
# (hallazgo P1 de Greptile, PR #20).
FASE_EN_CURSO = {"proceso": None}
INTERRUMPIDO = {"senal": 0}


def _al_recibir_senal(numero, _marco):
    """SIGTERM/SIGINT: se anota y se corta la fase; el cierre lo hace `main`."""
    INTERRUMPIDO["senal"] = numero
    proceso = FASE_EN_CURSO.get("proceso")
    if proceso is not None and proceso.poll() is None:
        try:
            os.killpg(proceso.pid, signal.SIGTERM)
        except OSError:
            pass


ESTADO = "ciclo-estado.json"
HISTORIAL = "ciclo-historial.jsonl"


# ---------------------------------------------------------------------------
# Lo que se puede probar sin Ansible (funciones puras, ver test/test_ciclo.py)
# ---------------------------------------------------------------------------

def normalizar_fases(texto):
    """'plan, destroy ,apply' -> ['plan', 'destroy', 'apply'].

    Falla en vez de adivinar: una fase desconocida se dice con el nombre y la lista de
    las que existen. Se conserva el ORDEN pedido, que es el orden de ejecución.
    """
    fases = [parte.strip() for parte in (texto or "").split(",") if parte.strip()]
    if not fases:
        raise ValueError("no hay ninguna fase que ejecutar")
    desconocidas = [fase for fase in fases if fase not in VERBOS]
    if desconocidas:
        raise ValueError(
            f"fase desconocida: {', '.join(desconocidas)} "
            f"(las que existen: {', '.join(VERBOS)})"
        )
    return fases


def leer_estado(ruta):
    """El estado del último ciclo, o None si no hay o está a medias.

    Un JSON truncado NO revienta la lectura: el estado es un auxiliar de orquestación,
    no una fuente de verdad, y quien espera prefiere «no hay estado» a una traza.
    """
    try:
        with open(ruta, encoding="utf-8") as fichero:
            datos = json.load(fichero)
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def escribir_estado(ruta, datos):
    """Escribe el estado de forma ATÓMICA (temporal + rename).

    Quien espera lee este fichero mientras se escribe: un rename es indivisible, así
    que nunca ve medio JSON y no hace falta que nadie bloquee nada.
    """
    temporal = f"{ruta}.tmp"
    with open(temporal, "w", encoding="utf-8") as fichero:
        json.dump(datos, fichero, indent=2, ensure_ascii=False)
        fichero.write("\n")
    os.replace(temporal, ruta)


def proceso_vivo(pid):
    """¿Existe ese PID? (señal 0: no envía nada, sólo pregunta).

    `PermissionError` significa que EXISTE y es de otro usuario: contarlo como muerto
    daría un ciclo «cortado» falso y quien espera se rendiría antes de tiempo.
    """
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False
    return True


def linea_fin(datos):
    """La marca de fin: una sola línea, con el veredicto y el reparto del tiempo.

    Es el disparador del paso siguiente cuando el ciclo va en segundo plano, así que
    tiene que ser estable, corta y llevar el código de salida: `=== CICLO FIN`.
    """
    fases = " ".join(f"{fase['nombre']}={int(fase.get('segundos', 0))}s"
                     for fase in datos.get("fases", []))
    return (f"{MARCA_FIN} lab={datos.get('lab')} estado={datos.get('estado')} "
            f"rc={datos.get('rc')} total={int(datos.get('total_s', 0))}s "
            f"{fases} log={datos.get('log')} ===")


def hay_ansible_en_vuelo(lab, omitir=()):
    """El PID de un `ansible-playbook` de ESTE lab, o None.

    Se lee /proc en vez de usar `pgrep -f`: el patrón de `pgrep` casaría con la propia
    orden que lo lanza (la skill lo tiene medido: un guardia así se espera a sí mismo).
    Aquí sólo cuentan los procesos AJENOS cuyo ejecutable es ansible-playbook.
    """
    omitidos = {int(pid) for pid in omitir if pid}
    try:
        candidatos = os.listdir("/proc")
    except OSError:
        return None
    for nombre in candidatos:
        if not nombre.isdigit() or int(nombre) in omitidos:
            continue
        try:
            with open(f"/proc/{nombre}/cmdline", "rb") as fichero:
                orden = fichero.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "ansible-playbook" in orden and lab in orden:
            return int(nombre)
    return None


def ahora():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------------------------
# La ejecución
# ---------------------------------------------------------------------------

def _ruta_logs(lab):
    return os.path.join(RAIZ, "labs", lab, "logs")


def _eco(diario, texto):
    """La misma línea a la terminal Y al diario del ciclo.

    El diario tiene que poder leerse solo (y `esperar.py --fichero` tiene que poder
    esperar su marca de fin): si la marca viviera sólo en la salida del proceso, el
    diario de un ciclo lanzado en segundo plano no diría cómo acabó.
    """
    print(texto, flush=True)
    diario.write(texto + "\n")
    diario.flush()


def tomar_cerrojo(ruta):
    """Toma el cerrojo del lab sin bloquearse. Devuelve (fichero, None) o (None, motivo).

    El cerrojo es lo único que decide «ya hay un ciclo»: el JSON dice quién corre, pero dos
    procesos que arrancan juntos leen «libre» los dos. `flock` no tiene esa ventana.
    """
    fichero = open(ruta, "w", encoding="utf-8")
    try:
        fcntl.flock(fichero, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fichero.close()
        return None, f"ya hay un ciclo en vuelo para este lab (cerrojo {ruta})"
    return fichero, None


def _fase(nombre, argumentos, diario, tope):
    """Ejecuta UNA fase del ciclo. Devuelve (rc, segundos, motivo_de_corte).

    La salida va al diario del ciclo, no a la terminal: el ciclo se lanza para que
    nadie lo mire, y el ruido de Ansible en el contexto de quien orquesta no aporta.
    """
    orden = [sys.executable, LAB, "--lab", argumentos["lab"], nombre]
    if nombre == "destroy":
        orden.append("--yes")
    inicio = time.time()
    _eco(diario, f"--- CICLO FASE {nombre} · {ahora()} · tope {tope or 'sin'}s")
    diario.write(f"\n########## CICLO FASE {nombre} · {ahora()} ##########\n")
    diario.flush()
    proceso = subprocess.Popen(
        orden, cwd=RAIZ, stdout=diario, stderr=subprocess.STDOUT,
        start_new_session=True,  # grupo propio: se puede matar la fase entera, no sólo el wrapper
    )
    FASE_EN_CURSO["proceso"] = proceso
    motivo = ""
    try:
        codigo = proceso.wait(timeout=tope or None)
    except subprocess.TimeoutExpired:
        motivo = f"la fase '{nombre}' pasó del tope de {tope}s"
        _eco(diario, f"--- CICLO FASE {nombre} · TOPE AGOTADO ({tope}s) · se corta")
        try:
            os.killpg(proceso.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            proceso.wait(timeout=GRACIA_AL_MATAR)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proceso.pid, signal.SIGKILL)
            except OSError:
                pass
            proceso.wait()
        codigo = 124  # el mismo código que `timeout(1)`: se distingue de un fallo de Ansible
    finally:
        FASE_EN_CURSO["proceso"] = None
    return codigo, time.time() - inicio, motivo


def main():
    analizador = argparse.ArgumentParser(
        description="Un ciclo de desarrollo completo de un lab, con marca de fin.",
        epilog=("Se lanza en segundo plano y el aviso de fin dispara el paso siguiente: "
                "terminal(background=true, notify=['=== CICLO FIN']). "
                "Para bloquearse con tope: python3 scripts/esperar.py --lab <lab>"),
    )
    analizador.add_argument("--lab", required=True, help="carpeta del lab (labs/<lab>)")
    analizador.add_argument(
        "--fases", default=FASES_POR_DEFECTO,
        help=(f"fases en orden, separadas por comas (por defecto {FASES_POR_DEFECTO}). "
              "`apply` ya importa verify.yml al final; añade `verify` sólo si quieres "
              "la pasada suelta que se exige antes de publicar"),
    )
    analizador.add_argument(
        "--tope-fase", type=int, default=TOPE_FASE_POR_DEFECTO,
        help=f"segundos por fase antes de cortarla (por defecto {TOPE_FASE_POR_DEFECTO}; 0 = sin tope)",
    )
    argumentos = analizador.parse_args()

    lab = argumentos.lab
    if not os.path.isdir(os.path.join(RAIZ, "labs", lab)):
        return _fallo(f"no existe labs/{lab}/")
    try:
        fases = normalizar_fases(argumentos.fases)
    except ValueError as error:
        return _fallo(str(error))

    carpeta = _ruta_logs(lab)
    os.makedirs(carpeta, exist_ok=True)

    # Cerrojo del lab. El estado en JSON dice quién corre, pero entre dos procesos que
    # arrancan a la vez no hay carrera que el JSON pueda ganar -- los dos leen «libre» y los
    # dos siguen. `flock` sí: el segundo se niega en el acto. Se toma ANTES de mirar el JSON
    # y se suelta al salir (el descriptor se cierra con el proceso) (hallazgo P1 de Greptile,
    # PR #20).
    ruta_cerrojo = os.path.join(carpeta, "ciclo.lock")
    cerrojo, motivo_cerrojo = tomar_cerrojo(ruta_cerrojo)
    if cerrojo is None:
        return _fallo(motivo_cerrojo)

    # Y una señal al ciclo corta la fase, no se queda a medias en silencio.
    signal.signal(signal.SIGTERM, _al_recibir_senal)
    signal.signal(signal.SIGINT, _al_recibir_senal)
    ruta_estado = os.path.join(carpeta, ESTADO)
    sello = time.strftime("%Y%m%dT%H%M%S")
    ruta_diario = os.path.join(carpeta, f"ciclo-{sello}.log")

    # Nunca dos ciclos del mismo lab a la vez: dos `apply` en paralelo se pisan los vmids
    # y dejan el nodo a medias. Se dice quién está corriendo, no se pisa.
    previo = leer_estado(ruta_estado)
    if previo and previo.get("estado") == "corriendo" and proceso_vivo(previo.get("pid")):
        return _fallo(
            f"ya hay un ciclo en vuelo para {lab} (pid {previo.get('pid')}, "
            f"fase {previo.get('fase_actual')}). Espera a su marca de fin con "
            f"`python3 scripts/esperar.py --lab {lab}`"
        )
    ajeno = hay_ansible_en_vuelo(lab, omitir=(os.getpid(), os.getppid()))
    if ajeno:
        return _fallo(
            f"hay un ansible-playbook de {lab} corriendo (pid {ajeno}) que no lanzó este "
            "ciclo: dos a la vez se pisan. Espera a que acabe"
        )

    datos = {
        "lab": lab, "sello": sello, "pid": os.getpid(), "estado": "corriendo",
        "inicio": ahora(), "fin": None, "total_s": 0, "rc": None,
        "fase_actual": fases[0], "fases": [],
        "log": os.path.relpath(ruta_diario, RAIZ),
    }
    escribir_estado(ruta_estado, datos)
    print(f"=== CICLO INICIO lab={lab} sello={sello} fases={','.join(fases)} ===", flush=True)
    print(f"log: {datos['log']}", flush=True)
    print(f"estado: {os.path.relpath(ruta_estado, RAIZ)}", flush=True)

    inicio = time.time()
    with open(ruta_diario, "w", encoding="utf-8") as diario:
        for fase in fases:
            datos["fase_actual"] = fase
            escribir_estado(ruta_estado, datos)
            inicio_fase = ahora()
            codigo, segundos, motivo = _fase(fase, {"lab": lab}, diario, argumentos.tope_fase)
            datos["fases"].append({
                "nombre": fase, "inicio": inicio_fase, "fin": ahora(),
                "segundos": round(segundos, 1), "rc": codigo, "motivo": motivo,
            })
            datos["rc"] = codigo
            datos["total_s"] = round(time.time() - inicio, 1)
            _eco(diario, f"=== CICLO FASE {fase} rc={codigo} {round(segundos)}s ===")
            if INTERRUMPIDO["senal"]:
                datos["estado"] = "interrumpido"
                datos["motivo"] = f"el ciclo recibió la señal {INTERRUMPIDO['senal']}"
                _eco(diario, f"--- CICLO INTERRUMPIDO por la señal {INTERRUMPIDO['senal']}")
                break
            if codigo != 0:
                datos["estado"] = "fallo"
                if motivo:
                    _eco(diario, f"--- CICLO motivo: {motivo}")
                break
        else:
            datos["estado"] = "ok"

    datos["fin"] = ahora()
    datos["total_s"] = round(time.time() - inicio, 1)
    datos["fase_actual"] = None
    escribir_estado(ruta_estado, datos)
    with open(os.path.join(carpeta, HISTORIAL), "a", encoding="utf-8") as historial:
        historial.write(json.dumps({
            "sello": sello, "lab": lab, "estado": datos["estado"], "rc": datos["rc"],
            "inicio": datos["inicio"], "total_s": datos["total_s"],
            "fases": {fase["nombre"]: fase["segundos"] for fase in datos["fases"]},
        }, ensure_ascii=False) + "\n")

    print(linea_fin(datos), flush=True)
    with open(ruta_diario, "a", encoding="utf-8") as diario:
        diario.write(f"\n{linea_fin(datos)}\n")
    return 0 if datos["estado"] == "ok" else 1


def _fallo(mensaje):
    print(f"FALLA ciclo: {mensaje}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
