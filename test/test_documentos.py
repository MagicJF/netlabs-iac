#!/usr/bin/env python3
# PROPÓSITO:   probar la REGIÓN GENERADA del documento de un lab --el diagrama de la
#              topología y las tablas-- derivándola de una declaración de verdad, sin
#              Proxmox y sin Ansible. Es la parte del documento que NINGÚN humano escribe,
#              así que sus fallos son silenciosos: una columna que enseña otra cosa o un
#              nombre sin sustituir no rompe nada, simplemente MIENTE.
# INVARIANTES: los casos que TIENEN que cumplirse, y que son el contrato:
#              1. el diagrama lleva un nodo por EQUIPO con su nombre canónico (el que el
#                 invitado tiene en el clúster, `<equipo>-<alias>`) y su dirección, y una
#                 unión por cada segmento por el que tiene pata;
#              2. la SALIDA del lab se dibuja sólo para quien la declara (`uplink`) y se
#                 dibuja distinta (discontinua): es lo que hay al otro lado, no un cable;
#              3. la forma del nodo dice QUÉ es el equipo (`fw` hexágono, `rt` estadio,
#                 `sw` paralelogramo...): con la forma y el color, el diagrama se lee solo;
#              4. la columna `tipo` de las tablas enseña el tipo de EQUIPO (`rt`, `fw`...)
#                 y la PLATAFORMA va aparte (`VM (qemu)`/`LXC`). Antes se pisaba `tipo` con
#                 la plataforma y la tabla decía «VM (qemu)» donde el repo entiende `fw`;
#              5. el nombre canónico sale SUSTITUIDO (`fw-borde`), nunca el literal
#                 `{equipo}-{alias}` -- se sustituía `{lab}`/`{rol}`, que no están en la
#                 plantilla del motor;
#              6. el check de marcadores sin sustituir NO confunde las formas de Mermaid
#                 (`{{"..."}}`, el hexágono del `fw`) con un marcador: un `fw` se renderiza.
# LÍMITES:     prueba el TEXTO generado, no cómo se ve el diagrama: que Mermaid lo dibuje
#              (y que las etiquetas se lean) se comprueba con `mermaid-cli`, que necesita
#              un navegador. Aquí se comprueba que lo GENERADO es correcto y determinista.
#              No toca ningún lab del repo: escribe una declaración en un directorio temporal.
# VER:         deployment_engine/tools/documentos.py (_diagrama_mermaid, _guests_normalizados,
#              _declara_salida, _leyenda_del_diagrama);
#              deployment_engine/templates/lab-region.md.j2; AGENTS.md §Documentación

import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "tools"))

import documentos  # noqa: E402

FALLOS = []


def comprobar(condicion, texto):
    if condicion:
        print(f"  OK    {texto}")
    else:
        print(f"  FALLA {texto}")
        FALLOS.append(texto)


# Una declaración mínima pero con lo que hace falta para que cada caso tenga sustancia: un
# cortafuegos (hexágono) con dos patas y salida, un conmutador (paralelogramo), un servidor
# (cilindro) con `nombre:` NUMÉRICO --para probar que el alias se unifica-- y un puesto que
# no declara salida ni config.
DECLARACION = """
lab:
  nombre: prueba
  bridges:
    - {nombre: vmb_p_gestion, address: 10.99.0.1/24}
    - {nombre: vmb_p_dmz, address: 10.99.9.1/24}
  stages: [1, 2]
vms:
  - {rol: borde, stage: 1, cores: 1, memory: 128, disk: 1, tipo: fw,
     bridges: [vmb_p_gestion, vmb_p_dmz], address: 10.99.0.5/24,
     config: {routeros: {uplink: {}}}, ready: {tipo: routeros_rest, espera: 120}}
containers:
  - {rol: nucleo, stage: 1, cores: 1, memory: 128, disk: 1, tipo: sw,
     names: vmb_p_gestion, bridges: [vmb_p_gestion], address: 10.99.0.6/24}
  - {rol: oficina, stage: 2, cores: 1, memory: 128, disk: 1, tipo: srv, nombre: 7,
     bridges: [vmb_p_dmz], address: 10.99.9.7/24}
  - {rol: puesto, stage: 2, cores: 1, memory: 128, disk: 1, tipo: ws,
     bridges: [vmb_p_gestion], address: 10.99.0.8/24}
"""


