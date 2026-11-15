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
# VER:         docs/decisiones/0005-el-driver-del-interior.md; docs/tunnel-del-bastion.md;
#              README.md §El interior; ./lab check declaracion

# --- Los dos tipos de interior ------------------------------------------------
# El tipo NO se adivina: lo dice la declaración (`config:<tipo>`). Un invitado sin
# `config` no se toca por dentro: el motor lo despliega y se calla.
TIPOS = ("linux", "routeros")

# --- Las áreas de cada tipo, EN ORDEN DE CONVERGENCIA -------------------------
# El orden importa y no es casual (es el que v3 pagó caro):
#   * `tunnel` va primero en Linux porque es LA FORMA DE ENTRAR: si el puesto de
#     control no tiene su salida, ninguna otra área de ese invitado se puede
#     converger (no hay túnel por el que llegar).
#   * `addresses` va ANTES de `dhcp_client` en RouterOS, y esto está MEDIDO, no
#     supuesto: al deshabilitar el cliente DHCP de fábrica, RouterOS se lleva la
#     dirección que ese cliente instaló, y con ella el REST --la escritura se queda
#     sin respuesta y el motor pierde el túnel a mitad de faena-- (comprobado en un
#     CHR 7.25.1 sobre `ether1`: la llamada murió a los 34 s, el equipo se quedó sin
#     dirección y hubo que rehacer el lab). Poniendo primero la dirección declarada,
#     el equipo sigue alcanzable pase lo que pase después.
#   * `identity` va la ÚLTIMA en RouterOS en la primera convergencia (ver
#     `identidad_al_final`), para no perder el túnel de vuelta a mitad de faena:
#     primero se añade y se verifica lo nuevo, y sólo entonces se cambia la
#     identidad del equipo. v3 lo llamaba intercambio atómico.
#   * `cortafuegos` va al final: no se cierra una vía de acceso antes de haber pasado por
#     ella.
AREAS = {
    # `addresses` (Linux) no es un área con driver propio: es la forma LISTA de
    # `address` -- las interfaces extra del invitado, una por bridge del lab. Está aquí
    # porque el vocabulario es cerrado y hay que nombrarla, y `areas_de` la funde en
    # `address` para que la convergencia tenga un solo túnel.
    "linux": ("tunnel", "address", "addresses", "ip_forward", "dhcp_server"),
    "routeros": (
        "identity", "addresses", "ip_services", "dhcp_client", "routes", "dhcp_server", "uplink",
    ),
}

# Las áreas que el encargo nombra y el motor TODAVÍA no converge. Se declaran aquí
# a propósito: la validación las rechaza con un motivo legible en vez de aceptarlas
# y luego no hacer nada con ellas, que es la forma más silenciosa de mentir.
AREAS_PENDIENTES = {
    "routeros": ("bridges", "firewall"),
    "linux": ("gateway", "routes", "dns", "claves"),
}

# --- Servicios: el alcance del área `ip_services` -------------------------------
# El área manda sobre estos servicios y sólo sobre estos: lo que se declara se
# deshabilita y lo que NO se declara (pero está en esta lista) se vuelve a
# habilitar. `www` no está: es donde vive REST, o sea el túnel de vuelta, y
# deshabilitarlo deja el equipo sin forma de ser configurado nunca más.
SERVICIOS_GESTIONADOS = ("api", "api-ssl", "ftp", "telnet", "ssh")
SERVICIOS_NUNCA_DESHABILITADOS = ("www",)

# --- El túnel ---------------------------------------------------------------
# El único vocabulario que el bastión declara es `tunnel`. El resto (por
# dónde sale, con qué clave, en qué puerto) es entorno, no lab: vive en secrets.yml
# y en vars/engine.yml. Un lab que llevara dentro la dirección de casa dejaría de
# poder desplegarse en otra casa.
CLAVE_TUNNEL = "tunnel"

# El nombre del script `echo <base64> | base64 -d | sh` que se manda por la consola.
# Lo pone el MOTOR dentro de su propio equipo, así que no es un valor de ningún lab.
RUTA_GUION_TUNNEL = "/usr/local/sbin/netlabs-tunnel"
UNIDAD_TUNNEL = "netlabs-tunnel.service"

# Las dos acciones del túnel, con nombre propio: el plan las nombra y el ejecutor
# las despacha, y una cadena suelta en dos sitios es una cadena que se separa.
ACCION_TUNNEL = "construir_tunnel"
ACCION_COMPROBAR_TUNNEL = "comprobar_tunnel"
ACCION_INTERIOR = "converger_interior"

# El puerto por el que se deja ver un RouterOS: su REST vive en el servicio `www` de
# fábrica. Es el MISMO que sondea la barrera de una etapa (`espera_de_servicio`), así
# que es una constante y no un número repetido en dos sitios que se puedan separar.
PUERTO_REST_ROUTEROS = 80


class ErrorMotor(Exception):
    """Mismo nombre que el error de Ansible: este módulo se prueba sin Ansible."""


# ---------------------------------------------------------------------------
# Vocabulario: qué se puede declarar dentro de cada tipo
# ---------------------------------------------------------------------------

def tipo_de(guest):
    """El tipo de interior declarado, o None si el invitado no declara `config`."""
    config = (guest or {}).get("config")
    if not isinstance(config, dict) or not config:
        return None
    tipos = [t for t in TIPOS if t in config]
    if len(tipos) != 1:
        raise ErrorMotor(
            "`config:` tiene que traer exactamente una clave de tipo "
            f"({', '.join(TIPOS)}), y trae {sorted(config.keys())}"
        )
    return tipos[0]


def areas_de(guest):
    """{área: valor declarado} del invitado, en orden de convergencia.

    La dirección del invitado es un área más, y por eso aparece aquí: el nivel de
    arriba (`address:` en el invitado) es la dirección de su interfaz de gestión, y
    dentro de un Linux es algo que hay que converger leyendo y escribiendo, no un
    campo que la API del hipervisor guarde.
    """
    tipo = tipo_de(guest)
    if tipo is None:
        return {}
    declaradas = dict((guest.get("config") or {}).get(tipo) or {})
    if tipo == "linux":
        # La de gestión sale del campo `address` del invitado (la de la interfaz por la que
        # el plan levanta el túnel), y va primero. Si el lab declara además `addresses`
        # --una lista de `{interfaz, direccion}`--, son las OTRAS interfaces: un puesto de
        # control necesita una por cada bridge del lab, porque si no, un invitado que
        # cuelgue de ese bridge es inalcanzable para el motor (medido: el CHR del segundo
        # etapa no contesta y su convergencia no se puede ni empezar).
        propias = [dict(p) for p in (declaradas.get("addresses") or [])]
        declaradas.pop("addresses", None)
        propia = str(guest.get("address") or "")
        if propia and propia != "dhcp":
            propias = [{"interface": "eth0", "address": propia}] + propias
        declaradas["address"] = propias or guest.get("address")
    if tipo == "routeros":
        # En un RouterOS, la dirección de su interfaz de GESTIÓN no la pone nadie de fuera: la
        # escribe el motor por su REST. Va DENTRO del área `addresses` (es la dirección
        # de una interfaz), en la primera interfaz -- que es donde vive el cliente DHCP de
        # fábrica que esta misma convergencia apaga (medido: `ether1`).
        #
        # Se DERIVA del `address:` del invitado, y por eso no se escribe dos veces ni se
        # puede olvidar: apagar el cliente de fábrica sin poner la dirección estática
        # dejaría al router sin dirección, o sea sin túnel de vuelta para el motor que lo
        # configura. Es el mismo papel que la línea de arriba, con otro mecanismo: en un
        # Linux la dirección la pone el propio invitado; en un RouterOS, el motor.
        propia = str(guest.get("address") or "")
        if propia and propia != "dhcp":
            declaradas["addresses"] = list(declaradas.get("addresses") or []) + [
                {"interface": INTERFAZ_GESTION_ROUTEROS, "address": propia}
            ]
    return {area: declaradas.get(area) for area in AREAS[tipo] if area in declaradas}


def areas_a_leer(guest):
    """Las áreas que el driver tiene que LEER dentro del equipo (las declaradas)."""
    return list(areas_de(guest).keys())


def es_direccion_dinamica(valor):
    """¿Esta dirección declarada es dinámica (`dhcp`)? (las otras formas son una
    estática `<ip>/<prefijo>` o ausente)."""
    return str(valor or "").strip().lower() == "dhcp"


def areas_que_piden_visita(guest):
    """Las áreas declaradas que exigen ENTRAR en el invitado (leer o escribir dentro).

    Una dirección DINÁMICA no pide visita: su valor es un hecho que se lee del HOST
    (`GET /nodes/<nodo>/lxc/<vmid>/interfaces`, §6.3/§11) y, además, no se podría
    escribir desde dentro sin saber primero a qué dirección conectar — un círculo.
    Un invitado cuya ÚNICA área sea ésa (un `config: linux: {}` con `address: dhcp`,
    el caso de los puestos dinámicos) no se converge: no hay nada que hacer dentro y
    el motor no entra a ciegas (regla 16). `configurar_<tipo>.yml` sólo se despacha
    para un invitado con áreas que piden visita.
    """
    return {
        area for area, valor in areas_de(guest).items()
        if not (area == "address" and es_direccion_dinamica(valor))
    }


def declara_interior(guest):
    """¿Este invitado declara interior? (si no, el motor no entra: ni lee ni escribe)."""
    return tipo_de(guest) is not None


def tiene_tunnel(guest):
    """¿Es el bastión? (declara `config.linux.tunnel`)."""
    return CLAVE_TUNNEL in ((guest.get("config") or {}).get("linux") or {})


# ---------------------------------------------------------------------------
# La dirección de la interfaz de gestión: el motor la DERIVA (nada derivado se guarda)
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


def salida_derivada(estado, parametros):
    """Lo que el motor DERIVA para la interfaz de fuera de un lab: vía de acceso y dirección.

    Son valores del ENTORNO -- por dónde sale este nodo y qué dirección libre hay en esa
    red -- así que el lab no los declara: el lab sólo dice QUE este router es la salida.

    Es la MISMA regla que la interfaz del bastión en ese mismo bridge: la dirección
    del bridge es la vía de acceso, y la del invitado se elige contando por ARRIBA entre las
    libres (así nunca cae dentro de un pool que reparta un router del lab). El DNS se toma
    también como la gateway: es donde este nodo sirve el resolutor de esa red (medido).

    (Se probó a pedir la dirección por DHCP, que sería lo natural, y en este entorno no
    puede ser: medido con captura, las ofertas del bridge de salida salen con el checksum
    UDP mal formado y un CHR las descarta -- se queda en `searching...` indefinidamente.
    Ver docs/decisiones/0012 y el documento del lab.)
    """
    puente = str(parametros.get("bridge_gestion") or "")
    subred = str((estado.get("bridges_direcciones") or {}).get(puente) or "")
    if not puente or "/" not in subred:
        raise ErrorMotor(
            f"este lab declara `uplink` (salida a internet) y el motor no sabe por "
            f"dónde sale el nodo: falta `pve_bridge_gestion` en secrets.yml o ese bridge "
            f"no tiene dirección en el nodo (salió: puente='{puente}', red='{subred}')"
        )
    gateway, _, prefijo = subred.partition("/")
    direccion = direccion_libre(subred, estado.get("direcciones_usadas") or [], desde_arriba=True)
    return {"salida_acceso": gateway, "salida_direccion": f"{direccion}/{prefijo}"}


def interfaces_del_bastion(guest, declaracion, estado, parametros):
    """Las interfaces del bastión, TODAS al nacer: (bridge, dirección, máscara, vía de acceso).

    Nace completo porque cambiarle las interfaces a un invitado en marcha obliga a
    reiniciarlo, y aquí no se reinicia la máquina que está trabajando (§5).

    **El ORDEN es el orden de `eth0, eth1, ...` dentro del invitado**, y por eso no es
    libre: primero las interfaces del LAB (la del bridge que el invitado declara la primera,
    porque es la que la declaración llama `eth0` en sus áreas --el servidor DHCP del
    puesto sirve por `eth0`--) y **la interfaz del bridge de gestión del NODO la ÚLTIMA**.
    Así el nombre de interfaz que escribe el lab sigue significando lo mismo en
    cualquier nodo, y el valor de entorno (qué bridge da salida) no se filtra a la
    declaración.

      * Una interfaz por cada bridge del LAB. La del bridge que el invitado declara lleva
        su dirección DECLARADA (la gestión no puede depender de los routers que está
        desplegando); las demás las elige el motor por arriba, esquivando las
        direcciones que el lab declara y las que están en uso.
      * La ÚLTIMA interfaz va en el bridge de gestión del NODO (valor de entorno, no del
        lab): es por donde el puesto sale hacia casa, y es la única que lleva PUERTA
        (la dirección que el nodo tiene en ese bridge). Su dirección la elige el motor
        de entre las libres, leyendo las que ya usa cada invitado del nodo.

    Si el invitado declara túnel y no hay bridge de gestión, esto **falla**: un puesto
    de control sin salida es un lab que no se puede converger, y decirlo es más útil
    que crear el invitado y descubrirlo tres pasos después.
    """
    puente_gestion = str(parametros.get("bridge_gestion") or "")
    direcciones_bridge = estado.get("bridges_direcciones") or {}
    usadas = estado.get("direcciones_usadas") or []
    if not puente_gestion:
        raise ErrorMotor(
            f"el invitado {guest.get('rol')} declara túnel y el motor no sabe por "
            "dónde da salida este nodo: falta `pve_bridge_gestion` en secrets.yml "
            "(el bridge del nodo con dirección y salida, hoy `vmbr1`)"
        )

    interfaces = []
    # Las direcciones que el lab declara en un bridge: ninguna interfaz de gestión puede
    # caer encima de un router o de un servidor que el lab ya ha reservado.
    declaradas_por_bridge = {}
    for otro in declaracion.get("guests", []):
        direccion = str(otro.get("address") or "")
        if direccion and direccion != "dhcp" and "/" in direccion:
            declaradas_por_bridge.setdefault(otro.get("bridge"), []).append(direccion)

    # La interfaz DECLARADA va la primera: es `eth0` para el invitado, y así lo que el lab
    # declara en sus áreas (`dhcp_server: interface: eth0`) dice lo mismo en cualquier
    # nodo. Es la única cuya dirección no decide el motor.
    if guest.get("bridge") and guest.get("address"):
        interfaces.append(
            {
                "bridge": guest["bridge"],
                "address": guest["address"],
                "gateway": "",
                "papel": "interfaz declarada del bastión",
            }
        )
    for bridge in declaracion.get("bridges", []):
        nombre = bridge.get("nombre")
        if not nombre or nombre == guest.get("bridge"):
            continue
        subred = bridge.get("address")
        usadas_aqui = list(usadas) + declaradas_por_bridge.get(nombre, [])
        direccion = direccion_libre(subred, usadas_aqui) if subred else ""
        interfaces.append(
            {
                "bridge": nombre,
                "address": f"{direccion}/{subred.split('/')[1]}" if direccion else "",
                "gateway": "",
                "papel": "interfaz del bastión en un bridge del lab",
            }
        )

    # Y la ÚLTIMA, la salida: el bridge de gestión del nodo, con su pasarela.
    subred = str(direcciones_bridge.get(puente_gestion) or "")
    if not subred:
        raise ErrorMotor(
            f"el bridge de gestión `{puente_gestion}` no tiene dirección en este nodo: "
            "sin dirección no hay vía de acceso por la que salir hacia casa"
        )
    usadas_salida = list(usadas) + [
        p["address"] for p in interfaces if p.get("address")
    ]
    direccion = direccion_libre(subred, usadas_salida)
    interfaces.append(
        {
            "bridge": puente_gestion,
            "address": f"{direccion}/{subred.split('/')[1]}",
            # La vía de acceso de la interfaz de gestión es la dirección que el NODO tiene en ese
            # bridge (10.10.10.1 en vmbr1): por ahí sale hacia casa. No es un valor del
            # lab: se lee de la red del nodo.
            "gateway": subred.split("/")[0],
            "papel": "salida hacia casa",
        }
    )
    return interfaces


