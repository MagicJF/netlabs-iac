#!/usr/bin/env python3
# PROPÓSITO:   probar el descifrado de `secrets.sops.yml` en el wrapper (informe §6.6):
#              que exista el fichero CIFRADO y no el claro dispare el descifrado, que un
#              claro más nuevo MANDE, y que falte `sops` o la clave se diga en claro en
#              vez de fallar por la cara.
# INVARIANTES: los casos que TIENEN que cumplirse:
#              1. sin `secrets.sops.yml` no se toca NADA (ni se crea nada);
#              2. con cifrado y sin claro, se descifra y el claro queda en 0600;
#              3. un claro MÁS NUEVO que el cifrado no se pisa;
#              4. sin el binario `sops`, se devuelve un error que lo nombra (no un crash);
#              5. sin la clave privada de age, se devuelve un error que la nombra.
# LÍMITES:     no cifra ni descifra con sops de verdad (no hay que inventarse una clave
#              age aquí): `sops` se SUSTITUYE por un doble que copia el fichero, así que
#              lo que se prueba es la DECISIÓN del wrapper, no la criptografía de sops.
#              Que sops descifre de verdad se prueba con un `apply` real y una clave de
#              verdad, que no viven en el repositorio.
# VER:         lab (función `descifrar_secretos`); docs/decisiones/0025-*.md

# Uso:  python3 test/test_secretos_cifrados.py     (código de salida != 0 si algo falla)

import importlib.machinery
import importlib.util
import os
import shutil
import stat
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def comprobar(condicion, descripcion):
    print(("  OK   " if condicion else "  FALLA") + f" {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)


def cargar_wrapper():
    """El módulo `lab` (el wrapper no tiene extensión; se carga por ruta)."""
    ruta = os.path.join(RAIZ, "lab")
    especificacion = importlib.util.spec_from_loader(
        "wrapper_lab", importlib.machinery.SourceFileLoader("wrapper_lab", ruta)
    )
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


DOBLE_SOPS = """#!/usr/bin/env python3
# Un doble de `sops`: copia el fichero de entrada al `--output`. No cifra nada.
import sys
argumentos = sys.argv[1:]
salida = argumentos[argumentos.index("--output") + 1]
origen = argumentos[-1]
with open(origen, encoding="utf-8") as entrada, open(salida, "w", encoding="utf-8") as destino:
    destino.write(entrada.read())
"""


def escenario(carpeta, con_cifrado, con_claro, con_clave, con_sops):
    """Monta una carpeta con las piezas que pida el caso y apunta el módulo ahí."""
    cifrados = os.path.join(carpeta, "secrets.sops.yml")
    claro = os.path.join(carpeta, "secrets.yml")
    clave = os.path.join(carpeta, "age.key")
    if con_cifrado:
        with open(cifrados, "w", encoding="utf-8") as fichero:
            fichero.write("pve_token" + "_secreto: ENC[AES256_GCM,data:abc,type:str]\n")
    if con_claro:
        with open(claro, "w", encoding="utf-8") as fichero:
            fichero.write("pve_token" + "_secreto: en-claro\n")
    if con_clave:
        with open(clave, "w", encoding="utf-8") as fichero:
            fichero.write("AGE-SECRET-KEY-1" + "A" * 40 + "\n")
    bin = os.path.join(carpeta, "bin")
    os.makedirs(bin, exist_ok=True)
    if con_sops:
        ruta_sops = os.path.join(bin, "sops")
        with open(ruta_sops, "w", encoding="utf-8") as fichero:
            fichero.write(DOBLE_SOPS)
        os.chmod(ruta_sops, os.stat(ruta_sops).st_mode | stat.S_IEXEC)
    return cifrados, claro, clave, bin


def apunta(modulo, cifrados, claro, clave):
    """Le dice al wrapper dónde están sus tres rutas (el módulo vive en el repo)."""
    for nombre, valor in (("SECRETS_CIFRADOS", cifrados), ("SECRETS", claro), ("CLAVE_AGE", clave)):
        setattr(modulo, nombre, valor)


def main():
    modulo = cargar_wrapper()
    print("1. sin `secrets.sops.yml` no se toca nada")
    carpeta = tempfile.mkdtemp(prefix="netlabs-cifrados-")
    try:
        cifrados, claro, clave, _ = escenario(carpeta, False, True, True, True)
        apunta(modulo, cifrados, claro, clave)
        antes = os.path.getmtime(claro)
        comprobar(modulo.descifrar_secretos() is None, "1.1 · devuelve None (no hay nada que hacer)")
        comprobar(os.path.getmtime(claro) == antes, "1.2 · el claro no se ha tocado")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    print("\n2. con cifrado y sin claro, se descifra y queda en 0600")
    carpeta = tempfile.mkdtemp(prefix="netlabs-cifrados-")
    try:
        cifrados, claro, clave, bin_dir = escenario(carpeta, True, False, True, True)
        apunta(modulo, cifrados, claro, clave)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        resultado = modulo.descifrar_secretos()
        comprobar(resultado is None, "2.1 · sin error")
        comprobar(os.path.exists(claro), "2.2 · el claro se ha creado")
        comprobar(
            stat.S_IMODE(os.stat(claro).st_mode) == 0o600,
            "2.3 · el claro queda en modo 0600",
        )
    finally:
        os.environ["PATH"] = os.environ["PATH"].split(os.pathsep, 1)[-1]
        shutil.rmtree(carpeta, ignore_errors=True)

    print("\n3. un claro MÁS NUEVO que el cifrado no se pisa")
    carpeta = tempfile.mkdtemp(prefix="netlabs-cifrados-")
    try:
        cifrados, claro, clave, bin_dir = escenario(carpeta, True, True, True, False)
        os.utime(cifrados, (1000, 1000))
        apunta(modulo, cifrados, claro, clave)
        os.utime(claro, (2000, 2000))
        comprobar(modulo.descifrar_secretos() is None, "3.1 · devuelve None")
        with open(claro, encoding="utf-8") as fichero:
            comprobar("en-claro" in fichero.read(), "3.2 · el claro sigue siendo el mío")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    print("\n4. sin el binario `sops`, se dice en claro")
    carpeta = tempfile.mkdtemp(prefix="netlabs-cifrados-")
    try:
        cifrados, claro, clave, _ = escenario(carpeta, True, False, True, False)
        apunta(modulo, cifrados, claro, clave)
        ruta_original = os.environ.get("PATH", "")
        os.environ["PATH"] = "/nonexistent"
        try:
            error = modulo.descifrar_secretos()
        finally:
            os.environ["PATH"] = ruta_original
        comprobar(error is not None and "sops" in error, "4.1 · el error nombra `sops`")
        comprobar(not os.path.exists(claro), "4.2 · no se ha creado un claro a medias")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    print("\n5. sin la clave privada de age, se dice en claro")
    carpeta = tempfile.mkdtemp(prefix="netlabs-cifrados-")
    try:
        cifrados, claro, clave, bin_dir = escenario(carpeta, True, False, False, True)
        apunta(modulo, cifrados, claro, clave)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        try:
            error = modulo.descifrar_secretos()
        finally:
            os.environ["PATH"] = os.environ["PATH"].split(os.pathsep, 1)[-1]
        comprobar(error is not None and "age.key" in error, "5.1 · el error nombra la clave")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    if FALLOS:
        print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
        return 1
    print("\nRESULTADO: el descifrado de secretos hace lo que dice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
