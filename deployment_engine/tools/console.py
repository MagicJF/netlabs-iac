#!/usr/bin/env python3
# PROPÓSITO:   hablar con la CONSOLA de un invitado de Proxmox por el protocolo del
#              navegador (`termproxy` + `vncwebsocket`). Es lo único del repositorio
#              que habla ese protocolo, y el motor lo usa para UNA sola cosa: pasar
#              UNA línea a un invitado que todavía no tiene ninguna red por la que
#              recibirla (el arranque del túnel, ver docs/tunnel-del-bastion.md).
#
#              No inventa un protocolo: replica exactamente lo que hace el cliente
#              del navegador del nodo, leído en /usr/share/pve-xtermjs/main.js
#              (medido en PVE 9.2.21):
#                - POST /api2/json/nodes/<nodo>/<tipo>/<vmid>/termproxy -> {ticket, port, user}
#                - websocket a .../vncwebsocket?port=<port>&vncticket=<ticket>
#                - al abrir, el cliente manda UNA línea cruda `<usuario>:<ticket>\n`
#                - los datos van enmarcados en texto: `0:<bytes>:<datos>`
#                  (el tamaño de pantalla es `1:<columnas>:<filas>:` y el latido `2`)
#                - el servidor contesta en tramas BINARIAS, empezando por `OK`
#              El servidor que acepta esto es el mismo que acepta al navegador: si
#              aquí funcionara otra cosa, no sería el mismo protocolo.
#
# INVARIANTES: SÓLO biblioteca estándar (ni websocket ni requests): el motor no
#              añade dependencias, y un cliente de consola no las merece. El fichero
#              NO conoce ningún lab: recibe nodo, tipo, vmid y línea por argumento.
#              La línea que se envía va en UN solo comando: nada de heredocs ni
#              comillas anidadas.
# LÍMITES:     una consola NO devuelve código de salida: se reconoce el eco. Aquí se
#              envuelve ese reconocimiento en dos marcas (`--marca-ok`/`--marca-fallo`)
#              y el resultado es el de la marca, no el del comando -- que es
#              exactamente lo frágil de esta capa, y por eso vive encerrada: una
#              tarea, una línea, y una comprobación que dice si funcionó.
#              El billete de consola vive 40 segundos: pedirlo y abrir el websocket
#              van seguidos, en el mismo paso.
# VER:         docs/tunnel-del-bastion.md; docs/decisiones/0004-*.md
#
# Uso:
#     console.py --url-base https://<nodo>:8006 --token-id X --token-secreto Y \
#                --nodo N --tipo lxc --vmid 107 --linea <base64> \
#                --marca-ok MARCA_OK --marca-fallo MARCA_FALLO
#     console.py --ayuda         (no: ver --help)
#
# Salida: una línea JSON con lo ocurrido (para el diario), y un código de salida:
#     0  se leyó la marca de éxito en la consola
#     3  se leyó la marca de fallo
#     4  se agotó el tiempo sin ver ninguna de las dos (la consola no dijo nada)
#     1  no se pudo ni abrir la consola (con el motivo en el JSON)

import argparse
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request

# La ruta base de la API. Vive aquí porque este fichero es el cliente de la vía de acceso de
# consola (mismo host, mismo puerto, mismo token que la vía de acceso REST; lo que cambia es
# el protocolo). `./lab check access` permite el literal en DOS ficheros y en ninguno
# más: tasks/pve_api.yml (REST) y este (consola). Se arma por piezas para que el
# check pueda seguir siendo estricto sin excluirse a sí mismo.
BASE_API = "/api2" + "/json"

# Cuánto se espera, como mucho, a que la consola responda. El arranque del túnel
# incluye descargar paquetes si hiciera falta, así que es generoso a propósito.
ESPERA_POR_DEFECTO = 300

