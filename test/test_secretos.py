#!/usr/bin/env python3
# PROPÓSITO:   probar el candado de `check secretos` (ADR 0024): que caza las formas
#              que dan acceso al NODO y que deja pasar lo que el repo cita a propósito
#              -- las credenciales de los labs y los huecos de la plantilla. Un check
#              que no se ha visto fallar no es un check.
# INVARIANTES: ninguna prueba toca la red ni escribe en el repo. Las que prueban el
#              modo `--staged` trabajan sobre un repositorio git DESECHABLE en un
#              directorio temporal, porque el modo staged lee el ÍNDICE.
#              Las formas vigiladas se arman por piezas: si este fichero las llevara
#              escritas, el propio candado se caería sobre la batería que lo prueba.
# LÍMITES:     no prueba la detección de secretos de forma desconocida (un token de
#              otro sistema, una contraseña de un lab): el candado no es un escáner de
#              entropía, es la lista de lo que abre el host. Tampoco mira el historial:
#              git no reescribe el pasado por un hook.
# VER:         deployment_engine/tools/framework_check.py §check_secretos; ADR 0024

import os
import shutil
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "tools"))

import framework_check as modulo  # noqa: E402

FALLOS = []


def comprobar(condicion, texto):
    if condicion:
        print(f"  OK    {texto}")
    else:
        FALLOS.append(texto)
        print(f"  FALLA {texto}")


# --- las formas, por piezas (ver INVARIANTES) ---------------------------------
BILLETE = "PVE" + ":root@pam:" + "0f1e2d3c"
CSRF = "CSRFPrevention" + "Token: " + "0123456789abcdef"
TOKEN = "PVEAPI" + "Token=" + "netlabs@pve!motor=" + "9f8e7d6c-1a2b-3c4d-5e6f-001122334455"
CLAVE = "-----BEGIN " + "OPENSSH " + "PRIVATE KEY-----"


def repo_desechable():
    """Un repo git vacío y desechable, con su índice, para probar el modo --staged."""
    carpeta = tempfile.mkdtemp(prefix="candado-")
    subprocess.run(["git", "init", "-q"], cwd=carpeta, check=True)
    return carpeta


def con_repo(carpeta, ficheros):
    """Escribe los ficheros, los deja en el índice y corre el check contra ese repo.

    Un valor `bytes` se escribe tal cual (para probar un binario); un `str`, en UTF-8.
    """
    for nombre, contenido in ficheros.items():
        if isinstance(contenido, (bytes, bytearray)):
            with open(os.path.join(carpeta, nombre), "wb") as fichero:
                fichero.write(contenido)
        else:
            with open(os.path.join(carpeta, nombre), "w", encoding="utf-8") as fichero:
                fichero.write(contenido)
    subprocess.run(["git", "add", "-A"], cwd=carpeta, check=True)
    anterior, modulo.RAIZ = modulo.RAIZ, carpeta
    modulo._CACHE_VERSIONADOS = None
    try:
        return modulo.check_secretos(staged=True)
    finally:
        modulo.RAIZ = anterior
        modulo._CACHE_VERSIONADOS = None


def con_repo_sin_staged(carpeta, ficheros):
    """Como `con_repo`, pero corre el modo por defecto (lee del DISCO vía `git ls-files`).

    Es el modo que usa `./lab check secretos` sin `--staged`, y el único que pasa por
    `_ficheros_versionados()`: aquí es donde un nombre con acento se escapaba.
    """
    for nombre, contenido in ficheros.items():
        with open(os.path.join(carpeta, nombre), "w", encoding="utf-8") as fichero:
            fichero.write(contenido)
    subprocess.run(["git", "add", "-A"], cwd=carpeta, check=True)
    anterior, modulo.RAIZ = modulo.RAIZ, carpeta
    modulo._CACHE_VERSIONADOS = None
    try:
        return modulo.check_secretos(staged=False)
    finally:
        modulo.RAIZ = anterior
        modulo._CACHE_VERSIONADOS = None


# --- 1. el repositorio de verdad, limpio --------------------------------------
# La primera prueba de un candado es no quedarse cerrado con la llave dentro.
print("\n1. el repositorio, hoy")
codigo = modulo.check_secretos()
comprobar(codigo == 0, "1.1 · lo que el repo versiona hoy no abre el nodo del host")

