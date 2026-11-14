# PROPÓSITO:   el vocabulario CERRADO del interior de un invitado y la función pura
#              que decide qué hay que cambiar dentro de cada área: (declarado, leído)
#              -> pasos del interior. Es el hermano de tools/plan.py para lo de
#              dentro: el plan decide qué invitados hay y en qué orden; esto decide
#              qué se escribe DENTRO de cada uno.
#
#              Un "área" es una parte del equipo de la que la declaración es dueña
#              (docs/decisiones/0005). Dentro de un área declarada, lo que no está
#              en el YAML se QUITA del equipo; fuera de las áreas declaradas el
#              motor no opina (regla 17).
#
# INVARIANTES: es PURA: no habla con nadie, no lee ficheros, no conoce ningún lab
#              concreto. Sólo mira la declaración, la identidad ya asignada y lo que
#              el driver LEYÓ dentro del equipo. Los tipos que conoce ("linux",
#              "routeros") son protocolos o sistemas operativos, nunca topologías:
#              cualquier lab con un CHR usa el mismo driver (regla 3 del encargo).
#              El vocabulario es CERRADO: lo que no está en AREAS no se valida y no
#              se converge. Una primitiva nueva se añade aquí, con su ADR.
# LÍMITES:     no sabe escribir: devuelve operaciones en el vocabulario del interior
#              y el driver (tasks/configurar_*.yml) las traduce a su protocolo. La
#              traducción a la sintaxis del equipo vive en el driver, en un solo
#              sitio, nunca en la declaración.
#              Este módulo NO implementa las áreas del encargo que el motor todavía
#              no converge (puentes, cortafuegos, dns…): están en AREAS_PENDIENTES y
#              la validación las rechaza diciéndolo, para que no parezca que se
#              ignoran. Añadirlas es un driver y un ADR, nunca una plantilla más.
# VER:         docs/decisiones/0005-areas-declaradas.md; docs/camino-del-puesto-de-control.md;
#              README.md §El interior; ./lab check declaracion

# --- Los dos tipos de interior ------------------------------------------------
# El tipo NO se adivina: lo dice la declaración (`config:<tipo>`). Un invitado sin
# `config` no se toca por dentro: el motor lo despliega y se calla.
TIPOS = ("linux", "routeros")

# --- Las áreas de cada tipo, EN ORDEN DE CONVERGENCIA -------------------------
# El orden importa y no es casual (es el que v3 pagó caro):
#   * `camino` va primero en Linux porque es LA FORMA DE ENTRAR: si el puesto de
#     control no tiene su salida, ninguna otra área de ese invitado se puede
#     converger (no hay camino por el que llegar).
#   * `identidad` va la ÚLTIMA en RouterOS en la primera convergencia (ver
#     `identidad_al_final`), para no perder el camino de vuelta a mitad de faena:
#     primero se añade y se verifica lo nuevo, y sólo entonces se cambia la
#     identidad del equipo. v3 lo llamaba intercambio atómico.
#   * `cortafuegos` va al final: no se cierra una puerta antes de haber pasado por
#     ella.
AREAS = {
    "linux": ("camino", "direccion", "reenvio", "dhcp_servidor"),
    "routeros": ("identidad", "servicios", "cliente_dhcp", "direcciones", "rutas", "dhcp"),
}

# Las áreas que el encargo nombra y el motor TODAVÍA no converge. Se declaran aquí
# a propósito: la validación las rechaza con un motivo legible en vez de aceptarlas
# y luego no hacer nada con ellas, que es la forma más silenciosa de mentir.
AREAS_PENDIENTES = {
    "routeros": ("puentes", "cortafuegos"),
    "linux": ("pasarela", "rutas", "dns", "claves"),
}

# --- Servicios: el alcance del área `servicios` -------------------------------
# El área manda sobre estos servicios y sólo sobre estos: lo que se declara se
# deshabilita y lo que NO se declara (pero está en esta lista) se vuelve a
# habilitar. `www` no está: es donde vive REST, o sea el camino de vuelta, y
# deshabilitarlo deja el equipo sin forma de ser configurado nunca más.
SERVICIOS_GESTIONADOS = ("api", "api-ssl", "ftp", "telnet", "ssh")
SERVICIOS_NUNCA_DESHABILITADOS = ("www",)

# --- El camino ---------------------------------------------------------------
# El único vocabulario que el puesto de control declara es `camino`. El resto (por
# dónde sale, con qué clave, en qué puerto) es entorno, no lab: vive en secrets.yml
# y en vars/engine.yml. Un lab que llevara dentro la dirección de casa dejaría de
# poder desplegarse en otra casa.
CLAVE_CAMINO = "camino"

# El nombre del script `echo <base64> | base64 -d | sh` que se manda por la consola.
# Lo pone el MOTOR dentro de su propio equipo, así que no es un valor de ningún lab.
RUTA_GUION_CAMINO = "/usr/local/sbin/netlabs-camino"
UNIDAD_CAMINO = "netlabs-camino.service"