def puerto_tunnel(vmid, parametros):
    """El puerto del nodo de control donde el puesto deja su sshd. DERIVADO del vmid."""
    return int(parametros.get("tunnel_puerto_base") or 20000) + int(vmid)


def puerto_rest_tunnel(vmid, parametros):
    """El puerto del nodo de control por el que se llega al REST de un invitado.

    El bastión reenvía, por el MISMO túnel del túnel, el puerto 80 de cada
    equipo con el que el motor habla por REST (los que declaran `config.routeros`). Así
    el `uri` se ejecuta en la máquina del motor --una sola vía de acceso, un solo sitio-- y el
    puesto sólo hace de túnel, en vez de delegarle la llamada. Se DERIVA del vmid, como
    el puerto del tunnel: nada que guardar (regla 11). La banda (21000+) no pisa la del
    túnel (20000+) para vmids de tres cifras, que es lo que usa un clúster normal.
    """
    return int(parametros.get("tunnel_rest_puerto_base") or 21000) + int(vmid)


def permitlisten_de(puertos):
    """`[20103, 21102]` -> `permitlisten="20103",permitlisten="21102"`.

    NO se escribe una lista dentro de una sola opción. `permitlisten="a,b"` parece lo
    natural --y el `man` de sshd invita a leerlo así--, pero lo que sshd admite es REPETIR
    la opción, separada por comas. Con la forma mala sshd **no encuentra la clave** y
    contesta «Permission denied (publickey)»: un error que no dice nada de lo que pasa de
    verdad y que cuesta media tarde. Medido: docs/decisiones/0010-*.md.
    """
    return ",".join(f'permitlisten="{puerto}"' for puerto in puertos)


def _declarado_por_rol(declaracion, rol):
    """El invitado DECLARADO con ese rol. La declaración normalizada es una lista plana."""
    for guest in (declaracion or {}).get("guests") or []:
        if guest.get("rol") == rol:
            return guest
    return {}


def interfaces_rest_del_bastion(declaracion, identidad, parametros):
    """Los equipos por los que el bastión tiene que abrir túnel de REST.

    Se pregunta a la DECLARACIÓN quién trae `config.routeros` --son los únicos con los
    que este motor habla por REST: el vocabulario es cerrado-- y al mapa de identidad
    por su vmid, que es de donde sale el puerto. Un equipo sin dirección declarada no
    entra: no hay a dónde reenviar, y un `dhcp` con interior de RouterOS ya lo rechaza
    la validación de la declaración. Sale ordenada por rol para que el guion del túnel
    sea el mismo en cada pasada (si no, un `apply` lo reescribiría por nada).
    """
    interfaces = []
    for guest in (identidad or {}).get("guests") or []:
        declarado = _declarado_por_rol(declaracion, guest.get("rol"))
        if "routeros" not in (declarado.get("config") or {}):
            continue
        # La dirección declarada, sin el prefijo: lo que viaja en `-R` es una dirección, no
        # una red. `dhcp` NO es una dirección --no se sabe a dónde reenviar--, así que un
        # equipo así no entra (la validación de la declaración ya lo rechaza cuando declara
        # interior; aquí se dice lo mismo por si llegara por otra vía).
        direccion = _sin_prefijo(declarado.get("address"))
        if not direccion or direccion == "dhcp":
            continue
        interfaces.append(
            {
                "rol": guest.get("rol"),
                "address": direccion,
                "puerto": puerto_rest_tunnel(guest.get("vmid"), parametros),
                "puerto_servicio": PUERTO_REST_ROUTEROS,
            }
        )
    return sorted(interfaces, key=lambda interface: str(interface["rol"]))


def guion_tunnel(clave_privada, host, puerto, usuario, puerto_local, interfaces_rest=None):
    """El texto que se manda por la consola: UNA sola vez, y queda puesto.

    Qué hace, y por qué esto y no otra cosa:

      1. deja la clave del túnel dentro del invitado, con sus permisos;
      2. escribe un GUION que abre la salida hacia casa con `ssh -R`: el puesto de
         control se conecta al sshd del nodo de control y deja reenviado un puerto
         local SUYO hacia su propio sshd (por ahí se le lee la consola y de ahí cuelga
         el lab) y, por cada equipo con el que el motor habla por REST, OTRO puerto
         local hacia el puerto 80 de ese equipo: así el `uri` del motor se ejecuta en
         la máquina del motor, y el puesto sólo hace de túnel;
      3. lo pone como UNIDAD de systemd con `Restart=always` y la habilita.

    El punto 3 es lo que hace que la consola se use UNA vez por vida del invitado y
    no en cada `apply`: si el invitado reinicia, el túnel se levanta solo. Y es
    idempotente: volver a mandarlo reescribe lo mismo y reinicia el servicio.

    Va en base64 porque la consola no es un canal de datos fiable: una línea, sin
    heredocs ni comillas que escapar, sin nada que el eco pueda romper.
    """
    # `\` + salto de línea: lo que la shell lee como «la línea sigue». Se escribe con
    # chr() para que ningún nivel de escapes lo pueda romper por el túnel.
    seguimos = chr(92) + "\n"
    ip_forwards = "".join(
        f"  -R {interface['puerto']}:{interface['address']}:{interface['puerto_servicio']} {seguimos}"
        for interface in (interfaces_rest or [])
    )
    return f"""#!/bin/sh
# PROPÓSITO: abrir la salida hacia casa del bastión y sostenerla.
# Lo escribe el motor UNA vez, por la consola, al nacer el invitado
# (docs/tunnel-del-bastion.md). Si el invitado reinicia, systemd lo
# vuelve a levantar: no hace falta volver a entrar por consola.
set -u
mkdir -p /root/.ssh && chmod 700 /root/.ssh
cat > /root/.ssh/netlabs_tunnel <<'FIN_CLAVE'
{clave_privada}
FIN_CLAVE
chmod 600 /root/.ssh/netlabs_tunnel
cat > {RUTA_GUION_TUNNEL} <<'FIN_GUION'
#!/bin/sh
exec ssh -i /root/.ssh/netlabs_tunnel \\
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \\
  -o ExitOnForwardFailure=yes \\
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \\
  -N -R {puerto_local}:localhost:22 \\
{ip_forwards}  -p {puerto} {usuario}@{host}
FIN_GUION
chmod 755 {RUTA_GUION_TUNNEL}
cat > /etc/systemd/system/{UNIDAD_TUNNEL} <<'FIN_UNIDAD'
[Unit]
Description=netlabs_v4_b: salida hacia el nodo de control (el túnel del lab)
After=network-online.target ssh.service
Wants=network-online.target

[Service]
Type=simple
ExecStart={RUTA_GUION_TUNNEL}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
FIN_UNIDAD
systemctl daemon-reload
systemctl enable --now {UNIDAD_TUNNEL}
sleep 4
echo {marca_tunnel()}
"""


def linea_consola(guion):
    """La ÚNICA línea que se manda por la consola: el guion, en base64, a `sh`.

    En base64 porque la consola NO es un canal de datos fiable: se manda una línea
    sin heredocs, sin comillas y sin nada que el eco pueda romper. Y se decodifica en
    el equipo (`base64 -d | sh`) para que lo que se ejecute sea exactamente lo que se
    codificó aquí, sin que nadie lo reinterprete por el túnel.
    """
    import base64 as modulo_base64

    codificado = modulo_base64.b64encode(guion.encode()).decode()
    return f"echo {codificado} | base64 -d | sh"


def marca_tunnel(_entrada=None):
    """Lo que el guion imprime al final: la consola no devuelve código de salida, se
    reconoce el ECO. Sin marca, el motor no sabe si la línea se ejecutó.

    Recibe un argumento que IGNORA porque se usa como filtro de Ansible
    (`'' | interior_marca_túnel`): un filtro siempre recibe lo de su izquierda. El
    valor de la marca no depende de nada: es una constante que el guion y el motor
    tienen que decir igual, y por eso vive en un solo sitio (aquí).
    """
    return "NETLABS_TUNNEL_PUESTO_42"


def tunnel_responde(estado):
    """¿El túnel del túnel está en pie, según lo último que el motor comprobó?

    Se lee del ESTADO (que lo trae una lectura: el puerto reenviado del nodo de
    control contesta o no), no de una marca que el motor se hubiera dejado: una
    marca se queda pegada cuando el puesto se reinicia, y un puerto que no contesta
    no se puede fingir. Ausente = no responde: en un clúster simulado (un `plan` sin
    credenciales) no hay túnel, y el plan lo dice.
    """
    return _afirmativo((estado or {}).get("tunnel", {}).get("responde"))


def _afirmativo(valor):
    """¿Un valor que viene por texto dice que SÍ?

    El estado viaja por texto entre tareas de Ansible, y ahí un «False» con letras es una
    CADENA: `bool('False')` es `True` en Python. Creerle a `bool()` convertiría un túnel
    caído en un túnel en pie -- justo el error que este estado existe para evitar--, así
    que se mira el texto y se dice lo que dice.
    """
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "yes", "si", "sí", "1")
    return bool(valor)


def pasos_del_tunnel(guest, declaracion, estado, parametros, identidad=None):
    """Los pasos del CAMINO de este invitado (el bastión), en orden.

    El túnel es lo que hace ENTRAR a Ansible en la red del lab, así que va antes de
    converger nada: sin él no se llega a ningún invitado. Tiene dos mitades:

      1. `construir_túnel` -- el arranque: el motor deja su clave pública dentro del
         invitado (al crear, por API), escribe UNA línea en su propio
         `authorized_keys` con `restrict,port-forwarding,permitlisten=<puerto>`, y
         manda por la consola UNA línea en base64 que levanta el túnel hacia casa.
      2. `comprobar_túnel` -- la prueba de punta a punta: que el puerto reenviado del
         nodo de control conteste. Eso demuestra la cadena entera (casa -> 443 ->
         puesto -> vuelta), no una parte.

    Si el túnel YA responde, la mitad 1 no se emite: reconstruir un túnel que
    funciona en cada `apply` sería justo el error que este plan viene a evitar. La
    comprobación se emite siempre: es una LECTURA, y `apply` tiene que poder decir
    que el túnel está en pie ahora, no que lo estuvo.

    La clave privada del túnel NO viaja en el paso: el plan no lleva secretos. El
    paso lleva lo que hay que hacer (dónde, en qué puerto, hacia quién) y el guion se
    arma al ejecutarlo, con la clave que el motor lee de su propio `~/.ssh`.
    """
    if not tiene_tunnel(guest):
        return []

    declarado = (guest.get("config") or {}).get("linux") or {}
    salida = (declarado.get(CLAVE_TUNNEL) or {}).get("salida") or {}
    puerto_local = puerto_tunnel(guest["vmid"], parametros)
    # Las interfaces de REST: una por equipo con el que el motor hablará por REST. Van dentro
    # del paso porque el puerto de cada una sale de su vmid, y el vmid sólo se conoce en
    # el plan (que los asigna todos de una vez), no al ejecutar el paso.
    interfaces_rest = interfaces_rest_del_bastion(declaracion, identidad, parametros)
    # Los puertos que el túnel dejará autorizados y reenviados: el suyo y el REST de cada
    # equipo. Es la MISMA lista que escribe `tasks/tunnel.yml` en `authorized_keys`.
    puertos_autorizados = permitlisten_de(
        [puerto_local] + [interface["puerto"] for interface in interfaces_rest]
    )
    if interfaces_rest:
        detalle_rest = "y, por el MISMO túnel, reenvía el puerto 80 de cada equipo de REST: " + (
            ", ".join(f"{interface['rol']}->127.0.0.1:{interface['puerto']}" for interface in interfaces_rest)
        )
    else:
        detalle_rest = "este lab no configura ningún RouterOS: por el túnel sólo va la consola"
    host_salida = str(salida.get("host") or parametros.get("tunnel_host") or "")
    puerto_salida = int(salida.get("puerto") or parametros.get("tunnel_puerto") or 443)

    pasos = []
    if not tunnel_responde(estado):
        interfaces = interfaces_del_bastion(guest, declaracion, estado, parametros)
        pasos.append(
            {
                "accion": ACCION_TUNNEL,
                "via": "tunnel",
                "rol": guest.get("rol"),
                "stage": guest.get("stage"),
                "metodo": None,
                "ruta": None,
                "parametros": {
                    "vmid": guest["vmid"],
                    "puerto": puerto_local,
                    "salida_host": host_salida,
                    "salida_puerto": puerto_salida,
                    "interfaces": [
                        {"bridge": interface["bridge"], "address": interface["address"]} for interface in interfaces
                    ],
                    "rest": interfaces_rest,
                },
                "detalle": [
                    "la clave pública del motor se deja en el invitado al CREARLO (ssh-public-keys):",
                    "  por ahí entra Ansible, y sin eso no habría forma de llegar a configurarlo",
                    f"en casa se añade UNA línea a authorized_keys con restrict,port-forwarding,"
                    f"{puertos_autorizados} (la clave del túnel no da shell, sólo los reenvíos de este túnel)",
                    f"por la consola del invitado se manda UNA línea (base64) que levanta "
                    f"ssh -R {puerto_local}:127.0.0.1:22 hacia {host_salida}:{puerto_salida}",
                    detalle_rest,
                    "la consola no devuelve código de salida: el guion termina imprimiendo una MARCA "
                    "y el motor la busca en el eco",
                ],
                "porque": (
                    f"el rol '{guest['rol']}' es el bastión de este lab: hasta que su "
                    f"túnel no esté en pie no se puede entrar en ningún invitado, así que va antes "
                    f"de converger nada"
                ),
            }
        )

    pasos.append(
        {
            "accion": ACCION_COMPROBAR_TUNNEL,
            "via": "tunnel",
            "rol": guest.get("rol"),
            "stage": guest.get("stage"),
            "metodo": None,
            "ruta": None,
            "parametros": {
                "puerto": puerto_local,
                "salida_host": host_salida,
                "salida_puerto": puerto_salida,
                "vmid": guest["vmid"],
            },
            "porque": (
                f"comprueba la cadena entera: si el puerto {puerto_local} del nodo de control "
                f"contesta, el túnel casa -> {host_salida}:{puerto_salida} -> puesto -> vuelta funciona"
            ),
        }
    )
    return pasos


