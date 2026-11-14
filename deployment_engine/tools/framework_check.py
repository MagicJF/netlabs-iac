#!/usr/bin/env python3
# PROPÓSITO:   los checks del motor. Son herramientas de DESARROLLO: miran el
#              repositorio (y por eso sí pueden leer `labs/`, cosa que el motor no
#              hace) y no necesitan credenciales ni Proxmox.
# INVARIANTES: cada check tiene que poder FALLAR de verdad por lo que vigila, y
#              decirlo con el fichero y el comando que lo arregla. Un check que no
#              puede fallar no es un check, es una promesa.
#              El código de salida es != 0 si algún check ha fallado. La caducidad
#              de los documentos AVISA (exige criterio); un hecho mecánico BLOQUEA.
# LÍMITES:     no prueba nada del mundo real: no hay API, no hay invitados, no hay
#              red. Y no opina sobre la prosa de los documentos.
# VER:         README.md §Checks; AGENTS.md §Qué correr y cuándo
#
# Uso (lo normal es a través de `./lab check [nombre]`):
#     python3 deployment_engine/tools/framework_check.py all
#     python3 deployment_engine/tools/framework_check.py links|docs|refs|puerta|...
#     python3 deployment_engine/tools/framework_check.py refs <ruta-del-repo>
#     python3 deployment_engine/tools/framework_check.py docs --actualizar
#     python3 deployment_engine/tools/framework_check.py docs --sellar <doc.md>

import hashlib
import json
import os
import re
import subprocess
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILTROS = os.path.join(RAIZ, "deployment_engine", "filter_plugins")
HERRAMIENTAS = os.path.join(RAIZ, "deployment_engine", "tools")
sys.path.insert(0, FILTROS)
sys.path.insert(0, HERRAMIENTAS)

import declaracion as modulo_declaracion  # noqa: E402  (la ruta se ajusta arriba)
import documentos as modulo_documentos  # noqa: E402

DIRECTORIO_LABS = os.path.join(RAIZ, "labs")
SELLO = os.path.join(RAIZ, "docs", "revisiones.json")
# Cache de la lista de ficheros versionados: `git ls-files` es barato, pero se llama
# desde el bucle de sellado y no hace falta repetirlo. None = "todavía no se sabe".
_CACHE_VERSIONADOS = None
DOCUMENTOS_DEL_MOTOR = (
    "README.md",
    "AGENTS.md",
)
# Los únicos sitios donde puede aparecer la ruta base de la API de Proxmox: la
# puerta (que la usa) y los documentos (que hablan de ella).
UNICA_PUERTA = "deployment_engine/tasks/pve_api.yml"
# La ruta base, partida en dos trozos A PROPÓSITO: así este fichero no contiene el
# literal que él mismo persigue, y el check puede seguir siendo estricto (sin
# excluirse a sí mismo de la comprobación).
RUTA_BASE_API = "/api2" + "/json"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _ficheros_con_extension(extension, subarbol=RAIZ):
    """Todos los ficheros de una extensión, saltando .git, __pycache__ y los logs de
    los labs (que son artefactos de ejecución, no fuente)."""
    for directorio, subdirectorios, ficheros in os.walk(subarbol):
        subdirectorios[:] = [
            d for d in subdirectorios if d not in (".git", "__pycache__", "logs")
        ]
        for fichero in ficheros:
            if fichero.endswith(extension):
                yield os.path.join(directorio, fichero)


def _relativo(ruta):
    return os.path.relpath(ruta, RAIZ)


def _leer(ruta):
    with open(ruta, encoding="utf-8") as fichero:
        return fichero.read()


def _sha256(ruta):
    with open(ruta, "rb") as fichero:
        return hashlib.sha256(fichero.read()).hexdigest()


def directorios_de_labs():
    """Los labs declarados: una carpeta con `<carpeta>.yml` dentro. Los nombres que
    empiezan por punto (`.plantilla`) no son labs."""
    if not os.path.isdir(DIRECTORIO_LABS):
        return []
    labs = []
    for nombre in sorted(os.listdir(DIRECTORIO_LABS)):
        ruta = os.path.join(DIRECTORIO_LABS, nombre)
        if nombre.startswith(".") or not os.path.isdir(ruta):
            continue
        if os.path.exists(os.path.join(ruta, f"{nombre}.yml")):
            labs.append(nombre)
    return labs