class ErrorMotor(Exception):
    """Mismo nombre que el error de Ansible: este módulo se prueba sin Ansible."""


# ---------------------------------------------------------------------------
# Vocabulario: qué se puede declarar dentro de cada tipo
# ---------------------------------------------------------------------------

def tipo_de(invitado):
    """El tipo de interior declarado, o None si el invitado no declara `config`."""
    config = (invitado or {}).get("config")
    if not isinstance(config, dict) or not config:
        return None
    tipos = [t for t in TIPOS if t in config]
    if len(tipos) != 1:
        raise ErrorMotor(
            "`config:` tiene que traer exactamente una clave de tipo "
            f"({', '.join(TIPOS)}), y trae {sorted(config.keys())}"
        )
    return tipos[0]


def areas_de(invitado):
    """{área: valor declarado} del invitado, en orden de convergencia.

    La dirección del invitado es un área más, y por eso aparece aquí: el nivel de
    arriba (`direccion:` en el invitado) es la dirección de su pata de gestión, y
    dentro de un Linux es algo que hay que converger leyendo y escribiendo, no un
    campo que la API del hipervisor guarde.
    """
    tipo = tipo_de(invitado)
    if tipo is None:
        return {}
    declaradas = dict((invitado.get("config") or {}).get(tipo) or {})
    if tipo == "linux":
        declaradas["direccion"] = invitado.get("direccion")
    return {area: declaradas.get(area) for area in AREAS[tipo] if area in declaradas}


def areas_a_leer(invitado):
    """Las áreas que el driver tiene que LEER dentro del equipo (las declaradas)."""
    return list(areas_de(invitado).keys())


def declara_interior(invitado):
    """¿Este invitado declara interior? (si no, el motor no entra: ni lee ni escribe)."""
    return tipo_de(invitado) is not None


def tiene_camino(invitado):
    """¿Es el puesto de control? (declara `config.linux.camino`)."""
    return CLAVE_CAMINO in ((invitado.get("config") or {}).get("linux") or {})


# ---------------------------------------------------------------------------
# La dirección de la pata de gestión: el motor la DERIVA (nada derivado se guarda)
# ---------------------------------------------------------------------------

def direccion_libre(subred, usadas, desde_arriba=True):
    """La primera dirección libre de `subred`, contando por arriba.

    Se cuenta por ARRIBA (`.254`, `.253`…) a propósito: los routers de los labs
    sirven DHCP desde el principio del rango, y las direcciones de gestión no
    pueden caer dentro de un pool que reparte el lab. `usadas` es una colección de
    direcciones sin máscara. La primera dirección de la subred (la del bridge) y la
    última (difusión) nunca se eligen.
    """
    base, _, prefijo = str(subred or "").partition("/")
    if not base or not prefijo:
        raise ErrorMotor(f"no se puede elegir una dirección libre en '{subred}': falta la máscara")
    octetos = [int(o) for o in base.split(".")]
    prefijo = int(prefijo)
    if prefijo % 8 != 0 or not (8 <= prefijo <= 24):
        # Sólo se eligen direcciones en redes de clase C (o más pequeñas): es donde
        # vive un bridge de laboratorio. Cualquier otra cosa se dice, no se adivina.
        raise ErrorMotor(
            f"no se sabe elegir una dirección libre en {subred}: el motor sólo "
            "gestiona prefijos /8 /16 /24"
        )
    ocupados = {str(u).split("/")[0] for u in (usadas or [])}
    ocupados.add(base)
    rango = range(1, 255) if desde_arriba is False else range(254, 0, -1)
    for ultimo in rango:
        candidata = ".".join(str(o) for o in octetos[:3] + [ultimo])
        if candidata in ocupados:
            continue
        return candidata
    raise ErrorMotor(f"no queda ninguna dirección libre en {subred}")