# ---------------------------------------------------------------------------
# Reservas DHCP derivadas: la MAC no se declara NUNCA (regla 14)
# ---------------------------------------------------------------------------

def reservas_derivadas(declaracion, identidad, guest_servidor, en_red=None):
    """Las reservas que el servidor DHCP de `invitado_servidor` tiene que tener.

    Se DERIVAN: por cada OTRO invitado alcanzable por ese servidor que declare una
    dirección estática, una reserva con la MAC que el motor deriva de su vmid. Así
    ningún cliente dinámico puede robarle la dirección a un router o a un servidor.
    El propio servidor no se reserva a sí mismo.

    ¿Quién es «alcanzable por ese servidor»? Eso lo dice el ÁMBITO, y hay dos casos
    porque hay dos formas de declararlo:

      * `en_red` (un prefijo, p. ej. 10.41.1.0/24): el servidor DHCP de un RouterOS
        declara la RED que sirve, y su interfaz (ether2) no tiene por qué coincidir
        con la interfaz de gestión del invitado (`bridge:`). Se reserva a quien tenga una
        dirección declarada DENTRO de esa red. Ésta es la forma buena para un router.
      * sin `en_red`: el ámbito es el BRIDGE del propio invitado. Es el caso de un
        Linux que sirve la red del bridge en el que está (el bastión).

    Ámbito por bridge como respaldo de un router: sirve para no dejar las reservas
    vacías cuando no se declara `red`, y por eso se usa sólo entonces.
    """
    servidor = str(guest_servidor.get("rol"))
    bridge = guest_servidor.get("bridge")
    por_rol = {i["rol"]: i for i in identidad["guests"]}
    reservas = []
    for otro in declaracion.get("guests", []):
        if otro.get("rol") == servidor:
            continue
        direccion = str(otro.get("address") or "")
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
                "address": direccion,
                "mac": identidad_otro["mac"],
            }
        )
    return sorted(reservas, key=lambda r: r["address"])