def declaracion_de(lab):
    return yaml.safe_load(_leer(os.path.join(DIRECTORIO_LABS, lab, f"{lab}.yml")))


def _fuera_de_bloques_de_codigo(texto):
    """Devuelve el texto sin los bloques ```...```.

    Un enlace dentro de un bloque de código es un ejemplo, no un puntero: si no se
    salta, `check links` daría falsos positivos y acabaría desactivándose.
    """
    lineas = []
    dentro = False
    for linea in texto.splitlines():
        if linea.lstrip().startswith("```"):
            dentro = not dentro
            continue
        if not dentro:
            lineas.append(linea)
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# check links — punteros vivos (del documento al código)
# ---------------------------------------------------------------------------

EXPRESION_ENLACE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def check_links():
    fallos = []
    for ruta in _ficheros_con_extension(".md"):
        texto = _fuera_de_bloques_de_codigo(_leer(ruta))
        for destino in EXPRESION_ENLACE.findall(texto):
            if destino.startswith(("http://", "https://", "mailto:", "#")):
                continue
            ruta_destino = destino.split("#", 1)[0]
            if not ruta_destino:
                continue
            absoluta = os.path.normpath(os.path.join(os.path.dirname(ruta), ruta_destino))
            if not os.path.exists(absoluta):
                fallos.append(f"{_relativo(ruta)}: el enlace `{destino}` no resuelve a ninguna ruta")
    if fallos:
        print("FALLA links: hay punteros a rutas que ya no existen:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("OK    links: todos los enlaces de los documentos resuelven a rutas existentes")
    return 0


# ---------------------------------------------------------------------------
# check docs — el render manda sobre el disco
# ---------------------------------------------------------------------------

def check_docs(actualizar=False):
    if actualizar:
        for lab in directorios_de_labs():
            modulo_documentos.actualizar(os.path.join(DIRECTORIO_LABS, lab))
        print("OK    docs: regiones generadas reescritas desde la declaración")
        return 0
    fallos = 0
    for lab in directorios_de_labs():
        fallos += modulo_documentos.comprobar(os.path.join(DIRECTORIO_LABS, lab))
    if fallos:
        return 1
    print(f"OK    docs: la región generada de {len(directorios_de_labs())} lab(s) coincide con su render")
    return 0


# ---------------------------------------------------------------------------
# check refs — índice inverso y caducidad por sellado (del código al documento)
# ---------------------------------------------------------------------------

EXPRESION_RUTA_DE_MOTOR = re.compile(r"deployment_engine/[A-Za-z0-9_./-]+")


def _rutas_versionadas_bajo(prefijo):
    """Los ficheros que git versiona (o versionaría) bajo un prefijo del repo.

    Se usa `--cached --others --exclude-standard`: lo ya añadido MÁS lo que no está
    ignorado. Así el check funciona igual antes del primer commit, y se cae
    `secrets.yml` (gitignored) sin tener que nombrarlo.
    """
    salida = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", prefijo],
        cwd=RAIZ, capture_output=True, text=True, check=False,
    ).stdout
    return {linea.strip() for linea in salida.splitlines() if linea.strip()}


def _ficheros_versionados():
    """Todos los ficheros versionados del repo (una sola vez por ejecución)."""
    global _CACHE_VERSIONADOS
    if _CACHE_VERSIONADOS is None:
        _CACHE_VERSIONADOS = _rutas_versionadas_bajo(".")
    return _CACHE_VERSIONADOS