def patas_del_puesto_control(invitado, declaracion, estado, parametros):
    """Las patas del puesto de control, TODAS al nacer: (bridge, dirección, máscara, puerta).

    Nace completo porque cambiarle las patas a un invitado en marcha obliga a
    reiniciarlo, y aquí no se reinicia la máquina que está trabajando (§5).

      * La PRIMERA pata va en el bridge de gestión del NODO (valor de entorno, no
        del lab): es por donde el puesto sale hacia casa. Su dirección la elige el
        motor de entre las libres, leyendo las que ya usa cada invitado del nodo.
        Su puerta es la dirección que el nodo tiene en ese bridge.
      * Después, una pata por cada bridge del LAB. La del bridge que el invitado
        declara lleva su dirección DECLARADA (la gestión no puede depender de los
        routers que está desplegando); las demás las elige el motor por arriba,
        esquivando las direcciones que el lab declara y las que están en uso.
    """
    puente_gestion = str(parametros.get("bridge_gestion") or "")
    direcciones_bridge = estado.get("bridges_direcciones") or {}
    usadas = estado.get("direcciones_usadas") or []

    patas = []
    if puente_gestion:
        subred = str(direcciones_bridge.get(puente_gestion) or "")
        direccion = direccion_libre(subred, usadas) if subred else ""
        patas.append(
            {
                "bridge": puente_gestion,
                "direccion": f"{direccion}/{subred.split('/')[1]}" if direccion else "",
                # La puerta de la pata de gestión es la dirección que el NODO tiene
                # en ese bridge (10.10.10.1 en vmbr1): por ahí sale hacia casa. No es
                # un valor del lab: se lee de la red del nodo.
                "puerta": subred.split("/")[0] if subred else "",
                "papel": "salida hacia casa",
            }
        )
    # Las direcciones que el lab declara en un bridge: ninguna pata de gestión puede
    # caer encima de un router o de un servidor que el lab ya ha reservado.
    declaradas_por_bridge = {}
    for otro in declaracion.get("invitados", []):
        direccion = str(otro.get("direccion") or "")
        if direccion and direccion != "dhcp" and "/" in direccion:
            declaradas_por_bridge.setdefault(otro.get("bridge"), []).append(direccion)

    for bridge in declaracion.get("bridges", []):
        nombre = bridge.get("nombre")
        if nombre == invitado.get("bridge") and invitado.get("direccion"):
            patas.append(
                {
                    "bridge": nombre,
                    "direccion": invitado["direccion"],
                    "puerta": "",
                    "papel": "pata declarada del puesto de control",
                }
            )
            continue
        subred = bridge.get("direccion")
        usadas_aqui = list(usadas) + declaradas_por_bridge.get(nombre, [])
        direccion = direccion_libre(subred, usadas_aqui) if subred else ""
        patas.append(
            {
                "bridge": nombre,
                "direccion": f"{direccion}/{subred.split('/')[1]}" if direccion else "",
                "puerta": "",
                "papel": "pata del puesto de control en un bridge del lab",
            }
        )
    return patas


def puerto_camino(vmid, parametros):
    """El puerto del nodo de control donde el puesto deja su sshd. DERIVADO del vmid."""
    return int(parametros.get("camino_puerto_base") or 20000) + int(vmid)


def guion_camino(clave_privada, host, puerto, usuario, puerto_local):
    """El texto que se manda por la consola: UNA sola vez, y queda puesto.

    Qué hace, y por qué esto y no otra cosa:

      1. deja la clave del camino dentro del invitado, con sus permisos;
      2. escribe un GUION que abre la salida hacia casa con `ssh -R` (el puesto de
         control se conecta al sshd del nodo de control y deja reenviado un puerto
         local SUYO hacia su propio sshd: por ahí entra Ansible y de ahí cuelga el
         resto del lab);
      3. lo pone como UNIDAD de systemd con `Restart=always` y la habilita.

    El punto 3 es lo que hace que la consola se use UNA vez por vida del invitado y
    no en cada `apply`: si el invitado reinicia, el camino se levanta solo. Y es
    idempotente: volver a mandarlo reescribe lo mismo y reinicia el servicio.

    Va en base64 porque la consola no es un canal de datos fiable: una línea, sin
    heredocs ni comillas que escapar, sin nada que el eco pueda romper.
    """
    return f"""#!/bin/sh
# PROPÓSITO: abrir la salida hacia casa del puesto de control y sostenerla.
# Lo escribe el motor UNA vez, por la consola, al nacer el invitado
# (docs/camino-del-puesto-de-control.md). Si el invitado reinicia, systemd lo
# vuelve a levantar: no hace falta volver a entrar por consola.
set -u
mkdir -p /root/.ssh && chmod 700 /root/.ssh
cat > /root/.ssh/netlabs_camino <<'FIN_CLAVE'
{clave_privada}
FIN_CLAVE
chmod 600 /root/.ssh/netlabs_camino
cat > {RUTA_GUION_CAMINO} <<'FIN_GUION'
#!/bin/sh
exec ssh -i /root/.ssh/netlabs_camino \\
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \\
  -o ExitOnForwardFailure=yes \\
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \\
  -N -R {puerto_local}:localhost:22 -p {puerto} {usuario}@{host}
FIN_GUION
chmod 755 {RUTA_GUION_CAMINO}
cat > /etc/systemd/system/{UNIDAD_CAMINO} <<'FIN_UNIDAD'
[Unit]
Description=netlabs_v4_b: salida hacia el nodo de control (el camino del lab)
After=network-online.target ssh.service
Wants=network-online.target

[Service]
Type=simple
ExecStart={RUTA_GUION_CAMINO}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
FIN_UNIDAD
systemctl daemon-reload
systemctl enable --now {UNIDAD_CAMINO}
sleep 4
echo {marca_camino()}
"""


def linea_consola(guion):
    """La ÚNICA línea que se manda por la consola: el guion, en base64, a `sh`.

    En base64 porque la consola NO es un canal de datos fiable: se manda una línea
    sin heredocs, sin comillas y sin nada que el eco pueda romper. Y se decodifica en
    el equipo (`base64 -d | sh`) para que lo que se ejecute sea exactamente lo que se
    codificó aquí, sin que nadie lo reinterprete por el camino.
    """
    import base64 as modulo_base64

    codificado = modulo_base64.b64encode(guion.encode()).decode()
    return f"echo {codificado} | base64 -d | sh"


