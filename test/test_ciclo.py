#!/usr/bin/env python3
# PROPÓSITO:   probar la capa de orquestación SIN Ansible y sin Proxmox: que el estado
#              de un ciclo se lea y se escriba entero, que una fase desconocida se
#              rechace antes de destruir nada, y —lo que más importa— que quien espera
#              distinga «sigue corriendo» de «se cortó» y no se quede esperando a un
#              proceso muerto.
# INVARIANTES: cada caso tiene que poder FALLAR de verdad. El caso del PID muerto es el
#              que da sentido a todo: si `veredicto` devolviera «sigue» para un ciclo
#              cuyo proceso ya no existe, `esperar.py` agotaría el tope en balde, que es
#              exactamente la espera ciega que estas herramientas vienen a quitar.
# LÍMITES:     prueba las DECISIONES y el contrato de la marca de fin, no el despliegue:
#              que un ciclo real converja lo dice el ciclo real (`scripts/ciclo.py`).
# VER:         AGENTS.md §El agente no espera: se le avisa; README.md §Cómo se usa
#
# Uso:  python3 test/test_ciclo.py     (código de salida != 0 si algo falla)

import json
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import ciclo  # noqa: E402
import esperar  # noqa: E402

FALLOS = []


def comprobar(nombre, condicion, detalle=""):
    if condicion:
        print(f"  ok    {nombre}")
    else:
        print(f"  ROJO  {nombre}{(' · ' + detalle) if detalle else ''}")
        FALLOS.append(nombre)


def caso_1_las_fases_se_normalizan_y_el_orden_se_respeta():
    comprobar("por defecto: plan, destroy, apply",
              ciclo.normalizar_fases(ciclo.FASES_POR_DEFECTO) == ["plan", "destroy", "apply"])
    comprobar("los espacios no cuentan y el orden pedido se conserva",
              ciclo.normalizar_fases(" apply , plan ") == ["apply", "plan"])
    try:
        ciclo.normalizar_fases("plan,applyy")
    except ValueError as error:
        comprobar("una fase desconocida se rechaza nombrando la que existe",
                  "applyy" in str(error) and "destroy" in str(error), str(error))
    else:
        comprobar("una fase desconocida se rechaza nombrando la que existe", False, "no falló")
    try:
        ciclo.normalizar_fases("  ,  ")
    except ValueError:
        comprobar("sin fases se rechaza", True)
    else:
        comprobar("sin fases se rechaza", False, "no falló")


def caso_2_el_estado_va_y_vuelve_entero():
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = os.path.join(carpeta, "ciclo-estado.json")
        comprobar("sin fichero, el estado es None", ciclo.leer_estado(ruta) is None)
        datos = {"lab": "x", "estado": "corriendo", "pid": os.getpid(),
                 "fases": [{"nombre": "plan", "segundos": 12.5, "rc": 0}]}
        ciclo.escribir_estado(ruta, datos)
        comprobar("lo escrito se lee igual", ciclo.leer_estado(ruta) == datos)
        comprobar("no queda temporal a medias", not os.path.exists(ruta + ".tmp"))
        with open(ruta, "w", encoding="utf-8") as fichero:
            fichero.write('{"lab": "x", "estado":')  # un /stop a mitad de escritura
        comprobar("un JSON truncado no revienta la lectura", ciclo.leer_estado(ruta) is None)


def caso_3_la_marca_de_fin_lleva_lo_que_hace_falta_para_disparar():
    datos = {"lab": "04_lab", "estado": "ok", "rc": 0, "total_s": 1141.4,
             "log": "labs/04_lab/logs/ciclo-x.log",
             "fases": [{"nombre": "destroy", "segundos": 154.2},
                       {"nombre": "apply", "segundos": 987.1}]}
    linea = ciclo.linea_fin(datos)
    comprobar("empieza por la marca exacta", linea.startswith(ciclo.MARCA_FIN))
    comprobar("lleva lab, estado y rc", "lab=04_lab" in linea and "estado=ok" in linea and "rc=0" in linea)
    comprobar("lleva el reparto del tiempo por fase",
              "destroy=154s" in linea and "apply=987s" in linea, linea)
    comprobar("es UNA sola línea", "\n" not in linea)