def region_generada():
    """La región de un lab de prueba, tal como la escribiría la herramienta.

    La declaración se llama como su CARPETA (`<lab>/<lab>.yml`), que es la regla del repo:
    el directorio temporal se llama `prueba` y por eso el YAML también.
    """
    base = tempfile.mkdtemp(prefix="documentos-")
    directorio = os.path.join(base, "prueba")
    os.mkdir(directorio)
    try:
        with open(os.path.join(directorio, "prueba.yml"), "w", encoding="utf-8") as fichero:
            fichero.write(DECLARACION)
        return documentos.renderizar_region(directorio)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    print("=" * 62)
    print("TESTS DEL DOCUMENTO GENERADO (fixtures, sin Proxmox)")
    print("=" * 62)

    texto = region_generada()

    print("\ncaso 1 — el diagrama es un diagrama de RED: equipos, segmentos y su unión")
    comprobar(
        "b_vmb_p_gestion" in texto and "10.99.0.1/24" in texto,
        "cada segmento (bridge) sale como nodo, con su subred",
    )
    comprobar(
        'i_borde{{"fw-borde<br/>10.99.0.5/24<br/>etapa 1"}}' in texto,
        "el equipo sale con su nombre canónico, su dirección y su etapa",
    )
    comprobar(
        texto.count("i_borde --- b_vmb_p_gestion") == 1
        and texto.count("i_borde --- b_vmb_p_dmz") == 1,
        "y una unión por CADA segmento por el que tiene pata",
    )

    print("\ncaso 2 — la salida se dibuja sólo para quien la declara, y distinta")
    comprobar(
        "i_borde -.->|uplink| salida" in texto,
        "el que declara `uplink` sale con línea discontinua a la salida",
    )
    comprobar(
        texto.count("salida") > 0 and "i_puesto -.->" not in texto,
        "quien NO la declara no tiene borde de salida",
    )

    print("\ncaso 3 — la FORMA dice qué es cada equipo")
    comprobar('i_borde{{"' in texto, "el `fw` es un hexágono")
    comprobar('i_nucleo[/"' in texto, "el `sw` es un paralelogramo")
    comprobar('i_oficina[("' in texto, "el `srv` es un cilindro")
    comprobar('i_puesto["' in texto, "el `ws` es un rectángulo")

    print("\ncaso 4 — `tipo` es el del EQUIPO y la plataforma va aparte")
    comprobar("| borde | fw (filtra) | VM (qemu) | 1 |" in texto, "el fw: tipo de equipo + plataforma")
    comprobar("| nucleo | sw (conmuta) | LXC | 1 |" in texto, "el sw en un contenedor: las dos columnas")
    comprobar("VM (qemu)" in texto and "LXC" in texto, "la plataforma sigue estando, en su columna")

    print("\ncaso 5 — el nombre canónico sale SUSTITUIDO")
    comprobar("{equipo}" not in texto and "{alias}" not in texto, "no queda la plantilla en crudo")
    comprobar("| oficina | srv (servidor) | srv-7 |" in texto, "y el `nombre:` numérico se unifica como alias")

    print("\ncaso 6 — la leyenda sólo habla de los tipos que el lab USA")
    comprobar("`fw` — fw (filtra)" in texto and "`srv` — srv (servidor)" in texto, "salen los que hay")
    comprobar("`rt` —" not in texto, "y NO sale el que no hay: la leyenda no es un vocabulario")

    print("\ncaso 7 — el `{{` de Mermaid no se confunde con un marcador sin sustituir")
    # El render de arriba TIRA (SystemExit) si cree que quedó un marcador. Un lab con `fw`
    # tiene un `{{` en el hexágono, así que llegar hasta aquí ya es la prueba; se afirma para
    # que se lea el porqué.
    comprobar('{{"' in texto, "el hexágono del `fw` se genera y el render no se queja")

    print()
    print("=" * 62)
    if FALLOS:
        print(f"RESULTADO: {len(FALLOS)} comprobación(es) en rojo")
        return 1
    print("RESULTADO: la región generada dice lo que la declaración dice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