def marca_camino():
    """Lo que el guion imprime al final: la consola no devuelve código de salida, se
    reconoce el ECO. Sin marca, el motor no sabe si la línea se ejecutó."""
    return "NETLABS_CAMINO_PUESTO_42"


# ---------------------------------------------------------------------------
# Reservas DHCP derivadas: la MAC no se declara NUNCA (regla 14)
# ---------------------------------------------------------------------------

def reservas_derivadas(declaracion, identidad, invitado_servidor, en_red=None):
    """Las reservas que el servidor DHCP de `invitado_servidor` tiene que tener.

    Se DERIVAN: por cada OTRO invitado alcanzable por ese servidor que declare una
    dirección estática, una reserva con la MAC que el motor deriva de su vmid. Así
    ningún cliente dinámico puede robarle la dirección a un router o a un servidor.
    El propio servidor no se reserva a sí mismo.

    ¿Quién es «alcanzable por ese servidor»? Eso lo dice el ÁMBITO, y hay dos casos
    porque hay dos formas de declararlo:

      * `en_red` (un prefijo, p. ej. 10.41.1.0/24): el servidor DHCP de un RouterOS
        declara la RED que sirve, y su interfaz (ether2) no tiene por qué coincidir
        con la pata de gestión del invitado (`bridge:`). Se reserva a quien tenga una
        dirección declarada DENTRO de esa red. Ésta es la forma buena para un router.
      * sin `en_red`: el ámbito es el BRIDGE del propio invitado. Es el caso de un
        Linux que sirve la red del bridge en el que está (el puesto de control).

    Ámbito por bridge como respaldo de un router: sirve para no dejar las reservas
    vacías cuando no se declara `red`, y por eso se usa sólo entonces.
    """
    servidor = str(invitado_servidor.get("rol"))
    bridge = invitado_servidor.get("bridge")
    por_rol = {i["rol"]: i for i in identidad["invitados"]}
    reservas = []
    for otro in declaracion.get("invitados", []):
        if otro.get("rol") == servidor:
            continue
        direccion = str(otro.get("direccion") or "")
        if not direccion or direccion == "dhcp" or "/" not in direccion:
            continue
        if en_red:
            if not en_red_siendo(direccion, en_red):
                continue
        elif otro.get("bridge") != bridge:
            continue
        identidad_otro = por_rol.get(otro.get("rol"))
        if identidad_otro is None:
            continue
        reservas.append(
            {
                "rol": otro.get("rol"),
                "direccion": direccion,
                "mac": identidad_otro["mac"],
            }
        )
    return sorted(reservas, key=lambda r: r["direccion"])


def en_red_siendo(direccion, red):
    """¿Cae `direccion` (con máscara) dentro de la red `red`?

    Se comparan los OCTETOS que la máscara de `red` cubre, entero a entero: 10.41.1.7
    está en 10.41.1.0/24 porque los tres primeros octetos coinciden. Con prefijos que
    no caen en un octeto no se opina (devuelve False) en vez de hacer aritmética
    fina: un cálculo sutil aquí sería otra cosa que puede estar mal sin que nadie lo
    note, y los labs usan /16 y /24.
    """
    base, _, prefijo = str(red or "").partition("/")
    if not base or not prefijo:
        return False
    bits = int(prefijo)
    if bits % 8 != 0:
        return False
    cuantos = bits // 8
    izquierda = str(direccion).split("/")[0].split(".")
    derecha = base.split(".")
    return izquierda[:cuantos] == derecha[:cuantos]


# ---------------------------------------------------------------------------
# (declarado, leído) -> pasos del interior
# ---------------------------------------------------------------------------

def _paso(accion, invitado, area, operaciones, porque):
    """Un paso del interior. Sin `porque` no hay paso: un paso sin razón es un bug."""
    return {
        "accion": accion,
        "via": "interior",
        "rol": invitado.get("rol"),
        "escalon": invitado.get("escalon"),
        "metodo": None,
        "ruta": None,
        "parametros": {
            "area": area,
            "tipo": tipo_de(invitado),
            "operaciones": operaciones,
        },
        "porque": porque,
    }


def _identidad_canonica(declarado, leido):
    """Diferencia del área `identidad`: nombre del equipo y credenciales del motor.

    El valor DECLARADO del área es el nombre, tal cual (`identidad: rt-borde`): la
    declaración no envuelve en un mapa lo que ya es un dato.
    """
    operaciones = []
    esperado = str(declarado or "")
    actual = str((leido or {}).get("nombre") or "")
    if esperado and actual != esperado:
        operaciones.append({"op": "poner_identidad", "nombre": esperado})
    if not (leido or {}).get("usuario_motor"):
        operaciones.append({"op": "crear_usuario_motor"})
    if not (leido or {}).get("clave_motor"):
        operaciones.append({"op": "importar_clave_motor"})
    return operaciones