# --- 2. lo que tiene que cazar -----------------------------------------------
print("\n2. lo que tiene que cazar")
casos = [
    ("2.1 · un ticket de sesión de la API", {"notas.txt": "GET ?" + BILLETE + "\n"}),
    ("2.2 · un CSRFPreventionToken", {"notas.txt": "headers = {" + CSRF + "}\n"}),
    ("2.3 · el token de la API con su valor", {"notas.txt": "Authorization: " + TOKEN + "\n"}),
    ("2.4 · una clave privada", {"id_ed25519": CLAVE + "\nabc\n"}),
    ("2.5 · el fichero de credenciales maestras", {"secrets.yml": "pve_nodo: 10.0.0.1\n"}),
    ("2.6 · una clave del HOST con valor", {"cfg.yml": 'pve_ssh' + '_password: "no-es-un-hueco"\n'}),
    ("2.7 · el secreto del token con valor", {"cfg.yml": "pve_token" + '_secreto: 9f8e7d6c\n'}),
    ("2.8 · una clave del HOST ENTRECOMILLADA (YAML válido)",
     {"cfg.yml": '"pve_token' + '_secreto": "9f8e7d6c-1a2b-3c4d"\n'}),
    ("2.9 · una clave del HOST en una entrada JSON",
     {"cfg.json": '{"pve_ssh' + '_password": "no-es-un-hueco", "otra": 1}\n'}),
    ("2.10 · la clave en un fichero con ACENTO en el nombre (nombre no ASCII)",
     {"configuración.yml": "pve_ssh" + '_usuario: "no-es-un-hueco"\n'}),
    ("2.11 · un valor ENTRECOMILLADO que empieza por coma",
     {"cfg.yml": 'pve_ssh' + '_password: ",no-es-un-hueco"\n'}),
    ("2.12 · el valor en la LÍNEA SIGUIENTE (YAML en bloque)",
     {"cfg.yml": "pve_token" + '_secreto:\n  9f8e7d6c-1a2b-3c4d-5e6f-001122334455\n'}),
    ("2.13 · dos claves en la MISMA línea (JSON), la segunda con valor",
     {"cfg.json": '{"pve_ssh' + '_usuario":"<usuario>","pve_token' + '_secreto":"9f8e7d6c-1a2b"}\n'}),
    ("2.14 · una contraseña ENTRECOMILLADA que empieza por almohadilla",
     {"cfg.yml": 'pve_ssh' + '_password: "#no-es-un-comentario"\n'}),
]
for texto, ficheros in casos:
    carpeta = repo_desechable()
    try:
        comprobar(con_repo(carpeta, ficheros) == 1, texto)
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

# --- 3. lo que NO puede cazar (la política es asimétrica) ---------------------
print("\n3. lo que no puede cazar")
permisos = [
    ("3.1 · un hueco `<...>`", {"doc.md": "Authorization: PVEAPI" + "Token=<usuario>@pve!<nombre>=<secreto>\n"}),
    ("3.2 · una expresión de Jinja", {"tareas.yml": "cabecera: \"PVEAPI" + "Token={{ pve_token_id }}={{ pve_token_secreto }}\"\n"}),
    ("3.3 · la contraseña de un LAB (se cita a propósito)", {"lab.md": 'routeros_clave: "admin/clave-de-sandbox-del-lab"\n'}),
    ("3.4 · una clave del HOST como hueco", {"doc.md": 'pve_ssh' + '_usuario: "<usuario>"\n'}),
    ("3.5 · la palabra «ticket» en prosa", {"doc.md": "El ticket de sesión caduca; por eso el motor lo pide en cada orden.\n"}),
    ("3.6 · una clave del HOST sin valor, seguida de una línea HERMANA",
     {"cfg.yml": "config:\n  pve_token" + "_secreto:\n  pve_puerto: 8006\n"}),
    ("3.7 · una clave del HOST que sólo lleva un comentario",
     {"cfg.yml": "pve_ssh" + '_usuario: # se pone en secrets.yml\n'}),
]
for texto, ficheros in permisos:
    carpeta = repo_desechable()
    try:
        comprobar(con_repo(carpeta, ficheros) == 0, texto)
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

# --- 4. lo que no puede TUMBAR el candado ------------------------------------
# Un binario en el índice no es un secreto, pero antes reventaba el check con un
# UnicodeDecodeError y bloqueaba un commit válido. Aquí se prueba que no lo hace.
print("\n4. lo que no puede tumbar el candado")
carpeta = repo_desechable()
try:
    binario = bytes(range(256))  # no es UTF-8 válido a propósito
    comprobar(con_repo(carpeta, {"logo.png": binario, "nota.md": "sin secretos\n"}) == 0,
              "4.1 · un fichero binario en el índice no bloquea el commit")
finally:
    shutil.rmtree(carpeta, ignore_errors=True)

# --- 5. el modo por defecto también ve los nombres raros ----------------------
print("\n5. el modo por defecto ve los nombres con acento")
carpeta = repo_desechable()
try:
    comprobar(con_repo_sin_staged(carpeta, {"configuración.yml": "pve_token" + '_secreto: 9f8e7d6c\n'}) == 1,
              "5.1 · sin `-z`, `git ls-files` escondía el fichero con acento")
finally:
    shutil.rmtree(carpeta, ignore_errors=True)

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el candado caza las cuatro formas de acceso al host y deja en paz los labs.")
