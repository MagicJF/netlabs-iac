#!/usr/bin/env python3
# PROPÓSITO:   leer los diarios de un lab y escribir, en un folio y en forma de INFORME, qué
#              ha pasado: de un vistazo (cuántas llamadas hizo cada vía de acceso y cuántas no
#              respondieron bien), a QUÉ EQUIPOS se les tocó algo (con su vmid y su rol, uno
#              por línea), los pasos del despliegue EN SU ORDEN, qué se escribió dentro de
#              cada equipo, y el veredicto de la última comprobación. Es lo que se mira al
#              terminar; el diario (logs/*.jsonl) es lo que se mira cuando algo va mal.
# INVARIANTES: sólo LEE. No habla con Proxmox ni con nadie, no escribe en los diarios, y no
#              inventa: lo que no está en ellos no aparece. Un invitado al que no se le tocó
#              nada sale con 0, no se esconde (regla 11: no hay fichero de estado, el mapa de
#              vmids se DERIVA de lo que el motor dijo al crear). Si un diario no existe, se
#              dice -- no se da por vacío (regla 5: una ejecución sin diario no ocurrió).
# LÍMITES:     sólo stdlib. No juzga si el lab está bien (eso es `verify`); traduce lo que ya
#              está escrito, para no tener que leer miles de líneas. El diario no marca dónde
#              empieza cada pasada, así que cuenta "todas las pasadas de ese verbo" (ADR 0014
#              §2), y por eso las escrituras repetidas se cuentan (`×N`) en vez de repetirse.
# VER:         docs/decisiones/0014; AGENTS.md §Mapa (los diarios de un lab)

import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cómo se llama cada vía de acceso en el informe. La de Proxmox no se etiqueta a sí misma en la
# línea (las otras sí, con `api`): se dice aquí, en un solo sitio, en vez de repartir la
# suposición por el código.
ACCESOS = {
    "proxmox": "Proxmox",
    "routeros": "RouterOS",
    "rest": "RouterOS",
    "console": "la consola",
}

# Las respuestas que cuentan como "bien". Lo que no esté aquí se señala aparte.
BIEN = ("200", "201", "204")

VERBOS_LEGIBLES = {
    "plan": "plan (ordenar sin tocar nada)",
    "preflight": "preflight (mirar sin tocar nada)",
    "apply": "apply (converger)",
    "verify": "verify (comprobar)",
    "destroy": "destroy (destruir)",
}


def _lineas(ruta):
    """Las líneas del diario que se puedan leer, con su número para poder citarlo.

    Una línea ilegible no se tira en silencio: se cuenta y se dice. Un diario roto es un
    dato, no un estorbo.
    """
    if not os.path.exists(ruta):
        return None, 0
    buenas, rotas = [], 0
    with open(ruta, encoding="utf-8") as fichero:
        for numero, texto in enumerate(fichero, 1):
            texto = texto.strip()
            if not texto:
                continue
            try:
                buenas.append((numero, json.loads(texto)))
            except json.JSONDecodeError:
                rotas += 1
    return buenas, rotas


def _tabla(cabeceras, filas):
    """Una tabla de verdad: cabecera, raya y columnas alineadas.

    Se pinta a mano, sin depender de nada, y se lee igual en crudo que renderizada: esto es
    un informe, no un volcado. Cada columna, tan ancha como su celda más larga.
    """
    todo = [[str(c) for c in cabeceras]] + [[str(c) for c in fila] for fila in filas]
    anchos = [max(len(fila[i]) for fila in todo) for i in range(len(cabeceras))]

    def _pintar(fila):
        return "| " + " | ".join(celda.ljust(anchos[i]) for i, celda in enumerate(fila)) + " |"

    salida = [_pintar(todo[0]), "|" + "|".join("-" * (a + 2) for a in anchos) + "|"]
    salida += [_pintar(fila) for fila in todo[1:]]
    return salida