def _servicios_canonicos(declarado, leido):
    """Diferencia del área `servicios`, en los dos sentidos y dentro del alcance.

    Lo declarado se deshabilita; lo que el motor gestiona y NO se declara se
    habilita. Fuera del alcance (p. ej. `www`) el motor no opina.
    """
    deseados = set(str(s) for s in ((declarado or {}).get("deshabilitar") or []))
    apagados = set(str(s) for s in ((leido or {}).get("deshabilitados") or []))
    operaciones = []
    for servicio in sorted(deseados - apagados):
        operaciones.append({"op": "deshabilitar_servicio", "servicio": servicio})
    for servicio in sorted((apagados - deseados) & set(SERVICIOS_GESTIONADOS)):
        operaciones.append({"op": "habilitar_servicio", "servicio": servicio})
    return operaciones


def _cliente_dhcp_canonico(declarado, leido):
    """Diferencia del área `cliente_dhcp`: el de fábrica de un CHR recién nacido."""
    if (declarado or {}).get("deshabilitar") and (leido or {}).get("habilitado"):
        return [{"op": "deshabilitar_cliente_dhcp"}]
    return []


def _direcciones_canonicas(declarado, leido):
    """Diferencia del área `direcciones`. La dinámica con el mismo valor NO se toca
    aquí: no se puede borrar por la API (es de otro dueño) y por eso es RESIDUO, y
    el residuo se resuelve con `reiniciar_invitado` (§9.2, ADR 0007).

    Lo DECLARADO es la lista tal cual se escribe en el lab
    (`- {interfaz: ether2, direccion: 10.40.1.1/24}`); lo LEÍDO es lo que el driver
    saca del equipo, ya separado en `estaticas` y `dinamicas`.
    """
    deseadas = {
        (str(d.get("interfaz")), str(d.get("direccion"))) for d in (declarado or [])
    }
    actuales = {
        (str(d.get("interfaz")), str(d.get("direccion")))
        for d in ((leido or {}).get("estaticas") or [])
    }
    operaciones = []
    for interfaz, direccion in sorted(deseadas - actuales):
        operaciones.append({"op": "poner_direccion", "interfaz": interfaz, "direccion": direccion})
    for interfaz, direccion in sorted(actuales - deseadas):
        operaciones.append({"op": "quitar_direccion", "interfaz": interfaz, "direccion": direccion})
    return operaciones


def _rutas_canonicas(declarado, leido):
    """Diferencia del área `rutas`: sólo las ESTÁTICAS. Las conectadas las pone el
    sistema y la dinámica del DHCP es residuo (`reiniciar_invitado`).

    Lo DECLARADO es la lista tal cual (`- {destino, pasarela}`); lo LEÍDO, lo que el
    driver saca del equipo.
    """
    deseadas = {
        (str(r.get("destino")), str(r.get("pasarela"))) for r in (declarado or [])
    }
    actuales = {
        (str(r.get("destino")), str(r.get("pasarela")))
        for r in ((leido or {}).get("estaticas") or [])
    }
    operaciones = []
    for destino, pasarela in sorted(deseadas - actuales):
        operaciones.append({"op": "poner_ruta", "destino": destino, "pasarela": pasarela})
    for destino, pasarela in sorted(actuales - deseadas):
        operaciones.append({"op": "quitar_ruta", "destino": destino, "pasarela": pasarela})
    return operaciones


def _red_normalizada(red):
    """La red DHCP declarada, en la forma en que se compara con lo leído.

    Se normalizan los tres campos que importan (prefijo, pasarela y DNS) y se ordena
    la lista de DNS: comparar dos listas de DNS en distinto orden y llamarlo cambio
    haría que la segunda ejecución escribiera sin que nada hubiera cambiado.
    """
    red = red or {}
    return {
        "prefijo": str(red.get("prefijo") or ""),
        "pasarela": str(red.get("pasarela") or ""),
        "dns": sorted(str(d) for d in (red.get("dns") or [])),
    }