def _citados_de_un_documento(ruta_documento):
    """{ruta-citada: hash} de los ficheros DEL MOTOR que cita un documento.

    Sólo cuenta lo que existe, es un fichero Y ESTÁ VERSIONADO por git. Un documento
    puede mencionar `deployment_engine/secrets.yml` (que está gitignored: existe en
    esta máquina pero no en ningún clon) o una carpeta; eso es una mención, no un
    puntero. Lo que sí se sella es lo que se puede romper: los ficheros versionados.
    """
    texto = _leer(ruta_documento)
    versionados = _ficheros_versionados()
    citados = {}
    for citado in sorted(set(EXPRESION_RUTA_DE_MOTOR.findall(texto))):
        ruta_citada = os.path.join(RAIZ, citado)
        if citado in versionados and os.path.isfile(ruta_citada):
            citados[citado] = _sha256(ruta_citada)
    return citados


def _documentos_que_citan(ruta_buscada):
    """Qué documentos citan una ruta del motor. El cambio va al revés del puntero:
    quien cambia el código necesita saber qué prosa lo explica."""
    citantes = []
    for ruta in _ficheros_con_extension(".md"):
        if ruta_buscada in _leer(ruta):
            citantes.append(ruta)
    return citantes


def _sellos():
    if not os.path.exists(SELLO):
        return {}
    return json.loads(_leer(SELLO)) or {}


def _escribir_sellos(sellos):
    with open(SELLO, "w", encoding="utf-8") as fichero:
        json.dump({clave: sellos[clave] for clave in sorted(sellos)}, fichero, indent=2, ensure_ascii=False)
        fichero.write("\n")


def sellar(ruta_documento):
    """Sella un documento: guarda el hash ACTUAL de cada fichero del motor que cita.

    Se re-sella cuando alguien confirma que la prosa sigue siendo cierta. No es
    automático a propósito: sellar sin leer es exactamente la mentira que la guarda
    quiere evitar.
    """
    relativo = _relativo(ruta_documento)
    if not os.path.exists(ruta_documento):
        print(f"FALLA refs: no existe el documento {relativo}")
        return 1
    citados = _citados_de_un_documento(ruta_documento)
    if not citados:
        print(f"OK    refs: {relativo} no cita ningún fichero del motor; no hay nada que sellar")
        return 0
    sellos = _sellos()
    sellos[relativo] = {"citados": citados}
    _escribir_sellos(sellos)
    print(f"OK    refs: sellado {relativo} contra {len(citados)} fichero(s) del motor")
    return 0


