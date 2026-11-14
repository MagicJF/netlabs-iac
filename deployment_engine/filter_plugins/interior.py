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

# Las dos acciones del camino, con nombre propio: el plan las nombra y el ejecutor
# las despacha, y una cadena suelta en dos sitios es una cadena que se separa.
ACCION_CAMINO = "construir_camino"
ACCION_COMPROBAR_CAMINO = "comprobar_camino"
ACCION_INTERIOR = "converger_interior"


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

    **El ORDEN es el orden de `eth0, eth1, ...` dentro del invitado**, y por eso no es
    libre: primero las patas del LAB (la del bridge que el invitado declara la primera,
    porque es la que la declaración llama `eth0` en sus áreas --el servidor DHCP del
    puesto sirve por `eth0`--) y **la pata del bridge de gestión del NODO la ÚLTIMA**.
    Así el nombre de interfaz que escribe el lab sigue significando lo mismo en
    cualquier nodo, y el valor de entorno (qué bridge da salida) no se filtra a la
    declaración.

      * Una pata por cada bridge del LAB. La del bridge que el invitado declara lleva
        su dirección DECLARADA (la gestión no puede depender de los routers que está
        desplegando); las demás las elige el motor por arriba, esquivando las
        direcciones que el lab declara y las que están en uso.
      * La ÚLTIMA pata va en el bridge de gestión del NODO (valor de entorno, no del
        lab): es por donde el puesto sale hacia casa, y es la única que lleva PUERTA
        (la dirección que el nodo tiene en ese bridge). Su dirección la elige el motor
        de entre las libres, leyendo las que ya usa cada invitado del nodo.

    Si el invitado declara camino y no hay bridge de gestión, esto **falla**: un puesto
    de control sin salida es un lab que no se puede converger, y decirlo es más útil
    que crear el invitado y descubrirlo tres pasos después.
    """
    puente_gestion = str(parametros.get("bridge_gestion") or "")
    direcciones_bridge = estado.get("bridges_direcciones") or {}
    usadas = estado.get("direcciones_usadas") or []
    if not puente_gestion:
        raise ErrorMotor(
            f"el invitado {invitado.get('rol')} declara camino y el motor no sabe por "
            "dónde da salida este nodo: falta `pve_bridge_gestion` en secrets.yml "
            "(el bridge del nodo con dirección y salida, hoy `vmbr1`)"
        )

    patas = []
    # Las direcciones que el lab declara en un bridge: ninguna pata de gestión puede
    # caer encima de un router o de un servidor que el lab ya ha reservado.
    declaradas_por_bridge = {}
    for otro in declaracion.get("invitados", []):
        direccion = str(otro.get("direccion") or "")
        if direccion and direccion != "dhcp" and "/" in direccion:
            declaradas_por_bridge.setdefault(otro.get("bridge"), []).append(direccion)

    # La pata DECLARADA va la primera: es `eth0` para el invitado, y así lo que el lab
    # declara en sus áreas (`dhcp_servidor: interfaz: eth0`) dice lo mismo en cualquier
    # nodo. Es la única cuya dirección no decide el motor.
    if invitado.get("bridge") and invitado.get("direccion"):
        patas.append(
            {
                "bridge": invitado["bridge"],
                "direccion": invitado["direccion"],
                "puerta": "",
                "papel": "pata declarada del puesto de control",
            }
        )
    for bridge in declaracion.get("bridges", []):
        nombre = bridge.get("nombre")
        if not nombre or nombre == invitado.get("bridge"):
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

    # Y la ÚLTIMA, la salida: el bridge de gestión del nodo, con su puerta.
    subred = str(direcciones_bridge.get(puente_gestion) or "")
    if not subred:
        raise ErrorMotor(
            f"el bridge de gestión `{puente_gestion}` no tiene dirección en este nodo: "
            "sin dirección no hay puerta por la que salir hacia casa"
        )
    usadas_salida = list(usadas) + [
        p["direccion"] for p in patas if p.get("direccion")
    ]
    direccion = direccion_libre(subred, usadas_salida)
    patas.append(
        {
            "bridge": puente_gestion,
            "direccion": f"{direccion}/{subred.split('/')[1]}",
            # La puerta de la pata de gestión es la dirección que el NODO tiene en ese
            # bridge (10.10.10.1 en vmbr1): por ahí sale hacia casa. No es un valor del
            # lab: se lee de la red del nodo.
            "puerta": subred.split("/")[0],
            "papel": "salida hacia casa",
        }
    )
    return patas
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


def marca_camino(_entrada=None):
    """Lo que el guion imprime al final: la consola no devuelve código de salida, se
    reconoce el ECO. Sin marca, el motor no sabe si la línea se ejecutó.

    Recibe un argumento que IGNORA porque se usa como filtro de Ansible
    (`'' | interior_marca_camino`): un filtro siempre recibe lo de su izquierda. El
    valor de la marca no depende de nada: es una constante que el guion y el motor
    tienen que decir igual, y por eso vive en un solo sitio (aquí).
    """
    return "NETLABS_CAMINO_PUESTO_42"


def camino_responde(estado):
    """¿El túnel del camino está en pie, según lo último que el motor comprobó?

    Se lee del ESTADO (que lo trae una lectura: el puerto reenviado del nodo de
    control contesta o no), no de una marca que el motor se hubiera dejado: una
    marca se queda pegada cuando el puesto se reinicia, y un puerto que no contesta
    no se puede fingir. Ausente = no responde: en un clúster simulado (un `plan` sin
    credenciales) no hay camino, y el plan lo dice.
    """
    return bool((estado or {}).get("camino", {}).get("responde"))


def pasos_del_camino(invitado, declaracion, estado, parametros):
    """Los pasos del CAMINO de este invitado (el puesto de control), en orden.

    El camino es lo que hace ENTRAR a Ansible en la red del lab, así que va antes de
    converger nada: sin él no se llega a ningún invitado. Tiene dos mitades:

      1. `construir_camino` -- el arranque: el motor deja su clave pública dentro del
         invitado (al crear, por API), escribe UNA línea en su propio
         `authorized_keys` con `restrict,port-forwarding,permitlisten=<puerto>`, y
         manda por la consola UNA línea en base64 que levanta el túnel hacia casa.
      2. `comprobar_camino` -- la prueba de punta a punta: que el puerto reenviado del
         nodo de control conteste. Eso demuestra la cadena entera (casa -> 443 ->
         puesto -> vuelta), no una parte.

    Si el camino YA responde, la mitad 1 no se emite: reconstruir un túnel que
    funciona en cada `apply` sería justo el error que este plan viene a evitar. La
    comprobación se emite siempre: es una LECTURA, y `apply` tiene que poder decir
    que el camino está en pie ahora, no que lo estuvo.

    La clave privada del camino NO viaja en el paso: el plan no lleva secretos. El
    paso lleva lo que hay que hacer (dónde, en qué puerto, hacia quién) y el guion se
    arma al ejecutarlo, con la clave que el motor lee de su propio `~/.ssh`.
    """
    if not tiene_camino(invitado):
        return []

    declarado = (invitado.get("config") or {}).get("linux") or {}
    salida = (declarado.get(CLAVE_CAMINO) or {}).get("salida") or {}
    puerto_local = puerto_camino(invitado["vmid"], parametros)
    host_salida = str(salida.get("host") or parametros.get("camino_host") or "")
    puerto_salida = int(salida.get("puerto") or parametros.get("camino_puerto") or 443)

    pasos = []
    if not camino_responde(estado):
        patas = patas_del_puesto_control(invitado, declaracion, estado, parametros)
        pasos.append(
            {
                "accion": ACCION_CAMINO,
                "via": "camino",
                "rol": invitado.get("rol"),
                "escalon": invitado.get("escalon"),
                "metodo": None,
                "ruta": None,
                "parametros": {
                    "vmid": invitado["vmid"],
                    "puerto": puerto_local,
                    "salida_host": host_salida,
                    "salida_puerto": puerto_salida,
                    "patas": [
                        {"bridge": pata["bridge"], "direccion": pata["direccion"]} for pata in patas
                    ],
                },
                "detalle": [
                    "la clave pública del motor se deja en el invitado al CREARLO (ssh-public-keys):",
                    "  por ahí entra Ansible, y sin eso no habría forma de llegar a configurarlo",
                    f"en casa se añade UNA línea a authorized_keys con restrict,port-forwarding,"
                    f"permitlisten=\"{puerto_local}\" (la clave del camino no da shell, sólo el reenvío)",
                    f"por la consola del invitado se manda UNA línea (base64) que levanta "
                    f"ssh -R {puerto_local}:127.0.0.1:22 hacia {host_salida}:{puerto_salida}",
                    "la consola no devuelve código de salida: el guion termina imprimiendo una MARCA "
                    "y el motor la busca en el eco",
                ],
                "porque": (
                    f"el rol '{invitado['rol']}' es el puesto de control de este lab: hasta que su "
                    f"túnel no esté en pie no se puede entrar en ningún invitado, así que va antes "
                    f"de converger nada"
                ),
            }
        )

    pasos.append(
        {
            "accion": ACCION_COMPROBAR_CAMINO,
            "via": "camino",
            "rol": invitado.get("rol"),
            "escalon": invitado.get("escalon"),
            "metodo": None,
            "ruta": None,
            "parametros": {
                "puerto": puerto_local,
                "salida_host": host_salida,
                "salida_puerto": puerto_salida,
                "vmid": invitado["vmid"],
            },
            "porque": (
                f"comprueba la cadena entera: si el puerto {puerto_local} del nodo de control "
                f"contesta, el camino casa -> {host_salida}:{puerto_salida} -> puesto -> vuelta funciona"
            ),
        }
    )
    return pasos


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
    herramientas = actual.get("herramientas") or {}
    faltan = [h for h in ("dnsmasq", "ethtool") if not herramientas.get(h, True)]
    if faltan:
        # Va PRIMERO: sin dnsmasq no hay servidor DHCP, y sin ethtool no hay forma de
        # apagar los offloads. Si el invitado es tan viejo que no sabemos qué tiene
        # (no se pudo leer nada), no se instala: se escribe y se deja que el fallo
        # hable. Instalar a ciegas es cambiar un equipo por si acaso.
        operaciones.append({"op": "instalar_herramientas", "paquetes": faltan})
    if str(actual.get("interfaz") or "") != interfaz or str(actual.get("rango") or "") != rango:
        operaciones.append({"op": "escribir_dnsmasq", "interfaz": interfaz, "rango": rango})
        hay_que_recargar = True
    if not actual.get("offload_apagado"):
        # Sin esto las ofertas DHCP salen con el checksum sin resolver y el kernel del
        # CHR las tira (medido en v3 y comprobado en esta fase): el laboratorio entero
        # depende de esta línea.
        operaciones.append({"op": "apagar_offload", "interfaz": interfaz})
        hay_que_recargar = True
    # Sin el prefijo: la reserva vive DENTRO del rango del bridge (eso ya lo valida la
    # declaración) y dnsmasq guarda la dirección pelada. Comparar con el prefijo haría que
    # las reservas nunca cuadraran y el fichero se reescribiera en cada pasada.
    deseadas = {str(r["mac"]).upper(): str(r["direccion"]) for r in reservas}
    actuales = {
        str(r.get("mac")).upper(): str(r.get("direccion")).split("/")[0]
        for r in (actual.get("reservas") or [])
    }
    for mac, direccion in sorted(deseadas.items()):
        # Se compara por DIRECCIÓN: la derivada lleva su prefijo y dnsmasq guarda la
        # dirección pelada. La operación sí lleva el valor derivado entero, que es el que
        # manda al fichero (la comparación es lo único que se normaliza).
        if actuales.get(mac) != direccion.split("/")[0]:
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
        # La forma GRUESA: UN paso por invitado. Un paso por área repetiría la misma
        # frase N veces para el mismo equipo y contaría como trabajo lo que es UNA sola
        # conversación con él: el plan es una explicación, y una que se repite no explica.
        # Las áreas declaradas van en el `porque` (informan, que es lo que se puede hacer
        # sin leer) pero NO como operaciones: sin lectura no se puede afirmar qué cambia,
        # y enseñar operaciones sería prometer un cambio que nadie ha comprobado.
        areas = ", ".join(sorted(declaradas))
        return [
            _paso(
                "converger_interior",
                invitado,
                # No es un área suelta (no se ha leído ninguna): es el invitado entero.
                None,
                [],
                f"el rol '{rol}' es un interior de tipo {tipo} y el plan no ha leído "
                f"dentro (sin credenciales): se converge el invitado entero, área por "
                f"área ({areas})",
            )
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


# ---------------------------------------------------------------------------
# (declaración) -> el puesto de control; y las LECTURAS y ESCRITURAS de un Linux
# ---------------------------------------------------------------------------

def puesto_control(declaracion):
    """El ROL del invitado que es el puesto de control del lab (el bastión del camino).

    No se pregunta por un nombre ni por un vmid: se pregunta quién declara `camino`,
    que es lo que hace que un invitado sea el que sale hacia casa. Devuelve '' si el
    lab no declara ninguno, y entonces `apply` dice que no hay por dónde entrar (regla
    16) en vez de intentarlo.
    """
    # La declaración que circula por el motor está NORMALIZADA: sus invitados son una
    # lista plana (`invitados`), cada uno con su `tipo`. Se lee igual que en el resto de
    # este fichero -- una sola forma de leer la declaración, o hay dos verdades.
    for invitado in (declaracion or {}).get("invitados") or []:
        if tiene_camino(invitado):
            return invitado.get("rol") or ""
    return ""


# Las lecturas, una por área, y el porqué de cada comando. Van aquí (y no en el
# playbook) porque son DATOS: el driver no decide qué preguntar, lo lee de aquí.
#
# Todas son de SOLO LECTURA y baratas: una vuelta de SSH por área, con el camino.
# Ninguna necesita `root` para preguntar, pero se entra como root porque para
# ESCRIBIR sí hace falta, y usar dos usuarios distintos según el paso sería una
# complicación sin premio.
LECTURAS_LINUX = {
    "direccion": {
        "comando": "ip -4 -o addr show dev eth0",
        "descripcion": "la dirección de su pata en el bridge del lab",
    },
    "reenvio": {
        "comando": "cat /proc/sys/net/ipv4/ip_forward",
        "descripcion": "si el equipo reenvía paquetes (lo necesita su servidor DHCP)",
    },
    "camino": {
        "comando": "systemctl is-active netlabs-camino",
        "descripcion": "si la salida hacia casa está levantada",
    },
    "dhcp_servidor": {
        # CUATRO cosas en un viaje, separadas por una marca que el analizador conoce:
        #   1) la configuración que el motor dejó (si la dejó),
        #   2) el estado REAL de los offloads de la interfaz,
        #   3) qué herramientas hay,
        #   4) si el servicio está VIVO (sin esto, `recargar` se pediría en cada pasada).
        # Sin la 2 no se puede decidir si hay que apagarlos, y sin apagarlos las
        # ofertas DHCP salen rotas y el CHR las tira (medido en v3; en esta fase se
        # vuelve a medir). Sin la 3 no se sabe si hay que instalarlas.
        "comando": "cat /etc/dnsmasq.d/netlabs.conf 2>/dev/null; echo ---NETLABS---; ethtool -k eth0 2>/dev/null; echo ---NETLABS---; for h in dnsmasq ethtool; do printf '%s=%s\\n' \"$h\" \"$(command -v $h || echo NO)\"; done; echo ---NETLABS---; systemctl is-active dnsmasq 2>/dev/null || echo inactive",
        "descripcion": "su configuración de DHCP, los offloads de su interfaz y las herramientas",
    },
    "claves": {
        "comando": "cat /root/.ssh/authorized_keys 2>/dev/null | wc -l",
        "descripcion": "cuántas claves autorizadas tiene (la del motor se deja al crear)",
    },
}

SEPARADOR = "---NETLABS---"


def lecturas_linux(invitado):
    """Las lecturas que hay que hacer dentro de un Linux, en orden, por área declarada.

    Sólo se pregunta por lo que el lab DECLARA: fuera de las áreas declaradas el motor
    no opina (regla 17), así que tampoco pregunta.
    """
    return [
        {
            "area": area,
            "accion": "leer",
            "comando": LECTURAS_LINUX[area]["comando"],
            "descripcion": LECTURAS_LINUX[area]["descripcion"],
        }
        for area in areas_a_leer(invitado)
        if area in LECTURAS_LINUX
    ]


def _lineas(texto):
    return [l.strip() for l in str(texto or "").splitlines() if l.strip()]


def _valor(lineas, clave, prefijo=""):
    """El valor de una línea `clave=valor` (o `clave: valor`), o '' si no está."""
    for linea in lineas:
        if linea.startswith(prefijo + clave):
            return linea.split("=", 1)[1].strip() if "=" in linea else linea.split(":", 1)[1].strip()
    return ""


def leido_linux(lecturas):
    """(lo que devolvió el invitado) -> el mapa `leído` que comen las diferencias.

    Función PURA: recibe `[{area, encontrado, rc}]` y devuelve `{area: {...}}` en la
    forma canónica que espera `pasos_de_convergencia`. Un `rc != 0` es AVERÍA, no
    estado: se marca como no leído (el área aparecerá como «no coincide» y el driver
    lo dirá al aplicarlo), en vez de inventar un estado falso.
    """
    leido = {}
    for lectura in lecturas or []:
        area = lectura.get("area")
        texto = lectura.get("encontrado") or ""
        if int(lectura.get("rc") or 0) != 0:
            continue
        lineas = _lineas(texto)

        if area == "direccion":
            partes = lineas[0].split() if lineas else []
            # `ip -4 -o addr show dev eth0` -> "3: eth0    inet 10.40.0.10/24 ..."
            direccion = partes[3] if len(partes) > 3 else ""
            leido["direccion"] = {"direccion": direccion}

        elif area == "reenvio":
            leido["reenvio"] = {"activo": (lineas[0] if lineas else "") == "1"}

        elif area == "camino":
            leido["camino"] = {"salida": (lineas[0] if lineas else "") == "active"}

        elif area == "claves":
            try:
                leido["claves"] = {"cuantas": int(lineas[0])} if lineas else {"cuantas": 0}
            except ValueError:
                leido["claves"] = {"cuantas": 0}

        elif area == "dhcp_servidor":
            bloques = str(texto).split(SEPARADOR)
            configuracion = _lineas(bloques[0] if bloques else "")
            offloads = bloques[1] if len(bloques) > 1 else ""
            herramientas = _lineas(bloques[2] if len(bloques) > 2 else "")
            # Los offloads que importan, tal y como los llama el kernel: si alguno
            # está en `on`, las ofertas DHCP pueden salir rotas.
            apagado = bool(offloads) and all(
                f"{nombre}: off" in offloads
                for nombre in ("tx-checksumming", "generic-segmentation-offload",
                               "tcp-segmentation-offload")
            )
            tiene = {herramienta: (_valor(herramientas, herramienta) != "NO")
                     for herramienta in ("dnsmasq", "ethtool")}
            # Las reservas que el fichero tiene AHORA, para compararlas una a una con las
            # derivadas: si falta una se pone, y si sobra se quita (los dos sentidos).
            reservas = []
            for linea in configuracion:
                if linea.startswith("dhcp-host="):
                    partes = linea[len("dhcp-host="):].split(",")
                    if len(partes) >= 2:
                        reservas.append({"mac": partes[0], "direccion": partes[1]})
            # El servicio: sin esto el motor no sabe si dnsmasq está vivo, y `recargar` se pediría
            # en CADA pasada -- que es exactamente romper la idempotencia.
            servicio = _lineas(bloques[3] if len(bloques) > 3 else "")
            leido["dhcp_servidor"] = {
                "reservas": reservas,
                "servicio_activo": bool(servicio) and servicio[0] == "active",
                "interfaz": _valor(configuracion, "interface", prefijo="").lstrip(),
                # dnsmasq escribe el rango como `inicio,fin,mascara,tiempo`; la
                # declaración lo escribe `inicio-fin`. Se normaliza AQUÍ para poder
                # comparar: sin esto el fichero se reescribiría en cada pasada y la
                # segunda ejecución dejaría de ser `changed=0` (regla 6).
                "rango": "-".join(_valor(configuracion, "dhcp-range").split(",")[:2]),
                "configurado": bool(configuracion),
                "offload_apagado": apagado,
                "herramientas": tiene,
                "conf": (bloques[0].strip() if bloques else ""),
            }
    return leido


def _b64(texto):
    import base64
    return base64.b64encode(str(texto).encode("utf-8")).decode("ascii")


def configuracion_dnsmasq(declarado, reservas):
    """El fichero de configuración del servidor DHCP, tal cual se escribe en el invitado.

    `port=0` a propósito: aquí se sirve DHCP, no DNS. El DNS de la red lo declara el
    router que sirve esa red (`red.dns`), no este equipo; montar un DNS aquí sería
    una primitiva que nadie ha declarado (regla 15).
    """
    interfaz = str((declarado or {}).get("interfaz") or "")
    rango = str((declarado or {}).get("rango") or "")
    if not interfaz or not rango:
        return ""
    inicio, _, fin = rango.partition("-")
    # El prefijo sale del rango declarado: `10.40.0.50-10.40.0.99` es una /24, y la
    # máscara es lo que dnsmasq necesita para saber de qué red reparte. Se cuentan los
    # octetos comunes, que es honesto con lo que el vocabulario admite.
    octetos = inicio.split(".")
    mascara = "255.255.255.0" if len(octetos) == 4 else "255.255.0.0"
    lineas = [
        "# PROPÓSITO: el servidor DHCP que da la primera dirección a los equipos del lab.",
        "# Lo escribe el motor (netlabs_v4_b) y lo reescribe cuando la declaración cambia:",
        "# no se edita a mano. Las reservas NO llevan MAC escrita a mano en ningún sitio:",
        "# salen del vmid del invitado que declara la dirección (regla 14).",
        "port=0",
        f"interface={interfaz}",
        "bind-interfaces",
        "dhcp-authoritative",
        f"dhcp-range={inicio},{fin},{mascara},12h",
        "log-dhcp",
    ]
    for reserva in reservas or []:
        if reserva.get("mac") and reserva.get("direccion"):
            lineas.append(f"dhcp-host={reserva['mac']},{reserva['direccion'].split('/')[0]}")
    return "\n".join(lineas) + "\n"


# La ruta del fichero del servidor DHCP, en un solo sitio: la usan el que lo escribe y
# el que comprueba si ya se escribió (dos literales separados se desincronizan).
RUTA_DNSMASQ = "/etc/dnsmasq.d/netlabs.conf"


def escrituras_linux(operaciones, invitado, declaracion, identidad, parametros):
    """(operaciones decididas) -> los comandos que las ejecutan, en orden.

    Función PURA: no ejecuta nada, sólo traduce una operación a la línea que la hace.
    Cada comando es IDEMPOTENTE (`ip addr replace`, `apt-get install -y`, reescribir el
    fichero entero, `ethtool -K` con el valor final): volver a aplicarlo deja el sistema
    igual, que es lo que hace verdadera la promesa de la regla 6.
    """
    declarado = areas_de(invitado)
    comandos = []
    for operacion in operaciones or []:
        op = operacion.get("op")

        if op == "poner_direccion":
            comandos.append({
                "area": "direccion", "accion": "escribir", "declarado": operacion.get("direccion"),
                "descripcion": "poner su dirección declarada",
                "comando": f"ip addr replace {operacion['direccion']} dev {operacion.get('interfaz') or 'eth0'}",
            })

        elif op == "activar_reenvio":
            comandos.append({
                "area": "reenvio", "accion": "escribir", "declarado": "true",
                "descripcion": "dejar que reenvíe paquetes",
                "comando": "sysctl -q -w net.ipv4.ip_forward=1 && printf 'net.ipv4.ip_forward=1\\n' > /etc/sysctl.d/99-netlabs.conf",
            })

        elif op in ("instalar_paquetes", "instalar_herramientas"):
            paquetes = " ".join(operacion.get("paquetes") or ["dnsmasq", "ethtool"])
            comandos.append({
                "area": "dhcp_servidor", "accion": "escribir", "declarado": paquetes,
                "descripcion": f"poner en el aparato del motor lo que el servidor DHCP necesita: {paquetes}",
                "comando": f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {paquetes}",
            })

        elif op in ("escribir_dnsmasq", "poner_reserva", "quitar_reserva"):
            # Las tres son la MISMA cosa: el fichero lleva TODAS las reservas, así que
            # cambiar una se hace reescribiéndolo entero. Reescribirlo dos veces en la
            # misma pasada sería trabajo duplicado: se hace una sola vez. El marcador es
            # la RUTA del fichero, escrita entera: buscar un trozo dio un fallo real
            # («dnsmasq.conf» NO está en «/etc/dnsmasq.d/netlabs.conf»).
            if not any(RUTA_DNSMASQ in c["comando"] for c in comandos):
                reservas = reservas_derivadas(declaracion, identidad, invitado)
                configuracion = configuracion_dnsmasq(declarado.get("dhcp_servidor"), reservas)
                comandos.append({
                    "area": "dhcp_servidor", "accion": "escribir",
                    "declarado": f"{declarado.get('dhcp_servidor', {}).get('rango')} + {len(reservas)} reserva(s) derivada(s)",
                    "descripcion": "escribir su configuración de servidor DHCP (con las reservas derivadas)",
                    "comando": f"echo {_b64(configuracion)} | base64 -d > {RUTA_DNSMASQ}",
                })

        elif op == "apagar_offload":
            interfaz = str((declarado.get("dhcp_servidor") or {}).get("interfaz") or "eth0")
            comandos.append({
                "area": "dhcp_servidor", "accion": "escribir", "declarado": "off",
                "descripcion": "apagar los offloads de la interfaz (sin esto las ofertas DHCP no llegan al CHR)",
                "comando": f"ethtool -K {interfaz} tx off gso off tso off",
            })

        elif op == "recargar_dnsmasq":
            comandos.append({
                "area": "dhcp_servidor", "accion": "escribir", "declarado": "activo",
                "descripcion": "poner en marcha (o recargar) el servidor DHCP",
                "comando": "systemctl enable --now dnsmasq >/dev/null 2>&1; systemctl restart dnsmasq",
            })

    return comandos


def pendiente_de_driver(operacion):
    """¿Qué ha pedido el plan que el driver de Linux TODAVÍA no sabe hacer?

    Existe para no fingir: si el plan decide una operación que aquí no está traducida,
    el driver PARA con su nombre en vez de saltársela en silencio.
    """
    conocidas = {
        "poner_direccion", "activar_reenvio", "instalar_paquetes", "instalar_herramientas",
        "escribir_dnsmasq", "poner_reserva", "quitar_reserva",
        "apagar_offload", "recargar_dnsmasq",
    }
    op = (operacion or {}).get("op")
    if op in conocidas:
        return None
    return op



def comando_de(resultado):
    """El comando que produjo un resultado de la puerta (`tasks/interior_ssh.yml`).

    Ansible NO deja la clave `item` cuando el bucle usa `loop_var` propio: deja el nombre
    que le diste (`interior_comando`) y lo dice en `ansible_loop_var`. Se leen las dos
    formas porque un analizador que sólo entiende `item` se queda mudo -- y pasó: el
    motor entró en el invitado, lo leyó (rc=0 en el diario) y luego dijo «el driver no leyó
    el área 'camino'», que era mentira.
    """
    if not isinstance(resultado, dict):
        return {}
    nombre = resultado.get("ansible_loop_var")
    if nombre and isinstance(resultado.get(nombre), dict):
        return resultado[nombre]
    return resultado.get("item") or {}


def leido_de_lecturas(resultados, invitado):
    """(lo que devolvió la puerta) -> el mapa `leído` que come `pasos_de_convergencia`.

    `resultados` es lo que deja la puerta (`interior_ssh.yml`): una lista con el
    comando de cada paso (`item`) y su salida (`stdout`, `rc`, `stderr`).

    Aquí se decide lo PRIMERO y más importante: si al invitado se le pudo PREGUNTAR.
    Un `rc` 255 es el de `ssh` cuando no consigue entrar --puerto cerrado, clave que
    no vale, bastión caído--: eso no es «el invitado está mal», es «no llegué», y el
    motor tiene que parar en vez de seguir a ciegas (regla 16). Un `rc` normal
    distinto de cero (un fichero que no existe, un comando ausente) SÍ es un estado
    legítimo: el invitado contestó, y lo que dijo es que eso no está.
    """
    areas = {}
    motivo = ""
    for resultado in resultados or []:
        item = comando_de(resultado)
        rc = int(resultado.get("rc") or 0)
        if rc == 255 and not motivo:
            motivo = (resultado.get("stderr") or "").strip().splitlines()[-1] if (resultado.get("stderr") or "").strip() else "no se pudo entrar"
    # Se reutiliza el analizador de Linux: es el mismo (declarado -> leído) de siempre.
    areas.update(leido_linux([
        {"area": comando_de(r).get("area"),
         "encontrado": r.get("stdout") or "",
         "rc": r.get("rc")}
        for r in (resultados or [])
    ]))
    return {
        "alcanzable": not motivo,
        "motivo": motivo,
        "areas": areas,
        "invitado": (invitado or {}).get("rol"),
    }


def operaciones_de_pasos(pasos):
    """Aplana las operaciones de los pasos del interior, en orden.

    El plan habla de PASOS; el driver ejecuta OPERACIONES. Esto es la traducción, y
    va aquí (pura) para que el playbook no lleve lógica.
    """
    operaciones = []
    for paso in pasos or []:
        for operacion in ((paso.get("parametros") or {}).get("operaciones") or []):
            operaciones.append(operacion)
    return operaciones


def requiere_lectura(area, leido):
    """¿El área declarada necesita releerse para comprobar la convergencia?

    Se relee TODO lo declarado y declarado-se-compara: la verificación no es «el
    comando no dio error», es «el estado real coincide con lo declarado» (los dos
    sentidos). Función aparte porque el orden importa: primero se escribe, después se
    lee, y lo que se lee es lo mismo que se leyó antes.
    """
    return area in (leido or {}).get("areas", {})


# Los DRIVERS que existen hoy en este motor: por vía, y por tipo de interior. Es una
# lista CORTA a propósito, y es la única verdad sobre qué sabe hacer el motor: la usan
# `apply.yml` para avisar de lo que va a parar y `paso.yml` para despachar. Si añades un
# driver (un `tasks/configurar_<tipo>.yml`), añádelo aquí -- y `test/test_interior.py`
# lo comprueba, para que no puedan divergir sin que nadie se entere.
DRIVERS = {
    "interior": {"linux"},   # `tasks/configurar_linux.yml`
    "sonda": set(),          # `tasks/sondar_servicio.yml` (todavía no)
}


def tiene_driver(via, tipo):
    """¿Este motor sabe ejecutar un paso de esa vía (y, si es interior, de ese tipo)?"""
    via = via or "api"
    if via in ("api", "camino"):
        return True
    if via == "interior":
        return tipo in DRIVERS.get("interior", set())
    return via in DRIVERS


def pasos_sin_driver(pasos):
    """Los pasos del plan que este motor todavía NO sabe ejecutar, en orden.

    Existe para que el aviso de `apply` no mienta: un plan que promete diez pasos y
    ejecuta tres tiene que decir CUÁLES de los otros siete no sabe hacer, y por qué.
    """
    return [
        paso for paso in (pasos or [])
        if not tiene_driver(paso.get("via"),
                            (paso.get("parametros") or {}).get("tipo"))
    ]


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
            "interior_lecturas_linux": lecturas_linux,
            "interior_leido_linux": leido_linux,
            "interior_escrituras_linux": escrituras_linux,
            "interior_pendiente_de_driver": pendiente_de_driver,
            "interior_leido": leido_de_lecturas,
            "interior_operaciones": operaciones_de_pasos,
            "interior_sin_driver": pasos_sin_driver,
            "interior_tiene_driver": tiene_driver,
            "interior_configuracion_dnsmasq": configuracion_dnsmasq,
            "interior_declara": declara_interior,
            "interior_tiene_camino": tiene_camino,
            "interior_puesto_control": puesto_control,
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