def _dhcp_canonico(declarado, leido, declaracion, identidad, invitado):
    """Diferencia del área `dhcp` de un RouterOS: red, servidor, pool y reservas.

    Las reservas se comparan por MAC: la dirección que reserva el router tiene que
    ser la que el motor DERIVA del vmid del invitado (regla 14). Una reserva con la
    MAC equivocada se quita: dentro del área, lo que no está declarado sale.

    Cada servidor declarado tiene SU ámbito (`red.prefijo`), así que sus reservas se
    derivan una a una: un router con dos LANs no puede reservar en la primera lo que
    vive en la segunda.
    """
    operaciones = []
    for declarado_servidor in declarado or []:
        interfaz = str(declarado_servidor.get("interfaz"))
        encontrado = None
        for candidato in (leido or {}).get("servidores") or []:
            if str(candidato.get("interfaz")) == interfaz:
                encontrado = candidato
                break
        rango = str((declarado_servidor.get("pool") or {}).get("rango") or "")
        if encontrado is None:
            operaciones.append({"op": "poner_servidor_dhcp", "interfaz": interfaz, "rango": rango})
        elif str(encontrado.get("rango") or "") != rango:
            operaciones.append({"op": "poner_servidor_dhcp", "interfaz": interfaz, "rango": rango})
        red = declarado_servidor.get("red") or {}
        if red and _red_normalizada(red) != _red_normalizada((encontrado or {}).get("red")):
            # Se compara con lo LEÍDO, no se escribe por si acaso: reescribir la red en
            # cada ejecución rompería la idempotencia (y mentiría sobre `changed=0`).
            normalizada = _red_normalizada(red)
            operaciones.append(
                {
                    "op": "poner_red_dhcp",
                    "prefijo": normalizada["prefijo"],
                    "pasarela": normalizada["pasarela"],
                    "dns": normalizada["dns"],
                }
            )
        # Las reservas de ESTE servidor: su ámbito es la RED que sirve (`red.prefijo`)
        # y, si no la declara, el bridge en el que vive el invitado.
        reservas = reservas_derivadas(
            declaracion, identidad, invitado, en_red=red.get("prefijo")
        )
        deseadas = {str(r["mac"]).upper(): str(r["direccion"]) for r in reservas}
        actuales = {
            str(r.get("mac")).upper(): str(r.get("direccion"))
            for r in ((leido or {}).get("reservas") or [])
        }
        for mac, direccion in sorted(deseadas.items()):
            if actuales.get(mac) != direccion:
                operaciones.append({"op": "poner_reserva", "mac": mac, "direccion": direccion})
        for mac in sorted(set(actuales) - set(deseadas)):
            operaciones.append({"op": "quitar_reserva", "mac": mac})

    # Las interfaces con DHCP que ya no se declaran: se quitan (dentro del área, lo
    # que no está declarado sale).
    declaradas = {str(s.get("interfaz")) for s in (declarado or [])}
    for candidato in (leido or {}).get("servidores") or []:
        if str(candidato.get("interfaz")) not in declaradas:
            operaciones.append(
                {"op": "quitar_servidor_dhcp", "interfaz": str(candidato.get("interfaz"))}
            )
    return operaciones


def _direccion_linux_canonica(declarado, leido):
    """Diferencia del área `direccion` de un Linux.

    `direccion: dhcp` no se escribe: se COMPRUEBA (§6.3). Por eso aquí no hay
    operaciones, y la comprobación de que la concesión está dentro del rango
    declarado la hace `verify`, que sí mira la tabla de concesiones.
    """
    if not declarado or str(declarado) == "dhcp":
        return []
    operaciones = []
    if str((leido or {}).get("direccion") or "") != str(declarado):
        operaciones.append(
            {"op": "poner_direccion", "interfaz": "eth0", "direccion": str(declarado)}
        )
    return operaciones


def _reenvio_canonico(declarado, leido):
    """Diferencia del área `reenvio`: `ip_forward` (lo necesita el servidor DHCP)."""
    if declarado and not (leido or {}).get("activo"):
        return [{"op": "activar_reenvio"}]
    return []


def _dhcp_servidor_canonico(declarado, leido, declaracion, identidad, invitado):
    """Diferencia del área `dhcp_servidor` de un Linux: dnsmasq, reservas y el
    apagado del offload del checksum, sin el cual las ofertas DHCP salen rotas y el
    kernel del CHR las tira (medido en v3, y sigue siendo cierto).

    El ámbito de sus reservas es el bridge en el que vive el invitado: un Linux sirve
    la red del bridge al que está colgado, que es justo donde están los demás.
    """
    if not declarado:
        return []
    reservas = reservas_derivadas(declaracion, identidad, invitado)
    operaciones = []
    interfaz = str(declarado.get("interfaz") or "")
    rango = str(declarado.get("rango") or "")
    actual = leido or {}
    # `hay_que_recargar` es lo que decide si dnsmasq se toca: no basta con que el
    # servicio esté vivo, porque un cambio de reservas no entra en vigor hasta que
    # dnsmasq vuelve a leer su configuración.
    hay_que_recargar = False
    if str(actual.get("interfaz") or "") != interfaz or str(actual.get("rango") or "") != rango:
        operaciones.append({"op": "escribir_dnsmasq", "interfaz": interfaz, "rango": rango})
        hay_que_recargar = True
    if not actual.get("offload_apagado"):
        # Sin esto las ofertas DHCP salen con el checksum sin resolver y el kernel del
        # CHR las tira (medido en v3 y comprobado en esta fase): el laboratorio entero
        # depende de esta línea.
        operaciones.append({"op": "apagar_offload", "interfaz": interfaz})
        hay_que_recargar = True
    deseadas = {str(r["mac"]).upper(): str(r["direccion"]) for r in reservas}
    actuales = {
        str(r.get("mac")).upper(): str(r.get("direccion"))
        for r in (actual.get("reservas") or [])
    }
    for mac, direccion in sorted(deseadas.items()):
        if actuales.get(mac) != direccion:
            operaciones.append({"op": "poner_reserva", "mac": mac, "direccion": direccion})
            hay_que_recargar = True
    for mac in sorted(set(actuales) - set(deseadas)):
        operaciones.append({"op": "quitar_reserva", "mac": mac})
        hay_que_recargar = True
    if hay_que_recargar or not actual.get("servicio_activo"):
        operaciones.append({"op": "recargar_dnsmasq"})
    return operaciones


