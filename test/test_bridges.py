#!/usr/bin/env python3
# PROPÓSITO:   probar la PROPIEDAD DE LOS BRIDGES sin Proxmox y sin Ansible: que el
#              plan MARQUE el bridge que crea, que `destroy` reconozca esa marca, y
#              —lo que más importa— que NO borre un bridge en la duda. Un bridge no
#              está en ningún pool, así que aquí no hay frontera de propiedad que
#              valga: la decisión entera descansa en el `comments` y en mirar quién
#              lo usa. Por eso se prueba con fixtures y no contra un clúster real.
# INVARIANTES: cada caso tiene que poder FALLAR de verdad. Los casos 3 a 7 describen
#              bridges que `destroy` NO puede tocar: si la función los devolviera en
#              `borrar`, el test se pone en rojo. El caso 1 es el ida y vuelta: la
#              marca que escribe el plan es EXACTAMENTE la que lee `destroy`.
# LÍMITES:     no toca la API real (eso exige credenciales): el estado del mundo es un
#              fixture escrito a mano. Prueba la DECISIÓN, no el efecto en Proxmox
#              (que el bridge desaparezca de verdad se comprueba con `./lab destroy`).
# VER:         README.md §Los bridges; AGENTS.md §Identidad
#
# Uso:  python3 test/test_bridges.py     (código de salida != 0 si algo falla)

import copy
import json
import os
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(RAIZ, "test", "fixtures")
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "tools"))

import declaracion as modulo_declaracion  # noqa: E402
import estado as modulo_estado  # noqa: E402
import identidad as modulo_identidad  # noqa: E402
import plan as modulo_plan  # noqa: E402

# Los mismos valores que los defaults del motor: el test no inventa un entorno, usa
# el del repositorio (vars/engine.yml).
PLANTILLA_DESCRIPCION = "lab={lab} rol={rol} gestionado por netlabs_v4_b"
PLANTILLA_NOMBRE = "{lab}-{rol}"
PLANTILLA_COMENTARIO_BRIDGE = "lab={lab} gestionado por netlabs_v4_b"
PREFIJO_MAC = "BC:24:11"
VMID_MINIMO = 100
VMID_MAXIMO = 999999
NODO = "nodo-de-prueba"

FALLOS = []


def comprobar(condicion, descripcion):
    if condicion:
        print(f"  ok    {descripcion}")
    else:
        print(f"  FALLA {descripcion}")
        FALLOS.append(descripcion)


def fixture_yaml(nombre):
    with open(os.path.join(FIXTURES, nombre), encoding="utf-8") as fichero:
        return yaml.safe_load(fichero)


def declaracion_alfa(bridges_extra=()):
    """La declaración del fixture alfa, normalizada por el motor.

    `bridges_extra` añade bridges a la copia: sirve para probar que de dos bridges
    declarados sólo cae el que lleva la marca.
    """
    normalizada = modulo_declaracion.declaracion_normalizar(fixture_yaml("declaracion-alfa.yml"))
    for nombre in bridges_extra:
        normalizada["bridges"].append({"nombre": nombre, "direccion": None})
    return normalizada


def estado_del_mundo(bridges, configs_ajenas=None, lab="alfa"):
    """El estado del mundo tal como lo compone `estado_desde_api` desde la API.

    `bridges` es {iface: comentario}. Se construye pasando por la función de verdad
    (no un dict a mano) para que el test también cubra la lectura del `comments`.
    """
    red_nodo = [
        {"iface": iface, "type": "bridge", "comments": comentario}
        for iface, comentario in bridges.items()
    ]
    # Los invitados ajenos van con su pool, para que salgan en cluster_recursos.
    cluster_recursos = [
        {"vmid": int(vmid), "type": "lxc", "name": f"ajeno-{vmid}", "node": NODO, "status": "running"}
        for vmid in (configs_ajenas or {})
    ]
    return modulo_estado.estado_desde_api(
        {
            "lab": lab,
            "nodo": NODO,
            "cluster_recursos": cluster_recursos,
            "pools_lista": [{"poolid": lab}],
            "red_nodo": red_nodo,
            "configs": {},
        }
    )


def parametros_motor(con_marca=True):
    parametros = {
        "nodo": NODO,
        "ostemplate_lxc": "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst",
        "comentario_pool": "topología gestionada por netlabs_v4_b (motor por API)",
    }
    if con_marca:
        parametros["comentario_bridge"] = PLANTILLA_COMENTARIO_BRIDGE
    return parametros


def identidad_de(declaracion, estado):
    return modulo_identidad.identidad_asignar(
        declaracion,
        estado,
        PLANTILLA_DESCRIPCION,
        PLANTILLA_NOMBRE,
        PREFIJO_MAC,
        VMID_MINIMO,
        VMID_MAXIMO,
    )


def paso_del_bridge(plan_pasos):
    return [paso for paso in plan_pasos if paso["accion"] == modulo_plan.ACCION_BRIDGE]