def _mapa_de_guests(api, tunnel, lab):
    """vmid -> (rol, tipo) y rol -> vmids. Se DERIVA del diario; no hay otro sitio.

    "El rol 'servidor' no está desplegado: se crea con el vmid 114" está escrito en el diario
    por el propio motor, así que de ahí sale el mapa sin inventar un fichero de estado
    (regla 11). Sin esto, el informe podría decir qué se hizo pero no A QUIÉN.
    """
    mapa = {}
    for _, d in api:
        etiqueta = str(d.get("etiqueta") or "")
        ruta = str(d.get("path") or "")
        tipo = "lxc" if "/lxc" in ruta else ("qemu" if "/qemu" in ruta else "")
        creado = re.search(r"el rol '([\w.\-]+)'.*?vmid (\d+)", etiqueta)
        if creado:
            vmid, rol = creado.group(2), creado.group(1)
            mapa.setdefault(vmid, [rol, ""])
            if tipo:
                mapa[vmid][1] = tipo
        # "paro del invitado 111 (<lab>-borde)": el nombre lleva el lab delante, y el rol es
        # lo que queda al quitárselo.
        por_nombre = re.search(r"invitado (\d+) \(([^)]+)\)", etiqueta)
        if por_nombre:
            vmid, nombre = por_nombre.group(1), por_nombre.group(2)
            rol = nombre[len(lab) + 1:] if nombre.startswith(lab + "-") else nombre
            mapa.setdefault(vmid, [rol, ""])
            if tipo and not mapa[vmid][1]:
                mapa[vmid][1] = tipo
    for _, d in tunnel:
        vmid = str(d.get("vmid") or "")
        if not vmid:
            continue
        del_rol = re.search(r"del rol ([\w.\-]+)", str(d.get("etiqueta") or ""))
        mapa.setdefault(vmid, ["", str(d.get("tipo") or "")])
        if del_rol and not mapa[vmid][0]:
            mapa[vmid][0] = del_rol.group(1)
    return mapa


def _guest_de(linea, mapa):
    """A qué equipo se le hizo esta llamada. Vacío = no es a un equipo (el clúster, un pool).

    Tres fuentes, en orden de fiabilidad: el campo que escribe la vía de acceso de RouterOS, el vmid
    de la ruta, y el rol que el propio motor nombró en su explicación.
    """
    if linea.get("guest"):
        return str(linea["guest"])
    en_ruta = re.search(r"/(?:lxc|qemu)/(\d+)", str(linea.get("path") or ""))
    if en_ruta and mapa.get(en_ruta.group(1), [""])[0]:
        return mapa[en_ruta.group(1)][0]
    en_texto = re.search(r"el rol '([\w.\-]+)'", str(linea.get("etiqueta") or ""))
    return en_texto.group(1) if en_texto else ""