def en_red_siendo(direccion, red):
    """¿Cae `address` (con máscara) dentro de la red `red`?

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

def _paso(accion, guest, area, operaciones, porque):
    """Un paso del interior. Sin `porque` no hay paso: un paso sin razón es un bug."""
    return {
        "accion": accion,
        "via": "interior",
        "rol": guest.get("rol"),
        "stage": guest.get("stage"),
        "metodo": None,
        "ruta": None,
        "parametros": {
            "area": area,
            "tipo": tipo_de(guest),
            "operaciones": operaciones,
        },
        "porque": porque,
    }


def _identity_canonica(declarado, leido):
    """Diferencia del área `identity`: nombre del equipo y credenciales del motor.

    El valor DECLARADO del área es el nombre, tal cual (`identity: rt-borde`): la
    declaración no envuelve en un mapa lo que ya es un dato.

    Son TRES cosas distintas y no se confunden (medido: un CHR nace con el usuario
    `admin` sin contraseña y sin ninguna clave): que el usuario exista, que la credencial
    del motor esté puesta en él, y que la clave pública esté importada. Si no se
    distinguieran, el motor daría por bueno un equipo con la vía de acceso abierta.
    """
    operaciones = []
    esperado = str(declarado or "")
    actual = str((leido or {}).get("nombre") or "")
    if esperado and actual != esperado:
        operaciones.append({"op": "set_identity", "nombre": esperado})
    # La CLAVE primero y la CREDENCIAL al final, y esto está medido: cambiar la contraseña
    # invalida al instante la de fábrica, y la escritura siguiente --importar la clave-- se
    # queda sin credencial con la que hablar (401 sobre `/user/ssh-keys/add`, medido en un
    # CHR 7.25.1: la contraseña se cambió, la clave no llegó, y el paso se paró). Con la
    # clave ya importada, el motor entra con ella y la contraseña es lo ÚLTIMO que se toca.
    if not (leido or {}).get("clave_motor"):
        operaciones.append({"op": "import_engine_key"})
    if not (leido or {}).get("usuario_motor"):
        operaciones.append({"op": "create_engine_user"})
    elif not (leido or {}).get("credencial_motor"):
        # `tolerar_sin_respuesta`: cambiar la contraseña del usuario con el que se está
        # hablando MATA la sesión, y RouterOS contesta 400 `Bad Request Session closed`
        # (medido en el CHR 7.25.1) aunque el cambio haya surtido efecto. Es un corte por
        # diseño, como apagar el cliente DHCP: se tolera, y la convergencia la dice la
        # REELECTURA (que ya entra con la credencial nueva).
        operaciones.append({"op": "set_engine_credential", "tolerar_sin_respuesta": True})
    return operaciones


def _ip_services_canonicos(declarado, leido):
    """Diferencia del área `ip_services`, en los dos sentidos y dentro del alcance.

    Lo declarado se deshabilita; lo que el motor gestiona y NO se declara se
    habilita. Fuera del alcance (p. ej. `www`) el motor no opina.
    """
    deseados = set(str(s) for s in ((declarado or {}).get("deshabilitar") or []))
    apagados = set(str(s) for s in ((leido or {}).get("deshabilitados") or []))
    operaciones = []
    for servicio in sorted(deseados - apagados):
        operaciones.append({"op": "disable_service", "servicio": servicio})
    for servicio in sorted((apagados - deseados) & set(SERVICIOS_GESTIONADOS)):
        operaciones.append({"op": "enable_service", "servicio": servicio})
    return operaciones


def _dhcp_client_canonico(declarado, leido):
    """Diferencia del área `dhcp_client`: el de fábrica de un CHR recién nacido."""
    if (declarado or {}).get("deshabilitar") and (leido or {}).get("habilitado"):
        return [{"op": "disable_dhcp_client"}]
    return []


def _addresses_canonicas(declarado, leido):
    """Diferencia del área `addresses`. La dinámica con el mismo valor NO se toca
    aquí: no se puede borrar por la API (es de otro dueño) y por eso es RESIDUO, y
    el residuo se resuelve con `reiniciar_invitado` (§9.2, ADR 0007).

    Lo DECLARADO es la lista tal cual se escribe en el lab
    (`- {interface: ether2, address: 10.40.1.1/24}`); lo LEÍDO es lo que el driver
    saca del equipo, ya separado en `estaticas` y `dinamicas`.
    """
    deseadas = {
        (str(d.get("interface")), str(d.get("address"))) for d in (declarado or [])
    }
    actuales = {
        (str(d.get("interface")), str(d.get("address")))
        for d in ((leido or {}).get("estaticas") or [])
    }
    operaciones = []
    for interfaz, direccion in sorted(deseadas - actuales):
        operaciones.append({"op": "add_address", "interface": interfaz, "address": direccion})
    for interfaz, direccion in sorted(actuales - deseadas):
        operaciones.append({"op": "remove_address", "interface": interfaz, "address": direccion})
    return operaciones


def _routes_canonicas(declarado, leido):
    """Diferencia del área `rutas`: sólo las ESTÁTICAS. Las conectadas las pone el
    sistema y la dinámica del DHCP es residuo (`reiniciar_invitado`).

    Lo DECLARADO es la lista tal cual (`- {destino, pasarela}`); lo LEÍDO, lo que el
    driver saca del equipo.
    """
    deseadas = {
        (str(r.get("dst_address")), str(r.get("gateway"))) for r in (declarado or [])
    }
    actuales = {
        (str(r.get("dst_address")), str(r.get("gateway")))
        for r in ((leido or {}).get("estaticas") or [])
    }
    operaciones = []
    for destino, pasarela in sorted(deseadas - actuales):
        operaciones.append({"op": "add_route", "dst_address": destino, "gateway": pasarela})
    for destino, pasarela in sorted(actuales - deseadas):
        operaciones.append({"op": "remove_route", "dst_address": destino, "gateway": pasarela})
    return operaciones


def _red_normalizada(red):
    """La red DHCP declarada, en la forma en que se compara con lo leído.

    Se normalizan los tres campos que importan (prefijo, pasarela y DNS) y se ordena
    la lista de DNS: comparar dos listas de DNS en distinto orden y llamarlo cambio
    haría que la segunda ejecución escribiera sin que nada hubiera cambiado.
    """
    red = red or {}
    return {
        "address": str(red.get("address") or ""),
        "gateway": str(red.get("gateway") or ""),
        "dns": sorted(str(d) for d in (red.get("dns") or [])),
    }


def _reserva_es_de_este_servidor(reserva, nombre_servidor, prefijo_red, cuantos_servidores):
    """¿La concesión `static_lease` la sirve el servidor DHCP de este ámbito?

    Un RouterOS con dos LANs tiene dos servidores, y cada concesión dice a cuál sirve
    (`server`). Compararlas TODAS contra cada ámbito -- que es lo que se hacía -- hacía
    que el de la segunda red pidiera quitar la reserva de la primera: que no es suya, y
    que el otro ámbito está declarando en la misma pasada. El router no convergía nunca
    (medido: es el primer caso con dos ámbitos DHCP en un mismo router).

    Y cuando la concesión no dice a quién sirve (`all`, o sin `server`), se atribuye a la
    red en la que CAE su dirección; y si el router declara UN solo servidor, a ése, sin
    más preguntas: es la regla que no cambia nada en un router de una sola LAN.
    """
    suyo = str(reserva.get("servidor") or "")
    if suyo == nombre_servidor:
        return True
    if suyo and suyo != "all":
        return False
    if cuantos_servidores <= 1:
        return True
    return bool(prefijo_red) and en_red_siendo(reserva.get("address"), prefijo_red)


def _dhcp_server_canonico(declarado, leido, declaracion, identidad, guest):
    """Diferencia del área `dhcp` de un RouterOS: red, servidor, pool y reservas.

    Las reservas se comparan por MAC: la dirección que reserva el router tiene que
    ser la que el motor DERIVA del vmid del invitado (regla 14). Una reserva con la
    MAC equivocada se quita: dentro del área, lo que no está declarado sale.

    Cada servidor declarado tiene SU ámbito (`red.prefijo`), así que sus reservas se
    derivan una a una: un router con dos LANs no puede reservar en la primera lo que
    vive en la segunda. Y al leer, cada ámbito mira SÓLO las concesiones que sirve el
    suyo: si no, el segundo ámbito pediría quitar las del primero (ver
    `_reserva_es_de_este_servidor`).
    """
    operaciones = []
    for declarado_servidor in declarado or []:
        interfaz = str(declarado_servidor.get("interface"))
        encontrado = None
        for candidato in (leido or {}).get("servidores") or []:
            if str(candidato.get("interface")) == interfaz:
                encontrado = candidato
                break
        rango = str((declarado_servidor.get("pool") or {}).get("rango") or "")
        if encontrado is None:
            operaciones.append({"op": "add_dhcp_server", "interface": interfaz, "rango": rango})
        elif str(encontrado.get("rango") or "") != rango:
            operaciones.append({"op": "add_dhcp_server", "interface": interfaz, "rango": rango})
        red = declarado_servidor.get("network") or {}
        if red and _red_normalizada(red) != _red_normalizada((encontrado or {}).get("network")):
            # Se compara con lo LEÍDO, no se escribe por si acaso: reescribir la red en
            # cada ejecución rompería la idempotencia (y mentiría sobre `changed=0`).
            normalizada = _red_normalizada(red)
            operaciones.append(
                {
                    "op": "add_dhcp_network",
                    "address": normalizada["address"],
                    "gateway": normalizada["gateway"],
                    "dns": normalizada["dns"],
                }
            )
        # Las reservas de ESTE servidor: su ámbito es la RED que sirve (`red.prefijo`)
        # y, si no la declara, el bridge en el que vive el invitado.
        reservas = reservas_derivadas(
            declaracion, identidad, guest, en_red=red.get("address")
        )
        # El prefijo no entra en la comparación: RouterOS guarda la dirección pelada
        # (`10.40.1.11`), y compararla con `10.40.1.11/24` haría que la reserva no
        # cuadrara NUNCA y se reescribiera en cada pasada.
        deseadas = {
            str(r["mac"]).upper(): str(r["address"]).split("/")[0] for r in reservas
        }
        # Y las que HAY: sólo las que sirve ESTE servidor (ver
        # `_reserva_es_de_este_servidor`). El nombre del servidor es derivado
        # (`netlabs-<interfaz>`): se lee si ya existe --y entonces se compara con el nombre
        # de verdad, por si alguien lo renombró-- y si no (es la pasada en la que se crea)
        # se deriva, que es lo mismo.
        nombre_servidor = str((encontrado or {}).get("nombre") or "") or (PREFIJO_POOL + interfaz)
        actuales = {
            str(r.get("mac")).upper(): str(r.get("address"))
            for r in ((leido or {}).get("static_leases") or [])
            if _reserva_es_de_este_servidor(
                r, nombre_servidor, str(red.get("address") or ""), len(declarado or [])
            )
        }
        for mac, direccion in sorted(deseadas.items()):
            if actuales.get(mac) != direccion:
                operaciones.append(
                    {
                        "op": "add_static_lease",
                        "mac": mac,
                        # Una reserva es una DIRECCIÓN, no una red: RouterOS guarda
                        # `10.40.1.11` y no `10.40.1.11/24`, y comparar con el prefijo
                        # haría que la reserva no cuadrara nunca (reescritura eterna).
                        "address": direccion.split("/")[0],
                        # Y va atada al servidor de ESA interface: un router con dos LANs
                        # no puede reservar en la primera lo que vive en la segunda.
                        "interface": interfaz,
                    }
                )
        for mac in sorted(set(actuales) - set(deseadas)):
            operaciones.append({"op": "remove_static_lease", "mac": mac})

    # Las interfaces con DHCP que ya no se declaran: se quitan (dentro del área, lo
    # que no está declarado sale).
    declaradas = {str(s.get("interface")) for s in (declarado or [])}
    for candidato in (leido or {}).get("servidores") or []:
        if str(candidato.get("interface")) not in declaradas:
            operaciones.append(
                {"op": "remove_dhcp_server", "interface": str(candidato.get("interface"))}
            )
    return operaciones


def _misma_red(una, otra, prefijo):
    """¿Dos direcciones caen en la misma red? (a mano: el motor no importa librerías).

    Se usa para decidir si la dirección que YA tiene la interfaz de fuera es de la red por la que
    se sale -- y adoptarla, en vez de renumerarla en cada pasada.
    """
    try:
        octetos_una = [int(x) for x in str(una).split(".")]
        octetos_otra = [int(x) for x in str(otra).split(".")]
        bits = int(prefijo)
    except (TypeError, ValueError):
        return False
    if len(octetos_una) != 4 or len(octetos_otra) != 4 or not 0 <= bits <= 32:
        return False
    mascara = ((1 << bits) - 1) << (32 - bits) if bits else 0
    valores = [
        (o[0] << 24) | (o[1] << 16) | (o[2] << 8) | o[3] for o in (octetos_una, octetos_otra)
    ]
    return (valores[0] & mascara) == (valores[1] & mascara)


def _uplink_canonico(declarado, leido, parametros):
    """Diferencia del área `uplink`: que la interfaz de fuera tenga salida, y nada más.

    Cuatro hechos, y ninguno se supone:
      * una dirección en la interfaz de fuera -- la que el motor DERIVA de la red por la que sale
        el nodo (el lab no declara ninguna dirección de casa);
      * una ruta por defecto (la que sea: si el lab ya declaró una, esa vale -- el consejo
        `exterior-con-ruta` avisa de que lo normal es no declararla y dejar que la ponga el
        motor por la pasarela de fuera);
      * la regla de MASQUERADE del motor (sus direcciones son privadas: sin traducirlas la
        respuesta no vuelve);
      * el resolutor DNS encendido Y apuntando a la pasarela de fuera, que es donde este nodo
        sirve el DNS de esa red (sin eso, los invitados que salen por aquí resuelven con
        quien no es).

    Lo que no es del motor no se toca: otra regla de NAT, otra ruta, otra dirección en esa
    interfaz (regla 17: el motor manda dentro de lo que declara, y sólo ahí).
    """
    if not isinstance(leido, dict):
        return []
    interfaz = str(leido.get("interface") or "")
    direccion = str(parametros.get("salida_direccion") or "")
    gateway = str(parametros.get("salida_acceso") or "")
    operaciones = []
    # La dirección, y una sola: si la interfaz YA tiene una de la red por la que se sale, el motor
    # la ADOPTA (no la renumera). Medido: derivándola en cada pasada el motor dejaba una
    # dirección nueva por pasada -- y el `changed` no bajaba nunca a cero. Las que sobren se
    # quitan, que es la regla de siempre dentro de un área declarada (regla 17).
    ya_puesta = str(leido.get("de_la_red") or "")
    deseada = direccion
    if ya_puesta and "/" in direccion and _misma_red(ya_puesta, gateway or direccion, direccion.split("/")[1]):
        deseada = f"{ya_puesta}/{direccion.split('/')[1]}"
    puestas = [str(d) for d in (leido.get("todas") or [])]
    for puesta in puestas:
        if puesta != deseada:
            operaciones.append(
                {
                    "op": "remove_address",
                    "interface": interfaz,
                    "address": puesta,
                    "id": str((leido.get("ids") or {}).get(puesta) or ""),
                }
            )
    if deseada and deseada not in puestas:
        operaciones.append({"op": "add_address", "interface": interfaz, "address": deseada})
    if gateway and not str(leido.get("por_defecto") or ""):
        operaciones.append({"op": "add_route", "dst_address": "0.0.0.0/0", "gateway": gateway})
    if not leido.get("masquerade"):
        operaciones.append({"op": "add_masquerade", "interface": interfaz})
    if not leido.get("resolutor") or gateway not in str(leido.get("servidores") or ""):
        operaciones.append({"op": "enable_dns_resolver", "servidores": [gateway] if gateway else []})
    return operaciones


def _address_linux_canonica(declarado, leido):
    """Diferencia del área `address` de un Linux.

    `address: dhcp` no se escribe: se COMPRUEBA (§6.3). Por eso aquí no hay
    operaciones, y la comprobación de que la concesión está dentro del rango
    declarado la hace `verify`, que sí mira la tabla de concesiones.

    El área admite dos formas, y la segunda existe por una razón medida: un puesto de
    control necesita UNA dirección por cada bridge del lab para poder llegar a los
    invitados que cuelgan de él. Cuando el lab declara `addresses` (lista de
    `{interfaz, direccion}`), se comparan una a una; la de gestión sigue viniendo del
    campo `address` del invitado, que es lo que el plan usa para el túnel.
    """
    if not declarado or str(declarado) == "dhcp":
        return []
    actuales = (leido or {}).get("addresses") or []
    if isinstance(declarado, list):
        # Si la lectura no trae la lista de interfaces (un motor viejo, o una lectura parcial),
        # se usa la de gestión: es la única que se conocía antes de esta forma, y sin este
        # respaldo el área se creería sin hacer y volvería a escribir en cada pasada.
        if not actuales and (leido or {}).get("address"):
            actuales = [{"interface": "eth0", "address": (leido or {}).get("address")}]
        tengo = {(str(p.get("interface")), str(p.get("address"))) for p in actuales}
        return [
            {
                "op": "add_address",
                "interface": str(p.get("interface")),
                "address": str(p.get("address")),
            }
            for p in declarado
            if (str(p.get("interface")), str(p.get("address"))) not in tengo
        ]
    operaciones = []
    if str((leido or {}).get("address") or "") != str(declarado):
        operaciones.append(
            {"op": "add_address", "interface": "eth0", "address": str(declarado)}
        )
    return operaciones


def _ip_forward_canonico(declarado, leido):
    """Diferencia del área `ip_forward`: `ip_forward` (lo necesita el servidor DHCP)."""
    if declarado and not (leido or {}).get("activo"):
        return [{"op": "enable_ip_forward"}]
    return []


def _dnsmasq_canonico(declarado, leido, declaracion, identidad, guest):
    """Diferencia del área `dhcp_server` de un Linux: dnsmasq, reservas y el
    apagado del offload del checksum, sin el cual las ofertas DHCP salen rotas y el
    kernel del CHR las tira (medido en v3, y sigue siendo cierto).

    El ámbito de sus reservas es el bridge en el que vive el invitado: un Linux sirve
    la red del bridge al que está colgado, que es justo donde están los demás.
    """
    if not declarado:
        return []
    reservas = reservas_derivadas(declaracion, identidad, guest)
    operaciones = []
    interfaz = str(declarado.get("interface") or "")
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
        operaciones.append({"op": "install_tools", "paquetes": faltan})
    if str(actual.get("interface") or "") != interfaz or str(actual.get("rango") or "") != rango:
        operaciones.append({"op": "write_dnsmasq", "interface": interfaz, "rango": rango})
        hay_que_recargar = True
    if not actual.get("offload_apagado"):
        # Sin esto las ofertas DHCP salen con el checksum sin resolver y el kernel del
        # CHR las tira (medido en v3 y comprobado en esta fase): el laboratorio entero
        # depende de esta línea.
        operaciones.append({"op": "disable_offload", "interface": interfaz})
        hay_que_recargar = True
    # Sin el prefijo: la reserva vive DENTRO del rango del bridge (eso ya lo valida la
    # declaración) y dnsmasq guarda la dirección pelada. Comparar con el prefijo haría que
    # las reservas nunca cuadraran y el fichero se reescribiera en cada pasada.
    deseadas = {str(r["mac"]).upper(): str(r["address"]) for r in reservas}
    actuales = {
        str(r.get("mac")).upper(): str(r.get("address")).split("/")[0]
        for r in (actual.get("static_leases") or [])
    }
    for mac, direccion in sorted(deseadas.items()):
        # Se compara por DIRECCIÓN: la derivada lleva su prefijo y dnsmasq guarda la
        # dirección pelada. La operación sí lleva el valor derivado entero, que es el que
        # manda al fichero (la comparación es lo único que se normaliza).
        if actuales.get(mac) != direccion.split("/")[0]:
            operaciones.append({"op": "add_static_lease", "mac": mac, "address": direccion})
            hay_que_recargar = True
    for mac in sorted(set(actuales) - set(deseadas)):
        operaciones.append({"op": "remove_static_lease", "mac": mac})
        hay_que_recargar = True
    if hay_que_recargar or not actual.get("servicio_activo"):
        operaciones.append({"op": "reload_dnsmasq"})
    return operaciones


def _tunnel_canonico(declarado, leido):
    """Diferencia del área `tunnel`. Lo ESCRIBE la consola, una sola vez por vida del
    invitado: aquí sólo se decide si hay que volver a mandar la línea."""
    if declarado is None:
        return []
    if (leido or {}).get("salida"):
        return []
    return [{"op": "send_console_line"}]


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


def pasos_de_convergencia(guest, identidad, declaracion, leido, parametros):
    """(declarado, leído) -> pasos del interior de ESTE invitado, en orden.

    `identity` es el mapa del LAB entero (no la identidad de este invitado): las
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
    tipo = tipo_de(guest)
    if tipo is None:
        return []
    if not areas_que_piden_visita(guest):
        # Nada que hacer DENTRO: la única área es una dirección dinámica, que se lee del
        # HOST (§6.3). Entrar sería a ciegas (no se sabe a qué dirección conectar).
        return []
    rol = guest.get("rol")
    declaradas = areas_de(guest)

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
                guest,
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
            f"alcanzar para convergerlo: {leido.get('motivo') or 'sin túnel'}. "
            "El verbo para aquí en vez de seguir a ciegas."
        )

    areas_leidas = leido.get("areas") or {}

    # La identidad de un RouterOS va la ÚLTIMA en la primera convergencia: primero
    # se añade y se verifica lo nuevo, y sólo entonces se cambia el equipo por
    # dentro. Si se cambiara antes, un fallo a mitad dejaría el equipo accesible con
    # las credenciales viejas y sin túnel de vuelta para el motor.
    #
    # «Primera convergencia» no se adivina por la forma del mapa leído: se decide con
    # lo que las operaciones dicen. Si la identidad no tiene nada que cambiar, no hay
    # paso de identidad y el orden da igual.
    operaciones_identidad = (
        _identity_canonica(declaradas["identity"], areas_leidas.get("identity"))
        if "identity" in declaradas
        else None
    )
    orden = list(declaradas.keys())
    if tipo == "routeros" and operaciones_identidad:
        orden.remove("identity")
        orden.append("identity")

    pasos = []
    for area in orden:
        actual = areas_leidas.get(area)
        if area == "identity":
            operaciones = operaciones_identidad or []
        elif area == "ip_services":
            operaciones = _ip_services_canonicos(declaradas[area], actual)
        elif area == "dhcp_client":
            operaciones = _dhcp_client_canonico(declaradas[area], actual)
        elif area == "addresses":
            operaciones = _addresses_canonicas(declaradas[area], actual)
        elif area == "routes":
            operaciones = _routes_canonicas(declaradas[area], actual)
        elif area == "uplink":
            operaciones = _uplink_canonico(declaradas[area], actual, parametros)
        elif area == "address":
            operaciones = _address_linux_canonica(declaradas[area], actual)
        elif area == "ip_forward":
            operaciones = _ip_forward_canonico(declaradas[area], actual)
        elif area == "dhcp_server":
            # El área se llama igual en los dos drivers: quién la atiende lo decide
            # el tipo de equipo, no el nombre del área.
            if tipo == "routeros":
                operaciones = _dhcp_server_canonico(
                    declaradas[area], actual, declaracion, identidad, guest
                )
            else:
                operaciones = _dnsmasq_canonico(
                    declaradas[area], actual, declaracion, identidad, guest
                )
        elif area == "tunnel":
            operaciones = _tunnel_canonico(declaradas[area], actual)
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
                    guest,
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
                "accion": "reiniciar_guest",
                "via": "api",
                "rol": rol,
                "stage": guest.get("stage"),
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


def espera_de_servicio(guest):
    """El paso que comprueba que un invitado CONTESTA --la barrera que va DELANTE de
    converger su interior-- y, con eso, que su etapa sirve antes de pasar al
    siguiente (regla 18: nunca se arranca una etapa antes de que el anterior esté
    convergido y sirviendo).

    Va antes del interior y no al final de la etapa porque un invitado recién arrancado
    no contesta al instante: un CHR tarda en bootear y en pedir su dirección por DHCP,
    y convergerlo nada más arrancarlo aborta la pasada. La sonda le da ese tiempo.

    No es un `wait_for` sobre el invitado: es una petición a la dirección que la
    declaración promete, en el puerto por el que ese tipo se deja ver (el REST de
    RouterOS, el sshd de un Linux). No necesita identity: la sonda va a la
    dirección declarada, que es lo que la declaración promete.
    """
    tipo = tipo_de(guest)
    if tipo is None:
        return None
    # Sólo se sondea lo que la declaración PROMETE con una dirección fija: un equipo que
    # toma su dirección por DHCP (`address: dhcp`) no tiene dirección que preguntar hasta
    # que su router se la da, así que no hay sonda que valga -- y no se inventa una. El
    # etapa se arranca sin barrera y el lab lo dice en su prosa.
    if _a_entero(_sin_prefijo(guest.get("address"))) is None:
        return None
    puerto = 80 if tipo == "routeros" else 22
    return {
        "accion": "esperar_servicio",
        "via": "sonda",
        "rol": guest.get("rol"),
        "stage": guest.get("stage"),
        "metodo": None,
        "ruta": None,
        "parametros": {
            "tipo": tipo,
            "address": str(guest.get("address") or "").split("/")[0],
            "puerto": puerto,
        },
        "porque": (
            f"el interior de '{guest['rol']}' no se toca hasta que contesta: un "
            f"invitado de la etapa {guest.get('stage')} recién arrancado tarda en "
            f"dar señales en el puerto {puerto}"
        ),
    }