def caso_1_el_plan_marca_y_destroy_reconoce():
    print("\ncaso 1 — la marca que escribe el plan es la que lee destroy (ida y vuelta)")
    declaracion = declaracion_alfa()
    # Un mundo sin el bridge: el plan lo crea.
    estado_vacio = estado_del_mundo({})
    pasos = paso_del_bridge(
        modulo_plan.construir_plan(
            declaracion, estado_vacio, identidad_de(declaracion, estado_vacio), parametros_motor()
        )
    )
    comprobar(len(pasos) == 1, "el plan crea el bridge que falta")
    comprobar(
        pasos[0]["parametros"].get("comments") == "lab=alfa gestionado por netlabs_v4_b",
        f"el bridge se crea con la marca del motor: {pasos[0]['parametros'].get('comments')!r}",
    )
    # Y ahora el mundo en el que ese bridge YA existe, con el comentario tal cual lo
    # devolvería Proxmox (con su salto de línea final incluido).
    creado = pasos[0]["parametros"]["comments"]
    estado = estado_del_mundo({"vmb_alfa": creado + "\n"})
    comprobar(
        modulo_estado.estado_bridges_candidatos(declaracion, estado) == ["vmb_alfa"],
        "destroy lo reconoce como candidato a borrar",
    )
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {})
    comprobar(decision["borrar"] == ["vmb_alfa"], "y lo borra: lo creó este lab y no lo usa nadie")


def caso_2_sin_plantilla_no_se_marca_y_por_tanto_no_se_borra():
    print("\ncaso 2 — sin la plantilla del motor el bridge nace sin marca (y se conserva)")
    declaracion = declaracion_alfa()
    estado_vacio = estado_del_mundo({})
    pasos = paso_del_bridge(
        modulo_plan.construir_plan(
            declaracion,
            estado_vacio,
            identidad_de(declaracion, estado_vacio),
            parametros_motor(con_marca=False),
        )
    )
    comprobar(
        "comments" not in pasos[0]["parametros"],
        "sin plantilla el plan NO escribe comentario: mejor sin marca que con una falsa",
    )
    estado = estado_del_mundo({"vmb_alfa": ""})
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {})
    comprobar(decision["borrar"] == [], "y destroy no lo borra: no consta que sea suyo")


def caso_3_un_bridge_sin_marca_se_conserva():
    print("\ncaso 3 — un bridge que ya estaba en el nodo se conserva, y se dice por qué")
    declaracion = declaracion_alfa()
    # El comentario es de una persona, no del motor: el lab encontró el bridge puesto.
    estado = estado_del_mundo({"vmb_alfa": "cable: sw-1 ether5 <-> rt-1 ether2"})
    comprobar(
        modulo_estado.estado_bridges_candidatos(declaracion, estado) == [],
        "no es ni candidato: no se gastará una sola llamada en mirar quién lo usa",
    )
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {})
    comprobar(decision["borrar"] == [], "no se borra")
    comprobar(
        len(decision["conservar"]) == 1 and "marca" in decision["conservar"][0]["motivo"],
        f"y el informe dice el motivo: {decision['conservar'][0]['motivo'] if decision['conservar'] else '—'}",
    )


def caso_4_lo_usa_un_invitado_ajeno():
    print("\ncaso 4 — un bridge del lab que usa un invitado ajeno NO se borra")
    declaracion = declaracion_alfa()
    estado = estado_del_mundo({"vmb_alfa": PLANTILLA_COMENTARIO_BRIDGE.format(lab="alfa")})
    configs_ajenas = {
        "100": {
            "name": "hermesagent",
            "digest": "0" * 40,
            "net0": "virtio=BC:24:11:00:00:01,bridge=vmb_alfa,firewall=1",
        }
    }
    comprobar(
        modulo_estado.estado_bridges_candidatos(declaracion, estado) == ["vmb_alfa"],
        "sí es candidato (lleva la marca del lab)",
    )
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, configs_ajenas)
    comprobar(decision["borrar"] == [], "pero no se borra: hay alguien colgado de él")
    comprobar(
        "vmid=100" in decision["conservar"][0]["motivo"],
        f"y el informe dice quién: {decision['conservar'][0]['motivo'] if decision['conservar'] else '—'}",
    )


def caso_5_se_miran_todas_las_patas():
    print("\ncaso 5 — se miran TODAS las interfaces, no sólo net0")
    declaracion = declaracion_alfa()
    estado = estado_del_mundo({"vmb_alfa": PLANTILLA_COMENTARIO_BRIDGE.format(lab="alfa")})
    configs_ajenas = {
        "101": {
            "name": "caddy",
            "digest": "0" * 40,
            "net0": "virtio=BC:24:11:00:00:02,bridge=vmbr0,firewall=1",
            "net1": "virtio=BC:24:11:00:00:03,bridge=vmb_alfa",
        }
    }
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, configs_ajenas)
    comprobar(
        decision["borrar"] == [],
        "la segunda pata del invitado cuenta igual: borrarlo lo dejaría sin esa red",
    )