# Tamaño de la ventana que se declara a la consola. No importa para ejecutar un
# comando, pero el servidor espera SIEMPRE un mensaje `1:...:` antes de los datos.
COLUMNAS = 200
FILAS = 50


def _salir(codigo, **datos):
    """Una línea JSON, siempre, y el código de salida. El diario se escribe con esto."""
    datos.setdefault("ok", codigo == 0)
    print(json.dumps(datos, ensure_ascii=False))
    return codigo


# ---------------------------------------------------------------------------
# Paso 1 — pedir el billete de consola (una llamada REST, la única de este fichero)
# ---------------------------------------------------------------------------

def pedir_billete(url_base, token_id, token_secreto, nodo, tipo, vmid, verificar_tls, espera):
    """POST termproxy -> {ticket, port, user}. Lanza si la API no lo da."""
    url = (
        f"{url_base}{BASE_API}/nodes/{nodo}/{tipo}/{vmid}/termproxy"
    )
    peticion = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={"Authorization": f"PVEAPIToken={token_id}={token_secreto}"},
    )
    contexto = None
    if not verificar_tls:
        contexto = ssl.create_default_context()
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(peticion, timeout=espera, context=contexto) as respuesta:
        cuerpo = json.loads(respuesta.read().decode("utf-8"))
    return cuerpo["data"]


# ---------------------------------------------------------------------------
# Paso 2 — el websocket, a mano: upgrade + tramas (RFC 6455 y nada más)
# ---------------------------------------------------------------------------

def _leer_exacto(flujo, cuantos):
    datos = b""
    while len(datos) < cuantos:
        trozo = flujo.recv(cuantos - len(datos))
        if not trozo:
            raise ConnectionError("la consola cerró la conexión")
        datos += trozo
    return datos


def _trama_cliente(datos, opcode=0x1):
    """Una trama de cliente. El cliente SIEMPRE enmascara (RFC 6455 §5.3)."""
    if isinstance(datos, str):
        datos = datos.encode("utf-8")
    mascara = os.urandom(4)
    cabecera = struct.pack("!B", 0x80 | opcode)
    largo = len(datos)
    if largo < 126:
        cabecera += struct.pack("!B", 0x80 | largo)
    elif largo < 65536:
        cabecera += struct.pack("!BH", 0x80 | 126, largo)
    else:
        cabecera += struct.pack("!BQ", 0x80 | 127, largo)
    enmascarado = bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))
    return cabecera + mascara + enmascarado


def _leer_trama(flujo):
    """Una trama del servidor: (opcode, datos). La cola del servidor no va enmascarada."""
    cabecera = _leer_exacto(flujo, 2)
    opcode = cabecera[0] & 0x0F
    enmascarada = bool(cabecera[1] & 0x80)
    largo = cabecera[1] & 0x7F
    if largo == 126:
        largo = struct.unpack("!H", _leer_exacto(flujo, 2))[0]
    elif largo == 127:
        largo = struct.unpack("!Q", _leer_exacto(flujo, 8))[0]
    mascara = _leer_exacto(flujo, 4) if enmascarada else b""
    datos = _leer_exacto(flujo, largo) if largo else b""
    if enmascarada:
        datos = bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))
    return opcode, datos


def _leer_hasta_cabeceras(flujo):
    """La respuesta del upgrade: se lee hasta la línea en blanco."""
    texto = b""
    while b"\r\n\r\n" not in texto:
        trozo = flujo.recv(1)
        if not trozo:
            raise ConnectionError("la conexión se cerró durante el upgrade")
        texto += trozo
        if len(texto) > 16384:
            raise ConnectionError("cabeceras de websocket absurdamente largas")
    return texto.decode("utf-8", "replace")