def caso_4_quien_espera_distingue_corriendo_de_cortado():
    # «Sin estado» no es una invocación inválida: es la primera vuelta de una espera legítima
    # (el ciclo se acaba de lanzar y todavía no ha escrito su estado). Se sigue esperando.
    comprobar("sin estado todavía no se sabe: sigue esperando",
              esperar.veredicto(None)[0] is None)
    codigo, _ = esperar.veredicto({"estado": "corriendo", "pid": os.getpid(), "fases": []})
    comprobar("corriendo con el proceso vivo: sigue esperando", codigo is None)
    codigo, texto = esperar.veredicto(
        {"estado": "corriendo", "pid": 999999, "fase_actual": "apply", "fases": []})
    comprobar("corriendo con el proceso muerto: se cortó, no se espera más",
              codigo == esperar.ROJO and "cortó" in texto, texto)
    comprobar("en verde da 0", esperar.veredicto({"estado": "ok", "fases": []})[0] == esperar.VERDE)
    comprobar("en rojo da 1", esperar.veredicto({"estado": "fallo", "rc": 2, "fases": []})[0] == esperar.ROJO)


def caso_5_el_pid_se_pregunta_sin_matar_nada():
    comprobar("el propio proceso está vivo", ciclo.proceso_vivo(os.getpid()) is True)
    comprobar("un pid que no existe no lo está", ciclo.proceso_vivo(999999) is False)


def caso_6_el_ciclo_se_niega_antes_de_tocar_nada():
    """La validación corre por el camino real (el CLI), no por una copia de la regla."""
    guion = os.path.join(RAIZ, "scripts", "ciclo.py")

    resultado = subprocess.run([sys.executable, guion, "--lab", "no_existe_este_lab"],
                               capture_output=True, text=True)
    comprobar("un lab que no existe se rechaza con 2",
              resultado.returncode == 2 and "no existe labs/" in resultado.stderr,
              resultado.stderr.strip())

    resultado = subprocess.run([sys.executable, guion, "--lab", "04_lab-red-routeros",
                                "--fases", "plan,applyy"], capture_output=True, text=True)
    comprobar("una fase con errata se rechaza ANTES de destruir nada",
              resultado.returncode == 2 and "applyy" in resultado.stderr,
              resultado.stderr.strip())


def caso_7_el_cerrojo_no_deja_pasar_dos_ciclos():
    """Dos ciclos a la vez se pisan los vmids: el segundo tiene que negarse EN EL ACTO.

    El JSON de estado no basta: dos procesos que arrancan juntos leen «libre» los dos. Se
    prueba con el cerrojo de verdad, no con una copia de la regla.
    """
    carpeta = tempfile.mkdtemp(prefix="ciclo-cerrojo-")
    ruta = os.path.join(carpeta, "ciclo.lock")
    primero, motivo = ciclo.tomar_cerrojo(ruta)
    comprobar("el primero toma el cerrojo", primero is not None and motivo is None, str(motivo))

    # El segundo es OTRO proceso: el cerrojo es del fichero, no del intérprete.
    guion = os.path.join(RAIZ, "scripts", "ciclo.py")
    resultado = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import ciclo; "
         "f, m = ciclo.tomar_cerrojo(%r); print('TOMA' if f else m)" % (
             os.path.join(RAIZ, "scripts"), ruta)],
        capture_output=True, text=True)
    comprobar("el segundo se niega y dice por qué",
              "cerrojo" in resultado.stdout and "TOMA" not in resultado.stdout,
              resultado.stdout.strip() + resultado.stderr.strip())

    primero.close()  # el descriptor se cierra: el cerrojo se suelta
    tercero, motivo3 = ciclo.tomar_cerrojo(ruta)
    comprobar("al soltarlo, el siguiente entra",
              tercero is not None and motivo3 is None, str(motivo3))
    if tercero:
        tercero.close()


def caso_8_una_senal_corta_la_fase_no_la_deja_huerfana():
    """Un SIGTERM al ciclo tiene que matar el `ansible-playbook` de dentro.

    Si no, el proceso que orquesta se corta, la fase sigue hablando con Proxmox y el mundo
    queda a medias sin que nadie lo sepa.
    """
    hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            start_new_session=True)
    try:
        ciclo.FASE_EN_CURSO["proceso"] = hijo
        ciclo._al_recibir_senal(15, None)
        hijo.wait(timeout=10)
        comprobar("la señal mata la fase en curso", hijo.returncode is not None)
        comprobar("y se anota la señal recibida", ciclo.INTERRUMPIDO["senal"] == 15,
                  str(ciclo.INTERRUMPIDO))
    finally:
        ciclo.FASE_EN_CURSO["proceso"] = None
        ciclo.INTERRUMPIDO["senal"] = 0
        if hijo.poll() is None:
            hijo.kill()



