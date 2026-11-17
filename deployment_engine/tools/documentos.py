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
import re
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
ETIQUETA_PLATAFORMA = {"qemu": "VM (qemu)", "lxc": "LXC"}

# El TIPO DE EQUIPO (`rt`, `fw`, `sw`, `srv`, `ws`, `ctl`) y la PLATAFORMA (`qemu`/`lxc`) son
# dos cosas distintas y la tabla las enseña por separado: el tipo dice QUÉ es el invitado en la
# red (ADR 0026), la plataforma dice CÓMO se virtualiza. Confundirlas hacía que la columna
# `tipo` dijera «VM (qemu)» -- la virtualización -- donde el repo entiende `rt`, `fw`, `srv`...
#
# Se repite el vocabulario a propósito, como el normalizador de invitados: `documentos.py` es
# una herramienta y no carga el filtro de Ansible para leer un YAML.
ETIQUETA_EQUIPO = {
    "rt": "rt (enruta y sale)",
    "fw": "fw (filtra)",
    "sw": "sw (conmuta)",
    "srv": "srv (servidor)",
    "ws": "ws (puesto de trabajo)",
    "ctl": "ctl (control del lab)",
}

# La FORMA de cada nodo en el diagrama, por tipo de equipo: un router no se dibuja como un
# servidor ni un cortafuegos como un puesto. Con la forma y el color, el diagrama de red se
# lee sin tener la tabla al lado.
FORMA_EQUIPO = {
    "rt": ("([\"", "\"])"),    # estadio: el borde, por donde se entra y se sale
    "fw": ("{{\"", "\"}}"),    # hexágono: el escudo
    "sw": ("[/\"", "\"/]"),    # paralelogramo: el que reparte
    "srv": ("[(\"", "\")]"),   # cilindro: el que guarda
    "ws": ("[\"", "\"]"),      # rectángulo: el que usa una persona
    "ctl": ("[[\"", "\"]]"),   # subrutina: el que manda
}

# El color, por el mismo tipo: la forma dice qué es y el color lo agrupa de un vistazo.
COLOR_EQUIPO = {
    "rt": "fill:#7c2d12,stroke:#fb923c,color:#ffedd5",
    "fw": "fill:#701a1a,stroke:#f87171,color:#fee2e2",
    "sw": "fill:#134e4a,stroke:#2dd4bf,color:#ccfbf1",
    "srv": "fill:#1e3a8a,stroke:#60a5fa,color:#dbeafe",
    "ws": "fill:#14532d,stroke:#4ade80,color:#dcfce7",
    "ctl": "fill:#4c1d95,stroke:#a78bfa,color:#ede9fe",
}


def _patas_de(invitado):
    """Los bridges por los que el invitado tiene interfaz, en el orden declarado.

    Un invitado puede declararlo como lista (`bridges`) o como uno solo (`bridge`); el motor
    admite las dos formas y aquí se leen las dos.
    """
    return invitado.get("bridges") or ([invitado["bridge"]] if invitado.get("bridge") else [])


def _declara_salida(invitado):
    """¿Este invitado declara por dónde se sale a la red de fuera? (`uplink`, ADR 0012.)

    `uplink` es una MARCA, y por eso en el YAML es un diccionario vacío: no vale preguntar si
    es verdadera -- siempre sería falsa --, se pregunta si ESTÁ. Y se mira en cualquier
    interior declarado (`routeros`, `linux`...), no en uno concreto: la marca es del motor.
    """
    for interior in (invitado.get("config") or {}).values():
        if isinstance(interior, dict) and "uplink" in interior:
            return True
    return False


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