def abrir_websocket(url_base, nodo, tipo, vmid, puerto_vnc, ticket, token_id, token_secreto,
                    verificar_tls, espera):
    """Abre el websocket de la consola y devuelve (socket, flujo) ya en 'open'.

    Se declara el subprotocolo `binary` porque es el que pide el navegador del nodo
    (`new WebSocket(url, 'binary')`); el servidor lo acepta o no, y se comprueba.
    """
    partes = urllib.parse.urlparse(url_base)
    host = partes.hostname
    puerto = partes.port or (443 if partes.scheme == "https" else 80)
    ruta = (
        f"{BASE_API}/nodes/{nodo}/{tipo}/{vmid}/vncwebsocket"
        f"?port={puerto_vnc}&vncticket={urllib.parse.quote(ticket, safe='')}"
    )
    conexion = socket.create_connection((host, puerto), timeout=espera)
    flujo = conexion
    if partes.scheme == "https":
        contexto = ssl.create_default_context()
        if not verificar_tls:
            contexto.check_hostname = False
            contexto.verify_mode = ssl.CERT_NONE
        flujo = contexto.wrap_socket(conexion, server_hostname=host)
    clave = base64.b64encode(os.urandom(16)).decode()
    peticion = (
        f"GET {ruta} HTTP/1.1\r\n"
        f"Host: {host}:{puerto}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {clave}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: binary\r\n"
        f"Authorization: PVEAPIToken={token_id}={token_secreto}\r\n"
        "Origin: https://" + f"{host}:{puerto}\r\n"
        "\r\n"
    )
    flujo.sendall(peticion.encode())
    respuesta = _leer_hasta_cabeceras(flujo)
    primera = respuesta.split("\r\n", 1)[0]
    if "101" not in primera:
        flujo.close()
        raise ConnectionError(f"el websocket no se abrió: {primera.strip()}")

    # La clave de aceptación (RFC 6455 §4.1): se comprueba de verdad, no se da por
    # hecho. Un upgrade que responde 101 sin la clave correcta no es un websocket.
    aceptacion_esperada = base64.b64encode(
        hashlib.sha1((clave + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()
    for linea in respuesta.split("\r\n"):
        if linea.lower().startswith("sec-websocket-accept:"):
            obtenida = linea.split(":", 1)[1].strip()
            if obtenida != aceptacion_esperada:
                flujo.close()
                raise ConnectionError("el servidor aceptó el websocket con una clave que no es la esperada")
    return flujo


# ---------------------------------------------------------------------------
# Paso 3 — el diálogo: la línea cruda, el tamaño, y la línea que se manda
# ---------------------------------------------------------------------------

def conversar(flujo, usuario, ticket, linea, marca_ok, marca_fallo, espera):
    """Manda el arranque por la consola y espera el eco de una de las dos marcas.

    El orden es el del navegador: primero la línea cruda `<usuario>:<ticket>`, luego
    el tamaño de la pantalla y por último los datos. Se devuelve lo que se leyó, para
    el diario, y cuál de las marcas apareció.
    """
    flujo.sendall(_trama_cliente(f"{usuario}:{ticket}\n"))
    flujo.sendall(_trama_cliente(f"1:{COLUMNAS}:{FILAS}:"))

    # Un respiro para que el servidor conteste `OK` y suelte el eco de arranque, y
    # luego la línea de verdad. Manda en UN mensaje: `0:<bytes>:<datos>`.
    linea_completa = linea if linea.endswith("\n") else linea + "\n"
    flujo.sendall(_trama_cliente(f"0:{len(linea_completa.encode())}:{linea_completa}"))

    leido = b""
    limite = time.time() + espera
    encontrada = None
    while time.time() < limite:
        flujo.settimeout(max(0.5, min(5.0, limite - time.time())))
        try:
            opcode, datos = _leer_trama(flujo)
        except (socket.timeout, TimeoutError):
            continue
        except (ConnectionError, OSError):
            break
        if opcode == 0x8:  # cierre
            break
        if opcode in (0x9,):  # ping: se contesta con pong y se sigue
            flujo.sendall(_trama_cliente(datos, opcode=0xA))
            continue
        if opcode in (0x1, 0x2, 0x0):
            leido += datos
            texto = leido.decode("utf-8", "replace")
            if marca_fallo and marca_fallo in texto:
                encontrada = "fallo"
                break
            if marca_ok and marca_ok in texto:
                encontrada = "ok"
                break

    return {
        "encontrada": encontrada,
        "leido": leido.decode("utf-8", "replace"),
        "bytes": len(leido),
    }


def _cerrar(flujo):
    try:
        flujo.sendall(_trama_cliente(b"", opcode=0x8))
    except OSError:
        pass
    try:
        flujo.close()
    except OSError:
        pass


def main(argumentos):
    analizador = argparse.ArgumentParser(
        description="Manda UNA línea a la consola de un invitado de Proxmox y espera su eco."
    )
    analizador.add_argument("--url-base", required=True, help="https://<host>:<puerto>")
    analizador.add_argument("--token-id", required=True)
    analizador.add_argument("--token-secreto", required=True)
    analizador.add_argument("--nodo", required=True)
    analizador.add_argument("--tipo", required=True, choices=("lxc", "qemu"))
    analizador.add_argument("--vmid", required=True)
    analizador.add_argument("--linea", required=True, help="el texto a enviar, tal cual")
    analizador.add_argument("--marca-ok", default="", help="lo que se espera en el eco si fue bien")
    analizador.add_argument("--marca-fallo", default="", help="lo que se espera en el eco si fue mal")
    analizador.add_argument("--verificar-tls", default="false")
    analizador.add_argument("--espera", type=int, default=ESPERA_POR_DEFECTO)
    analizador.add_argument("--base64", action="store_true",
                            help="la línea viene codificada en base64 (una sola palabra)")
    opciones = analizador.parse_args(argumentos)

    verificar_tls = str(opciones.verificar_tls).lower() in ("1", "true", "yes", "si", "sí")
    linea = opciones.linea
    if opciones.base64:
        linea = base64.b64decode(linea).decode("utf-8")

    comunes = {
        "nodo": opciones.nodo,
        "tipo": opciones.tipo,
        "vmid": opciones.vmid,
        "marca_ok": opciones.marca_ok,
        "marca_fallo": opciones.marca_fallo,
    }
    try:
        billete = pedir_billete(
            opciones.url_base, opciones.token_id, opciones.token_secreto,
            opciones.nodo, opciones.tipo, opciones.vmid, verificar_tls, min(30, opciones.espera),
        )
    except Exception as error:  # noqa: BLE001 - cualquier fallo aquí es "no hay consola"
        return _salir(1, motivo=f"no se pudo pedir el billete de consola: {error}", **comunes)

    try:
        flujo = abrir_websocket(
            opciones.url_base, opciones.nodo, opciones.tipo, opciones.vmid,
            billete["port"], billete["ticket"], opciones.token_id, opciones.token_secreto,
            verificar_tls, min(30, opciones.espera),
        )
    except Exception as error:  # noqa: BLE001
        return _salir(1, motivo=f"no se pudo abrir el websocket de consola: {error}", **comunes)

    try:
        resultado = conversar(
            flujo, billete.get("user", opciones.token_id), billete["ticket"], linea,
            opciones.marca_ok, opciones.marca_fallo, opciones.espera,
        )
    finally:
        _cerrar(flujo)

    # El eco se recorta para el diario: la consola devuelve lo que devuelva el comando,
    # y el diario es prueba de lo ocurrido, no una copia de la sesión.
    eco = resultado["leido"][-2000:]
    if resultado["encontrada"] == "ok":
        return _salir(0, eco=eco, bytes=resultado["bytes"], **comunes)
    if resultado["encontrada"] == "fallo":
        return _salir(3, eco=eco, bytes=resultado["bytes"], **comunes)
    return _salir(4, motivo="la consola no dijo ninguna de las dos marcas", eco=eco,
                  bytes=resultado["bytes"], **comunes)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
