#!/usr/bin/env python3
# PROPÓSITO:   demostrar que la fase 2 NO cambió el plan de un lab de la fase 1. Un
#              lab que no declara `config:` ni `imagen:` tiene que producir
#              EXACTAMENTE el mismo plan que producía antes de que existiera la
#              configuración del interior: ni un paso más, ni uno menos, ni con otros
#              parámetros.
# INVARIANTES: la comparación es el plan ENTERO (línea a línea), no un resumen: si
#              cambia el orden, se cuela un paso o cambia un parámetro, el test falla.
#              El plan se calcula SIEMPRE contra el fixture (nunca contra el clúster
#              real), o la referencia no significaría nada: los vmids de un clúster
#              real dependen de lo que haya desplegado ese día.
# LÍMITES:     no prueba la fase 2 (eso es `test_interior.py` y el ciclo real): prueba
#              que la fase 1 sigue intacta. Y no puede regenerar la referencia: la
#              referencia es una DECISIÓN (el plan de la fase 1, congelado), y un test
#              que se reescribe solo no vigila nada. Si un cambio del motor altera
#              legítimamente el plan de un lab de la fase 1, se actualiza el fixture
#              A MANO y se dice en el commit por qué.
# VER:         AGENTS.md §Commits y subida a GitHub; docs/decisiones/0005-areas-declaradas.md
#
# 15-nov-2026: las referencias de `test/fixtures/planes-fase1/` se regeneraron A MANO, y por
# un motivo que no es del test: los labs pasaron a llevar su número de antigüedad delante y
# el nombre de cada invitado dejó de ser `<lab>-<rol>` para decir qué EQUIPO es (ADR 0015).
# Las dos cosas cambian la forma del plan --el poolid, la descripción y el `name`/`hostname`
# de cada invitado--, y ese cambio es la decisión, no una regresión. El resto del plan (qué
# pasos, en qué orden, con qué parámetros) no cambió ni un paso: es lo que este test vigila.

# Uso:  python3 test/test_regresion_planes.py     (código de salida != 0 si algo falla)

import difflib
import os
import re
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(RAIZ, "test", "fixtures", "planes-fase1")

# Los labs de la fase 1 del repositorio: ni `config:` ni `imagen:` en ninguno.
# Se listan a mano y el test comprueba que de verdad no declaran config (si algún
# día uno la declara, el test lo dice: ya no es un lab de la fase 1 y su plan PUEDE
# cambiar, pero eso tiene que ser una decisión, no un silencio).
LABS_FASE_1 = ("03_lab-dos-redes", "02_lab-minimo", "01_ejemplo-topologia")

FALLOS = []

# El NOMBRE DEL NODO es entorno, no forma del plan: la referencia se tomó sin
# `secrets.yml` (nodo-simulado) y en una máquina con `secrets.yml` el plan nombra el
# nodo real. Se normaliza ese nombre y NADA MÁS: el resto del plan se compara letra a
# letra. (Con los ficheros de la fase 1 el nodo aparece en las rutas REST y en el
# `porque` de los pasos del pool y de los bridges.)
NODO_DE_REFERENCIA = "nodo-simulado"


def normalizar_nodo(texto):
    """Cambia el nombre real del nodo por el de la referencia, y sólo eso."""
    nombres = re.findall(r"/nodes/([^/\s]+)", texto)
    for nombre in set(nombres):
        if nombre != NODO_DE_REFERENCIA:
            texto = texto.replace(nombre, NODO_DE_REFERENCIA)
    return texto


def comprobar(condicion, descripcion):
    print(("  OK   " if condicion else "  FALLA") + f" {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)
    return condicion


def leer(ruta):
    with open(ruta, encoding="utf-8") as fichero:
        return fichero.read()


def declara_config(lab):
    """¿El lab DECLARA ya `config:` o `imagen:`? Se mira el YAML sin comentarios: una
    mención en un comentario (los `# LÍMITES` hablan del vocabulario) no es una
    declaración, y el test vigila declaraciones, no prosa."""
    texto = leer(os.path.join(RAIZ, "labs", lab, f"{lab}.yml"))
    codigo = "\n".join(
        linea for linea in texto.splitlines() if not linea.lstrip().startswith("#")
    )
    return "config:" in codigo or "imagen:" in codigo


def plan_generado(lab):
    """El plan que el motor produce HOY para ese lab, contra el fixture."""
    orden = ["./lab", "--lab", lab, "plan"]
    proceso = subprocess.run(
        orden, cwd=RAIZ, capture_output=True, text=True, timeout=300
    )
    if proceso.returncode != 0:
        raise RuntimeError(
            f"`{' '.join(orden)}` falló (código {proceso.returncode}):\n"
            + proceso.stdout[-2000:]
            + proceso.stderr[-2000:]
        )
    return leer(os.path.join(RAIZ, "labs", lab, "logs", "plan.txt"))


print("REGRESIÓN DE LOS PLANES DE LA FASE 1 (un lab sin `config:` no cambia de plan)\n")

for lab in LABS_FASE_1:
    print(f"{lab}:")
    if not comprobar(
        not declara_config(lab),
        f"{lab} sigue siendo un lab de la fase 1 (no declara `config:` ni `imagen:`)",
    ):
        continue
    referencia = normalizar_nodo(leer(os.path.join(FIXTURES, f"{lab}.plan.txt")))
    generado = normalizar_nodo(plan_generado(lab))
    igual = referencia == generado
    comprobar(igual, f"{lab}: el plan es idéntico al de la fase 1")
    if not igual:
        print("      diferencias (< lo que había antes, > lo que sale ahora):")
        for linea in list(
            difflib.unified_diff(
                referencia.splitlines(), generado.splitlines(), lineterm="", n=1
            )
        )[:60]:
            print(f"      {linea}")
    print()

if FALLOS:
    print(f"RESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("RESULTADO: el plan de los labs de la fase 1 no cambió ni un paso.")