def resumen_de_lab(carpeta, verbo=None):
    """El informe de un lab: (texto para leer, texto para el fichero).

    `verbo` elige la pasada que se cuenta -- `apply` enseña lo que el motor escribió, que es
    lo que se quiere mirar al terminar. Por defecto, la última que haya en el diario: si
    después se pasó un `verify`, lo que se lee es la comprobación, que es otra cosa.
    """
    salida, escribir = [], []

    def ambos(texto=""):
        salida.append(texto)
        escribir.append(texto)

    def tabla(cabeceras, filas):
        for linea in _tabla(cabeceras, filas):
            ambos(linea)

    api, rotas_api = _lineas(os.path.join(carpeta, "api.jsonl"))
    interior, rotas_interior = _lineas(os.path.join(carpeta, "interior.jsonl"))
    tunnel, rotas_tunnel = _lineas(os.path.join(carpeta, "console.jsonl"))
    # Un diario que no existe no es un diario vacío: se dice (regla 5). Se mira ANTES de
    # vaciar a `None` para no confundir "no lo hay" con "no tiene líneas".
    faltan = [nombre for nombre, leidas in (("api.jsonl", api), ("interior.jsonl", interior),
                                            ("console.jsonl", tunnel)) if leidas is None]
    api, interior, tunnel = api or [], interior or [], tunnel or []
    rotas = (rotas_api or 0) + (rotas_interior or 0) + (rotas_tunnel or 0)

    lab = (api[0][1].get("lab") if api else "") or os.path.basename(carpeta)
    verbos = [str(d.get("verb") or "") for _, d in api]
    pasada = verbo or (verbos[-1] if verbos else "")
    mapa = _mapa_de_guests(api, tunnel, lab)

    de_la_pasada = [(n, d) for n, d in api if str(d.get("verb") or "") == pasada]
    interior_pasada = [d for _, d in interior if str(d.get("verb") or "") == pasada]
    tunnel_pasada = [d for _, d in tunnel if str(d.get("verb") or "") == pasada]
    horas = [str(d.get("ts") or "")[11:19] for _, d in de_la_pasada if d.get("ts")]

    # --- Cabecera ----------------------------------------------------------------------
    ambos(f"# Resumen del lab `{lab}`")
    ambos()
    if not pasada:
        ambos("**No hay ninguna pasada en el diario.** Si esto no cuadra, mira si el verbo")
        ambos("llegó a arrancar: una ejecución que no deja diario no ocurrió (regla 5).")
        if faltan:
            ambos()
            ambos("No hay diario de: " + ", ".join(f"`{n}`" for n in faltan) + ".")
        ambos()
        return "\n".join(salida), "\n".join(escribir)
    ambos(f"**Pasada: {VERBOS_LEGIBLES.get(pasada, pasada)}**"
          + (f" — de {horas[0]} a {horas[-1]}" if horas else "")
          + f", {len(de_la_pasada)} llamada(s) por las vías de acceso.")
    ambos()
    ambos("> Cuenta todas las pasadas de ese verbo que hay en el diario, no sólo la última: el")
    ambos("> diario no marca dónde empieza cada ejecución (es lo que arregla el ADR 0014 §2).")
    ambos("> Por eso lo que se repite se cuenta (`×N`) en vez de repetirse.")
    ambos()

    # --- De un vistazo ----------------------------------------------------------------
    ambos("## De un vistazo")
    ambos()
    filas = []
    por_acceso = {}
    for _, d in de_la_pasada:
        por_acceso.setdefault(str(d.get("api") or "proxmox"), []).append(d)
    for gateway in sorted(por_acceso, key=lambda p: (p not in ("proxmox", "routeros"), p)):
        llamadas = por_acceso[gateway]
        lecturas = [c for c in llamadas if str(c.get("method") or "").upper() == "GET"]
        malas = [c for c in llamadas if str(c.get("status") or "") not in BIEN]
        filas.append([ACCESOS.get(gateway, gateway), len(llamadas), len(lecturas),
                      len(llamadas) - len(lecturas), len(malas)])
    if interior_pasada:
        malas = [d for d in interior_pasada
                 if str(d.get("resultado") or d.get("rc") or "ok") not in ("ok", "0")]
        filas.append(["el interior (SSH / REST del router)", len(interior_pasada), "—", "—", len(malas)])
    if tunnel_pasada:
        filas.append(["la consola de la API", len(tunnel_pasada), "—", "—", "—"])
    tabla(["gateway", "llamadas", "lecturas", "escrituras", "no 2xx"], filas)
    ambos()
    if faltan:
        ambos("No hay diario de: " + ", ".join(f"`{n}`" for n in faltan) + ".")
        ambos()
    if rotas:
        ambos(f"({rotas} línea(s) ilegible(s) en los diarios: están tocados.)")
        ambos()

    # --- A quién se le tocó, y qué -----------------------------------------------------
    escrituras = [(n, d) for n, d in de_la_pasada if str(d.get("method") or "").upper() != "GET"]
    por_guest = {}
    for _, d in escrituras:
        rol = _guest_de(d, mapa)
        if rol:
            por_guest.setdefault(rol, []).append(d)
    areas_interior = {}
    for d in interior_pasada:
        areas_interior.setdefault(str(d.get("guest") or "?"), set()).add(str(d.get("area") or "?"))

    ambos("## A qué equipos se les tocó algo")
    ambos()
    filas = []
    for rol in sorted(set(por_guest) | set(areas_interior)):
        vmids = sorted(v for v, (r, _t) in mapa.items() if r == rol)
        tipos = sorted({t for _v, (r, t) in mapa.items() if r == rol and t})
        filas.append([rol, ", ".join(vmids) or "—", ", ".join(tipos) or "—",
                      len(por_guest.get(rol, [])),
                      ", ".join(sorted(areas_interior.get(rol, set()))) or "—"])
    if filas:
        tabla(["guest", "vmid", "tipo", "escrituras", "áreas por dentro"], filas)
    else:
        ambos("Ninguno: esta pasada no escribió nada en ningún equipo.")
    ambos()
    ambos("Un invitado con 0 escrituras no es un olvido: si su dirección la da el DHCP (o el")
    ambos("lab la pone en su interfaz), al equipo no hay que entrarle. Lo que se configura por la")
    ambos("red no se configura por dentro.")
    ambos()

    # --- Los pasos del despliegue, en su orden -----------------------------------------
    pasos, areas, otros, torcidas = [], [], [], []
    for _n, d in de_la_pasada:
        if str(d.get("method") or "").upper() == "GET":
            continue
        etiqueta = str(d.get("etiqueta") or "").strip()
        rol = _guest_de(d, mapa)
        llamada = f"{d.get('method')} {d.get('path')}"
        estado = str(d.get("status") or "")
        con_paso = re.match(r"^paso\s+(\d+):\s*(\w+)\s*(?:--\s*(.*))?$", etiqueta, re.DOTALL)
        con_area = re.match(r"^escribir\s+(\w+):\s*(.*)$", etiqueta, re.DOTALL)
        if con_paso:
            pasos.append([int(con_paso.group(1)), con_paso.group(2), rol or "—",
                          con_paso.group(3) or etiqueta, llamada, estado])
        elif con_area:
            areas.append([rol or "—", con_area.group(1), con_area.group(2), llamada, estado])
        else:
            otros.append([rol or "—", etiqueta or "(sin explicación en el diario)", llamada, estado])
        if estado not in BIEN:
            torcidas.append([estado, rol or "—", llamada, etiqueta or "(sin explicación)"])

    def _sin_repetir(filas):
        """La misma escritura, en varias pasadas, es UNA: se cuenta, no se repite."""
        cuenta = {}
        for fila in filas:
            cuenta[tuple(fila)] = cuenta.get(tuple(fila), 0) + 1
        return [list(fila) + ([f"×{n}"] if n > 1 else [""]) for fila, n in cuenta.items()]

    unos = _sin_repetir(pasos)
    ambos(f"## Los pasos del despliegue ({len(unos)} paso(s), en el orden del plan)")
    ambos()
    if unos:
        tabla(["paso", "guest", "qué hace", "y por qué", "orden lanzada", "respuesta", "veces"],
              [[p[0], p[2], p[1], p[3], p[4], p[5], p[6]] for p in sorted(unos, key=lambda p: p[0])])
    else:
        ambos("Ninguno: esta pasada no creó ni arrancó nada.")
    ambos()

    escritas = _sin_repetir(areas)
    ambos(f"## Dentro de los equipos ({len(escritas)} cosa(s) escrita(s))")
    ambos()
    if escritas:
        tabla(["guest", "área", "qué se escribió", "orden lanzada", "respuesta", "veces"], escritas)
    else:
        ambos("Nada: esta pasada no entró a configurar ningún equipo.")
    ambos()

    if otros:
        ambos("## Otros cambios")
        ambos()
        tabla(["guest", "qué se hizo", "orden lanzada", "respuesta", "veces"], _sin_repetir(otros))
        ambos()

    # --- Lo que no salió bien, aparte y sin adornos ------------------------------------
    if torcidas:
        ambos(f"## Lo que no respondió 2xx ({len(_sin_repetir(torcidas))})")
        ambos()
        tabla(["respuesta", "guest", "orden lanzada", "qué se quería", "veces"],
              _sin_repetir(torcidas))
        ambos()

    # --- El interior, uno por uno ------------------------------------------------------
    if areas_interior:
        ambos("## El interior, invitado por invitado")
        ambos()
        filas = []
        for guest in sorted(areas_interior):
            pasos_inv = [d for d in interior_pasada if str(d.get("guest") or "?") == guest]
            malos = [d for d in pasos_inv
                     if str(d.get("resultado") or d.get("rc") or "ok") not in ("ok", "0")]
            filas.append([guest, ", ".join(sorted(areas_interior[guest])),
                          len(pasos_inv), len(malos)])
        tabla(["guest", "áreas por las que se entró", "pasos", "fallos"], filas)
        ambos()

    # --- El veredicto, si lo hay -------------------------------------------------------
    veredicto_txt = os.path.join(carpeta, "ultimo-verify.txt")
    if os.path.exists(veredicto_txt):
        with open(veredicto_txt, encoding="utf-8", errors="replace") as fichero:
            suyas = [l.rstrip() for l in fichero if l.strip()]
        if suyas:
            ambos("## El veredicto de la última comprobación")
            ambos()
            ambos("```")
            for linea in suyas[:12]:
                ambos(linea)
            if len(suyas) > 12:
                ambos(f"... ({len(suyas) - 12} línea(s) más en `logs/ultimo-verify.txt`)")
            ambos("```")
            ambos()

    return "\n".join(salida), "\n".join(escribir)


def main():
    if len(sys.argv) < 2:
        print("uso: resumen.py <carpeta-del-lab> [apply|verify|plan|destroy]")
        print("     (imprime el informe y lo deja en logs/resumen.md)")
        return 2
    carpeta = sys.argv[1]
    verbo = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.isdir(os.path.join(carpeta, "logs")) and os.path.basename(carpeta) != "logs":
        print(f"no encuentro los diarios de '{carpeta}': ¿es una carpeta de lab?")
        return 2
    logs = os.path.join(carpeta, "logs") if os.path.basename(carpeta) != "logs" else carpeta
    texto, _ = resumen_de_lab(logs, verbo)
    print(texto)
    destino = os.path.join(logs, "resumen.md")
    with open(destino, "w", encoding="utf-8") as fichero:
        fichero.write(texto + "\n")
    print(f"\n(guardado en {os.path.relpath(destino, RAIZ)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