def _guests_normalizados(declaracion, motor):
    """Misma normalización que el motor, sin depender de él.

    Se repite a propósito: `documentos.py` es una herramienta y no debe cargar el
    filtro de Ansible para leer un YAML. La duplicación es de 6 líneas y está aquí
    a la vista; la alternativa (importar el filtro) ataría la documentación a
    Ansible, que es justo lo que se quiere evitar.

    Dos campos NO se dejan como vengan:

    - `tipo` es el del EQUIPO (`rt`, `fw`, `srv`...) y se respeta tal cual: es lo que dice qué
      es el invitado en la red (ADR 0026). La VIRTUALIZACIÓN (`qemu`/`lxc`) va aparte, en
      `plataforma`. Antes se pisaba `tipo` con la plataforma y las tablas acababan diciendo
      «VM (qemu)» en la columna del tipo de equipo -- que no es lo que el repo llama tipo.
    - `canonico` es el nombre con el que el invitado existe en el clúster, y se deriva con la
      MISMA plantilla del motor (`{equipo}-{alias}`), no con una copia: si la plantilla cambia,
      el documento cambia con ella.
    """
    guests = []
    for seccion, plataforma in (("vms", "qemu"), ("containers", "lxc")):
        for guest in declaracion.get(seccion) or []:
            # El alias es el `nombre:` corto si lo hay, y si no el rol (como hace el motor).
            alias = guest["rol"] if guest.get("nombre") is None else str(guest["nombre"])
            guests.append({**guest, "plataforma": plataforma, "alias": alias})
    for guest in guests:
        guest["canonico"] = (
            motor["engine_plantilla_nombre"]
            .replace("{equipo}", str(guest.get("tipo") or "?"))
            .replace("{alias}", guest["alias"])
        )
    guests.sort(key=lambda i: (i["stage"], i["rol"]))
    return guests


def _id_mermaid(texto, clase):
    """Un identificador de nodo Mermaid a partir de un nombre del lab.

    Mermaid no admite guiones, puntos ni acentos en un identificador, así que todo lo que
    no sea alfanumérico o `_` pasa a `_`, y se antepone la CLASE para que no empiece por
    dígito. Dos nombres distintos pueden colisionar (`puente-a` y `puente_a`): en un
    identificador eso da un nodo compartido, y por eso el nombre de verdad viaja SIEMPRE
    en la etiqueta, que es la que se lee.

    La clase (`b` para un bridge, `i` para un invitado) no es decorativa: el espacio de
    nombres de un lab es uno solo, así que un bridge llamado igual que un rol --`control`
    es las dos cosas-- compartiría nodo y el diagrama dibujaría un bucle sobre sí mismo
    en vez de una pata. Son DOS clases de cosa y se ven como dos.
    """
    limpio = "".join(c if c.isalnum() or c == "_" else "_" for c in texto)
    return clase + "_" + limpio


def _diagrama_mermaid(guests, bridges):
    """La topología como DIAGRAMA DE RED, derivada de la declaración.

    Se dibuja lo que SE CONECTA, no lo que se lista: un nodo por SEGMENTO (cada bridge, con su
    subred), un nodo por EQUIPO -- con su nombre canónico y su dirección -- unido al segmento
    por el que tiene pata, y la SALIDA del lab para quien la declara (`uplink`, ADR 0012). La
    salida es la pregunta que un diagrama de red tiene que contestar de un vistazo: por dónde
    se sale.

    La FORMA y el COLOR dicen qué es cada equipo (router, cortafuegos, servidor, puesto...):
    así el diagrama se lee sin tener la tabla al lado.

    Determinista: los equipos salen en el orden de la declaración (etapa, rol) y los segmentos
    en el suyo. Reordenar un diccionario no puede cambiar el documento.
    """
    lineas = ["```mermaid", "graph LR"]
    lineas.append("    classDef segmento fill:#0b1220,stroke:#38bdf8,color:#dbeafe;")
    lineas.append(
        "    classDef salida fill:#111827,stroke:#9ca3af,color:#e5e7eb,stroke-dasharray:4 3;"
    )
    for tipo, color in COLOR_EQUIPO.items():
        lineas.append(f"    classDef {tipo} {color};")

    # Los segmentos primero: son el suelo del lab, y verlos arriba ordena la lectura.
    for puente in bridges:
        etiqueta = puente["nombre"]
        if puente.get("address"):
            etiqueta += "<br/>" + str(puente["address"])
        lineas.append(
            "    " + _id_mermaid(puente["nombre"], "b") + '(["' + etiqueta + '"]):::segmento'
        )

    # Sólo hay nodo de salida si algún equipo la declara.
    if any(_declara_salida(invitado) for invitado in guests):
        lineas.append('    salida["salida · la red del nodo"]:::salida')

    varias_etapas = len({invitado["stage"] for invitado in guests}) > 1
    for invitado in guests:
        identificador = _id_mermaid(invitado["rol"], "i")
        partes = [invitado["canonico"]]
        if invitado.get("address"):
            partes.append(str(invitado["address"]))
        # La etapa sólo se escribe cuando hay más de una: en un lab de una sola etapa sería
        # ruido en cada nodo; en uno por etapas dice el ORDEN, que es la mitad del diseño.
        if varias_etapas:
            partes.append(f"etapa {invitado['stage']}")
        abre, cierra = FORMA_EQUIPO.get(invitado["tipo"], ('["', '"]'))
        lineas.append(
            "    " + identificador + abre + "<br/>".join(partes) + cierra
            + f":::{invitado['tipo']}"
        )
        for nombre_puente in _patas_de(invitado):
            lineas.append(
                "    " + identificador + " --- " + _id_mermaid(nombre_puente, "b")
            )
        # La salida se dibuja DISCONTINUA: no es un cable del lab, es lo que hay al otro lado.
        if _declara_salida(invitado):
            lineas.append("    " + identificador + " -.->|uplink| salida")
    lineas.append("```")
    return "\n".join(lineas)