def caso_6_si_no_se_pudo_leer_una_config_no_se_borra():
    print("\ncaso 6 — si no se pudo leer la red de un invitado ajeno, no se borra nada")
    declaracion = declaracion_alfa()
    estado = estado_del_mundo({"vmb_alfa": PLANTILLA_COMENTARIO_BRIDGE.format(lab="alfa")})
    # Una config VACÍA es un error de la API: una lectura con éxito siempre trae algo
    # (como mínimo `digest`). No se puede descartar que ese invitado use el bridge.
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {"105": {}})
    comprobar(decision["borrar"] == [], "no se borra: la duda va al lado de conservar")
    comprobar(
        "no se pudo leer" in decision["conservar"][0]["motivo"],
        f"y se dice qué pasó: {decision['conservar'][0]['motivo'] if decision['conservar'] else '—'}",
    )


def caso_7_la_marca_de_otro_lab_no_se_toca():
    print("\ncaso 7 — un bridge marcado por OTRO lab no se toca")
    declaracion = declaracion_alfa()
    estado = estado_del_mundo({"vmb_alfa": PLANTILLA_COMENTARIO_BRIDGE.format(lab="beta")})
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {})
    comprobar(decision["borrar"] == [], "no se borra")
    comprobar(
        "'beta'" in decision["conservar"][0]["motivo"],
        f"y el informe nombra al dueño real: {decision['conservar'][0]['motivo'] if decision['conservar'] else '—'}",
    )


def caso_8_de_dos_declarados_cae_solo_el_marcado():
    print("\ncaso 8 — de dos bridges declarados, sólo cae el que lleva la marca")
    declaracion = declaracion_alfa(bridges_extra=["vmb_alfa_2"])
    estado = estado_del_mundo(
        {
            "vmb_alfa": PLANTILLA_COMENTARIO_BRIDGE.format(lab="alfa"),
            "vmb_alfa_2": "",  # ya estaba en el nodo antes que el lab
        }
    )
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {})
    comprobar(decision["borrar"] == ["vmb_alfa"], f"se borra sólo el marcado: {decision['borrar']}")
    comprobar(
        [c["nombre"] for c in decision["conservar"]] == ["vmb_alfa_2"],
        "y el otro se conserva con su motivo",
    )
    texto = modulo_estado.estado_bridges_texto(decision)
    comprobar(
        "vmb_alfa" in texto and "vmb_alfa_2" in texto,
        "el informe del destroy nombra los dos, borrados y conservados",
    )


def caso_9_un_bridge_declarado_que_no_existe():
    print("\ncaso 9 — un bridge declarado que no existe en el nodo no ensucia el informe")
    declaracion = declaracion_alfa()
    estado = estado_del_mundo({})
    comprobar(
        modulo_estado.estado_bridges_candidatos(declaracion, estado) == [],
        "no hay candidatos: nada que borrar ni que leer",
    )
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {})
    comprobar(
        decision["borrar"] == [] and decision["conservar"] == [],
        "y no se inventa una línea de informe por un bridge que no está",
    )
    comprobar(
        "no declara ninguno que exista" in modulo_estado.estado_bridges_texto(decision),
        "el informe dice exactamente eso",
    )


def caso_10_el_informe_no_se_deja_ningun_bridge_declarado():
    print("\ncaso 10 — con la duda presente, el informe sigue nombrando TODOS los declarados")
    declaracion = declaracion_alfa(bridges_extra=["vmb_alfa_2"])
    estado = estado_del_mundo(
        {
            "vmb_alfa": PLANTILLA_COMENTARIO_BRIDGE.format(lab="alfa"),
            "vmb_alfa_2": "",  # sin marca
        }
    )
    decision = modulo_estado.estado_bridges_a_borrar(declaracion, estado, {"105": {}})
    comprobar(decision["borrar"] == [], "no se borra ninguno: hay una config sin leer")
    comprobar(
        sorted(c["nombre"] for c in decision["conservar"]) == ["vmb_alfa", "vmb_alfa_2"],
        "y el informe nombra los dos, cada uno con su motivo",
    )


def main():
    print("=" * 62)
    print("TESTS DE LA PROPIEDAD DE LOS BRIDGES (fixtures, sin Proxmox)")
    print("=" * 62)
    caso_1_el_plan_marca_y_destroy_reconoce()
    caso_2_sin_plantilla_no_se_marca_y_por_tanto_no_se_borra()
    caso_3_un_bridge_sin_marca_se_conserva()
    caso_4_lo_usa_un_invitado_ajeno()
    caso_5_se_miran_todas_las_patas()
    caso_6_si_no_se_pudo_leer_una_config_no_se_borra()
    caso_7_la_marca_de_otro_lab_no_se_toca()
    caso_8_de_dos_declarados_cae_solo_el_marcado()
    caso_9_un_bridge_declarado_que_no_existe()
    caso_10_el_informe_no_se_deja_ningun_bridge_declarado()
    print()
    print("=" * 62)
    if FALLOS:
        print(f"RESULTADO: {len(FALLOS)} comprobación(es) en rojo")
        return 1
    print("RESULTADO: todos los casos en verde")
    return 0


if __name__ == "__main__":
    sys.exit(main())