def caso_9_la_espera_no_se_conforma_con_el_ciclo_anterior():
    """Un `--lab` recién lanzado no puede leer el `ok` del ciclo ANTERIOR y dar el paso por bueno.

    Se prueba por el camino real (el CLI), con un estado viejo escrito en un lab de mentira: la
    espera tiene que agotar el tope, no contestar verde.
    """
    import shutil
    base = tempfile.mkdtemp(prefix="esperar-")
    lab = "lab_de_prueba_esperar"
    carpeta = os.path.join(base, "labs", lab, "logs")
    os.makedirs(carpeta)
    try:
        # El estado de un ciclo que terminó hace un rato y en verde.
        viejo = {"estado": "ok", "inicio": "2026-11-20T10:00:00", "fin": "2026-11-20T10:10:00",
                 "total_s": 600, "rc": 0, "fases": [{"nombre": "apply", "segundos": 600}],
                 "fase_actual": None, "log": "x"}
        with open(os.path.join(carpeta, ciclo.ESTADO), "w", encoding="utf-8") as f:
            json.dump(viejo, f)
        def correr(extra):
            guion = (
                "import sys; sys.path.insert(0, %r); import esperar, ciclo; ciclo.RAIZ = %r; "
                "sys.argv = ['esperar', '--lab', %r, '--tope', '3', '--intervalo', '0.5', "
                "'--latido', '0'] + %r; sys.exit(esperar.main())"
                % (os.path.join(RAIZ, "scripts"), base, lab, extra))
            return subprocess.run([sys.executable, "-c", guion], capture_output=True, text=True)

        resultado = correr([])
        comprobar("con un estado anterior se agota el tope (no se da por bueno)",
                  resultado.returncode == 3 and "tope" in resultado.stderr,
                  f"rc={resultado.returncode} {resultado.stdout.strip()} {resultado.stderr.strip()}")

        resultado = correr(["--desde", "0"])
        comprobar("con --desde 0 sí vale el que haya",
                  resultado.returncode == 0 and "VERDE" in resultado.stdout,
                  f"rc={resultado.returncode} {resultado.stdout.strip()}")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def caso_10_una_invocacion_invalida_sale_con_2():
    guion = os.path.join(RAIZ, "scripts", "esperar.py")
    resultado = subprocess.run([sys.executable, guion, "--fichero", "/etc/hostname"],
                               capture_output=True, text=True)
    comprobar("--fichero sin --patron es uso inválido (2), no tope agotado (3)",
              resultado.returncode == 2, f"rc={resultado.returncode} {resultado.stderr.strip()}")
    resultado = subprocess.run([sys.executable, guion, "--patron", "x"],
                               capture_output=True, text=True)
    comprobar("--patron sin --fichero también es uso inválido",
              resultado.returncode == 2, f"rc={resultado.returncode} {resultado.stderr.strip()}")

    # Una FIFO sin escritor dejaría `open()` bloqueado y el tope no se miraría nunca.
    base = tempfile.mkdtemp(prefix="esperar-fifo-")
    fifo = os.path.join(base, "tubo")
    os.mkfifo(fifo)
    try:
        resultado = subprocess.run([sys.executable, guion, "--fichero", fifo, "--patron", "x",
                                    "--tope", "2"], capture_output=True, text=True, timeout=15)
        comprobar("una FIFO se rechaza en el acto (no se cuelga abriéndola)",
                  resultado.returncode == 2 and "fichero normal" in resultado.stderr,
                  f"rc={resultado.returncode} {resultado.stderr.strip()}")
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)

def main():
    print("=" * 62)
    print("TESTS DE LA ORQUESTACIÓN DEL CICLO (sin Ansible, sin Proxmox)")
    print("=" * 62)
    caso_1_las_fases_se_normalizan_y_el_orden_se_respeta()
    caso_2_el_estado_va_y_vuelve_entero()
    caso_3_la_marca_de_fin_lleva_lo_que_hace_falta_para_disparar()
    caso_4_quien_espera_distingue_corriendo_de_cortado()
    caso_5_el_pid_se_pregunta_sin_matar_nada()
    caso_6_el_ciclo_se_niega_antes_de_tocar_nada()
    caso_7_el_cerrojo_no_deja_pasar_dos_ciclos()
    caso_8_una_senal_corta_la_fase_no_la_deja_huerfana()
    caso_9_la_espera_no_se_conforma_con_el_ciclo_anterior()
    caso_10_una_invocacion_invalida_sale_con_2()
    print()
    print("=" * 62)
    if FALLOS:
        print(f"RESULTADO: {len(FALLOS)} comprobación(es) en rojo")
        return 1
    print("RESULTADO: todos los casos en verde")
    return 0


if __name__ == "__main__":
    sys.exit(main())