def _leyenda_del_diagrama(guests):
    """La leyenda del diagrama: qué tipo de equipo hay y qué significa su forma.

    Sólo los tipos que el lab USA, en el orden del vocabulario: una leyenda que enumera seis
    formas cuando el lab tiene dos es ruido. Se deriva, como el resto: no se escribe a mano en
    la prosa del lab (la prosa no repite lo que la región generada ya dice).
    """
    presentes = [tipo for tipo in ETIQUETA_EQUIPO if any(i["tipo"] == tipo for i in guests)]
    return "\n".join(f"- `{tipo}` — {ETIQUETA_EQUIPO[tipo]}" for tipo in presentes) or "—"


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

    guests = _guests_normalizados(declaracion, motor)
    bridges = declaracion["lab"]["bridges"]
    stages = sorted(set(declaracion["lab"]["stages"]))

    tabla_guests = _filas(
        [
            [
                i["rol"],
                ETIQUETA_EQUIPO.get(i["tipo"], str(i["tipo"] or "—")),
                ETIQUETA_PLATAFORMA[i["plataforma"]],
                i["stage"],
                i["cores"],
                i["memory"],
                i["disk"],
                # Las interfaces del invitado, en orden. Un invitado de varias (`bridges`) las
                # enseña todas: la tabla es la lectura rápida de la topología.
                " + ".join(i.get("bridges") or [i.get("bridge") or ""]),
                i["address"],
            ]
            for i in guests
        ],
        9,
    )

    tabla_bridges = _filas(
        [[b["nombre"], b.get("address") or "—"] for b in bridges],
        2,
    )

    # El orden de arranque, derivado: qué roles caen en cada etapa.
    tabla_stages = _filas(
        [
            [
                stage,
                ", ".join(i["rol"] for i in guests if i["stage"] == stage) or "—",
            ]
            for stage in stages
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
                ETIQUETA_EQUIPO.get(i["tipo"], str(i["tipo"] or "—")),
                i["canonico"],
                "—",
                "—",
            ]
            for i in guests
        ],
        5,
    )

    # Acceso: cómo se ENTRA a cada equipo. El usuario y la FORMA de acceso se derivan
    # de la declaración y del motor; la CREDENCIAL se cita por su ORIGEN, nunca por su
    # valor; y el puerto sale del vmid, que no se conoce hasta `apply`, así que se enseña
    # la FÓRMULA. Un invitado sin `config:` no se toca, y su fila lo dice en vez de fingir
    # un acceso que no existe.
    #
    # El valor NO se imprime aunque `secrets.yml` esté a mano: si dependiera de él, la
    # región generada NO sería función de la declaración -- en un clon sin credenciales
    # (el CI) rendiría otra cosa, `./lab check docs` no podría pasar nunca y el `.md`
    # publicado llevaría la contraseña dentro. Lo destapó el CI del §6.5.
    #
    # `routeros` / `linux` son el VOCABULARIO del interior, no un valor de ningún lab:
    # la declaración cuelga las áreas de `config.<interior>` (ver `interior.py`).
    hay_bastion = any(
        "tunnel" in (((i.get("config") or {}).get("linux")) or {}) for i in guests
    )

    def _fila_de_acceso(i):
        config = i.get("config") or {}
        if not config:
            return [i["rol"], ETIQUETA_EQUIPO.get(i["tipo"], str(i["tipo"] or "—")), "—", "—",
                    "no se entra: no declara `config:`"]
        if "routeros" in config:
            usuario = motor["engine_routeros_usuario"]
            return [
                i["rol"], ETIQUETA_EQUIPO.get(i["tipo"], str(i["tipo"] or "—")),
                usuario,
                f"`{usuario}` / la de `secrets.yml` → `routeros_clave` (HTTP Basic)",
                f"REST por el túnel del bastión "
                f"(`{motor['engine_tunnel_rest_puerto_base']}`+vmid); su consola, por la "
                f"serial del nodo",
            ]
        es_bastion = "tunnel" in ((config.get("linux")) or {})
        if es_bastion:
            acceso = (f"SSH a `127.0.0.1`:(`{motor['engine_tunnel_puerto_base']}`+vmid): "
                      f"él ES el bastión, se entra directo por su túnel")
        elif hay_bastion:
            acceso = "SSH por el bastión (salta por su túnel), a su dirección en el lab"
        else:
            acceso = "SSH: este lab no declara bastión, y sin él no se entra al interior"
        return [
            i["rol"], ETIQUETA_EQUIPO.get(i["tipo"], str(i["tipo"] or "—")),
            motor["engine_usuario_guest"],
            f"clave del lab (`{motor['engine_tunnel_clave_base']}_"
            f"{declaracion['lab']['nombre']}_ed25519`), sin contraseña",
            acceso,
        ]

    tabla_acceso = _filas([_fila_de_acceso(i) for i in guests], 5)

    with open(PLANTILLA, encoding="utf-8") as fichero:
        plantilla = fichero.read()

    # Sustitución simple y explícita: un marcador despistado se ve en el render.
    sustituciones = {
        "archivo_declaracion": archivo_declaracion,
        "prefijo_mac": motor["engine_prefijo_mac"],
        "diagrama_mermaid": _diagrama_mermaid(guests, bridges),
        "leyenda_diagrama": _leyenda_del_diagrama(guests),
        "tabla_guests": tabla_guests,
        "tabla_bridges": tabla_bridges,
        "tabla_stages": tabla_stages,
        "tabla_identidad": tabla_identidad,
        "tabla_acceso": tabla_acceso,
    }
    resultado = plantilla
    # El comentario de cabecera de la plantilla no es parte de la región: se quita
    # ANTES de buscar marcadores sin sustituir, porque en él aparece `{{ clave }}`
    # como ejemplo y no es un marcador de verdad.
    if resultado.lstrip().startswith("<!-- PROPÓSITO"):
        resultado = resultado[resultado.index(MARCA_INICIO):]
    for clave, valor in sustituciones.items():
        resultado = resultado.replace("{{ " + clave + " }}", str(valor))

    # Un marcador que se quedó sin sustituir tiene SIEMPRE la forma `{{ clave }}`. No vale
    # buscar un `{{` a secas: el diagrama de red usa formas de Mermaid que llevan llaves
    # (`{{"..."}}`, el hexágono del cortafuegos) y eso no es un marcador.
    sobrantes = [
        linea
        for linea in resultado.splitlines()
        if re.search(r"\{\{\s*[a-z_]+\s*\}\}", linea)
    ]
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