def check_refs(ruta=None):
    """Sin ruta: vigila el sellado (falla si un doc cita el motor y no está sellado,
    o si un fichero sellado desaparece; AVISA si ha caducado). Con ruta: dice qué
    documentos citan ese fichero."""
    if ruta:
        relativo = _relativo(os.path.abspath(ruta))
        citantes = _documentos_que_citan(relativo)
        if not citantes:
            print(f"OK    refs: ningún documento cita `{relativo}` (revisa si debería)")
            return 0
        print(f"refs: `{relativo}` lo citan {len(citantes)} documento(s):")
        for citante in citantes:
            print(f"  - {_relativo(citante)}")
        print("      Si cambiaste ese fichero, revisa esas prosas y re-sella con "
              "`./lab check docs --sellar <doc>`")
        return 0

    sellos = _sellos()
    fallos = []
    caducados = []
    for ruta_md in _documentos_con_citas_al_motor():
        relativo = _relativo(ruta_md)
        citados_ahora = _citados_de_un_documento(ruta_md)
        if relativo not in sellos:
            fallos.append(
                f"{relativo}: cita ficheros del motor y no está sellado "
                f"(se sella con `./lab check docs --sellar {relativo}`)"
            )
            continue
        sellados = sellos[relativo].get("citados") or {}
        for citado, sello in sellados.items():
            ruta_citada = os.path.join(RAIZ, citado)
            if not os.path.isfile(ruta_citada):
                fallos.append(f"{relativo}: cita `{citado}`, que ya no existe")
            elif _sha256(ruta_citada) != sello:
                caducados.append(f"{relativo} cita `{citado}`, que ha cambiado desde que se revisó")
        nuevos = sorted(set(citados_ahora) - set(sellados))
        if nuevos:
            caducados.append(
                f"{relativo} cita ficheros del motor que no estaban cuando se selló "
                f"({', '.join(nuevos)}): vuélvelo a sellar si la prosa sigue siendo cierta"
            )

    if fallos:
        print("FALLA refs: documentos que citan el motor sin sellar, o sellos rotos:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    for caducado in caducados:
        print(f"AVISO refs: {caducado}")
    print(f"OK    refs: {len(sellos)} documento(s) sellado(s), {len(caducados)} aviso(s) de caducidad")
    return 0


def _documentos_con_citas_al_motor():
    for ruta in _ficheros_con_extension(".md"):
        if _citados_de_un_documento(ruta):
            yield ruta


# ---------------------------------------------------------------------------
# check puerta — nadie llama a la API fuera de la puerta común
# ---------------------------------------------------------------------------

def check_puerta():
    """Nadie llama a la API fuera de la puerta común.

    Se revisa el CÓDIGO (los .yml y .py del motor, y el wrapper): los documentos
    pueden hablar de la ruta de la API todo lo que quieran -- de hecho es su trabajo.
    """
    fallos = []
    rutas = list(_ficheros_con_extension(".yml", os.path.join(RAIZ, "deployment_engine")))
    rutas += list(_ficheros_con_extension(".py", os.path.join(RAIZ, "deployment_engine")))
    rutas += [os.path.join(RAIZ, "lab"), os.path.join(RAIZ, ".githooks", "pre-commit")]
    for ruta in rutas:
        if not os.path.exists(ruta):
            continue
        if RUTA_BASE_API in _leer(ruta) and _relativo(ruta) != UNICA_PUERTA:
            fallos.append(_relativo(ruta))
    if fallos:
        print("FALLA puerta: alguien llama a la API fuera de " + UNICA_PUERTA + ":")
        for fallo in sorted(set(fallos)):
            print(f"  - {fallo}")
        return 1
    print(f"OK    puerta: la única llamada a la API está en {UNICA_PUERTA}")
    return 0


# ---------------------------------------------------------------------------
# check privilegios — el motor no concede privilegios, y sus invitados no nacen
#                     privilegiados
# ---------------------------------------------------------------------------

# El ÚNICO fichero del motor autorizado a hablar con /access/...: la guarda de
# preflight, que sólo LEE y hace una operación NULA. Si aparece en otro sitio, el
# motor está administrando permisos, y eso no es su trabajo (regla 16).
#
# Los literales que este check persigue se construyen por PIEZAS a propósito (igual
# que RUTA_BASE_API más arriba): así este fichero no los contiene y el check puede
# seguir siendo estricto sin excluirse a sí mismo.
_GUARDA = "guardia_privilegios"
_YML = ".yml"
GUARDA_PRIVILEGIOS = "deployment_engine/tasks/" + _GUARDA + _YML
# Y ese fichero sólo puede incluirlo `preflight`: un verbo que escribe nunca debe
# llevar la guarda (no es una comprobación: es una lectura más una escritura nula,
# y dejaría el diario de un apply con una escritura que no converge).
UNICO_QUE_INCLUYE_LA_GUARDA = "deployment_engine/playbooks/preflight.yml"
# La ruta de la API de administración de permisos. En un .yml cuenta cualquier
# mención (un comentario no llama a la API, pero un `pve_api_ruta:` sí, y
# distinguirlos con una heurística sería frágil). En un .py sólo cuenta el literal
# ENTRE COMILLAS: los filtros y este mismo check hablan de esa ruta en comentarios
# y docstrings, y prohibir la palabra en prosa no protege de nada.
RUTA_ACCESS = "/access" + "/"
RUTA_ACCESS_CITA = '"' + RUTA_ACCESS

# Claves crudas de LXC que montarían rutas del HOST dentro de un invitado, y
# dispositivos. Ninguna tiene sitio en el vocabulario del motor: si aparecen, es que
# alguien está construyendo un contenedor que escapa del contenedor. Se arman por
# piezas, otra vez, para que este fichero no las contenga.
_CRUDO = "lxc."
CLAVES_PROHIBIDAS = tuple(_CRUDO + sufijo for sufijo in (
    "mount.entry", "mount", "cgroup", "cap.drop", "cap.keep", "apparmor", "idmap", "hook",
)) + tuple(
    "unprivileged" + sufijo for sufijo in (": 0", ": false", "=0", ": no", ": \"0\"")
) + tuple("dev" + str(numero) for numero in range(3))


def _ficheros_del_motor():
    rutas = list(_ficheros_con_extension(".yml", os.path.join(RAIZ, "deployment_engine")))
    rutas += list(_ficheros_con_extension(".py", os.path.join(RAIZ, "deployment_engine")))
    return rutas


def _menciona_access(texto, es_python):
    """¿Este texto llama (o podría llamar) a la API de permisos?"""
    if not es_python:
        return RUTA_ACCESS in texto
    return RUTA_ACCESS_CITA in texto


def check_privilegios():
    """Dos afirmaciones, las dos comprobables, sobre los privilegios.

    1. El motor NO concede privilegios: `/access/` sólo aparece en la guarda, y la
       guarda sólo la incluye `preflight`. Tampoco construye invitados que escapen
       del invitado (claves crudas de LXC, dispositivos).
    2. El motor SÍ detecta un invitado privilegiado: se llama a la función que lo
       lee y se comprueba con un caso que DEBE dar positivo. Una comprobación que
       no se prueba con un caso malo no prueba nada.
    """
    fallos = []
    for ruta in _ficheros_del_motor():
        relativo = _relativo(ruta)
        texto = _leer(ruta)
        es_python = ruta.endswith(".py")
        if _menciona_access(texto, es_python) and relativo != GUARDA_PRIVILEGIOS:
            fallos.append(
                f"{relativo}: habla con {RUTA_ACCESS}, y sólo puede hacerlo {GUARDA_PRIVILEGIOS}"
            )
        # Las comillas se quitan antes de buscar: la misma afirmación se escribe con
        # comillas alrededor del nombre en un diccionario Python y sin ellas en un
        # YAML, y una regla que sólo viera una de las dos formas no protege de nada.
        sin_comillas = texto.replace('"', "").replace("'", "")
        for clave in CLAVES_PROHIBIDAS:
            if clave in sin_comillas:
                fallos.append(f"{relativo}: contiene '{clave}', que el motor no debe usar nunca")

    # La guarda sólo se incluye desde preflight.
    for ruta in _ficheros_del_motor():
        relativo = _relativo(ruta)
        if relativo == GUARDA_PRIVILEGIOS:
            continue
        if (_GUARDA + _YML) in _leer(ruta) and relativo != UNICO_QUE_INCLUYE_LA_GUARDA:
            fallos.append(
                f"{relativo}: incluye la guarda de privilegios, y sólo puede hacerlo "
                f"{UNICO_QUE_INCLUYE_LA_GUARDA}"
            )

    # El caso que DEBE dar positivo: un contenedor sin `unprivileged` está
    # privilegiado, y el motor tiene que verlo.
    import estado as modulo_estado  # noqa: E402  (la ruta se ajusta arriba)

    estado_malo = {"invitados": {
        "200": {"vmid": 200, "nombre": "lab-x-puesto", "tipo": "lxc", "privilegiado": True},
        "201": {"vmid": 201, "nombre": "lab-x-servidor", "tipo": "lxc", "privilegiado": False},
    }}
    detectados = modulo_estado.estado_invitados_privilegiados(estado_malo)
    if [d["vmid"] for d in detectados] != [200]:
        fallos.append(
            "el motor NO detecta un contenedor privilegiado: con un invitado "
            "privilegiado y otro no, `estado_invitados_privilegiados` devolvió "
            f"{detectados} y debía devolver sólo el 200"
        )

    if fallos:
        print("FALLA privilegios: el motor está concediendo o dejando pasar privilegios:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("OK    privilegios: el motor no habla con /access/ fuera de su guarda (y sólo "
          "la incluye preflight), no usa claves crudas de LXC ni dispositivos, y detecta "
          "un invitado privilegiado")
    return 0


# ---------------------------------------------------------------------------
# check declaracion — coherencia de cada estado deseado
# ---------------------------------------------------------------------------

def check_declaracion():
    fallos = []
    labs = directorios_de_labs()
    for lab in labs:
        try:
            declaracion = declaracion_de(lab)
        except yaml.YAMLError as error:
            fallos.append(f"labs/{lab}/{lab}.yml: YAML inválido: {error}")
            continue
        for error in modulo_declaracion.declaracion_validar(declaracion, carpeta=lab):
            fallos.append(f"labs/{lab}/{lab}.yml: {error}")
    if fallos:
        print("FALLA declaracion: el estado deseado es incoherente:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print(f"OK    declaracion: {len(labs)} declaración(es) coherente(s)")
    return 0


# ---------------------------------------------------------------------------
# check colisiones — los conjuntos declarados por los labs son disjuntos
# ---------------------------------------------------------------------------

def _conjuntos_declarados(lab):
    """Lo que este lab declara y podría chocar con otro lab.

    Los nombres canónicos también son disjuntos por construcción (llevan el nombre
    del lab delante), pero se comprueban igual: si algún día dejan de llevarlo, este
    check es el que se entera. Los VMIDS no están aquí a propósito: los asigna el
    motor al aplicar y su disjunción no es comprobable sin credenciales (se dice en
    el README, no se maquilla).
    """
    declaracion = declaracion_de(lab)
    bridges = {b["nombre"] for b in declaracion["lab"]["bridges"]}
    direcciones = set()
    nombres = set()
    for seccion in ("vms", "containers"):
        for invitado in declaracion.get(seccion) or []:
            direcciones.add(str(invitado["direccion"]).split("/", 1)[0])
            nombres.add(f"{lab}-{invitado['rol']}")
    return {"bridges": bridges, "direcciones": direcciones, "nombres": nombres}


# Cómo se nombra cada conjunto al informar de una colisión (no `clave[:-1]`: eso
# escribiría "direccione").
ETIQUETA_DE_CONJUNTO = {
    "bridges": "el bridge",
    "direcciones": "la dirección",
    "nombres": "el nombre canónico",
}


def check_colisiones():
    labs = directorios_de_labs()
    conjuntos = {lab: _conjuntos_declarados(lab) for lab in labs}
    fallos = []
    for indice, lab_a in enumerate(labs):
        for lab_b in labs[indice + 1:]:
            for clave, etiqueta in ETIQUETA_DE_CONJUNTO.items():
                repetidos = conjuntos[lab_a][clave] & conjuntos[lab_b][clave]
                for repetido in sorted(repetidos):
                    fallos.append(f"'{lab_a}' y '{lab_b}' comparten {etiqueta}: {repetido}")
    if fallos:
        print("FALLA colisiones: dos labs declaran lo mismo (no pueden convivir):")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print(f"OK    colisiones: los conjuntos declarados de {len(labs)} lab(s) "
          "(bridges, direcciones, nombres canónicos) son disjuntos dos a dos")
    print("      (la disjunción de VMIDS no se puede comprobar sin credenciales: los asigna el motor al aplicar)")
    return 0


# ---------------------------------------------------------------------------
# check pureza-lab — ni un valor de lab dentro del motor
# ---------------------------------------------------------------------------

def check_pureza_lab():
    labs = directorios_de_labs()
    valores = {}
    for lab in labs:
        declaracion = declaracion_de(lab)
        tokens = {lab}
        for bridge in declaracion["lab"]["bridges"]:
            tokens.add(bridge["nombre"])
        for seccion in ("vms", "containers"):
            for invitado in declaracion.get(seccion) or []:
                tokens.add(f"{lab}-{invitado['rol']}")
        valores[lab] = sorted(tokens)

    fallos = []
    # Todo el motor: playbooks, tareas, filtros, plantillas y herramientas. Si el
    # nombre de un lab aparece en cualquiera de ellos, añadir un lab obligaría a
    # tocar el motor, que es justo lo que el encargo prohíbe.
    for extension in (".yml", ".py", ".j2", ".cfg"):
        for ruta in _ficheros_con_extension(extension, os.path.join(RAIZ, "deployment_engine")):
            texto = _leer(ruta)
            for lab, tokens in valores.items():
                for token in tokens:
                    if token in texto:
                        fallos.append(f"{_relativo(ruta)} contiene el valor del lab '{token}'")

    ruta_wrapper = os.path.join(RAIZ, "lab")
    if os.path.exists(ruta_wrapper):
        texto = _leer(ruta_wrapper)
        for lab, tokens in valores.items():
            for token in tokens:
                if token in texto:
                    fallos.append(f"lab contiene el valor del lab '{token}'")

    if fallos:
        print("FALLA pureza-lab: el motor contiene valores de un lab (el motor no conoce topologías):")
        for fallo in sorted(set(fallos)):
            print(f"  - {fallo}")
        return 1
    print(f"OK    pureza-lab: ni el nombre de un lab ni sus bridges aparecen dentro del motor ({len(labs)} lab(s) comprobados)")
    return 0


# ---------------------------------------------------------------------------
# check readme — el README habla del motor, no de un lab
# ---------------------------------------------------------------------------

def check_readme():
    ruta = os.path.join(RAIZ, "README.md")
    # La prosa del README no puede llevar valores de ningún lab; pero SÍ puede
    # CITAR literalmente la salida de un check (dentro de un bloque de código
    # cercado), porque esa salida ES la evidencia del ejercicio de romper a
    # propósito, y reescribirla sería mentir. Se quitan los bloques cercados antes
    # de buscar (misma función que usa `check links`): lo que queda es la prosa, lo
    # que el README afirma por su cuenta.
    texto = _fuera_de_bloques_de_codigo(_leer(ruta))
    fallos = []
    for lab in directorios_de_labs():
        declaracion = declaracion_de(lab)
        tokens = {lab}
        for bridge in declaracion["lab"]["bridges"]:
            tokens.add(bridge["nombre"])
        for seccion in ("vms", "containers"):
            for invitado in declaracion.get(seccion) or []:
                tokens.add(str(invitado["direccion"]))
                tokens.add(f"{lab}-{invitado['rol']}")
        for token in sorted(tokens):
            if token in texto:
                fallos.append(f"README.md contiene el valor del lab '{token}'")
    if fallos:
        print("FALLA readme: el README describe el motor y no puede llevar valores de ningún lab:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("OK    readme: el README no lleva ningún valor de ningún lab")
    return 0


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

CHECKS = {
    "links": check_links,
    "docs": check_docs,
    "refs": check_refs,
    "puerta": check_puerta,
    "privilegios": check_privilegios,
    "declaracion": check_declaracion,
    "colisiones": check_colisiones,
    "pureza-lab": check_pureza_lab,
    "readme": check_readme,
}


def ejecutar_todos():
    print("=" * 62)
    print("CHECKS DEL MOTOR (sin credenciales y sin Proxmox)")
    print("=" * 62)
    fallos = 0
    for nombre in CHECKS:
        print()
        fallos += int(CHECKS[nombre]() != 0)
    print()
    print("=" * 62)
    if fallos:
        print(f"RESULTADO: {fallos} check(s) en rojo. Arréglalos antes de seguir.")
        return 1
    print("RESULTADO: todos los checks en verde.")
    return 0


def main(argumentos):
    if not argumentos:
        return ejecutar_todos()
    orden = argumentos[0]
    resto = argumentos[1:]

    if orden == "all":
        return ejecutar_todos()
    if orden == "refs" and resto:
        return check_refs(resto[0])
    if orden == "docs" and resto:
        if resto[0] == "--actualizar":
            return check_docs(actualizar=True)
        if resto[0] == "--sellar":
            if len(resto) < 2:
                print("FALLA refs: --sellar necesita la ruta de un documento")
                return 2
            return sellar(resto[1])
    if orden in CHECKS:
        return CHECKS[orden]()
    print(f"check desconocido: {orden}. Los que hay: {', '.join(CHECKS)}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