def _camino_canonico(declarado, leido):
    """Diferencia del área `camino`. Lo ESCRIBE la consola, una sola vez por vida del
    invitado: aquí sólo se decide si hay que volver a mandar la línea."""
    if declarado is None:
        return []
    if (leido or {}).get("salida"):
        return []
    return [{"op": "mandar_linea_consola"}]


def residuo_dinamico(leido):
    """¿Queda residuo del cliente DHCP de fábrica? -> (sí/no, motivo).

    Medido (v3, y se vuelve a medir en esta fase): la dirección y la ruta que
    instala el cliente de fábrica NO se pueden borrar por la API («created by a
    different owner»). Si están, el plan declara un `reiniciar_invitado` y lo
    explica; no se esconde en un `command` con `ignore_errors`.
    """
    residuo = (leido or {}).get("residuo") or {}
    motivos = []
    if residuo.get("direccion_dinamica"):
        motivos.append("la dirección dinámica del cliente de fábrica sigue puesta")
    if residuo.get("ruta_dinamica"):
        motivos.append("la ruta por defecto dinámica del cliente de fábrica sigue puesta")
    return (bool(motivos), "; ".join(motivos))


def pasos_de_convergencia(invitado, identidad, declaracion, leido, parametros):
    """(declarado, leído) -> pasos del interior de ESTE invitado, en orden.

    `identidad` es el mapa del LAB entero (no la identidad de este invitado): las
    reservas DHCP del servidor de un bridge se derivan de las direcciones estáticas
    de LOS DEMÁS invitados de ese bridge, así que sin la identidad completa no se
    pueden calcular. Se pasa entera y no se recorta: un mapa recortado da reservas
    vacías y una convergencia que dice que ha ido bien sin haber reservado nada.

    Dos formas, y la diferencia importa:

      * SIN lectura (`leido` vacío), la forma GRUESA: un paso por área declarada.
        Es lo que puede imprimir un `plan` sin credenciales, contra un clúster
        simulado donde no hay nada dentro que leer.
      * CON lectura, la forma EXACTA: sólo las áreas que de verdad cambian algo.
        Un área que ya coincide no genera paso: por eso la segunda ejecución sale
        `changed=0` con los diarios llenos de lecturas.
    """
    tipo = tipo_de(invitado)
    if tipo is None:
        return []
    rol = invitado.get("rol")
    declaradas = areas_de(invitado)

    if not leido:
        return [
            _paso(
                "converger_interior",
                invitado,
                area,
                [],
                f"el rol '{rol}' es un interior de tipo {tipo} y el plan no ha leído "
                "dentro (sin credenciales): se converge el área entera",
            )
            for area in declaradas
        ]

    if not leido.get("alcanzable"):
        raise ErrorMotor(
            f"el invitado '{rol}' tiene interior declarado ({tipo}) y no se puede "
            f"alcanzar para convergerlo: {leido.get('motivo') or 'sin camino'}. "
            "El verbo para aquí en vez de seguir a ciegas."
        )

    areas_leidas = leido.get("areas") or {}

    # La identidad de un RouterOS va la ÚLTIMA en la primera convergencia: primero
    # se añade y se verifica lo nuevo, y sólo entonces se cambia el equipo por
    # dentro. Si se cambiara antes, un fallo a mitad dejaría el equipo accesible con
    # las credenciales viejas y sin camino de vuelta para el motor.
    #
    # «Primera convergencia» no se adivina por la forma del mapa leído: se decide con
    # lo que las operaciones dicen. Si la identidad no tiene nada que cambiar, no hay
    # paso de identidad y el orden da igual.
    operaciones_identidad = (
        _identidad_canonica(declaradas["identidad"], areas_leidas.get("identidad"))
        if "identidad" in declaradas
        else None
    )
    orden = list(declaradas.keys())
    if tipo == "routeros" and operaciones_identidad:
        orden.remove("identidad")
        orden.append("identidad")

    pasos = []
    for area in orden:
        actual = areas_leidas.get(area)
        if area == "identidad":
            operaciones = operaciones_identidad or []
        elif area == "servicios":
            operaciones = _servicios_canonicos(declaradas[area], actual)
        elif area == "cliente_dhcp":
            operaciones = _cliente_dhcp_canonico(declaradas[area], actual)
        elif area == "direcciones":
            operaciones = _direcciones_canonicas(declaradas[area], actual)
        elif area == "rutas":
            operaciones = _rutas_canonicas(declaradas[area], actual)
        elif area == "dhcp":
            operaciones = _dhcp_canonico(declaradas[area], actual, declaracion, identidad, invitado)
        elif area == "direccion":
            operaciones = _direccion_linux_canonica(declaradas[area], actual)
        elif area == "reenvio":
            operaciones = _reenvio_canonico(declaradas[area], actual)
        elif area == "dhcp_servidor":
            operaciones = _dhcp_servidor_canonico(
                declaradas[area], actual, declaracion, identidad, invitado
            )
        elif area == "camino":
            operaciones = _camino_canonico(declaradas[area], actual)
        else:  # pragma: no cover - el validador ya rechaza lo que no está en AREAS
            raise ErrorMotor(f"el área '{area}' no tiene driver: añadirla es un ADR")

        if not isinstance(actual, dict):
            # Área declarada y NO leída. No se escribe a ciegas ni se da por buena:
            # sin lectura no se puede afirmar si coincide, y escribir «por si acaso»
            # rompería la idempotencia (la segunda ejecución volvería a escribir).
            # El driver tiene que leer TODAS las áreas declaradas: si falta una, el
            # verbo para y lo dice.
            raise ErrorMotor(
                f"el driver no leyó el área '{area}' del rol '{rol}' ({tipo}): sin "
                "lectura no se puede decir si coincide con lo declarado"
            )
        if operaciones:
            pasos.append(
                _paso(
                    "converger_interior",
                    invitado,
                    area,
                    operaciones,
                    f"el área '{area}' del rol '{rol}' ({tipo}) no coincide con lo "
                    f"declarado ({len(operaciones)} operación/es)",
                )
            )

    hay_residuo, motivo = residuo_dinamico(leido)
    if hay_residuo:
        pasos.append(
            {
                "accion": "reiniciar_invitado",
                "via": "api",
                "rol": rol,
                "escalon": invitado.get("escalon"),
                "metodo": "POST",
                "ruta": None,  # el plan la completa con el nodo y el vmid
                "parametros": {"reinicio": "residuo del cliente DHCP de fábrica"},
                "porque": (
                    f"el rol '{rol}' conserva residuo del cliente DHCP de fábrica y la "
                    f"API no puede borrarlo ({motivo}): se reinicia UNA vez y el "
                    "residuo se va con el arranque (declarado en el plan, no escondido)"
                ),
            }
        )
    return pasos