# ---------------------------------------------------------------------------
# (declaración) -> el bastión; y las LECTURAS y ESCRITURAS de un Linux
# ---------------------------------------------------------------------------

def bastion(declaracion):
    """El ROL del invitado que es el bastión del lab (el bastión del túnel).

    No se pregunta por un nombre ni por un vmid: se pregunta quién declara `tunnel`,
    que es lo que hace que un invitado sea el que sale hacia casa. Devuelve '' si el
    lab no declara ninguno, y entonces `apply` dice que no hay por dónde entrar (regla
    16) en vez de intentarlo.
    """
    # La declaración que circula por el motor está NORMALIZADA: sus invitados son una
    # lista plana (`guests`), cada uno con su `tipo`. Se lee igual que en el resto de
    # este fichero -- una sola forma de leer la declaración, o hay dos verdades.
    for guest in (declaracion or {}).get("guests") or []:
        if tiene_tunnel(guest):
            return guest.get("rol") or ""
    return ""


# Las lecturas, una por área, y el porqué de cada comando. Van aquí (y no en el
# playbook) porque son DATOS: el driver no decide qué preguntar, lo lee de aquí.
#
# Todas son de SOLO LECTURA y baratas: una vuelta de SSH por área, con el túnel.
# Ninguna necesita `root` para preguntar, pero se entra como root porque para
# ESCRIBIR sí hace falta, y usar dos usuarios distintos según el paso sería una
# complicación sin premio.
LECTURAS_LINUX = {
    "address": {
        # TODAS las interfaces con dirección (no sólo eth0): el bastión declara una
        # dirección por cada bridge del lab, porque un CHR del segundo etapa cuelga de un
        # bridge al que el puesto sólo llega si tiene interfaz con dirección ahí (medido: sin
        # ella, el router no contesta y su convergencia es imposible).
        "comando": "ip -4 -o addr show scope global",
        "descripcion": "las direcciones de sus interfaces (gestión y bridges del lab)",
    },
    "ip_forward": {
        "comando": "cat /proc/sys/net/ipv4/ip_forward",
        "descripcion": "si el equipo reenvía paquetes (lo necesita su servidor DHCP)",
    },
    "tunnel": {
        "comando": "systemctl is-active netlabs-tunnel",
        "descripcion": "si la salida hacia casa está levantada",
    },
    "dhcp_server": {
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


def lecturas_linux(guest):
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
        for area in areas_a_leer(guest)
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

        if area == "address":
            partes = lineas[0].split() if lineas else []
            # `ip -4 -o addr show scope global` -> "3: eth0    inet 10.40.0.10/24 ..."
            # Una línea por interfaz con dirección: la de gestión (eth0, la que el plan usa
            # para el túnel) y las que el lab declare para los bridges del lab.
            interfaces = []
            for linea in lineas:
                trozos = linea.split()
                if len(trozos) > 3 and trozos[2] == "inet":
                    interfaces.append({"interface": trozos[1], "address": trozos[3]})
            de_gestion = [p for p in interfaces if p["interface"] == "eth0"]
            leido["address"] = {
                "address": (de_gestion or interfaces or [{"address": ""}])[0]["address"],
                "addresses": interfaces,
            }

        elif area == "ip_forward":
            leido["ip_forward"] = {"activo": (lineas[0] if lineas else "") == "1"}

        elif area == "tunnel":
            leido["tunnel"] = {"salida": (lineas[0] if lineas else "") == "active"}

        elif area == "claves":
            try:
                leido["claves"] = {"cuantas": int(lineas[0])} if lineas else {"cuantas": 0}
            except ValueError:
                leido["claves"] = {"cuantas": 0}

        elif area == "dhcp_server":
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
                        reservas.append({"mac": partes[0], "address": partes[1]})
            # El servicio: sin esto el motor no sabe si dnsmasq está vivo, y `recargar` se pediría
            # en CADA pasada -- que es exactamente romper la idempotencia.
            servicio = _lineas(bloques[3] if len(bloques) > 3 else "")
            leido["dhcp_server"] = {
                "static_leases": reservas,
                "servicio_activo": bool(servicio) and servicio[0] == "active",
                "interface": _valor(configuracion, "interface", prefijo="").lstrip(),
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
    interfaz = str((declarado or {}).get("interface") or "")
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
        if reserva.get("mac") and reserva.get("address"):
            lineas.append(f"dhcp-host={reserva['mac']},{reserva['address'].split('/')[0]}")
    return "\n".join(lineas) + "\n"


# La ruta del fichero del servidor DHCP, en un solo sitio: la usan el que lo escribe y
# el que comprueba si ya se escribió (dos literales separados se desincronizan).
RUTA_DNSMASQ = "/etc/dnsmasq.d/netlabs.conf"


def escrituras_linux(operaciones, guest, declaracion, identidad, parametros):
    """(operaciones decididas) -> los comandos que las ejecutan, en orden.

    Función PURA: no ejecuta nada, sólo traduce una operación a la línea que la hace.
    Cada comando es IDEMPOTENTE (`ip addr replace`, `apt-get install -y`, reescribir el
    fichero entero, `ethtool -K` con el valor final): volver a aplicarlo deja el sistema
    igual, que es lo que hace verdadera la promesa de la regla 6.
    """
    declarado = areas_de(guest)
    comandos = []
    for operacion in operaciones or []:
        op = operacion.get("op")

        if op == "add_address":
            comandos.append({
                "area": "address", "accion": "escribir", "declarado": operacion.get("address"),
                "descripcion": "poner su dirección declarada",
                "comando": f"ip addr replace {operacion['address']} dev {operacion.get('interface') or 'eth0'}",
            })

        elif op == "enable_ip_forward":
            comandos.append({
                "area": "ip_forward", "accion": "escribir", "declarado": "true",
                "descripcion": "dejar que reenvíe paquetes",
                "comando": "sysctl -q -w net.ipv4.ip_forward=1 && printf 'net.ipv4.ip_forward=1\\n' > /etc/sysctl.d/99-netlabs.conf",
            })

        elif op in ("install_packages", "install_tools"):
            paquetes = " ".join(operacion.get("paquetes") or ["dnsmasq", "ethtool"])
            comandos.append({
                "area": "dhcp_server", "accion": "escribir", "declarado": paquetes,
                "descripcion": f"poner en el aparato del motor lo que el servidor DHCP necesita: {paquetes}",
                "comando": f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {paquetes}",
            })

        elif op in ("write_dnsmasq", "add_static_lease", "remove_static_lease"):
            # Las tres son la MISMA cosa: el fichero lleva TODAS las reservas, así que
            # cambiar una se hace reescribiéndolo entero. Reescribirlo dos veces en la
            # misma pasada sería trabajo duplicado: se hace una sola vez. El marcador es
            # la RUTA del fichero, escrita entera: buscar un trozo dio un fallo real
            # («dnsmasq.conf» NO está en «/etc/dnsmasq.d/netlabs.conf»).
            if not any(RUTA_DNSMASQ in c["comando"] for c in comandos):
                reservas = reservas_derivadas(declaracion, identidad, guest)
                configuracion = configuracion_dnsmasq(declarado.get("dhcp_server"), reservas)
                comandos.append({
                    "area": "dhcp_server", "accion": "escribir",
                    "declarado": f"{declarado.get('dhcp_server', {}).get('rango')} + {len(reservas)} reserva(s) derivada(s)",
                    "descripcion": "escribir su configuración de servidor DHCP (con las reservas derivadas)",
                    "comando": f"echo {_b64(configuracion)} | base64 -d > {RUTA_DNSMASQ}",
                })

        elif op == "disable_offload":
            interfaz = str((declarado.get("dhcp_server") or {}).get("interface") or "eth0")
            comandos.append({
                "area": "dhcp_server", "accion": "escribir", "declarado": "off",
                "descripcion": "apagar los offloads de la interfaz (sin esto las ofertas DHCP no llegan al CHR)",
                "comando": f"ethtool -K {interfaz} tx off gso off tso off",
            })

        elif op == "reload_dnsmasq":
            comandos.append({
                "area": "dhcp_server", "accion": "escribir", "declarado": "activo",
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
        "add_address", "enable_ip_forward", "install_packages", "install_tools",
        "write_dnsmasq", "add_static_lease", "remove_static_lease",
        "disable_offload", "reload_dnsmasq",
    }
    op = (operacion or {}).get("op")
    if op in conocidas:
        return None
    return op



def comando_de(resultado):
    """El comando que produjo un resultado de la vía de acceso (`tasks/interior_ssh.yml`).

    Ansible NO deja la clave `item` cuando el bucle usa `loop_var` propio: deja el nombre
    que le diste (`interior_comando`) y lo dice en `ansible_loop_var`. Se leen las dos
    formas porque un analizador que sólo entiende `item` se queda mudo -- y pasó: el
    motor entró en el invitado, lo leyó (rc=0 en el diario) y luego dijo «el driver no leyó
    el área 'tunnel'», que era mentira.
    """
    if not isinstance(resultado, dict):
        return {}
    nombre = resultado.get("ansible_loop_var")
    if nombre and isinstance(resultado.get(nombre), dict):
        return resultado[nombre]
    return resultado.get("item") or {}


def leido_de_lecturas(resultados, guest):
    """(lo que devolvió la vía de acceso) -> el mapa `leído` que come `pasos_de_convergencia`.

    `resultados` es lo que deja la vía de acceso (`interior_ssh.yml`): una lista con el
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
        "guest": (guest or {}).get("rol"),
    }


def operaciones_de_pasos(pasos):
    """Aplana las operaciones de los pasos del interior, en orden.

    El plan habla de PASOS; el driver ejecuta OPERACIONES. Esto es la traducción, y
    va aquí (pura) para que el playbook no lleve lógica.

    A cada operación se le estampa su ÁREA: la operación dice QUÉ hay que cambiar y el
    área dice DÓNDE. Sin el área, quien traduce (Linux o RouterOS) tendría que adivinar
    de qué parte del equipo se trata -- y un mensaje de error sin área no se puede
    arreglar.
    """
    operaciones = []
    for paso in pasos or []:
        area = (paso.get("parametros") or {}).get("area")
        for operacion in ((paso.get("parametros") or {}).get("operaciones") or []):
            operaciones.append(dict(operacion, area=area))
    return operaciones


def requiere_lectura(area, leido):
    """¿El área declarada necesita releerse para comprobar la convergencia?

    Se relee TODO lo declarado y declarado-se-compara: la verificación no es «el
    comando no dio error», es «el estado real coincide con lo declarado» (los dos
    sentidos). Función aparte porque el orden importa: primero se escribe, después se
    lee, y lo que se lee es lo mismo que se leyó antes.
    """
    return area in (leido or {}).get("areas", {})


# ---------------------------------------------------------------------------
# RouterOS: lo que se lee por su REST y lo que se escribe por su REST
# ---------------------------------------------------------------------------
# Un RouterOS no se toca por SSH en este motor (regla 13): se lee y se escribe por su
# REST, que es la misma vía de acceso (`tasks/ros_api.yml`). Igual que en Linux, las lecturas
# son DATOS y no lógica: el driver no decide qué preguntar, lo lee de aquí.
#
# Cada ruta se eligió midiendo un CHR real (7.25.1): `/system/identity` contesta un
# OBJETO (`{"name":"CHR"}`) y una tabla contesta una LISTA. El analizador sabe leer las
# dos formas porque las dos existen.
LECTURAS_ROUTEROS = {
    "identity": (
        ("/system/identity", "el nombre del equipo"),
        ("/user", "los usuarios que tiene (el del motor, si está)"),
        ("/user/ssh-keys", "las claves autorizadas (la del motor, si está importada)"),
    ),
    "ip_services": (("/ip/service", "qué servicios de gestión tiene abiertos"),),
    "dhcp_client": (("/ip/dhcp-client", "el cliente de fábrica, si sigue vivo"),),
    "addresses": (("/ip/address", "sus direcciones, estáticas y dinámicas"),),
    "routes": (("/ip/route", "sus rutas: estáticas, conectadas y las del DHCP"),),
    "dhcp_server": (
        ("/ip/dhcp-server", "los servidores DHCP que tiene"),
        ("/ip/pool", "los rangos de direcciones que reparte"),
        ("/ip/dhcp-server/network", "las redes que anuncia"),
        ("/ip/dhcp-server/lease", "sus concesiones y sus reservas"),
    ),
    # La salida del lab: la tabla de NAT (para saber si la regla del motor está), el
    # resolutor y el cliente de fuera (su concesión es la prueba de que la interfaz tiene red).
    "uplink": (
        ("/ip/address", "la dirección de la interfaz de fuera (si la tiene)"),
        ("/ip/route", "por dónde manda lo que no es de ninguna de sus redes"),
        ("/ip/firewall/nat", "sus reglas de NAT (la del motor, si está)"),
        ("/ip/dns", "cómo tiene el resolutor y a quién le pregunta"),
    ),
}

# El nombre del rango de direcciones que el motor crea en el router. Se deriva del rango
# declarado (`10.40.1.100-10.40.1.200` -> `netlabs-10.40.1.100`): el lab declara el
# rango, no el nombre de un objeto intermedio del equipo, y así no hay que guardar nada.
PREFIJO_POOL = "netlabs-"

# La interfaz de gestión de un RouterOS: la primera, y donde vive el cliente DHCP de fábrica
# (medido en un CHR: `ether1`, con su concesión dinámica). No es un valor de ningún lab:
# es cómo numera RouterOS sus interfaces ethernet (empieza en 1, y `net0` de Proxmox es
# `ether1` del router). El motor la usa para poner la dirección de gestión DERIVADA del
# `address:` del invitado, que es lo que impide dejarlo sin túnel de vuelta.
INTERFAZ_GESTION_ROUTEROS = "ether1"

# --- El uplink: la salida del lab -------------------------------------------
# Un router que declara `uplink` es la pasarela del lab hacia fuera. La interfaz de fuera la
# añade el PLAN (una más, la ÚLTIMA, sobre el bridge del nodo que tiene salida: valor de
# entorno, `pve_bridge_gestion` en secrets.yml, nunca del lab), así que su interfaz no se
# declara: se deriva de cuántas interfaces declaró el invitado. En un router con dos bridges el
# exterior es `ether3`.
#
# Lo que hace el motor con esa interfaz es lo mínimo para que haya salida, y ninguna de las
# tres cosas lleva un valor de casa dentro:
#   * un cliente DHCP en esa interfaz, que es lo que le da dirección, ruta por defecto y
#     servidores DNS de la red de fuera (sin que el motor tenga que saber ninguno);
#   * MASQUERADE por esa interfaz, porque las direcciones del lab son privadas y sin
#     traducirlas no vuelven;
#   * el resolutor DNS del router encendido (`allow-remote-requests`), para que los
#     invitados que lo tienen de pasarela puedan resolver nombres.
MARCA_EXTERIOR = "netlabs-uplink"


def interfaces_de_un_guest(guest):
    """Las interfaces DECLARADAS de un invitado, en orden: la lista `bridges` de una VM, o el
    `bridge` suelto de un contenedor.

    Vive aquí y no se importa de `declaracion.py` a propósito: la flecha va de la
    validación al interior, nunca al revés (sería un círculo).
    """
    interfaces = guest.get("bridges")
    if isinstance(interfaces, list) and interfaces:
        return [str(interface) for interface in interfaces]
    if guest.get("bridge"):
        return [str(guest["bridge"])]
    return []


def interfaz_exterior(guest):
    """La interfaz de la interfaz de fuera de un RouterOS, o '' si no declara `uplink`.

    Se DERIVA: es la siguiente a las interfaces declaradas (el plan añade la suya al final).
    Así el lab no nombra una interfaz que no ha declarado -- si lo hiciera, la validación
    la rechazaría, porque no está entre sus interfaces, y con razón.
    """
    if "uplink" not in ((guest.get("config") or {}).get("routeros") or {}):
        return ""
    return f"ether{len(interfaces_de_un_guest(guest)) + 1}"

# Los campos que son credenciales: si alguno viaja en el cuerpo de una llamada, su valor
# se tapa en el diario. Por NOMBRE y no por confianza en el llamante: la contraseña del
# motor viaja de verdad en el cuerpo de `set_engine_credential`, y un descuido no puede
# acabar con ella escrita en un fichero.
CAMPOS_SECRETOS = ("password", "passphrase", "clave", "key", "secret", "private-key")


def sin_secretos(datos):
    """Copia de `datos` con los valores de los campos que son credenciales tapados.

    Recursiva: los cuerpos de RouterOS llevan listas y mapas anidados, y una contraseña
    escondida un nivel más abajo se escaparía de una comprobación plana.
    """
    if isinstance(datos, dict):
        return {
            clave: ("···" if str(clave).lower() in CAMPOS_SECRETOS else sin_secretos(valor))
            for clave, valor in datos.items()
        }
    if isinstance(datos, (list, tuple)):
        return [sin_secretos(valor) for valor in datos]
    return datos


def lecturas_routeros(guest):
    """Las lecturas que hay que hacer por REST en un RouterOS, por área declarada.

    Sólo se pregunta por lo que el lab DECLARA: fuera de las áreas declaradas el motor
    no opina (regla 17), así que tampoco pregunta.
    """
    lecturas = []
    for area in areas_a_leer(guest):
        for ruta, descripcion in LECTURAS_ROUTEROS.get(area, ()):
            lecturas.append(
                {
                    "area": area,
                    "accion": "leer",
                    "metodo": "GET",
                    "ruta": ruta,
                    "descripcion": descripcion,
                }
            )
    return lecturas


def _ros_lista(datos):
    """Lo que contestó el REST, como lista.

    RouterOS contesta LISTA al preguntar por una tabla y OBJETO al preguntar por un dato
    suelto. Se respeta la diferencia (no se normaliza a la brava) pero se presenta de la
    única forma que las diferencias saben recorrer.
    """
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        return [datos] if datos else []
    return []


def _ros_si(valor):
    """RouterOS dice los booleanos como cadenas: "true" / "false"."""
    return str(valor).lower() in ("true", "yes", "1")


def _ros_ids(entradas, clave=lambda e: None):
    """{clave: .id} de una tabla de RouterOS: es lo que hace falta para ESCRIBIR."""
    ids = {}
    for entrada in entradas:
        nombre = clave(entrada)
        if nombre is not None:
            ids[str(nombre)] = str(entrada.get(".id") or "")
    return ids


def _ros_clave(*partes):
    """La clave con la que se recuerda el `.id` de algo compuesto.

    En una dirección o en una ruta hacen falta DOS cosas para identificarlas (la
    interfaz y la dirección; el destino y la pasarela), y en un router con dos interfaces la
    dirección sola no basta. Se unen en una CADENA y no en una tupla: esto viaja por
    hechos de Ansible, y una tupla como clave de un mapa se rompe en cuanto algo lo
    serializa a JSON.
    """
    return "|".join(str(parte) for parte in partes)


def leido_routeros(leidos, guest=None, usuario_motor="", clave_publica="", credencial="motor"):
    """(lo que contestó el REST) -> el mapa `leído` que comen las diferencias.

    `leidos` es lo que acumula la gateway: `{ruta: {area, status, json, error}}`. Función
    PURA: se prueba con fixtures, sin RouterOS delante.

    La primera decisión es si al equipo se le pudo PREGUNTAR, y ahí un `status` -1 (no
    se pudo conectar) NO es lo mismo que un 401 (se llegó y la credencial que llevo no
    vale). El segundo caso es legítimo la primera vez --el equipo aún tiene la de
    fábrica-- y el driver lo usa para decidir con cuál converger; el primero PARA el
    verbo, porque no se escribe a ciegas.
    """
    leidos = leidos or {}
    areas = {}
    motivo = ""
    for entrada in leidos.values():
        if int((entrada or {}).get("status") or 0) == -1 and not motivo:
            motivo = str((entrada or {}).get("error") or "no se pudo conectar con el invitado")

    # --- identity: el nombre, el usuario del motor y su clave ---
    if "/system/identity" in leidos:
        identidad = leidos.get("/system/identity") or {}
        nombre_dato = identidad.get("json")
        nombre = str(nombre_dato.get("name") or "") if isinstance(nombre_dato, dict) else ""
        usuarios = _ros_lista((leidos.get("/user") or {}).get("json"))
        existe_usuario = any(str(u.get("name") or "") == str(usuario_motor) for u in usuarios)
        claves = _ros_lista((leidos.get("/user/ssh-keys") or {}).get("json"))
        clave_puesta = any(
            str(k.get("user") or "") == str(usuario_motor)
            and str(k.get("key") or "").strip().startswith(str(clave_publica).strip()[:40])
            for k in claves
            if str(clave_publica).strip()
        )
        areas["identity"] = {
            "nombre": nombre,
            "usuario_motor": existe_usuario,
            # Se llegó con la credencial del motor: eso ES el estado «la credencial del
            # motor está puesta». No se puede leer de otra forma sin escribir.
            "credencial_motor": str(credencial) == "motor",
            "clave_motor": clave_puesta,
            "usuarios": _ros_ids(usuarios, lambda u: u.get("name")),
        }

    # --- servicios ---
    # Sólo las entradas ESTÁTICAS son configuración. Un RouterOS lista también las
    # entradas DINÁMICAS de su tabla de servicios -- las conexiones vivas y los servicios
    # que levanta un proceso (medido: `www` aparece dos veces, una estática `*2` y otra
    # dinámica `*E` con la conexión del propio motor) --, y tomarlas por configuración
    # daría un `.id` que no se puede tocar y un estado que cambia con cada llamada.
    if "/ip/service" in leidos:
        servicios = [
            s
            for s in _ros_lista((leidos.get("/ip/service") or {}).get("json"))
            if not _ros_si(s.get("dynamic"))
        ]
        areas["ip_services"] = {
            "deshabilitados": [str(s.get("name")) for s in servicios if _ros_si(s.get("disabled"))],
            "habilitados": [str(s.get("name")) for s in servicios if not _ros_si(s.get("disabled"))],
            "ids": _ros_ids(servicios, lambda s: s.get("name")),
        }

    # --- dhcp_client: el de fábrica, el de las interfaces DEL LAB ---
    # El cliente de la interfaz de FUERA (área `uplink`) no cuenta aquí, y es una decisión:
    # no es un residuo, es la salida del lab. Si contara, el motor lo quitaría --quitar el
    # cliente de fábrica se lleva TODOS los que encuentre-- y el lab se quedaría sin salida
    # en la primera pasada; y mientras estuviera vivo, el residuo dinámico no se declararía
    # nunca y el intercambio de la dirección de gestión no llegaría a hacerse, así que la
    # segunda pasada pediría cosas de más (la idempotencia se rompe justo por aquí).
    exterior = interfaz_exterior(guest)
    cliente = []
    if "/ip/dhcp-client" in leidos:
        cliente = [
            entrada
            for entrada in _ros_lista((leidos.get("/ip/dhcp-client") or {}).get("json"))
            if str(entrada.get("interface")) != exterior
        ]
        areas["dhcp_client"] = {
            "habilitado": any(not _ros_si(c.get("disabled")) for c in cliente),
            "interfaces": [str(c.get("interface")) for c in cliente],
            "ids": _ros_ids(cliente, lambda c: c.get("interface")),
        }

    # --- addresses: estáticas y dinámicas, separadas (la dinámica es RESIDUO) ---
    direcciones = []
    if "/ip/address" in leidos:
        direcciones = _ros_lista((leidos.get("/ip/address") or {}).get("json"))
        # La interfaz de FUERA no es una interfaz del lab: su dirección no la manda esta área, la
        # manda `uplink`. Si se leyera aquí, esta área la tomaría por una dirección de
        # más (regla 17) y la quitaría en cada pasada -- y con ella la salida del lab.
        de_fuera = interfaz_exterior(guest)
        direcciones = [
            d for d in direcciones if str(d.get("interface")) != de_fuera
        ]
        estaticas = [
            {"interface": str(d.get("interface")), "address": str(d.get("address"))}
            for d in direcciones
            if not _ros_si(d.get("dynamic"))
        ]
        dinamicas = [
            {"interface": str(d.get("interface")), "address": str(d.get("address"))}
            for d in direcciones
            if _ros_si(d.get("dynamic"))
        ]
        areas["addresses"] = {
            "estaticas": estaticas,
            "dinamicas": dinamicas,
            # El `.id` es lo único con lo que se puede QUITAR una entrada, y se guarda
            # por interfaz Y dirección: en un router con dos interfaces, la dirección sola no
            # la identifica.
            "ids": {
                _ros_clave(d.get("interface"), d.get("address")): str(d.get(".id") or "")
                for d in direcciones
                if not _ros_si(d.get("dynamic"))
            },
        }

    # --- rutas: las que pone el motor son estáticas; las demás son del sistema ---
    if "/ip/route" in leidos:
        routes = _ros_lista((leidos.get("/ip/route") or {}).get("json"))
        # La ruta por defecto es de `uplink` cuando este router es la salida (él la pone,
        # por la pasarela de fuera): si esta área la leyera, la tomaría por una ruta de más y
        # la quitaría en cada pasada -- y el lab se quedaría sin salida.
        if interfaz_exterior(guest):
            routes = [r for r in routes if str(r.get("dst-address")) != "0.0.0.0/0"]
        estaticas = [
            {"dst_address": str(r.get("dst-address")), "gateway": str(r.get("gateway"))}
            for r in routes
            if not _ros_si(r.get("dynamic"))
        ]
        areas["routes"] = {
            "estaticas": estaticas,
            "ids": {
                _ros_clave(r.get("dst-address"), r.get("gateway")): str(r.get(".id") or "")
                for r in routes
                if not _ros_si(r.get("dynamic"))
            },
        }

    # --- dhcp: servidores, pools, redes y reservas, atados entre sí ---
    if "/ip/dhcp-server" in leidos:
        pools = _ros_lista((leidos.get("/ip/pool") or {}).get("json"))
        redes = _ros_lista((leidos.get("/ip/dhcp-server/network") or {}).get("json"))
        concesiones = _ros_lista((leidos.get("/ip/dhcp-server/lease") or {}).get("json"))
        rango_de_pool = {}
        for pool in pools:
            rangos = str(pool.get("ranges") or "")
            rango_de_pool[str(pool.get("name"))] = rangos
        servidores = []
        for servidor in _ros_lista((leidos.get("/ip/dhcp-server") or {}).get("json")):
            interfaz = str(servidor.get("interface"))
            rango = rango_de_pool.get(str(servidor.get("address-pool")), "")
            # Su red es la que cubre el rango que reparte: un router con dos LANs tiene
            # dos servidores, y cada uno anuncia la suya.
            red = {}
            for candidata in redes:
                if en_red_siendo(rango.split("-")[0], str(candidata.get("address") or "")):
                    red = {
                        "address": str(candidata.get("address")),
                        "gateway": str(candidata.get("gateway")),
                        "dns": [
                            d.strip()
                            for d in str(candidata.get("dns-server") or "").split(",")
                            if d.strip()
                        ],
                        "id": str(candidata.get(".id") or ""),
                    }
                    break
            servidores.append(
                {
                    "interface": interfaz,
                    "rango": rango,
                    "nombre": str(servidor.get("name") or ""),
                    "id": str(servidor.get(".id") or ""),
                    "network": red,
                }
            )
        areas["dhcp_server"] = {
            "servidores": servidores,
            "pools": {
                str(p.get("name")): {"id": str(p.get(".id") or ""), "rango": str(p.get("ranges") or "")}
                for p in pools
            },
            # Las concesiones DINÁMICAS no son static_leases: son equipos que pidieron
            # dirección, y el motor no las declara ni las quita (no son suyas).
            "static_leases": [
                {
                    "mac": str(c.get("mac-address")),
                    "address": str(c.get("address")),
                    "servidor": str(c.get("server") or ""),
                    "id": str(c.get(".id") or ""),
                }
                for c in concesiones
                if not _ros_si(c.get("dynamic")) and str(c.get("mac-address") or "")
            ],
        }

    # --- uplink: la salida del lab ---
    # Cuatro hechos, los cuatro leídos del equipo: la dirección de la interfaz de fuera, si
    # tiene ruta por defecto (y por dónde), si está la regla de NAT del motor, y cómo tiene
    # el resolutor (encendido y con quién resuelve). Nada se supone: se lee.
    if exterior and "/ip/firewall/nat" in leidos:
        propias = _ros_lista((leidos.get("/ip/address") or {}).get("json"))
        # Las de la interfaz de fuera, con su `.id` (es lo único con lo que se puede quitar una,
        # y aquí SÍ puede haber más de una: cada pasada que no adoptara la que hay dejaría
        # otra puesta -- medido, y por eso el motor ADOPTA la primera que encuentre).
        de_la_interface = [
            d for d in propias
            if str(d.get("interface")) == exterior and not _ros_si(d.get("dynamic"))
        ]
        direccion_propia = str(de_la_interface[0].get("address")) if de_la_interface else ""
        # La dirección de la interfaz, en la forma en que se compara (sin el prefijo), para saber
        # si la que hay es de la red por la que se sale.
        direccion_desnuda = direccion_propia.split("/")[0]
        rutas_propias = _ros_lista((leidos.get("/ip/route") or {}).get("json"))
        por_defecto = next(
            (
                str(r.get("gateway"))
                for r in rutas_propias
                if str(r.get("dst-address")) == "0.0.0.0/0" and not _ros_si(r.get("dynamic"))
            ),
            "",
        )
        reglas = _ros_lista((leidos.get("/ip/firewall/nat") or {}).get("json"))
        nuestra = None
        for regla in reglas:
            if str(regla.get("comment") or "").strip() == MARCA_EXTERIOR:
                nuestra = regla
                break
        ajustes_dns = (leidos.get("/ip/dns") or {}).get("json")
        areas["uplink"] = {
            "interface": exterior,
            "address": direccion_propia,
            "de_la_red": direccion_desnuda,   # la de la interfaz, sin el prefijo
            "todas": [str(d.get("address")) for d in de_la_interface],
            "ids": {str(d.get("address")): str(d.get(".id") or "") for d in de_la_interface},
            "por_defecto": por_defecto,
            "masquerade": nuestra is not None,
            "id_masquerade": str((nuestra or {}).get(".id") or ""),
            "resolutor": (
                _ros_si(ajustes_dns.get("allow-remote-requests"))
                if isinstance(ajustes_dns, dict) else False
            ),
            "servidores": (
                str(ajustes_dns.get("servers") or "") if isinstance(ajustes_dns, dict) else ""
            ),
        }

    # --- el RESIDUO del cliente de fábrica (§9.2) ---
    # Solo cuenta lo que el cliente de fábrica dejó instalado y la API no puede borrar:
    # una dirección DINÁMICA con el valor de una dirección DECLARADA del invitado, y una
    # ruta por defecto DINÁMICA puesta por el DHCP.
    #
    # Mientras el cliente de fábrica siga VIVO, esa dirección dinámica es lo NORMAL -- es
    # la forma de que el equipo sea alcanzable hasta que el motor entre a configurarlo --,
    # así que el residuo se declara sólo cuando el cliente ya está apagado. Si no, el plan
    # pediría un reinicio en la misma pasada en que lo apaga, sin saber si hacía falta.
    cliente_vivo = bool((areas.get("dhcp_client") or {}).get("habilitado"))
    dinamicas = (areas.get("addresses") or {}).get("dinamicas") or []
    declaradas = {
        f"{d['interface']}:{d['address']}"
        for d in (areas.get("addresses") or {}).get("estaticas") or []
    }
    propia = str((guest or {}).get("address") or "")
    if propia and propia != "dhcp":
        # La dirección con la que el invitado nace (`address:` del lab) también es
        # declarada: es la que el cliente de fábrica pidió por DHCP y la que se queda.
        declaradas.add(f"ether1:{propia}")
    residuo_direccion = (not cliente_vivo) and any(
        f"{d['interface']}:{d['address']}" in declaradas for d in dinamicas
    )
    rutas_crudas = _ros_lista((leidos.get("/ip/route") or {}).get("json"))
    # Un router que ES la salida del lab tiene una ruta por defecto dinámica A PROPÓSITO:
    # la puso su cliente de fuera. Eso no es residuo de nadie, es el diseño -- y si contara
    # como residuo, el plan pediría un reinicio del router en CADA pasada.
    residuo_ruta = (not cliente_vivo) and not exterior and any(
        _ros_si(r.get("dynamic"))
        and _ros_si(r.get("dhcp"))
        and str(r.get("dst-address")) == "0.0.0.0/0"
        for r in rutas_crudas
    )

    if not areas:
        areas = {}
    return {
        "alcanzable": not motivo,
        "motivo": motivo,
        "credencial": str(credencial),
        "areas": areas,
        "residuo": {"direccion_dinamica": residuo_direccion, "ruta_dinamica": residuo_ruta},
        "guest": (guest or {}).get("rol"),
    }


def _a_entero(direccion):
    """'10.40.0.11' -> entero, o None si no es una IPv4 con puntos."""
    partes = str(direccion or "").split(".")
    if len(partes) != 4:
        return None
    try:
        valores = [int(parte) for parte in partes]
    except ValueError:
        return None
    if any(valor < 0 or valor > 255 for valor in valores):
        return None
    return (valores[0] << 24) | (valores[1] << 16) | (valores[2] << 8) | valores[3]


def _a_texto(valor):
    return ".".join(str((valor >> desplazamiento) & 255)
                    for desplazamiento in (24, 16, 8, 0))


def _sin_prefijo(direccion):
    """'10.40.0.11/24' -> '10.40.0.11' (el prefijo se mira aparte)."""
    return str(direccion or "").split("/")[0]


def _prefijo_de(direccion):
    """'10.40.0.11/24' -> '24'; sin prefijo, ''."""
    partes = str(direccion or "").split("/")
    return partes[1] if len(partes) > 1 else ""


def _intercambio_de_la_gestion(operaciones, declaracion, guest, leido):
    """Ordena las escrituras de RouterOS cuando la dirección de gestión la tiene puesta un
    cliente DHCP, y emite ese intercambio como UN guion que ejecuta el router ÉL MISMO.

    El problema, medido en un CHR 7.25.1: la imagen nace con un cliente DHCP en `ether1`
    que se queda con una dirección, y RouterOS RECHAZA una estática que la duplica
    (`failure: already have such address`). Apagar el cliente por REST se lleva la
    dirección --y con ella el REST-- antes de contestar, así que desde fuera no hay manera
    de poner la estática: es un círculo, y ya se intentó rodearlo a pasos desde fuera (con
    una dirección prestada): frágil, cuatro llamadas y dos formas de quedarse a medias.

    La salida no da pasos desde fuera: se manda UNA llamada --`POST /execute` con un
    guion-- y lo que el router ejecuta DENTRO, de una sola vez, es lo que tiene que ir
    junto o no ir:

      1. quitar el cliente DHCP de la interfaz de gestión (`/ip dhcp-client remove`);
      2. soltar la entrada dinámica que ese cliente dejó atrás, si sigue puesta: RouterOS
         no la borra al irse el cliente, y sin soltarla el `add` de la estática choca
         (es la otra forma de la misma trampa, también medido);
      3. poner la dirección declarada de esa interfaz.

    Así no hay ventana en la que el equipo esté sin dirección, y no se depende de acertar
    el momento entre llamadas (medido: un `POST /ip/address/add` desde fuera se quedó sin
    respuesta en el CHR del segundo etapa, con el MISMO cuerpo que en el primero contesta
    200). El guion va al final de todo y justo antes de la credencial --que es el
    intercambio que cierra--, porque es la escritura que puede dejar al equipo sin túnel un
    instante: lo que se pueda dar hecho antes, hecho está. Y va declarando que puede no
    contestar (`tolerar_sin_respuesta`): quien prueba el efecto es la RELECTURA.

    Sin cliente que quitar y sin residuo dinámico no hay nada que ordenar, y se devuelven
    las operaciones tal cual: es el caso normal de una pasada ya convergida.
    """
    operaciones = [dict(operacion) for operacion in (operaciones or [])]
    areas = (leido or {}).get("areas") or {}
    direcciones_leidas = areas.get("addresses") or {}
    dinamicas = {
        _sin_prefijo((entrada or {}).get("address"))
        for entrada in direcciones_leidas.get("dinamicas") or []
    }
    propia = _sin_prefijo((guest or {}).get("address"))
    cliente_vivo = bool((areas.get("dhcp_client") or {}).get("habilitado"))

    apagones = [
        operacion for operacion in operaciones
        if operacion.get("op") == "disable_dhcp_client"
    ]
    choque = None
    for operacion in operaciones:
        if operacion.get("op") != "add_address":
            continue
        if str(operacion.get("interface")) != INTERFAZ_GESTION_ROUTEROS:
            continue
        if _sin_prefijo(operacion.get("address")) in dinamicas:
            choque = operacion
    # El residuo: la entrada dinámica que dejó un cliente YA retirado. Sin cliente que
    # quitar, lo que hay que soltar es la entrada -- y lo dice la LECTURA, no la memoria.
    # Si la dirección ya está puesta como ESTÁTICA, no hay nada que soltar: pedirlo sería una
    # llamada de más en cada pasada, y la idempotencia vive de no tenerlas.
    estaticas = {
        _sin_prefijo((entrada or {}).get("address"))
        for entrada in direcciones_leidas.get("estaticas") or []
    }
    residuo = (
        bool(propia) and not cliente_vivo and propia in dinamicas and propia not in estaticas
    )
    if not apagones and not residuo:
        return operaciones

    lineas = [
        # Los clientes que hay que quitar, por interface: el op dice QUE hay que quitarlo y la
        # LECTURA dice dónde está (su mapa de `.id`s por interfaz), que es lo que el guion
        # necesita para encontrarlo.
        f"/ip dhcp-client remove [find interface={interfaz}]"
        for interfaz in (
            sorted(((areas.get("dhcp_client") or {}).get("ids") or {}).keys())
            if apagones else []
        )
    ]
    if residuo:
        lineas.append(
            f"/ip address remove [find address={propia} "
            f"interface={INTERFAZ_GESTION_ROUTEROS} dynamic=yes]"
        )
        # Un respiro entre soltar y poner: el guion corre ENTERO dentro del router, así que
        # esto no abre ventana hacia fuera, sólo le da tiempo a soltar la entrada.
        lineas.append(":delay 2s")
    if choque is not None:
        lineas.append(
            f"/ip address add address={choque.get('address')} "
            f"interface={choque.get('interface')}"
        )

    guion = {
        "op": "run_script", "area": "addresses", "lineas": lineas,
        "tolerar_sin_respuesta": True,
        "descripcion": "el intercambio de la dirección de gestión, dentro del router y de una vez",
    }
    # De las escrituras se descartan las que van DENTRO del guion: el cliente que se quita
    # y la estática que se pone junto a él. Dejarlas fuera sería mandarlas dos veces --y la
    # segunda, con el duplicado que RouterOS rechaza--.
    fuera = [
        operacion for operacion in operaciones
        if operacion.get("op") != "disable_dhcp_client" and operacion is not choque
    ]
    # Y el guion, al final, pero por delante de la credencial: el cambio de credencial deja
    # sin credencial a cualquier escritura posterior (medido: un 401 tolerado que se queda
    # sin hacer), así que la credencial sigue siendo lo ÚLTIMO que se toca.
    donde = len(fuera)
    for posicion, operacion in enumerate(fuera):
        if operacion.get("op") == "set_engine_credential":
            donde = posicion
            break
    fuera.insert(donde, guion)
    return fuera


def escrituras_routeros(operaciones, guest, declaracion, identidad, parametros, leido):
    """(operaciones decididas) -> llamadas al REST, en orden.

    Aquí está el ÚNICO sitio donde el vocabulario del lab se traduce a objetos de
    RouterOS (`/ip/address/add`, `/ip/dhcp-server/lease/set`...). El lab declara qué
    quiere; esto dice cómo se pide. Cada llamada sale con su `metodo`, su `ruta` y su
    `cuerpo`, y la vía de acceso la diariza igual que cualquier otra.

    Trampas ya pagadas y no repetidas (medidas en v3 y re-medidas en esta fase):
      * escribir una ruta se hace con `POST /add` (un `PUT` a la ruta de las rutas
        responde 400 «no such command»: comprobado en un CHR 7.25.1);
      * RouterOS no tiene «crear o actualizar»: si el objeto no está, se AÑADE, y si
        está, se MODIFICA -- y eso se decide aquí, con lo que se leyó;
      * `www` no se deshabilita: es donde vive el REST, o sea el túnel de vuelta;
      * una estática que duplica una dinámica se RECHAZA, y por eso el intercambio de la
        dirección de gestión se le manda al router ENTERO y de una vez, como un guion
        (ver `_intercambio_de_la_gestion`).
    """
    usuario = str((parametros or {}).get("usuario") or "")
    clave = str((parametros or {}).get("clave") or "")
    clave_publica = str((parametros or {}).get("clave_publica") or "")
    areas = (leido or {}).get("areas") or {}
    llamadas = []
    # Por dónde se habla en la llamada que se está montando. Vacío = la dirección declarada
    # del invitado, y es siempre el caso: nadie cambia de dirección a media convergencia.
    dirigirse_a = ""

    def llamada(area, metodo, ruta, cuerpo, descripcion):
        item = {
            "area": area,
            "accion": "escribir",
            "metodo": metodo,
            "ruta": ruta,
            "cuerpo": cuerpo,
            "descripcion": descripcion,
        }
        if dirigirse_a:
            item["address"] = dirigirse_a
        if operacion.get("tolerar_sin_respuesta"):
            item["tolerar_sin_respuesta"] = True
        llamadas.append(item)
        # Se devuelve además de apuntarla: hay traducciones que necesitan retocar la llamada
        # después (la relectura que se marca como `accion: leer`).
        return item

    # La dirección de gestión la deriva el motor del `address:` del invitado (ver
    # `pasos_de_convergencia`), así que la capa pura ya la tiene en el invitado normalizado.
    operaciones = _intercambio_de_la_gestion(
        operaciones, declaracion, guest, leido
    )

    for operacion in operaciones or []:
        op = str((operacion or {}).get("op") or "")
        area = str((operacion or {}).get("area") or "")
        dirigirse_a = str((operacion or {}).get("dirigirse_a") or "")

        if op == "run_script":
            # El intercambio de la dirección de gestión, de UNA vez y dentro del router: él
            # quita su cliente DHCP, suelta la entrada dinámica que ese cliente dejó y pone
            # la estática, todo en la misma ejecución. Medido en un CHR 7.25.1: por pasos
            # desde fuera no se puede --quitar el cliente se lleva la dirección y la petición
            # muere sin contestar--, y un guion sí, porque corre entero dentro del equipo.
            llamada(area or "addresses", "POST", "/execute",
                    {"script": "; ".join(operacion.get("lineas") or [])},
                    str(operacion.get("descripcion") or "el intercambio de la dirección de gestión"))

        elif op == "set_identity":
            llamada(area, "POST", "/system/identity/set",
                    {"name": str(operacion.get("nombre"))},
                    f"poner el nombre del equipo a '{operacion.get('nombre')}'")

        elif op == "create_engine_user":
            # Se crea CON la credencial del motor puesta: crear un usuario sin contraseña
            # y ponérsela después deja una ventana en la que el equipo está abierto.
            llamada(area, "POST", "/user/add",
                    {"name": usuario, "group": "full", "password": clave},
                    f"crear el usuario del motor ('{usuario}') con su credencial")

        elif op == "set_engine_credential":
            llamada(area, "POST", "/user/set",
                    {"numbers": usuario, "password": clave},
                    "poner la credencial del motor en el usuario del motor")

        elif op == "import_engine_key":
            llamada(area, "POST", "/user/ssh-keys/add",
                    {"user": usuario, "key": clave_publica},
                    "importar la clave pública del motor (sólo para depurar: se converge por REST)")

        elif op in ("disable_service", "enable_service"):
            servicio = str(operacion.get("servicio"))
            identificador = ((areas.get("ip_services") or {}).get("ids") or {}).get(servicio) or servicio
            apagado = "yes" if op == "disable_service" else "no"
            llamada(area, "POST", "/ip/service/set",
                    {"numbers": identificador, "disabled": apagado},
                    f"{'deshabilitar' if apagado == 'yes' else 'habilitar'} el servicio '{servicio}'")

        # (aquí no hay traducción de `disable_dhcp_client`, y es a propósito: al cliente
        # de fábrica no se le apaga desde fuera -- apagarlo se lleva la dirección y la petición
        # muere sin contestar --, se le QUITA dentro del guion del intercambio, junto a la
        # estática que hay que poner en su lugar: ver `_intercambio_de_la_gestion`)
        elif op == "add_address":
            llamada(area, "POST", "/ip/address/add",
                    {"address": str(operacion.get("address")),
                     "interface": str(operacion.get("interface"))},
                    f"poner la dirección {operacion.get('address')} en {operacion.get('interface')}")

        elif op == "remove_address":
            clave_id = _ros_clave(operacion.get("interface"), operacion.get("address"))
            identificador = str(operacion.get("id") or "") or (
                ((areas.get("addresses") or {}).get("ids") or {}).get(clave_id)
            )
            llamada(area, "POST", "/ip/address/remove",
                    {"numbers": identificador or str(operacion.get("address"))},
                    f"quitar la dirección {operacion.get('address')} de {operacion.get('interface')}")

        elif op == "add_route":
            llamada(area, "POST", "/ip/route/add",
                    {"dst-address": str(operacion.get("dst_address")),
                     "gateway": str(operacion.get("gateway"))},
                    f"poner la ruta {operacion.get('dst_address')} por {operacion.get('gateway')}")

        elif op == "remove_route":
            clave_id = _ros_clave(operacion.get("dst_address"), operacion.get("gateway"))
            identificador = ((areas.get("routes") or {}).get("ids") or {}).get(clave_id)
            llamada(area, "POST", "/ip/route/remove",
                    {"numbers": identificador or str(operacion.get("dst_address"))},
                    f"quitar la ruta {operacion.get('dst_address')} por {operacion.get('gateway')}")

        elif op == "add_masquerade":
            interfaz = str(operacion.get("interface"))
            llamada(area, "POST", "/ip/firewall/nat/add",
                    {"chain": "srcnat", "out-interface": interfaz,
                     "action": "masquerade", "comment": MARCA_EXTERIOR},
                    f"traducir lo que sale del lab por {interfaz} (masquerade): sus "
                    "direcciones son privadas y sin esto la respuesta no vuelve")

        elif op == "enable_dns_resolver":
            servidores = [str(s) for s in (operacion.get("servidores") or []) if str(s)]
            cuerpo = {"allow-remote-requests": "yes"}
            if servidores:
                cuerpo["servers"] = ",".join(servidores)
            llamada(area, "POST", "/ip/dns/set", cuerpo,
                    "encender el resolutor DNS y decirle a quién preguntar: los invitados "
                    "que salen por aquí le preguntan a él")

        elif op == "add_dhcp_server":
            interfaz = str(operacion.get("interface"))
            rango = str(operacion.get("rango") or "")
            nombre_pool = PREFIJO_POOL + rango.split("-")[0]
            pools = ((areas.get("dhcp_server") or {}).get("pools") or {})
            if nombre_pool in pools:
                llamada(area, "POST", "/ip/pool/set",
                        {"numbers": pools[nombre_pool]["id"] or nombre_pool, "ranges": rango},
                        f"ajustar el rango que reparte el router ({rango})")
            else:
                llamada(area, "POST", "/ip/pool/add",
                        {"name": nombre_pool, "ranges": rango},
                        f"declarar el rango que reparte el router ({rango})")
            existente = None
            for servidor in (areas.get("dhcp_server") or {}).get("servidores") or []:
                if str(servidor.get("interface")) == interfaz:
                    existente = servidor
                    break
            cuerpo = {"interface": interfaz, "address-pool": nombre_pool, "disabled": "no"}
            if existente:
                llamada(area, "POST", "/ip/dhcp-server/set",
                        dict(cuerpo, numbers=existente.get("id") or existente.get("nombre") or interfaz),
                        f"servir DHCP en {interfaz} desde el rango {rango}")
            else:
                cuerpo["name"] = PREFIJO_POOL + interfaz
                llamada(area, "POST", "/ip/dhcp-server/add", cuerpo,
                        f"servir DHCP en {interfaz} desde el rango {rango}")

        elif op == "remove_dhcp_server":
            interfaz = str(operacion.get("interface"))
            for servidor in (areas.get("dhcp_server") or {}).get("servidores") or []:
                if str(servidor.get("interface")) == interfaz:
                    llamada(area, "POST", "/ip/dhcp-server/remove",
                            {"numbers": servidor.get("id") or interfaz},
                            f"dejar de servir DHCP en {interfaz} (ya no se declara)")

        elif op == "add_dhcp_network":
            dns = operacion.get("dns") or []
            cuerpo = {
                "address": str(operacion.get("address")),
                "gateway": str(operacion.get("gateway")),
                "dns-server": ",".join(str(d) for d in dns),
            }
            existente = None
            for servidor in (areas.get("dhcp_server") or {}).get("servidores") or []:
                if str((servidor.get("network") or {}).get("address")) == str(operacion.get("address")):
                    existente = (servidor.get("network") or {}).get("id")
                    break
            if existente:
                llamada(area, "POST", "/ip/dhcp-server/network/set",
                        dict(cuerpo, numbers=existente),
                        f"anunciar la red {operacion.get('address')} con pasarela {operacion.get('gateway')}")
            else:
                llamada(area, "POST", "/ip/dhcp-server/network/add", cuerpo,
                        f"anunciar la red {operacion.get('address')} con pasarela {operacion.get('gateway')}")

        elif op == "add_static_lease":
            mac = str(operacion.get("mac"))
            interfaz = str(operacion.get("interface"))
            # El servidor que static_lease: el que ya está (leído), y si no, el que esta MISMA
            # pasada acaba de crear (su nombre es derivado, no hay que adivinarlo). Nunca
            # `all`: una reserva sin servidor la puede servir cualquiera de las dos LANs.
            servidor = PREFIJO_POOL + interfaz if interfaz else ""
            for candidato in (areas.get("dhcp_server") or {}).get("servidores") or []:
                if str(candidato.get("interface")) == interfaz:
                    servidor = str(candidato.get("nombre") or servidor)
                    break
            existente = None
            for reserva in (areas.get("dhcp_server") or {}).get("static_leases") or []:
                if str(reserva.get("mac")).upper() == mac.upper():
                    existente = reserva.get("id")
                    break
            cuerpo = {
                "address": str(operacion.get("address")),
                "mac-address": mac,
                # La reserva se ata al servidor de ESA interface: un router con dos LANs
                # no puede reservar en la primera lo que vive en la segunda.
                "server": servidor or "all",
            }
            if existente:
                llamada(area, "POST", "/ip/dhcp-server/lease/set",
                        dict(cuerpo, numbers=existente),
                        f"reservar {operacion.get('address')} a la MAC derivada {mac}")
            else:
                llamada(area, "POST", "/ip/dhcp-server/lease/add", cuerpo,
                        f"reservar {operacion.get('address')} a la MAC derivada {mac}")

        elif op == "remove_static_lease":
            mac = str(operacion.get("mac"))
            identificador = None
            for reserva in (areas.get("dhcp_server") or {}).get("static_leases") or []:
                if str(reserva.get("mac")).upper() == mac.upper():
                    identificador = reserva.get("id")
                    break
            llamada(area, "POST", "/ip/dhcp-server/lease/remove",
                    {"numbers": identificador or mac},
                    f"quitar la reserva de la MAC {mac} (ya no se declara)")

        else:
            # Una operación sin traducir NO se cae de la lista en silencio: se marca y el
            # driver para antes de escribir (si no, diría «convergido» habiendo ignorado
            # algo, que es la forma más silenciosa de mentir).
            llamadas.append({"area": area, "accion": "sin_traducir", "op": op})

    return llamadas


# Los DRIVERS que existen hoy en este motor: por vía, y por tipo de interior. Es una
# lista CORTA a propósito, y es la única verdad sobre qué sabe hacer el motor: la usan
# `apply.yml` para avisar de lo que va a parar y `paso.yml` para despachar. Si añades un
# driver (un `tasks/configurar_<tipo>.yml`), añádelo aquí -- y `test/test_interior.py`
# lo comprueba, para que no puedan divergir sin que nadie se entere.
DRIVERS = {
    "interior": {"linux", "routeros"},   # `tasks/configurar_linux.yml`, `tasks/configurar_routeros.yml`
    "sonda": set(),          # `tasks/sonda.yml` (esta vía no elige tipo: el conjunto va vacío)
}


def tiene_driver(via, tipo):
    """¿Este motor sabe ejecutar un paso de esa vía (y, si es interior, de ese tipo)?"""
    via = via or "api"
    if via in ("api", "tunnel"):
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


def guests_a_verificar(declaracion):
    """Los invitados que hay que MIRAR por dentro, para `verify` (regla 11 del README de
    verificación): los que declaran `config` con áreas que piden visita.

    Es la MISMA frontera que usa el plan (`areas_que_piden_visita`): a un invitado al
    que no hay nada que preguntarle no se le abre una conexión -- ni siquiera para
    leer. Devuelve `[{'rol': …, 'tipo': …}]` en el orden de la declaración.
    """
    # La declaración normalizada trae `guests` (una sola lista, con el tipo ya
    # resuelto); la cruda trae `vms` + `containers`. Se aceptan las dos para que la
    # función sirva igual desde `verify` (normalizada) y desde una prueba (cruda).
    if "guests" in declaracion:
        candidatos = declaracion.get("guests") or []
    else:
        candidatos = list(declaracion.get("vms") or []) + list(declaracion.get("containers") or [])
    fuera = []
    for guest in candidatos:
        tipo = tipo_de(guest)
        if tipo and areas_que_piden_visita(guest):
            fuera.append({"rol": guest.get("rol"), "tipo": tipo})
    return fuera


def informe_ok(informe_interior):
    """¿Pasa el INTERIOR de un lab? Sí cuando todo invitado mirado se pudo LEER
    (`alcanzable`) y no le queda ninguna operación pendiente. Un invitado que no se pudo
    leer NO pasa: no se aprueba lo que no se ha mirado (es la misma honestidad que el
    «no verificable» del mundo de la API)."""
    for entrada in (informe_interior or {}).values():
        if not entrada.get("alcanzable") or entrada.get("pendiente"):
            return False
    return True


def sin_comprobar(entradas, motivo):
    """El informe del interior cuando NO se pudo mirar (p. ej. el túnel del lab no
    responde): cada invitado a verificar queda como «no alcanzable» con el motivo. No se
    aprueba lo que no se ha mirado, así que el veredicto de `verify` cae por su propio
    peso en vez de dar por bueno lo que nadie ha comprobado."""
    return {
        e["rol"]: {"tipo": e.get("tipo"), "alcanzable": False, "motivo": motivo, "pendiente": []}
        for e in (entradas or [])
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
            "interior_lecturas_linux": lecturas_linux,
            "interior_leido_linux": leido_linux,
            "interior_escrituras_linux": escrituras_linux,
            "interior_lecturas_routeros": lecturas_routeros,
            "interior_leido_routeros": leido_routeros,
            "interior_escrituras_routeros": escrituras_routeros,
            "interior_sin_secretos": sin_secretos,
            "interior_pendiente_de_driver": pendiente_de_driver,
            "interior_leido": leido_de_lecturas,
            "interior_operaciones": operaciones_de_pasos,
            "interior_sin_driver": pasos_sin_driver,
            "interior_tiene_driver": tiene_driver,
            "interior_configuracion_dnsmasq": configuracion_dnsmasq,
            "interior_declara": declara_interior,
            "interior_tiene_tunnel": tiene_tunnel,
            "interior_bastion": bastion,
            "interior_direccion_libre": direccion_libre,
            "interior_interfaces": interfaces_del_bastion,
            "interior_salida": salida_derivada,
            "interior_puerto_tunnel": puerto_tunnel,
            "interior_puerto_rest": puerto_rest_tunnel,
            "interior_permitlisten": permitlisten_de,
            "interior_interfaces_rest": interfaces_rest_del_bastion,
            "interior_guion_tunnel": guion_tunnel,
            "interior_linea_consola": linea_consola,
            "interior_marca_tunnel": marca_tunnel,
            "interior_reservas": reservas_derivadas,
            "interior_residuo": residuo_dinamico,
            "interior_pasos": pasos_de_convergencia,
            "interior_espera": espera_de_servicio,
            "interior_a_verificar": guests_a_verificar,
            "interior_informe_ok": informe_ok,
            "interior_sin_comprobar": sin_comprobar,
        }