def espera_de_servicio(invitado):
    """El paso que comprueba que un escalón SIRVE de verdad antes de pasar al
    siguiente (regla 18: nunca se arranca un escalón antes de que el anterior esté
    convergido y sirviendo).

    No es un `wait_for` sobre el invitado: es una petición a la dirección que la
    declaración promete, en el puerto por el que ese tipo se deja ver (el REST de
    RouterOS, el sshd de un Linux). No necesita identidad: la sonda va a la
    dirección declarada, que es lo que la declaración promete.
    """
    tipo = tipo_de(invitado)
    if tipo is None:
        return None
    puerto = 80 if tipo == "routeros" else 22
    return {
        "accion": "esperar_servicio",
        "via": "sonda",
        "rol": invitado.get("rol"),
        "escalon": invitado.get("escalon"),
        "metodo": None,
        "ruta": None,
        "parametros": {
            "tipo": tipo,
            "direccion": str(invitado.get("direccion") or "").split("/")[0],
            "puerto": puerto,
        },
        "porque": (
            f"el rol '{invitado['rol']}' pertenece al escalón {invitado.get('escalon')}: "
            f"el siguiente escalón no se toca hasta que este conteste en el puerto {puerto}"
        ),
    }


class FilterModule:
    """El módulo, visto desde Ansible.

    Ansible carga TODO `.py` de `filter_plugins/` como un plugin de filtros y exige
    esta clase: sin ella avisa «no attribute 'FilterModule'» y salta el fichero. Así
    que la clase existe, y de paso es la frontera honesta entre lo puro y el
    playbook: los playbooks NO llevan lógica, llaman a estas funciones.

    No se registran los ayudantes privados (`_…`): lo que no se puede probar como
    función pura desde una tarea es que no debería llamarse desde una tarea.
    """

    def filters(self):
        return {
            "interior_tipo": tipo_de,
            "interior_areas": areas_de,
            "interior_areas_a_leer": areas_a_leer,
            "interior_declara": declara_interior,
            "interior_tiene_camino": tiene_camino,
            "interior_direccion_libre": direccion_libre,
            "interior_patas": patas_del_puesto_control,
            "interior_puerto_camino": puerto_camino,
            "interior_guion_camino": guion_camino,
            "interior_linea_consola": linea_consola,
            "interior_marca_camino": marca_camino,
            "interior_reservas": reservas_derivadas,
            "interior_residuo": residuo_dinamico,
            "interior_pasos": pasos_de_convergencia,
            "interior_espera": espera_de_servicio,
        }
