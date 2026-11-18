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
    "linux": ("tunnel", "address", "addresses", "routes", "latido", "ip_forward", "dhcp_server",
              "servicio", "monitorizacion"),
    "routeros": (
        "identity", "addresses", "ip_services", "dhcp_client", "routes", "dhcp_server", "uplink",
        "snmp",
        "firewall",
    ),
}

# Las áreas que el encargo nombra y el motor TODAVÍA no converge. Se declaran aquí
# a propósito: la validación las rechaza con un motivo legible en vez de aceptarlas
# y luego no hacer nada con ellas, que es la forma más silenciosa de mentir.
AREAS_PENDIENTES = {
    "routeros": ("bridges",),
    "linux": ("gateway", "dns", "claves"),
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
# El latido (área `latido` de un Linux): el guion que da el toque, y el TEMPORIZADOR que lo
# repite. Se lee y se compara por la unidad del temporizador, que es la que está armada.
RUTA_LATIDO = "/usr/local/sbin/netlabs-latido"
UNIDAD_LATIDO = "netlabs-latido.timer"
UNIDAD_LATIDO_SERVICIO = "netlabs-latido.service"
# La cadencia por defecto, si el lab no dice otra cosa. Se elige MENOR que la vida de una
# entrada ARP dinámica en RouterOS (minutos) a propósito: lo que el latido promete es que la
# entrada esté SIEMPRE ahí, no que aparezca a veces -- quien lee esa caché es la vigilancia,
# y lo hace cada cuarto de hora, así que una entrada que caduque entre medias no se ve.
CADENCIA_LATIDO = "2min"

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


def publica_servicio(guest):
    """¿Declara un `servicio` que hay que poder ABRIR desde fuera del lab?

    Un servicio (área `servicio`, vocabulario de Linux) se instala y se deja sirviendo
    para que se ENTRE en él por su web. En un lab de un solo invitado, quien entra por él
    es el navegador de quien mira: el invitado ES el bastión, y su pata en el puente de
    gestión del nodo ya existe por el túnel. En un lab con su propio bastión, un servicio
    aparte necesita esa MISMA pata, y no por casualidad: es la única red por la que el
    nodo publica hacia fuera (su Caddy) y por la que el invitado alcanza el repositorio
    para instalarse. Por eso publicar un servicio también pide la pata de gestión.
    """
    return "servicio" in areas_de(guest)


def el_motor_entra(guest):
    """¿El motor tiene que ENTRAR en este invitado para configurarlo?

    Es una razón DISTINTA de `necesita_pata_de_gestion`, y por eso no se mezclan: la pata de
    gestión es una INTERFAZ (red); esto es una LLAVE (entrar). Un invitado puede necesitar las
    dos -- el bastión, quien publica un servicio -- o SÓLO la llave: cualquiera al que el lab
    le declare un interior Linux, porque al motor se le alcanza por donde haga falta (p. ej.
    por la pata que el bastión ya tiene en su zona) pero no se entra SIN clave.

    Sólo cuenta el Linux: al RouterOS se le habla por su REST, con las credenciales que el lab
    declara, y ahí no hay llave que dejar.
    """
    config = guest.get("config")
    return bool(isinstance(config, dict) and config.get("linux"))


def necesita_pata_de_gestion(guest):
    """¿Este invitado necesita la ÚLTIMA pata: el puente de gestión del NODO?

    Dos razones, y sólo dos: ser el bastión (por ahí sale el túnel hacia casa) o PUBLICAR
    un servicio (por ahí se entra en él y se alcanza internet para instalarlo). Se escribe
    una vez porque las dos piden lo mismo -- una interfaz en el puente de gestión del nodo,
    la última, con pasarela -- y tenerlo en dos sitios dejaría al plan y al interior
    discrepando el día que se cambie una.
    """
    return tiene_tunnel(guest) or publica_servicio(guest)


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
        lab): es por donde el puesto sale hacia casa, y es la única que lleva PASARELA
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
    interfaces.append(
        _interfaz_de_salida(interfaces, puente_gestion, direcciones_bridge, usadas)
    )
    return interfaces


def _interfaz_de_salida(interfaces_ya_puestas, puente_gestion, direcciones_bridge, usadas):
    """La ÚLTIMA pata de un invitado que sale del lab: el bridge de gestión del NODO.

    Es la única que lleva PASARELA (la dirección que el nodo tiene en ese bridge), y por eso
    es «la salida»: por ahí se llega a casa (el túnel del bastión) y a internet (el
    repositorio del que se instala un servicio). Su dirección la elige el MOTOR de entre las
    libres del bridge, leyendo las que ya usa cada invitado del nodo -- nada derivado se
    guarda (regla 11). Va aparte porque la piden DOS clases de invitado que salen del lab: el
    bastión (que además lleva una pata por cada bridge del lab) y el que PUBLICA un servicio
    (que sólo lleva la suya y ésta).
    """
    subred = str(direcciones_bridge.get(puente_gestion) or "")
    if not subred:
        raise ErrorMotor(
            f"el bridge de gestión `{puente_gestion}` no tiene dirección en este nodo: "
            "sin dirección no hay vía de acceso por la que salir hacia casa"
        )
    usadas_salida = list(usadas) + [
        p["address"] for p in interfaces_ya_puestas if p.get("address")
    ]
    direccion = direccion_libre(subred, usadas_salida)
    return {
        "bridge": puente_gestion,
        "address": f"{direccion}/{subred.split('/')[1]}",
        # La vía de acceso de la interfaz de gestión es la dirección que el NODO tiene en ese
        # bridge (10.10.10.1 en vmbr1): por ahí sale hacia casa. No es un valor del
        # lab: se lee de la red del nodo.
        "gateway": subred.split("/")[0],
        "papel": "salida hacia fuera del lab",
    }


def interfaces_del_publicador(guest, declaracion, estado, parametros):
    """Las interfaces de un invitado que PUBLICA un servicio: su red declarada y la salida.

    Un invitado que declara `servicio` y NO es el bastión no es el puesto de control: no
    lleva una pata por cada bridge del lab (eso es del bastión, que tiene que estar en todas
    las redes para desplegarlas). Lleva las SUYAS -- las que el lab declara, igual que
    cualquier invitado -- y la ÚLTIMA en el bridge de gestión del nodo, que es la salida: por
    ahí se ENTRA en su web desde el Caddy del nodo y por ahí alcanza el repositorio para
    instalarse. La pata de gestión es la misma que la del bastión (`_interfaz_de_salida`),
    porque el porqué es el mismo.

    La primera interfaz declarada lleva su dirección (la que el lab escribe); las demás, si
    las hay, van sin dirección -- no se le inventan direcciones en bridges que el lab no ha
    declarado con puerta para este invitado.
    """
    puente_gestion = str(parametros.get("bridge_gestion") or "")
    direcciones_bridge = estado.get("bridges_direcciones") or {}
    usadas = estado.get("direcciones_usadas") or []
    if not puente_gestion:
        raise ErrorMotor(
            f"el invitado {guest.get('rol')} publica un servicio y el motor no sabe por "
            "dónde da salida este nodo: falta `pve_bridge_gestion` en secrets.yml "
            "(el bridge del nodo con dirección y salida, hoy `vmbr1`)"
        )
    interfaces = []
    for indice, bridge in enumerate(interfaces_de_un_guest(guest)):
        interfaces.append({
            "bridge": bridge,
            "address": str(guest.get("address") or "") if indice == 0 else "",
            "gateway": "",
            "papel": ("interfaz declarada del invitado" if indice == 0
                      else "interfaz declarada del invitado (extra)"),
        })
    interfaces.append(
        _interfaz_de_salida(interfaces, puente_gestion, direcciones_bridge, usadas)
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
    """Los pasos del TÚNEL de este invitado (el bastión), en orden.

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
                # La MISMA lista de reenvíos que la mitad 1, y no es un detalle: este paso
                # es el único de los dos que se emite SIEMPRE (el `construir` no se emite
                # si el túnel ya responde), así que es el que converge la línea de
                # `authorized_keys`. Sin esto, `tasks/tunnel.yml` --que calcula lo que
                # autoriza desde `item.parametros.rest`-- reescribía la línea con la lista
                # VACÍA y dejaba el túnel sin los reenvíos REST: la primera sesión, abierta
                # antes de esa reescritura, seguía viva y todo parecía funcionar, y a la
                # primera reconexión el bastión se quedaba mudo sin que nada diera error.
                # Medido: 230 «request was denied» de sshd y 0/6 invitados leídos.
                "rest": interfaces_rest,
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


def _cadencia_latido(declarado):
    """La cadencia declarada, o la del motor si el lab no dice nada.

    Es un valor DEL LAB (el lab dice cada cuánto quiere el toque; el motor no lo adivina,
    regla 7). El formato lo valida el esquema, así que aquí sólo se recoge.
    """
    return str((declarado or {}).get("cada") or "").strip() or CADENCIA_LATIDO


def escrituras_latido(cadencia):
    """Los ficheros del latido, tal cual se escriben dentro del invitado.

    Son TRES, y ninguna sobra: el guion da el toque, la unidad lo ejecuta una vez y el
    temporizador la repite. La MARCA (`# netlabs latido ...`) vive en el temporizador y la
    lee el driver: es lo que hace que un cambio de cadencia se note y se corrija.

    El toque es un ping a la PASARELA -- no a internet -- y no importa si contesta: el
    trabajo lo hace la PREGUNTA por su MAC, que sale antes de que nadie decida si el
    paquete pasa. Por eso el latido funciona con el cortafuegos en `drop` y sin internet,
    y por eso no abre nada: un paquete dentro de su propia red.
    """
    guion = """#!/bin/sh
# PROPÓSITO: el latido. Mantiene a este equipo PRESENTE en la tabla ARP de su pasarela,
#            que es lo que hace que la vigilancia lo vea sin preguntarle a él.
# INVARIANTES: no configura nada, no abre puertas y no toca la red del lab. Si no hay
#            pasarela, sale sin hacer nada: no hay nada que mantener presente.
# LÍMITES:   no promete que el equipo CONTESTE a nadie -- sólo que está en la tabla.
# VER:       docs/decisiones/0031-el-latido.md
PUERTA=$(ip -4 route show default 2>/dev/null | awk '{print $3; exit}')
[ -n "$PUERTA" ] || exit 0
ping -c 1 -W 2 "$PUERTA" >/dev/null 2>&1
exit 0
"""
    unidad = f"""[Unit]
# PROPÓSITO: dar el toque una vez (el temporizador lo repite).
# VER: docs/decisiones/0031-el-latido.md
Description=netlabs: el latido (mantiene este equipo en la tabla ARP de su pasarela)
After=network-online.target

[Service]
Type=oneshot
ExecStart={RUTA_LATIDO}
"""
    temporizador = f"""# netlabs latido cada={cadencia}
[Unit]
# PROPÓSITO: repetir el latido para que la entrada ARP no caduque entre dos lecturas de
#            la vigilancia (que sondea cada cuarto de hora).
# VER: docs/decisiones/0031-el-latido.md
Description=netlabs: el latido, cada {cadencia}

[Timer]
OnBootSec=30s
OnUnitActiveSec={cadencia}
AccuracySec=5s

[Install]
WantedBy=timers.target
"""
    return {
        f"/etc/systemd/system/{UNIDAD_LATIDO}": temporizador,
        f"/etc/systemd/system/{UNIDAD_LATIDO_SERVICIO}": unidad,
        RUTA_LATIDO: guion,
    }


def _latido_canonico(declarado, leido):
    """Diferencia del área `latido`: que el equipo se vea en la red por la que vive.

    Lo que promete el área es una cosa y sólo una: que este equipo aparezca en la topología
    de la vigilancia sin que la vigilancia tenga que preguntarle a él. Se consigue estando
    en la tabla ARP de su pasarela, y eso se consigue con un toque cada poco.

    Se compara la MARCA (con qué cadencia se puso) ADEMÁS de estar armado y habilitado: si
    el lab cambia la cadencia, la marca no coincide y se vuelve a escribir. Mirar sólo que
    esté `active` dejaría la cadencia vieja puesta y el motor diría «convergido» -- el
    mismo caso que la marca del sembrado de la vigilancia.
    """
    # Que el área esté declarada ES la declaración: `latido: {{}}` es una MARCA (como
    # `monitorizacion`), así que aquí no se comprueba el valor -- que el área esté en el
    # YAML ya quiere decir «este equipo tiene que verse». Su único valor posible es `cada`,
    # y tiene defecto. Un `if not declarado: return []` aquí sería un fallo silencioso:
    # la marca es el diccionario VACÍO, y el latido no se pondría nunca.
    actual = leido or {}
    marca = f"# netlabs latido cada={_cadencia_latido(declarado)}"
    if actual.get("marca") == marca and actual.get("activo") and actual.get("habilitado"):
        return []
    return [
        {"op": "write_latido", "cadencia": _cadencia_latido(declarado)},
        {"op": "start_latido"},
    ]


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


def _firewall_canonico(declarado, leido):
    """Diferencia del área `firewall`: la tabla de filtrado ENTERA, y en su orden.

    El orden ES la semántica --RouterOS aplica la PRIMERA regla que casa y para--, así
    que lo declarado es la tabla completa y en su orden: una regla que no se declara se
    QUITA (regla 17: el área entera es del lab). Si la tabla leída ya coincide, no hay
    operación, y la 2ª pasada sólo lee.

    Cuando NO coincide, se RECONSTRUYE: se quitan todas las leídas y se ponen las
    declaradas en orden. No es lo más fino, es lo único que garantiza el ORDEN sin
    depender de `move` (que por REST no es razonable), y con el transporte por guion
    cuesta UNA llamada. El precio, dicho: entre el `remove` y el `add` hay un instante
    sin filtro -- y es la ÚLTIMA área en converger, a propósito (ver
    `pasos_de_convergencia`).
    """
    if not isinstance(leido, dict):
        return []
    deseadas = [_filtro_normalizado(r, de_declaracion=True) for r in (declarado or []) if isinstance(r, dict)]
    actuales = [r for r in (leido.get("reglas") or []) if isinstance(r, dict)]
    if [_clave_de_filtro(r) for r in deseadas] == [_clave_de_filtro(r) for r in actuales]:
        return []
    operaciones = [
        {
            "op": "remove_filter_rule",
            "id": str(regla.get("id") or ""),
            "descripcion": _descripcion_de_filtro(regla),
        }
        for regla in actuales
    ]
    operaciones += [
        {
            "op": "add_filter_rule",
            # Sólo los campos DECLARADOS: mandar los vacíos haría que RouterOS rechazara
            # la regla por un valor que nadie pidió.
            "regla": {k: v for k, v in regla.items() if v != ""},
            "descripcion": _descripcion_de_filtro(regla),
        }
        for regla in deseadas
    ]
    return operaciones


def _snmp_canonico(declarado, leido):
    """Diferencia del área `snmp`: que el equipo ACEPTE que se le pregunte, y nada más.

    Dos hechos, y los dos se leen:
      * el agente encendido (`/snmp` es `no` de fábrica);
      * una comunidad de LECTURA con el nombre del motor (`COMUNIDAD_SNMP`) entre las que
        el equipo tiene -- sin ella el colector no puede preguntar con la suya.

    No se recorta ni se borra la comunidad de fábrica ni las demás: el área dice «este
    equipo se vigila», no «estas son TODAS tus comunidades». Un equipo ya convergido no
    produce NINGUNA operación -- que es lo que hace verdadera la promesa de la regla 6.
    """
    if not isinstance(leido, dict):
        return []
    operaciones = []
    if not leido.get("habilitado"):
        operaciones.append({"op": "enable_snmp"})
    if COMUNIDAD_SNMP not in (leido.get("comunidades") or []):
        operaciones.append({"op": "add_snmp_community", "nombre": COMUNIDAD_SNMP})
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
    # Y el CORTAFUEGOS va lo ÚLTIMO de todo, incluso después de la identidad: es lo único
    # capaz de dejar al motor FUERA del equipo. Se cierra la puerta con todo lo demás ya
    # puesto y probado, y con la credencial del motor ya cambiada -- no con la de fábrica.
    # Aun así, un `drop` en la cadena `input` que no deje pasar la red de gestión corta el
    # túnel: es un aviso del ADR, y el lab tiene que declarar su excepción.
    if tipo == "routeros" and "firewall" in orden:
        orden.remove("firewall")
        orden.append("firewall")

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
        elif area == "firewall":
            operaciones = _firewall_canonico(declaradas[area], actual)
        elif area == "snmp":
            operaciones = _snmp_canonico(declaradas[area], actual)
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
        elif area == "latido":
            # El área del latido: que el equipo esté PRESENTE en la red por la que vive.
            # No configura nada del equipo ni de la red: da un toque a su pasarela cada
            # poco, y con eso su MAC queda en la caché ARP del router -- que es lo que
            # la vigilancia lee para encolar el nodo (medido en el sondeo de NetXMS).
            operaciones = _latido_canonico(declaradas[area], actual)
        elif area == "servicio":
            # El área del servicio declarado: instalar, configurar, arrancar y comprobar que
            # SIRVE. El valor declarado es el NOMBRE del servicio (vocabulario cerrado).
            operaciones = _servicio_canonico(declaradas[area], actual)
        elif area == "monitorizacion":
            # El área de la vigilancia: que el servidor declarado SEPA a quién vigilar. Va
            # DESPUÉS de `servicio` (siempre, por el orden de `AREAS`), así que cuando corre
            # el sembrado el servicio ya está arrancado y su unidad contesta.
            operaciones = _monitorizacion_canonica(
                declaradas[area], actual, declaradas.get("servicio")
            )
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


# 6.3 · Lo que cuesta UN intento de la sonda: el `timeout` de cada intento más la pausa
# entre intentos (`engine_sonda_espera` (2) + `engine_sonda_pausa` (5), en `vars/engine.yml`).
# Vive aquí para poder traducir una espera en SEGUNDOS -- que es lo que un lab sabe estimar --
# a intentos, que es lo que la sonda cuenta. Si cambian las de engine.yml, cambia ésta.
SONDA_SEGUNDOS_POR_INTENTO = 7
# 6.2 · Y lo que cuesta un intento de una PRUEBA: el `timeout` del propio comando más su
# `sleep` (ver `_comando_de_prueba`). También en segundos, y también para traducir.
PRUEBA_SEGUNDOS_POR_INTENTO = 6


# ---------------------------------------------------------------------------
# 6.2 · Las PRUEBAS FUNCIONALES de un lab (ADR 0022).
#
# `verify` contesta a «¿existe y coincide con lo declarado?». Esto contesta a la
# pregunta de al lado, que hasta ahora no contestaba nadie: «¿hace lo que dice que
# hace?». El lab declara sus pruebas, el motor las lanza DESDE DENTRO del invitado
# que el lab nombra -- por la misma vía de acceso que ya usa el interior, que es el
# único sitio del motor que entra en un invitado -- y cada una deja su veredicto.
#
# El vocabulario es CERRADO: un tipo de prueba que el motor no sabe lanzar no se
# acepta, en vez de aceptarse y no comprobar nada.
# ---------------------------------------------------------------------------

PRUEBA_TIPOS = ("ping", "servicio", "dns")

# El `porque` de una prueba, en una línea, para el diario y para el veredicto.
PRUEBA_QUE_HACE = {
    "ping": "contesta al ping",
    "servicio": "acepta conexiones",
    "dns": "resuelve el nombre",
}


def _ventana_de_intentos(espera, por_defecto, coste):
    """Una espera en SEGUNDOS -- lo que un lab sabe estimar -- dicha en INTENTOS.

    El coste de un intento lo pone quien llama (`SONDA_SEGUNDOS_POR_INTENTO`,
    `PRUEBA_SEGUNDOS_POR_INTENTO`), y así un lab tiene una sola forma de decir «dale
    tiempo» en todo el motor: segundos.
    """
    if isinstance(espera, int) and not isinstance(espera, bool) and espera > 0:
        return max(1, espera // coste)
    return por_defecto


def _comando_de_prueba(prueba):
    """El comando shell que lanza UNA prueba y sale con su veredicto en el código.

    0 = pasó, 1 = falló, 3 = no se pudo comprobar. Ese TERCER código es la mitad del
    diseño: un KO tiene que significar que el lab falla, no que al invitado le falte
    `ping` o no pueda usarlo. Sin él, media docena de pruebas saldrían en rojo por el
    entorno y el veredicto no valdría nada.

    Todo el comando va dentro de UN `bash -c '...'`, así que DENTRO no puede haber ni
    una sola comilla simple: partiría el entrecomillado y `bash` se comería el resto
    (pasó, y lo cazó el banco: `cut -d' '` rompía el comando de `dns`).
    """
    hacia = prueba["hacia"]
    intentos = prueba["intentos"]
    tipo = prueba["tipo"]
    if tipo == "ping":
        return (
            # La sonda de capacidades: el binario puede estar y NO poder usarse (sin
            # `CAP_NET_RAW`, `ping` contesta «Operation not permitted»). Sin esta línea,
            # un invitado sin permiso de red saldría en ROJO y el veredicto culparía al
            # lab de algo que no es del lab.
            f"bash -c 'command -v ping >/dev/null 2>&1 || "
            f'{{ echo "OMITIDA: no hay ping en el invitado"; exit 3; }}; '
            f"ping -c 1 -W 1 127.0.0.1 >/dev/null 2>&1 || "
            f'{{ echo "OMITIDA: hay ping pero no puede usarlo (sin permiso de red)"; exit 3; }}; '
            f"i=0; while [ $i -lt {intentos} ]; do i=$((i+1)); "
            f"if ping -c 2 -W 2 {hacia} >/dev/null 2>&1; then "
            f'echo "OK: {hacia} contesta al ping (intento $i)"; exit 0; fi; '
            f"sleep 3; done; "
            f'echo "KO: {hacia} no contestó al ping en $i intentos"; exit 1'
            f"'"
        )
    if tipo == "servicio":
        puerto = prueba["puerto"]
        return (
            f"bash -c 'i=0; while [ $i -lt {intentos} ]; do i=$((i+1)); "
            f'if timeout 2 bash -c "</dev/tcp/{hacia}/{puerto}" 2>/dev/null; then '
            f'echo "OK: {hacia}:{puerto} acepta conexiones (intento $i)"; exit 0; fi; '
            f"sleep 3; done; "
            f'echo "KO: {hacia}:{puerto} no acepta conexiones en $i intentos"; exit 1'
            f"'"
        )
    return (
        f"bash -c 'command -v getent >/dev/null 2>&1 || "
        f'{{ echo "OMITIDA: no hay getent en el invitado"; exit 3; }}; '
        f"i=0; while [ $i -lt {intentos} ]; do i=$((i+1)); "
        f"if getent ahostsv4 {hacia} >/dev/null 2>&1; then "
        # La dirección que salió, para poder citarla -- sin `cut` ni comillas simples,
        # que partirían el `bash -c '...'` de fuera.
        f'echo "OK: {hacia} resuelve a: $(getent ahostsv4 {hacia} | head -1)"; exit 0; fi; '
        f"sleep 3; done; "
        f'echo "KO: {hacia} no resolvió en $i intentos"; exit 1'
        f"'"
    )


def pruebas_de(declaracion, intentos_por_defecto=6):
    """Las pruebas funcionales del lab, con su comando ya escrito. PURA.

    (declaración, intentos del motor) -> la lista de pruebas resueltas, en el orden en
    que el lab las declaró. El plan y el driver leen LO MISMO: si divergieran, la
    prueba que se lanza no sería la que se declaró.
    """
    salida = []
    for indice, cruda in enumerate(declaracion.get("tests") or []):
        if not isinstance(cruda, dict):
            continue
        desde = str(cruda.get("desde") or "").strip()
        tipo = str(cruda.get("tipo") or "").strip()
        hacia = str(cruda.get("hacia") or "").strip()
        prueba = {
            "indice": indice,
            "nombre": str(cruda.get("nombre") or f"prueba-{indice + 1}").strip(),
            "desde": desde,
            "tipo": tipo,
            "hacia": hacia,
            "puerto": cruda.get("puerto"),
            "intentos": _ventana_de_intentos(cruda.get("espera"), intentos_por_defecto, PRUEBA_SEGUNDOS_POR_INTENTO),
        }
        prueba["comando"] = _comando_de_prueba(prueba)
        prueba["porque"] = (
            f"el lab declara que '{desde}' {PRUEBA_QUE_HACE.get(tipo, tipo)} a '{hacia}'"
            + (f" en el puerto {prueba['puerto']}" if tipo == "servicio" else "")
        )
        salida.append(prueba)
    return salida


# ---------------------------------------------------------------------------
# 6.4 · CAPTURA e IMPAIRMENT desde el bastión (ADR 0023).
#
# El bastión tiene una pata en cada bridge del lab, así que es el sitio natural para
# mirar el tráfico y (se suponía) para estropearlo. Las dos se declaran en el lab y se
# encienden con su verbo -- `capture` y `impair` --, NO con `apply`: no son estado
# deseado, son experimentos, y un experimento que sobrevive a la pasada es una mina.
#
# Por eso el impairment es ACOTADO: se aplica, se espera lo que el lab diga y se QUITA,
# siempre. Nunca queda un lab con `netem` puesto y sin dueño.
# ---------------------------------------------------------------------------

def _patas_de(guest):
    """Las interfaces declaradas de un invitado, EN ORDEN."""
    if guest.get("bridges"):
        return list(guest["bridges"])
    if guest.get("bridge"):
        return [guest["bridge"]]
    return []


def _invitados_de(declaracion):
    """Los invitados, en CUALQUIERA de las dos formas que circulan por el motor.

    La declaración cruda trae `vms` y `containers`; la normalizada, una lista plana
    `guests`. Quien lee de las dos (el validador, que ve la cruda, y el driver, que ve
    la normalizada) tiene que leer de las dos o hay dos verdades -- y eso ya rompió
    esto una vez.
    """
    if declaracion.get("guests"):
        return list(declaracion["guests"])
    return list(declaracion.get("vms") or []) + list(declaracion.get("containers") or [])


def interfaz_del_bastion(declaracion, puente):
    """La interfaz del bastión que está en ese bridge (`ethN`), o None.

    El índice es el ORDEN de las interfaces declaradas del bastión, igual que `etherN`
    en un RouterOS: las interfaces no tienen nombre propio en el motor (no se inventa
    un dato que el invitado pone solo), así que la forma de nombrarlas es su posición.
    """
    for guest in _invitados_de(declaracion):
        if isinstance(guest, dict) and tiene_tunnel(guest):
            patas = _patas_de(guest)
            if puente in patas:
                return f"eth{patas.index(puente)}"
    return None


def captura_de(declaracion):
    """El comando de captura que se lanzaría en el bastión, ya escrito. PURA.

    Una captura que no se puede lanzar no devuelve un comando a medias: devuelve su
    `error`, y quien llama lo dice en vez de capturar el vacío.
    """
    decl = declaracion.get("capture")
    if not isinstance(decl, dict):
        return None
    puente = str(decl.get("bridge") or "").strip()
    iface = interfaz_del_bastion(declaracion, puente)
    if iface is None:
        return {"error": f"el bastión no tiene una interfaz en el bridge '{puente}'"}
    segundos = decl.get("segundos")
    filtro = str(decl.get("filtro") or "").strip()
    comando = (
        f"bash -c 'command -v tcpdump >/dev/null 2>&1 || "
        f"(apt-get update -qq && apt-get install -y -qq tcpdump) >/dev/null 2>&1; "
        f"command -v tcpdump >/dev/null 2>&1 || "
        f'{{ echo "OMITIDA: no hay tcpdump en el bastión ni se pudo instalar"; exit 3; }}; '
        f"echo \"CAPTURANDO en {iface} ({puente}) durante {segundos} s: {filtro or 'todo el tráfico'}\"; "
        f"timeout {segundos} tcpdump -i {iface} -n -l {filtro} 2>/dev/null; "
        f"echo \"FIN DE LA CAPTURA\"; exit 0'"
    )
    return {
        "bridge": puente,
        "interfaz": iface,
        "filtro": filtro,
        "segundos": segundos,
        "comando": comando,
        "porque": (
            f"el lab pide mirar el tráfico de '{puente}' durante {segundos} s, y el bastión "
            f"tiene una pata ahí ({iface})"
        ),
    }


def impairment_de(declaracion):
    """El comando de impairment que se lanzaría en el bastión, ya escrito. PURA.

    Es ACOTADO por diseño: `tc ... add`, espera, `tc ... del`. Un `netem` que se queda
    puesto convierte el lab en un lab roto que nadie recuerda haber roto.
    """
    decl = declaracion.get("impairment")
    if not isinstance(decl, dict):
        return None
    puente = str(decl.get("bridge") or "").strip()
    iface = interfaz_del_bastion(declaracion, puente)
    if iface is None:
        return {"error": f"el bastión no tiene una interfaz en el bridge '{puente}'"}
    segundos = decl.get("segundos")
    retardo = str(decl.get("retardo") or "").strip()
    jitter = str(decl.get("jitter") or "").strip()
    perdida = str(decl.get("perdida") or "").strip()
    partes = []
    if retardo or jitter:
        partes.append(f"delay {retardo or '0ms'}" + (f" {jitter}" if jitter else ""))
    if perdida:
        partes.append(f"loss {perdida}")
    netem = " ".join(partes)
    comando = (
        f"bash -c 'command -v tc >/dev/null 2>&1 || "
        f'{{ echo "OMITIDA: no hay tc en el bastión (hace falta iproute2)"; exit 3; }}; '
        f"tc qdisc del dev {iface} root >/dev/null 2>&1; "
        f"tc qdisc add dev {iface} root netem {netem} || "
        f'{{ echo "KO: el bastión no aceptó el impairment ({netem})"; exit 1; }}; '
        f"echo \"IMPAIRMENT ENCENDIDO en {iface} ({puente}): {netem} durante {segundos} s\"; "
        f"sleep {segundos}; tc qdisc del dev {iface} root >/dev/null 2>&1; "
        f"echo \"IMPAIRMENT APAGADO en {iface}: el lab vuelve a estar como estaba\"; exit 0'"
    )
    return {
        "bridge": puente,
        "interfaz": iface,
        "segundos": segundos,
        "netem": netem,
        "comando": comando,
        "porque": (
            f"el lab pide estropear el tráfico de '{puente}' ({netem}) durante {segundos} s, "
            f"y el bastión tiene una pata ahí ({iface})"
        ),
    }


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
    # 6.3 · La barrera que el lab DECLARA (ADR 0021) manda sobre la que el motor insinúa
    # por el tipo del equipo. `ninguno` la quita: un invitado que no tiene por qué
    # contestar a nadie se arranca sin barrera, y decirlo es distinto de olvidarlo.
    ready = guest.get("ready") if isinstance(guest.get("ready"), dict) else {}
    clase = str(ready.get("tipo") or "").strip()
    if clase == "ninguno":
        return None
    tipo = tipo_de(guest)
    # Sin interior declarado el motor no insinúa nada (¿qué va a insinuar, si no hay
    # `config`?). Pero si el LAB declara la barrera, la hay: eso era justo lo que no se
    # podía pedir -- un invitado sin `config` no tenía forma de decir «espérame».
    if tipo is None and clase not in ("ssh", "routeros_rest"):
        return None
    tipo = tipo or "linux"
    # Sólo se sondea lo que la declaración PROMETE con una dirección fija: un equipo que
    # toma su dirección por DHCP (`address: dhcp`) no tiene dirección que preguntar hasta
    # que su router se la da, así que no hay sonda que valga -- y no se inventa una. El
    # etapa se arranca sin barrera y el lab lo dice en su prosa.
    if _a_entero(_sin_prefijo(guest.get("address"))) is None:
        return None
    # El puerto: el que el lab declare, o el que el tipo del equipo promete.
    if clase == "ssh":
        puerto = 22
    elif clase == "routeros_rest":
        puerto = 80
    else:
        puerto = 80 if tipo == "routeros" else 22
    # Y la ventana: una espera en SEGUNDOS -- que es lo que un lab sabe estimar -- dicha
    # en intentos, que es lo que la sonda cuenta. `None` = la del motor.
    espera = ready.get("espera")
    intentos = None
    if isinstance(espera, int) and not isinstance(espera, bool) and espera > 0:
        intentos = max(1, espera // SONDA_SEGUNDOS_POR_INTENTO)
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
            "intentos": intentos,
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
    "routes": {
        # Las rutas ESTÁTICAS, y sólo ésas: se piden las que llevan pasarela (` via `) y se
        # descartan las conectadas (`proto kernel`, las pone el sistema), las del DHCP y la
        # de salida por defecto (`default`), que la declara el lab a nivel de plataforma.
        # `|| true` NO es decoración: el analizador marca como NO LEÍDA toda área cuyo `rc`
        # no sea 0 (un `rc != 0` es AVERÍA, no estado) -- y un `grep` sin resultados devuelve
        # 1. Sin esto, un Linux SIN rutas estáticas se leería como «no pude leer» y el driver
        # pararía con «no leyó el área 'routes'» en vez de concluir, correctamente, que no hay
        # ninguna que poner. Medido: es exactamente lo que pasó en el primer apply.
        "comando": ("ip -4 route show | grep ' via ' "
                    "| grep -vE '^(default|169\\.254)' | grep -v ' proto dhcp ' || true"),
        "descripcion": "sus rutas estáticas (las que el motor gobierna)",
    },
    "latido": {
        # TRES cosas en un viaje, en este orden: si el temporizador está ARMADO, si está
        # habilitado al arranque, y LA MARCA del fichero, que dice con qué cadencia se puso.
        # Sin la marca, cambiar la cadencia no se notaría y el motor diría «convergido» con
        # la cadencia vieja puesta -- que es la forma silenciosa de mentir.
        "comando": (f"systemctl is-active {UNIDAD_LATIDO} 2>/dev/null || echo inactive; "
                    f"systemctl is-enabled {UNIDAD_LATIDO} 2>/dev/null || echo disabled; "
                    f"grep -h '^# netlabs latido' /etc/systemd/system/{UNIDAD_LATIDO} "
                    "2>/dev/null || echo sin-marca"),
        "descripcion": "si el latido está armado, y con qué cadencia",
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
    # El área `servicio` NO vive aquí: su lectura depende de QUÉ servicio declara el lab
    # (cuántos ficheros, qué comprobación), así que la construye `lectura_servicio(nombre)`.
}

SEPARADOR = "---NETLABS---"


def lecturas_linux(guest):
    """Las lecturas que hay que hacer dentro de un Linux, en orden, por área declarada.

    Sólo se pregunta por lo que el lab DECLARA: fuera de las áreas declaradas el motor
    no opina (regla 17), así que tampoco pregunta.
    """
    declaradas = areas_de(guest)
    lecturas = []
    for area in areas_a_leer(guest):
        if area == "servicio":
            nombre = declaradas.get("servicio")
            lecturas.append({
                "area": area,
                "accion": "leer",
                "comando": lectura_servicio(nombre),
                "descripcion": (f"si el servicio '{nombre}' está instalado, su unidad viva, "
                                "sus ficheros puestos y sirviendo lo que promete"),
            })
        elif area == "monitorizacion":
            nombre_servicio = str(declaradas.get("servicio") or "")
            vigilancia = (SERVICIOS_LINUX_OPCIONES.get(nombre_servicio) or {}).get("monitorizacion")
            if vigilancia:
                lecturas.append({
                    "area": area,
                    "accion": "leer",
                    "comando": vigilancia["comando"],
                    "descripcion": (f"si el servidor de vigilancia '{nombre_servicio}' ya sabe a "
                                    "quién tiene que vigilar"),
                })
        elif area in LECTURAS_LINUX:
            lecturas.append({
                "area": area,
                "accion": "leer",
                "comando": LECTURAS_LINUX[area]["comando"],
                "descripcion": LECTURAS_LINUX[area]["descripcion"],
            })
    return lecturas


def lectura_servicio(nombre):
    """La lectura de un Linux cuyo área `servicio` declara `nombre` (un solo viaje).

    SIETE bloques separados por la marca de siempre:
      1) qué herramientas hay -- las del servicio y lo que la comprobación necesita,
      2) si su unidad está VIVA (`is-active`),
      3) si además está HABILITADA (`is-enabled`),
      4)..n) el CONTENIDO de cada fichero que el motor gobierna, EN EL ORDEN de la tabla,
      n+1) si de verdad SIRVE (el comando del servicio),
      n+2) la comprobación ADICIONAL (o `na` si no la tiene).

    Los dos últimos van SIEMPRE, para que el analizador no necesite saber de qué servicio se
    trata. Un nombre fuera del vocabulario no tiene lectura: el validador lo rechaza antes.
    """
    opciones = SERVICIOS_LINUX_OPCIONES.get(str(nombre or ""))
    if not opciones:
        return ""
    partes = [
        "for h in " + " ".join(opciones["herramientas"])
        + '; do echo "$h=$(command -v $h || echo NO)"; done',
        f"systemctl is-active {opciones['unidad']} 2>/dev/null || echo inactive",
        f"systemctl is-enabled {opciones['unidad']} 2>/dev/null || echo disabled",
    ]
    partes += [f"cat {ruta} 2>/dev/null" for ruta in opciones["ficheros"]]
    partes += [opciones["sirve"], opciones["extra"]]
    return ("; echo " + SEPARADOR + "; ").join(partes)


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

        elif area == "routes":
            # `ip -4 route show` -> "10.44.1.0/24 via 10.44.0.11 dev eth0 proto static"
            # Sólo lo que el motor gobierna: destino y pasarela. Lo conectado y lo del DHCP
            # ya lo filtró la orden de lectura.
            estaticas = []
            for linea in lineas:
                trozos = linea.split()
                if "via" in trozos:
                    estaticas.append({"dst_address": trozos[0],
                                      "gateway": trozos[trozos.index("via") + 1]})
            leido["routes"] = {"estaticas": estaticas}

        elif area == "latido":
            leido["latido"] = {
                "activo": (lineas[0] if lineas else "") == "active",
                "habilitado": len(lineas) > 1 and lineas[1] == "enabled",
                "marca": lineas[2] if len(lineas) > 2 else "",
            }

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

        elif area == "servicio":
            # SIETE bloques en un viaje, y el analizador NO necesita saber de qué servicio se
            # trata: herramientas, vivo, habilitado, un bloque por fichero gobernado (`sirve`
            # y `extra` van SIEMPRE los dos últimos, con `na` en `extra` cuando el servicio no
            # tiene comprobación adicional). Así el mismo analizador sirve para todo el
            # vocabulario, y el que decide qué significa cada fichero es `_servicio_canonico`,
            # que sí sabe qué servicio se declaró.
            bloques = str(texto).split(SEPARADOR)
            if len(bloques) < 5:
                # Una lectura incompleta no es un estado: sin los siete bloques no se puede
                # decir si el servicio está bien, así que se deja el área SIN LEER y el driver
                # para con su nombre, en vez de inventar «no sirve» y recargar a ciegas.
                continue
            activa = _lineas(bloques[1])
            habilitada = _lineas(bloques[2])
            servido = bloques[-2]
            leido["servicio"] = {
                "herramientas": _lineas_servicio(bloques[0]),
                # DOS hechos distintos, no uno: estar VIVO (`is-active`) y estar HABILITADO
                # (`is-enabled`). Un servicio vivo pero deshabilitado no arranca al reiniciar,
                # y mirar sólo `is-active` lo daba por bueno para siempre.
                "activo": bool(activa) and activa[0] == "active",
                "habilitado": bool(habilitada) and habilitada[0] == "enabled",
                # Los ficheros se leen ENTEROS, crudos y EN ORDEN: quien decide si están bien
                # es el canónico, que es quien sabe qué se escribiría. La marca sola no prueba
                # nada -- una configuración editada a mano la conserva, y un fichero puede no
                # estar.
                "ficheros_leidos": [b if isinstance(b, str) else "" for b in bloques[3:-2]],
                # Sirve si curl sacó algo que NO sea la marca de fallo: un 200 con cuerpo.
                "sirve": bool(str(servido).strip()) and "NO-SIRVE" not in str(servido),
                # La comprobación ADICIONAL del servicio (`si`/`no`), que sólo él sabe hacer.
                "extra": str(bloques[-1]).strip(),
            }

        elif area == "monitorizacion":
            # Un solo dato: si el servidor de vigilancia ya sabe a quién vigilar. El
            # comando del servicio imprime `si`/`no` (y `no` si ni siquiera está).
            leido["monitorizacion"] = {"sembrado": (lineas[0] if lineas else "no") == "si"}
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


# ---------------------------------------------------------------------------
# El área `servicio`: un servicio instalado, configurado y SIRVIENDO
# ---------------------------------------------------------------------------
# El vocabulario CERRADO de servicios que un Linux puede declarar en el área `servicio`.
# Cada miembro es un SERVICIO que el motor sabe instalar, configurar y dejar SIRVIENDO; un
# nombre que no esté aquí se RECHAZA en el validador (`declaracion.py`) con su motivo: el lab
# no inventa primitivas (regla 15). Añadir un miembro es una primitiva nueva, con su ADR.
SERVICIOS_LINUX = ("caddy", "netxms")

# El repositorio APT de NetXMS no está en Debian: lo añade su paquete de release, que se
# descarga de packages.netxms.org. Se pincha VERSIÓN de la web porque el cliente web (el WAR)
# y el servidor (el paquete) se hablan: el WAR no está en el repositorio APT, sólo en la web
# del proyecto. Sin versión fija, un `apply` podría dejar el WAR y el servidor de versiones
# distintas y la web dejaría de entrar (el cliente comprueba la versión del protocolo).
NETXMS_VERSION = "7.0.3"
NETXMS_REPO_DEB = "https://packages.netxms.org/netxms-release-latest.deb"
NETXMS_WAR = f"https://netxms.org/download/releases/7.0/nxmc-{NETXMS_VERSION}.war"
NETXMS_WEBAPPS = "/var/lib/tomcat10/webapps"
NETXMS_BD = {"nombre": "netxms", "usuario": "netxms", "clave": "netlabs", "tipo": "pgsql"}

# El ADMINISTRADOR de la web de NetXMS. `nxdbmgr init` genera una clave al azar y la imprime
# UNA vez si no se le da: una web a la que no se puede entrar no cumple nada, así que el
# motor le PONE una clave conocida. No es un valor de lab (regla 7) ni abre nada del
# anfitrión: es la cuenta de la propia aplicación, dentro del invitado, y el lab la cita en
# su documentación para poder mirarla (como el resto de credenciales del banco de pruebas).
NETXMS_ADMIN = {"usuario": "admin", "clave": "netlabs"}

# La marca que deja el SEMBRADO de la vigilancia (área `monitorizacion`): mientras exista, el
# motor sabe que ya le dijo al servidor a quién vigilar y no vuelve a pedirlo (regla 6).
RUTA_MARCA_SEMBRADO = "/var/lib/netlabs-vigilancia-sembrada"

# Donde el preparador guarda el HASH de la clave buena del administrador (nunca la clave en
# claro) para poder devolverla sin rehacer la base: el paquete reescribe ese hash al entrar y,
# medido, el que escribe ya no verifica -- es el camino de vuelta barato.
RUTA_CLAVE_BUENA = "/var/lib/netlabs-vigilancia-clave"

# La ruta del preparador de NetXMS: un guion que el motor ESCRIBE en el invitado (como la
# configuración) y que hace las piezas que necesitan más de un comando: base, usuario,
# esquema y WAR. Su contenido es del motor (regla 7), y va en un fichero en vez de en una
# línea de shell kilométrica porque cada pieza es idempotente por separado y así se lee.
RUTA_PREPARADOR_NETXMS = "/usr/local/sbin/netlabs-servicio-netxms"

# La unidad del paquete arranca `netxmsd -S` SIN decirle dónde está su configuración, y el
# servidor NO lee `/etc/netxmsd.conf` por su cuenta (medido: arrancó con una base SQLite
# local, en vez de la PostgreSQL que declara el fichero). No se adivina la ruta que el
# binario trae por defecto: se le dice la nuestra con un `drop-in` de systemd, que es del
# motor como el resto de la configuración.
RUTA_DROPIN_NETXMS = "/etc/systemd/system/netxms-server.service.d/netlabs.conf"

# Lo que el motor sabe hacer con cada servicio, en un solo sitio. Nada de esto es un valor de
# ningún lab: es vocabulario del MOTOR (regla 7). Las claves, todas obligatorias (un servicio
# sin alguna de ellas no se puede gobernar entero, así que no entra en el vocabulario):
#   paquetes           lo que se instala (incluido `curl`, que la relectura necesita)
#   herramientas       ejecutables cuya AUSENCIA prueba que falta el paquete
#   unidad             la unidad de systemd del servicio
#   ficheros           rutas que el motor gobierna, EN ORDEN (el contenido se compara entero)
#   sirve              comando que comprueba que el servicio de verdad sirve
#   extra              lectura ADICIONAL (imprime `si`/`no`); `na` si el servicio no la tiene
#   extra_esperado     el valor de `extra` que significa «preparado» (None: no se usa)
#   preparar           comandos idempotentes que dejan el servicio en estado de arrancar
#   preparar_paquetes  lo que hay que hacer ANTES de instalar (p. ej. añadir el repositorio)
#   espera             segundos de respiro tras arrancar, antes de que la relectura pregunte
SERVICIOS_LINUX_OPCIONES = {
    "caddy": {
        "paquetes": ("caddy", "curl"),
        "herramientas": ("caddy", "curl"),
        "unidad": "caddy",
        "ficheros": ("/etc/caddy/Caddyfile", "/var/www/html/index.html"),
        "sirve": "curl -fsS -m 5 http://127.0.0.1/ 2>/dev/null || echo NO-SIRVE",
        "extra": "echo na",
        "extra_esperado": None,
        "preparar": (),
        "preparar_paquetes": (),
        "espera": 2,
    },
    "netxms": {
        # `netxms-server` es el servidor; `netxms-dbdrv-pgsql` su driver de base (el paquete
        # NO trae ninguno: sin driver, el servidor no arranca); `postgresql` la base;
        # `tomcat10` el contenedor de servlets de la web (Jakarta EE 10, que es lo que pide
        # el WAR de NetXMS); `curl` lo que la relectura y el preparador usan para descargar.
        "paquetes": ("netxms-server", "netxms-dbdrv-pgsql", "postgresql", "tomcat10", "curl"),
        "herramientas": ("netxmsd", "nxdbmgr", "nxadm", "psql", "curl", "java"),
        "unidad": "netxms-server",
        "ficheros": ("/etc/netxmsd.conf", RUTA_DROPIN_NETXMS, RUTA_PREPARADOR_NETXMS),
        # SIRVE = se puede ENTRAR por el navegador: pide la página a Tomcat, no el puerto del
        # servidor (4700), porque lo que el lab promete es la interfaz web. Reintenta acotado:
        # un WAR de 53 MB no está desplegado dos segundos después de arrancar Tomcat, y sin
        # reintento la primera pasada pediría recargar para siempre.
        # CON `-L`: `/nxmc/` contesta 302 (a la aplicación ligera) y sin seguir la redirección
        # el cuerpo llega VACÍO -- que la relectura leería como «no sirve» para siempre
        # (medido). Se sigue UNA redirección y se exige que la página traiga cuerpo.
        "sirve": ("curl -fsSL -m 10 --retry 12 --retry-delay 5 --retry-connrefused "
                  "http://127.0.0.1:8080/nxmc/ 2>/dev/null || echo NO-SIRVE"),
        "extra": f"sh {RUTA_PREPARADOR_NETXMS} estado 2>/dev/null || echo no",
        "extra_esperado": "si",
        "preparar": (f"sh {RUTA_PREPARADOR_NETXMS} preparar",),
        # La VIGILANCIA (área `monitorizacion`): `sembrar` es lo que le dice al servidor
        # quién hay que vigilar, de UNA vez, recorriendo la red por la que el invitado ve a
        # los equipos (él mismo la deriva de su interfaz: no es un valor de lab). Deja una
        # marca, y esa marca es lo que hace la operación idempotente (regla 6): la segunda
        # pasada lee `si` y no pide nada.
        "monitorizacion": {
            "comando": f"sh {RUTA_PREPARADOR_NETXMS} sembrado 2>/dev/null || echo no",
            "esperado": "si",
        },
        "sembrar": (f"sh {RUTA_PREPARADOR_NETXMS} sembrar",),
        # Sin `apt-get update` DESPUÉS de añadir el repositorio, el `install` no ve sus
        # paquetes; y sin `ca-certificates` el `curl` de la descarga no puede verificar el
        # certificado de packages.netxms.org en la imagen base.
        "preparar_paquetes": (
            ("DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates "
             "lsb-release"),
            # El paquete de release trae la clave Y una lista con `VENDOR`/`DIST` que
            # rellena su postinst con `lsb_release` -- y si ese postinst no llega a correr
            # (dependencia sin resolver), la lista queda con la plantilla y `apt-get update`
            # falla ENTERO: no instala NADA, ni siquiera lo de Debian (medido). Por eso la
            # lista se escribe aquí, desde el propio invitado (`/etc/os-release` dice
            # distribuidor y versión), en vez de confiar en que el postinst la arregle.
            (f"if ! dpkg -s netxms-release 2>/dev/null | grep -qx 'Status: install ok installed'; then "
             f"curl -fsSL -o /tmp/netxms-release.deb {NETXMS_REPO_DEB} && "
             "dpkg -i --force-confnew /tmp/netxms-release.deb; fi"),
            ('. /etc/os-release && printf '
             '"deb [signed-by=/etc/apt/keyrings/netxms-keyring.gpg] '
             'https://packages.netxms.org/7.x/%s %s main\\n" "$ID" "$VERSION_CODENAME" '
             '> /etc/apt/sources.list.d/netxms.list'),
            "DEBIAN_FRONTEND=noninteractive apt-get update -qq",
        ),
        "espera": 5,
    },
}

# La marca que el motor escribe en la configuración del servicio: es lo que distingue «el
# motor pasó por aquí» de «el paquete trae la suya». Sin ella, la relectura daría por buena
# una configuración ajena y el área no gobernaría el fichero que dice gobernar.
MARCA_SERVICIO = "# netlabs-servicio"


def configuracion_servicio(nombre):
    """El fichero de configuración de `caddy`, tal cual se escribe en el invitado.

    Se queda con este nombre por lo que ya significa en el motor y en las pruebas: el
    `Caddyfile` del servicio `caddy`. La forma general es `_ficheros_servicio`, que es la que
    usa el área; para un servicio que no es `caddy` esto devuelve "".
    """
    return _ficheros_servicio(nombre).get("/etc/caddy/Caddyfile", "")


def pagina_servicio():
    """La página de relleno que sirve `caddy`.

    Es del MOTOR, no del lab: el lab sólo pide que HAYA un servicio, y para comprobar que
    de verdad sirve hace falta algo que servir (un `file_server` sin `index.html` contesta
    404, y la relectura lo leería como «no sirve» para siempre).
    """
    return (
        "<!doctype html>\n<title>netlabs</title>\n"
        "<p>netlabs: servicio declarado y sirviendo.</p>\n"
    )


def _configuracion_caddy():
    """El `Caddyfile` mínimo que sirve una página: escucha en el 80 y sirve `/var/www/html`.

    La ruta y el contenido son del MOTOR -- el lab sólo declara el NOMBRE del servicio --
    porque un servidor web que no sirve nada no cumple nada. Lleva la MARCA que distingue el
    fichero del motor del que trae el paquete.
    """
    return "\n".join([
        "# PROPÓSITO: sirve una página de laboratorio; lo escribe el motor (netlabs).",
        "# No se edita a mano: el motor lo reescribe desde la declaración.",
        MARCA_SERVICIO,
        ":80 {",
        "\troot * /var/www/html",
        "\tfile_server",
        "}",
    ]) + "\n"


def _configuracion_netxms():
    """La configuración del servidor NetXMS (`/etc/netxmsd.conf`).

    Dice SÓLO dónde está su base: driver, nombre, usuario, clave y host. La clave es del
    laboratorio (sandbox) y vive en el motor, no en la declaración: un lab no escribe
    credenciales (regla 7). `DBHost` es 127.0.0.1 y no un socket porque PostgreSQL, en
    Debian, autentica `peer` por socket -- como el motor entra por SSH como `root`, el
    usuario `postgres` no es el del servicio y el socket no le valdría.
    """
    return "\n".join([
        "# PROPÓSITO: la configuración del servidor NetXMS; la escribe el motor (netlabs).",
        "# No se edita a mano: el motor la reescribe desde la declaración.",
        MARCA_SERVICIO,
        "DBDriver = pgsql",
        f"DBName = {NETXMS_BD['nombre']}",
        f"DBLogin = {NETXMS_BD['usuario']}",
        f"DBPassword = {NETXMS_BD['clave']}",
        "DBHost = 127.0.0.1",
    ]) + "\n"


# El guion que el motor escribe en el invitado para preparar NetXMS. Es una PLANTILLA con
# tres huecos (`%(webapps)s`, `%(war)s`, los de la base) y no un f-string porque el shell está
# lleno de llaves (`${1:-preparar}`, `$((i + 1))`) que un f-string se comería.
PLANTILLA_PREPARADOR_NETXMS = r'''#!/bin/sh
# PROPÓSITO: dejar NetXMS en estado de arrancar: su base en PostgreSQL con su usuario, su
#            esquema y su interfaz web desplegada en Tomcat. Lo escribe el motor (netlabs)
#            desde el área `servicio`; no se edita a mano.
# USO:       netlabs-servicio-netxms preparar|estado|sembrar|sembrado
#            `preparar` es idempotente; `estado` imprime `si` cuando la base ya tiene el
#            esquema de NetXMS Y el WAR de la web está desplegado (es lo que el motor lee
#            para decidir si hay que preparar); `sembrar` le dice al servidor a QUIÉN tiene
#            que vigilar (ronda la red del propio invitado por SNMP) y deja su marca;
#            `sembrado` imprime `si` si esa marca está.
set -u

WEBAPPS="%(webapps)s"
WAR="%(war)s"
ADMIN="%(admin_usuario)s"
ADMIN_CLAVE="%(admin_clave)s"
COMUNIDAD="%(comunidad)s"
MARCA="%(marca)s"
# La clave buena del administrador -- SÓLO su hash, nunca la clave en claro -- tal y como la
# dejó `init`: es el camino de vuelta BARATO cuando el paquete la estropea (ver `reponer_clave`).
CLAVE_BUENA="%(clave_buena)s"

# Todo lo que va a PostgreSQL se ejecuta como `postgres` y desde /tmp: `su` sin `-` conserva
# el directorio, y `root` no es accesible para ese usuario (sólo dejaría un aviso inútil).
como_postgres() {
    su postgres -c "cd /tmp && $*" 2>/dev/null
}

tablas() {
    como_postgres "psql -tA -d %(bd)s -c \"select count(*) from information_schema.tables where table_schema = 'public'\""
}

esquema() {
    n=$(tablas | tr -d ' \r')
    case "$n" in
        ''|0|*[!0-9]*) echo no ;;
        *) echo si ;;
    esac
}

# El estado que le importa al motor es TODO lo que tiene que existir para que el servicio
# SIRVA: el esquema de la base, el WAR de la web... y que se pueda ENTRAR. Si se mirara sólo
# la base, un WAR que no llegó a descargarse no se volvería a pedir nunca (la base ya está) y
# la web no serviría jamás. Y sin la tercera -- la clave del administrador APLICADA -- la web
# está en pie y no se entra: el paquete ARRANCA el servidor al instalarse, deja la base
# bloqueada y la clave se queda en la que `init` generó al azar (medido). Un servicio al que
# no se puede entrar no está convergido.
# Lo que CONTESTA el API web al intentar entrar: el código HTTP, o `000` si no contesta. Se
# pregunta por el API WEB porque es EXACTAMENTE la puerta por la que entra la interfaz. `nxadm`
# (la consola de depuración) queda PROHIBIDA aquí: autentica bien y aun así deja la clave rota
# para la web (medido: justo antes de la consola el API contesta 201; justo después, 403
# `errorCode 61`, y ya no se recupera).
respuesta_de_la_web() {
    curl -sS -m 10 -o /dev/null -w '%%{http_code}' -X POST "http://127.0.0.1:8000/v1/login" \
        -H 'Content-Type: application/json' \
        -d "{\"username\":\"$ADMIN\",\"password\":\"$ADMIN_CLAVE\"}" 2>/dev/null || echo 000
}

# ¿Se puede entrar? Tres respuestas, y la diferencia IMPORTA:
#   `si`          -- el API contesta 201: la clave está aplicada y se entra.
#   `rechaza`     -- contesta y NO acepta la clave: es la AL AZAR del paquete. Se rehace la base.
#   `no-contesta` -- no hay API (un servidor que aún arranca, tomcat caído). NO se rehace nada:
#                    rehacer la base por esto tiraba el descubrimiento entero (medido). Se le da
#                    un respiro largo -- un servidor tarda ~7 s en activar -- y se vuelve a mirar.
entra() {
    codigo=000
    i=0
    while [ "$i" -lt 20 ]; do
        codigo=$(respuesta_de_la_web)
        [ "$codigo" = "201" ] && { echo si; return 0; }
        i=$((i + 1)); sleep 3
    done
    if [ "$codigo" = "000" ]; then echo no-contesta; else echo rechaza; fi
}

# Devolver la clave buena SIN tocar un solo dato. `netxms-server`, al ENTRAR con un hash en
# formato viejo, lo reescribe a argon2id (`[userdb] Password hash has to be recomputed`) y ese
# argon2id -- medido, determinista -- deja de verificar: desde ahí TODO login contesta 403. Una
# base con la topología ya descubierta no se tira por eso: se para el servidor, se devuelve el
# hash que `init` dejó (el que SÍ verifica) y se vuelve a arrancar. Se comprueba preguntando.
reponer_clave() {
    [ -s "$CLAVE_BUENA" ] || return 1
    systemctl stop netxms-server >/dev/null 2>&1
    sleep 2
    buena=$(cat "$CLAVE_BUENA")
    como_postgres "psql -q -d %(bd)s -c \"update users set password='$buena' where id=1\"" \
        || { systemctl start netxms-server >/dev/null 2>&1; return 1; }
    systemctl start netxms-server >/dev/null 2>&1
    [ "$(entra)" = "si" ]
}

# Los equipos que el servidor tiene YA en su base -- lo que la web enseña --. Se leen de la
# base, no de la consola: la consola rompe la clave del administrador (medido).
vigilados() {
    como_postgres "psql -tA -d netxms -c 'select count(*) from nodes'" 2>/dev/null | tr -d ' \r'
}

estado() {
    [ "$(esquema)" = "si" ] && [ -s "$WEBAPPS/nxmc.war" ] \
        && [ "$(entra)" = "si" ] \
        && echo si || echo no
}

case "${1:-preparar}" in
estado)
    estado
    ;;
sembrado)
    # Lo que lee el motor para decidir si hay que sembrar (regla 6): la marca, y nada más.
    if [ -f "$MARCA" ]; then echo si; else echo no; fi
    ;;
sembrar)
    # Se pregunta por el API WEB (la puerta de la interfaz), nunca por la consola: `nxadm`
    # autentica bien y aun así deja la clave rota para la web (medido). Y se le da un respiro
    # acotado: una ronda antes de que el servidor arranque no siembra nada.
    como=$(entra)
    if [ "$como" != "si" ]; then
        if [ "$como" = "rechaza" ]; then
            echo "el servidor de vigilancia NO acepta la clave del administrador: no se puede sembrar" >&2
        else
            echo "el servidor de vigilancia no contesta en su API web: no se puede sembrar" >&2
        fi
        exit 1
    fi
    # La red por la que ESTE invitado ve a los equipos vigilados: la suya. No es un valor de
    # lab -- se deriva de su propia interfaz, y el banco de pruebas declara sus redes /24.
    base=$(ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | head -1 | cut -d/ -f1 | cut -d. -f1-3)
    if [ -z "$base" ]; then
        echo "sin dirección en eth0: no se sabe a quién vigilar" >&2
        exit 1
    fi
    # El descubrimiento NO se dispara desde aquí: lo hace el SERVIDOR solo -- el `preparar` le
    # deja declarada la red a vigilar y el descubrimiento activo encendido --, y aquí sólo se
    # ESPERA a que sus hallazgos estén en la base. La consola (`nxadm -c "scan"`) era lo que
    # rompía la clave del administrador (medido), así que se fue de aquí.
    i=0
    while [ "$i" -lt 40 ] && [ "$(vigilados)" = "0" ]; do
        i=$((i + 1)); sleep 3
    done
    if [ "$(vigilados)" = "0" ]; then
        echo "el servidor de vigilancia no ha añadido un solo equipo todavía: tiene declarada la red $base.0/24 con descubrimiento activo, y la ronda tarda (se le da otra pasada)" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$MARCA")"
    : > "$MARCA"
    ;;
preparar)
    # El `drop-in` de la unidad acaba de escribirse: sin recargar systemd no lo ve.
    systemctl daemon-reload
    # `netxms-server` arrastra `netxms-agent` como dependencia, y el agente se queda con el
    # puerto 4700 (el suyo). Este lab no monitoriza nada: el agente no pinta nada y sólo
    # añade un servicio que el lab no ha declarado.
    systemctl disable --now netxms-agent >/dev/null 2>&1
    systemctl enable --now postgresql >/dev/null 2>&1
    i=0
    while [ "$i" -lt 30 ] && ! pg_isready -q; do i=$((i + 1)); sleep 1; done
    if [ "$(como_postgres "psql -tA -c \"select 1 from pg_roles where rolname = 'netxms'\"")" != "1" ]; then
        como_postgres "psql -qc \"create role netxms login password 'netlabs'\""
    fi
    if [ "$(como_postgres "psql -tA -c \"select 1 from pg_database where datname = 'netxms'\"")" != "1" ]; then
        como_postgres "createdb -O netxms netxms"
    fi
    # ¿Se puede ENTRAR en el servicio que ya hay? La única forma de saberlo es PREGUNTARLE al
    # servidor -- es el que verifica una clave --, así que se ARRANCA para preguntar: en un
    # invitado recién creado el paquete lo deja CAÍDO (arranca antes de que exista su
    # configuración, no encuentra la base y se muere), y "está activo" no se puede dar por
    # hecho. Y se le da un respiro acotado antes de decidir: rehacer una base es una decisión
    # gorda y no se toma por un fallo pasajero (ni por un servidor que aún no ha terminado de
    # arrancar).
    systemctl start netxms-server >/dev/null 2>&1
    se_entra=$(entra)
    # Hay esquema pero la clave NO vale (el servidor contesta y la rechaza): es la AL AZAR que
    # dejó el paquete al instalarse -- nadie la leyó y la web no se puede entrar --, y dentro de
    # lo que el área declara la BASE ES DEL MOTOR: se rehace (regla 17). Una web a la que no se
    # puede entrar no cumple nada, así que "hay esquema" no basta. Y si el API no CONTESTA
    # (`no-contesta`) NO se rehace nada: no es la clave, es que aún no hay servidor, y rehacer la
    # base por eso tiraría el descubrimiento entero (medido).
    # Un `rechaza` NO se paga rehaciendo la base: primero el camino BARATO -- devolver el hash
    # que `init` dejó, sin tocar un solo dato --, y sólo si eso tampoco deja entrar se rehace.
    if [ "$se_entra" = "rechaza" ]; then
        reponer_clave && se_entra=si
    fi
    if [ "$(esquema)" != "si" ] || [ "$se_entra" = "rechaza" ]; then
        # El servidor se PARA antes de tocar la base: con él en marcha la base está BLOQUEADA
        # -- `nxdbmgr` contesta "Database is locked by server ..." y no inicializa ni pone
        # clave ninguna (medido) --. Se vuelve a arrancar al final, cuando la base está como
        # tiene que estar.
        systemctl stop netxms-server >/dev/null 2>&1
        sleep 2
        # Se rehace desde cero: lo que no está declarado se quita, y una base con una clave que
        # nadie conoce no vale para nada.
        como_postgres "psql -qc 'drop database if exists %(bd)s'"
        como_postgres "createdb -O %(usuario)s %(bd)s" || exit 1
        # Con `-c` EXPLÍCITO: sin él `nxdbmgr` no encuentra la configuración y contesta
        # "Cannot determine database type from driver name" (medido).
        # Y el TIPO explícito: `nxdbmgr init` a secas deduce el motor del nombre del
        # driver... y con `-c` apuntando a la configuración contesta "Cannot determine
        # database type from driver name" (medido: `init pgsql` sí, `init` no).
        # La CLAVE DEL ADMINISTRADOR va AQUÍ, en el `init` (`-p`): `nxdbmgr init` genera una al
        # azar si no se le da -- y una web a la que no se puede entrar no cumple nada. El otro
        # camino (`set-user-password`, después) NO sirve: pide la clave por el terminal y en un
        # guion contesta "Cannot read password" (medido; con un TTY de verdad sí funciona, pero
        # un TTY no es algo que el motor deba necesitar para poner una clave).
        nxdbmgr -c /etc/netxmsd.conf -p "$ADMIN_CLAVE" init %(tipo)s || exit 1
        # La clave BUENA que el `init` acaba de escribir: se guarda SÓLO su hash -- nunca la
        # clave en claro, y en modo 600 -- para poder DEVOLVERLA sin rehacer la base. El paquete
        # la estropea él solo más adelante (ver `reponer_clave`), y sin este camino de vuelta la
        # única salida era tirar la base y con ella todo lo que el servidor hubiera aprendido
        # (medido: de 9 equipos vigilados a 3).
        como_postgres "psql -tA -d %(bd)s -c 'select password from users where id=1'" > "$CLAVE_BUENA"
        chmod 600 "$CLAVE_BUENA"
        # La base es nueva: lo que dijera la marca del sembrado ya es mentira -- no hay ni un
        # nodo --, así que se borra y la siembra vuelve a correr. Una marca que sobrevive a su
        # base no dice nada (regla 6: la marca vale porque describe lo que hay).
        rm -f "$MARCA"
    fi
    # Y la VIGILANCIA: que el servidor PREGUNTE -- descubrimiento activo, con sonda SNMP, sobre
    # la red que ESTE invitado ve (derivada de su propia interfaz: jamás un valor de lab) -- y
    # con qué comunidad: la MISMA que los equipos declaran con el área `snmp` (una constante del
    # motor, no un valor de lab, para que no haya dos sitios que se descoordinen). La ronda la
    # hace el SERVIDOR solo, cada `Interval` horas y al arrancar: no la dispara la consola, que
    # dejaba la clave del administrador rota para la web (medido).
    base=$(ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | head -1 | cut -d/ -f1 | cut -d. -f1-3)
    if [ -z "$base" ]; then
        echo "sin dirección en eth0: no se sabe qué red vigilar" >&2
        exit 1
    fi
    # `nxdbmgr set` deja el valor que se le da; repetirlo no cambia nada. Si no se pudiera
    # escribir, se PARA: un servidor que no pregunta no vigila, y darlo por bueno sería una
    # promesa sin respaldo.
    for ajuste in "DefaultCommunityString $COMUNIDAD" \
                  "NetworkDiscovery.Type 3" \
                  "NetworkDiscovery.ActiveDiscovery.EnableSNMPProbing 1" \
                  "NetworkDiscovery.ActiveDiscovery.AddressRange $base.0/24" \
                  "NetworkDiscovery.ActiveDiscovery.Interval 1" \
                  "NetworkDiscovery.ActiveDiscovery.Enabled 1"; do
        nxdbmgr -c /etc/netxmsd.conf set $ajuste >/dev/null 2>&1 || {
            echo "no se pudo dejar el ajuste '$ajuste' en el servidor de vigilancia" >&2
            exit 1
        }
    done
    nueva_web=no
    mkdir -p "$WEBAPPS"
    if [ ! -s "$WEBAPPS/nxmc.war" ]; then
        curl -fsSL -o "$WEBAPPS/nxmc.war" "$WAR" || exit 1
        nueva_web=si
    fi
    systemctl enable --now tomcat10 >/dev/null 2>&1
    if [ "$nueva_web" = "si" ]; then
        systemctl restart tomcat10
    fi
    # Y el servidor se ARRANCA al final -- pero SÓLO si no está ya arrancado: se para más arriba
    # para poder tocar la base, y un servidor parado sirve la web pero no deja ENTRAR en ella.
    # Un reinicio de MÁS no es inocuo (medido): al arrancar, el paquete reescribe el hash del
    # administrador a argon2id y ese argon2id deja de verificar -- el reinicio gratuito de cada
    # pasada era, él solo, lo que dejaba la clave rota.
    systemctl enable netxms-server >/dev/null 2>&1
    systemctl is-active --quiet netxms-server || systemctl start netxms-server >/dev/null 2>&1
    ;;
*)
    echo "uso: $0 preparar|estado|sembrar|sembrado" >&2
    exit 2
    ;;
esac
'''

def _dropin_netxms():
    """El `drop-in` de systemd que le dice al servidor DÓNDE está su configuración.

    Vaciar `ExecStart` antes de redefinirlo es obligatorio: systemd ACUMULA las líneas de
    `ExecStart` de la unidad y de sus `drop-in`, y sin el vaciado el servidor arrancaría dos
    veces (una sin configuración, con SQLite, y otra con la buena).
    """
    return "\n".join([
        "# PROPÓSITO: arrancar netxmsd con la configuración que gobierna el motor (netlabs).",
        "# No se edita a mano: el motor lo reescribe desde la declaración.",
        MARCA_SERVICIO,
        "[Service]",
        "ExecStart=",
        "ExecStart=/usr/bin/netxmsd -S -c /etc/netxmsd.conf",
    ]) + "\n"


def _preparador_netxms():
    """El guion que deja NetXMS en estado de arrancar (base, esquema y web).

    Va como fichero y no como una línea de shell porque son cuatro piezas idempotentes por
    separado. `estado` es la MISMA pregunta que hace la relectura del área (`extra`): si la
    base ya tiene tablas. Y `preparar` no lanza `nxdbmgr init` sobre una base ya inicializada
    (es un error, no una repetición inocua).
    """
    return PLANTILLA_PREPARADOR_NETXMS % {
        "webapps": NETXMS_WEBAPPS,
        "war": NETXMS_WAR,
        "bd": NETXMS_BD["nombre"],
        "usuario": NETXMS_BD["usuario"],
        "clave": NETXMS_BD["clave"],
        "tipo": NETXMS_BD["tipo"],
        "admin_usuario": NETXMS_ADMIN["usuario"],
        "admin_clave": NETXMS_ADMIN["clave"],
        "comunidad": COMUNIDAD_SNMP,
        "marca": RUTA_MARCA_SEMBRADO,
        "clave_buena": RUTA_CLAVE_BUENA,
    }


def _ficheros_servicio(nombre):
    """{ruta: contenido} de TODOS los ficheros que el área gobierna para `nombre`, en orden.

    Es el único sitio que sabe qué se escribe en cada fichero; el que los escribe y el que
    comprueba que están bien comparan lo mismo, así que no pueden desincronizarse. Devuelve
    un dict vacío para un nombre fuera del vocabulario: el validador lo rechaza antes, y
    aquí no se inventa contenido.
    """
    opciones = SERVICIOS_LINUX_OPCIONES.get(str(nombre or ""))
    if not opciones:
        return {}
    generadores = {
        "/etc/caddy/Caddyfile": _configuracion_caddy,
        "/var/www/html/index.html": pagina_servicio,
        "/etc/netxmsd.conf": _configuracion_netxms,
        RUTA_DROPIN_NETXMS: _dropin_netxms,
        RUTA_PREPARADOR_NETXMS: _preparador_netxms,
    }
    return {ruta: generadores[ruta]() for ruta in opciones["ficheros"]}


def _lineas_servicio(bloque):
    """Las líneas `clave=valor` de un bloque de herramientas -> {clave: presente}."""
    presentes = {}
    for linea in _lineas(bloque):
        clave, _, valor = linea.partition("=")
        if clave:
            # Un `command -v` sin resultado se toma por PRESENTE, igual que en `dhcp_server`:
            # la ausencia de la línea es una lectura incompleta, no una prueba de que falte;
            # sólo un `NO` explícito pide instalarlo.
            presentes[clave.strip()] = valor.strip() != "NO"
    return presentes


def _servicio_canonico(declarado, leido):
    """Diferencia del área `servicio`: qué hay que hacer para que el servicio sirva.

    El valor DECLARADO es el NOMBRE del servicio (`servicio: netxms`), tal cual: la
    declaración no envuelve en un mapa lo que ya es un dato. El resto -- paquetes, ficheros,
    comprobación -- es del motor, y cada miembro del vocabulario lo declara en
    `SERVICIOS_LINUX_OPCIONES`.

    Va en DOS sentidos, como el resto del interior: si falta el paquete se instala, si falta
    la configuración se escribe, si la base no está preparada se prepara, si la unidad no
    está viva se arranca y si no sirve se recarga. Un invitado ya convergido no produce
    NINGUNA operación -- que es lo que hace verdadera la promesa de la regla 6.
    """
    nombre = str(declarado or "")
    opciones = SERVICIOS_LINUX_OPCIONES.get(nombre)
    if not opciones:
        # El validador ya rechaza un nombre fuera del vocabulario; aquí sólo se es honesto:
        # sin opciones no se sabe qué escribir, así que no se decide nada (y el `else` de
        # `pasos_de_convergencia` no llegaría a dispararse porque el área sí existe).
        return []
    actual = leido if isinstance(leido, dict) else {}
    operaciones = []

    # Se pregunta por las HERRAMIENTAS, no por los paquetes: es lo que un `command -v` puede
    # contestar. Si falta cualquiera, se instala la lista entera -- `apt-get install` sobre lo
    # ya instalado no hace nada, y así no hay que mantener un mapa paquete->ejecutable.
    herramientas = actual.get("herramientas") or {}
    if any(not herramientas.get(h, True) for h in opciones["herramientas"]):
        operaciones.append({"op": "install_service", "servicio": nombre,
                            "paquetes": list(opciones["paquetes"])})

    # Los ficheros que el motor gobierna se comparan por su CONTENIDO ENTERO, en orden, contra
    # lo que el motor escribiría -- no por su marca: una configuración editada a mano conserva
    # la marca, y una página borrada no tiene ninguna, así que la marca sola daba el área por
    # buena con los ficheros mal (hallazgo del PR #12). El orden es el de la tabla.
    esperados = list(_ficheros_servicio(nombre).values())
    leidos = actual.get("ficheros_leidos") or []
    ficheros_cambiados = (len(leidos) != len(esperados) or any(
        str(leido_f or "").strip() != str(esperado or "").strip()
        for leido_f, esperado in zip(leidos, esperados)))
    if ficheros_cambiados:
        operaciones.append({"op": "write_service_config", "servicio": nombre})

    # Lo que el servicio necesita ANTES de arrancar y no pone ningún paquete: en NetXMS, la
    # base con su usuario y su esquema. Se pregunta por lo que el servicio mismo sabe mirar
    # (`extra`), no por «¿hay algo?»: `is-active` del servidor estaría en verde con la base
    # vacía y el servidor se caería en la primera consulta.
    if opciones.get("extra_esperado") and \
            str(actual.get("extra") or "").strip() != opciones["extra_esperado"]:
        operaciones.append({"op": "prepare_service", "servicio": nombre})

    # `is-active` no es `is-enabled`: un servicio VIVO pero DESHABILITADO no arranca al
    # reiniciar el invitado, y mirar sólo si está vivo lo daba por bueno para siempre.
    if not actual.get("activo") or not actual.get("habilitado"):
        operaciones.append({"op": "enable_service", "servicio": nombre})

    # Si la configuración se acaba de escribir, el servicio ya vivo seguiría sirviendo la
    # vieja hasta recargarlo; por eso «recargar» también se pide cuando los ficheros cambian.
    # Y si simplemente no sirve (config inválida, unidad a medias), recargar es lo que lo
    # levanta.
    if not actual.get("sirve") or ficheros_cambiados:
        operaciones.append({"op": "reload_service", "servicio": nombre})

    return operaciones


def _monitorizacion_canonica(declarado, leido, servicio):
    """Diferencia del área `monitorizacion`: que el servidor de vigilancia SEPA a quién vigilar.

    El valor declarado es una MARCA (`monitorizacion: {}`), como `uplink`: el lab dice «este
    servidor tiene que vigilar la red por la que ve a los equipos», y el CÓMO es del motor
    (ronda la red del propio invitado por SNMP). No hay nada que el lab pueda afinar sin
    inventarse una primitiva, y por eso no lleva opciones.

    Un solo hecho: si el servidor ya está sembrado (lo dice la marca que deja el sembrado).
    Sembrado, no produce NINGUNA operación -- que es lo que hace verdadera la promesa de la
    regla 6: la segunda pasada sólo lee.

    Sin un servicio que sepa vigilar no hay nada que sembrar: el validador ya lo rechaza, y
    aquí se devuelve la lista vacía en vez de inventar una operación que nadie traduce.
    """
    if not isinstance(leido, dict):
        return []
    opciones = SERVICIOS_LINUX_OPCIONES.get(str(servicio or "")) or {}
    if not opciones.get("sembrar"):
        return []
    if leido.get("sembrado"):
        return []
    return [{"op": "sembrar_monitorizacion", "servicio": str(servicio or "")}]



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

        elif op == "add_route":
            comandos.append({
                "area": "routes", "accion": "escribir",
                "declarado": f"{operacion.get('dst_address')} via {operacion.get('gateway')}",
                "descripcion": f"poner su ruta a {operacion.get('dst_address')} por {operacion.get('gateway')}",
                # `replace` y no `add`: repetirlo no es un error y deja el mismo estado (regla 6).
                # `proto static` la marca como del motor -- ni conectada ni del DHCP.
                "comando": (f"ip route replace {operacion.get('dst_address')} "
                            f"via {operacion.get('gateway')} proto static"),
            })

        elif op == "remove_route":
            comandos.append({
                "area": "routes", "accion": "escribir", "declarado": "(fuera)",
                "descripcion": f"quitar la ruta a {operacion.get('dst_address')} que no está declarada",
                "comando": (f"ip route del {operacion.get('dst_address')} "
                            f"via {operacion.get('gateway')} 2>/dev/null || true"),
            })

        elif op == "write_latido":
            cadencia = str(operacion.get("cadencia") or CADENCIA_LATIDO)
            partes = [f"echo {_b64(contenido)} | base64 -d > {ruta}"
                      for ruta, contenido in escrituras_latido(cadencia).items()]
            partes.append(f"chmod 0755 {RUTA_LATIDO}")
            partes.append("systemctl daemon-reload")
            comandos.append({
                "area": "latido", "accion": "escribir", "declarado": f"cada {cadencia}",
                "descripcion": "escribir el latido (guion, unidad y temporizador)",
                "comando": " && ".join(partes),
            })

        elif op == "start_latido":
            comandos.append({
                "area": "latido", "accion": "escribir", "declarado": "armado",
                # `start` del servicio ADEMÁS de habilitar el temporizador: así el equipo se
                # presenta en su red en esta misma pasada, sin esperar al primer tic.
                "descripcion": "armar el latido y dar el primer toque",
                "comando": (f"systemctl enable --now {UNIDAD_LATIDO} >/dev/null 2>&1; "
                            f"systemctl start {UNIDAD_LATIDO_SERVICIO}; sleep 1"),
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

        elif op in ("enable_service", "reload_service"):
            nombre = str(operacion.get("servicio") or "")
            opciones = SERVICIOS_LINUX_OPCIONES.get(nombre) or {}
            unidad = opciones.get("unidad") or nombre
            # La espera es del SERVICIO, no del motor: `caddy` vuelve a escuchar en un suspiro
            # y Tomcat tarda en desplegar un WAR de 53 MB. La relectura corre en el paso
            # siguiente, así que sin esta espera se preguntaría demasiado pronto.
            espera = int(opciones.get("espera") or 2)
            if op == "enable_service":
                comando = (f"systemctl daemon-reload; "
                           f"systemctl enable --now {unidad} >/dev/null 2>&1; sleep {espera}")
                descripcion = f"poner en marcha (y habilitar) el servicio '{nombre}'"
            else:
                # `restart` y no `reload`: la recarga de un Caddyfile admite formas distintas y
                # un restart es idempotente y no depende de que el proceso ya esté sano.
                comando = (f"systemctl daemon-reload; "
                           f"systemctl enable --now {unidad} >/dev/null 2>&1; "
                           f"systemctl restart {unidad}; sleep {espera}")
                descripcion = f"recargar el servicio '{nombre}' y dejarlo sirviendo"
            comandos.append({
                "area": "servicio", "accion": "escribir", "declarado": "activo",
                "descripcion": descripcion,
                "comando": comando,
            })

        elif op == "install_service":
            paquetes = " ".join(operacion.get("paquetes") or [])
            opciones = SERVICIOS_LINUX_OPCIONES.get(str(operacion.get("servicio") or "")) or {}
            # Lo que hay que hacer ANTES de instalar es del SERVICIO: NetXMS añade su
            # repositorio APT (no está en Debian) y refresca las listas DESPUÉS de añadirlo,
            # o el `install` no ve sus paquetes.
            pasos = list(opciones.get("preparar_paquetes") or ())
            pasos.append(f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {paquetes}")
            comandos.append({
                "area": "servicio", "accion": "escribir", "declarado": paquetes,
                "descripcion": f"instalar el servicio declarado y lo que la comprobación necesita: {paquetes}",
                # `apt-get update` DELANTE, no por gusto: la imagen base trae las listas
                # ENVEJECIDAS y apuntan a versiones que el espejo ya no tiene (404, MEDIDO),
                # así que un `install` a secas sale con rc=100 sin instalar nada. Refrescar
                # las listas primero es barato y sólo ocurre cuando falta algo.
                "comando": ("DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
                            + " && ".join(pasos)),
            })

        elif op == "write_service_config":
            nombre = str(operacion.get("servicio") or "")
            ficheros = _ficheros_servicio(nombre)
            # TODOS los ficheros que el servicio gobierna se escriben en UN solo paso: el
            # servicio no cumple con unos sí y otros no, y separarlos sólo daría un estado
            # intermedio que no cumple. Los directorios se crean con `-p` porque pueden no
            # existir: el de `caddy` en la imagen base, el de `tomcat10` si el paquete aún no
            # lo trajo, y `/usr/local/sbin` (que sí existe, pero no se supone).
            directorios = sorted({ruta.rsplit("/", 1)[0] for ruta in ficheros})
            escrituras = " && ".join(
                f"echo {_b64(contenido)} | base64 -d > {ruta}"
                for ruta, contenido in ficheros.items())
            comandos.append({
                "area": "servicio", "accion": "escribir", "declarado": nombre,
                "descripcion": f"escribir la configuración del servicio '{nombre}' y sus ficheros",
                "comando": f"mkdir -p {' '.join(directorios)} && {escrituras}",
            })

        elif op == "prepare_service":
            nombre = str(operacion.get("servicio") or "")
            opciones = SERVICIOS_LINUX_OPCIONES.get(nombre) or {}
            # Lo que el servicio necesita antes de arrancar (base, usuario, esquema). Va
            # DESPUÉS de escribir sus ficheros y ANTES de arrancar la unidad: `nxdbmgr init`
            # lee `/etc/netxmsd.conf`, y `netxms-server` no arranca sin esquema.
            pasos = list(opciones.get("preparar") or ())
            comandos.append({
                "area": "servicio", "accion": "escribir", "declarado": nombre,
                "descripcion": f"preparar lo que el servicio '{nombre}' necesita antes de arrancar",
                "comando": " && ".join(pasos),
            })

        elif op == "sembrar_monitorizacion":
            nombre = str(operacion.get("servicio") or "")
            opciones = SERVICIOS_LINUX_OPCIONES.get(nombre) or {}
            # El sembrado es del SERVICIO: quien sabe a quién vigilar y cómo preguntarle es
            # su preparador. UN paso, y deja su marca: mientras esté, el área lee `si` y no
            # vuelve a pedirlo (regla 6).
            comandos.append({
                "area": "monitorizacion", "accion": "escribir",
                "declarado": nombre,
                "descripcion": (f"decirle al servidor de vigilancia '{nombre}' a quién tiene "
                                "que vigilar (ronda su red por SNMP)"),
                "comando": " && ".join(opciones.get("sembrar") or ()),
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
        "install_service", "write_service_config", "prepare_service",
        "enable_service", "reload_service", "sembrar_monitorizacion",
        "add_route", "remove_route", "write_latido", "start_latido",
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
    # El cortafuegos: la tabla de filtrado ENTERA, y en su orden -- el orden es la
    # semántica, no un detalle de presentación.
    "firewall": (("/ip/firewall/filter", "sus reglas de filtrado, en orden"),),
    # La vigilancia por SNMP: si el agente está encendido y qué comunidades tiene. El
    # agente es de fábrica `no` (`/snmp` es un menú de AJUSTES: contesta un OBJETO, no una
    # lista) y su comunidad por defecto (`public`) tiene lectura sobre todo.
    "snmp": (
        ("/snmp", "si el agente SNMP está encendido"),
        ("/snmp/community", "las comunidades que pueden leerlo"),
    ),
}

# El vocabulario CERRADO del área `firewall`: qué campos de una regla de filtrado se
# declaran y con qué nombre. A la izquierda, lo que escribe el lab (snake_case, como el
# resto del vocabulario); a la derecha, el nombre del objeto en RouterOS. Lo que no esté
# aquí no se declara -- y por tanto no se puede pedir (el vocabulario es cerrado).
CAMPOS_FILTRO = (
    ("chain", "chain"),
    ("action", "action"),
    ("protocol", "protocol"),
    ("src_address", "src-address"),
    ("dst_address", "dst-address"),
    ("src_port", "src-port"),
    ("dst_port", "dst-port"),
    ("in_interface", "in-interface"),
    ("out_interface", "out-interface"),
    ("connection_state", "connection-state"),
    ("comment", "comment"),
    ("disabled", "disabled"),
)

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

# --- La vigilancia: el área `snmp` ------------------------------------------
# Un dispositivo de red que declara `snmp` ACEPTA que se le pregunte por SNMP (lectura):
# el motor enciende su agente y le pone una comunidad de LECTURA propia. El nombre de esa
# comunidad es una CONSTANTE DEL MOTOR (no un valor de lab): la misma que el servidor de
# vigilancia usa por defecto (`servicio: netxms` -> `DefaultCommunityString`), así que no
# hay dos sitios que se puedan desincronizar. El lab declara QUE un equipo se vigila; cómo
# se le pregunta es del motor.
#
# El agente es de fábrica `no`, y encenderlo es todo lo que hace falta para que un
# colector de la misma red lea el equipo. Aquí NO se recorta la comunidad de fábrica
# (`public`) ni se borra: el motor manda dentro de lo que declara (regla 17) y la
# excepción del área es la que limita quién llega -- un `snmp: {}` no abre el equipo a
# nadie que no llegue ya por la red de gestión.
COMUNIDAD_SNMP = "netlabs"
MARCA_SNMP = "netlabs-snmp"


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


def _si_no(valor):
    """Un booleano de RouterOS, en la forma en que se compara (`yes`/`no`).

    RouterOS contesta los booleanos como CADENAS (`"true"`/`"false"`), y el lab los
    declara como booleanos de YAML (`true`/`false`): los dos tienen que acabar en el
    mismo texto o una regla idéntica parecería distinta en cada pasada.
    """
    return "yes" if str(valor).lower() in ("true", "yes", "1") else "no"


def _filtro_normalizado(regla, de_declaracion=False):
    """Una regla de filtrado -> {campo_de_RouterOS: valor}, con TODO el vocabulario.

    Se rellena el vocabulario ENTERO (lo que no viene, como cadena vacía) para que
    comparar dos reglas sea comparar todas las claves: una regla declarada sin `dst_port`
    y una leída sin `dst-port` son la MISMA regla, y una que lo declara no lo es.
    """
    normalizado = {}
    for declarado_key, ros_key in CAMPOS_FILTRO:
        valor = regla.get(declarado_key if de_declaracion else ros_key, "")
        normalizado[ros_key] = _si_no(valor) if ros_key == "disabled" else (
            "" if valor is None else str(valor)
        )
    return normalizado


def _clave_de_filtro(regla):
    """La identidad de una regla de filtrado, para comparar dos listas en orden."""
    return tuple(str(regla.get(ros_key, "")) for _, ros_key in CAMPOS_FILTRO)


def _descripcion_de_filtro(regla):
    """Una regla, dicha en una línea -- para el diario y para el `porque` de un paso."""
    partes = [
        str(regla.get("chain") or "?"),
        str(regla.get("action") or "?"),
        str(regla.get("protocol") or ""),
    ]
    if regla.get("src-address") or regla.get("dst-address"):
        partes.append(f"{regla.get('src-address') or 'any'}->{regla.get('dst-address') or 'any'}")
    if regla.get("dst-port"):
        partes.append(f"puerto {regla.get('dst-port')}")
    if regla.get("comment"):
        partes.append(f"「{regla.get('comment')}」")
    return " ".join(p for p in partes if p)


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
    # El área `firewall`: la tabla de filtrado ENTERA y en su orden. Cada regla se
    # normaliza al vocabulario del área y se le cuelga su `.id` (es lo único con lo que se
    # puede QUITAR una regla). Se lee tal cual está: no se supone ninguna.
    if "/ip/firewall/filter" in leidos:
        entradas = _ros_lista((leidos.get("/ip/firewall/filter") or {}).get("json"))
        areas["firewall"] = {
            "reglas": [
                dict(_filtro_normalizado(entrada), id=str(entrada.get(".id") or ""))
                for entrada in entradas
            ],
        }

    # --- snmp: si el equipo acepta que se le pregunte ---
    # El agente (un OBJETO de ajustes) y sus comunidades (una lista). La comunidad de
    # LECTURA del motor y las demás se leen tal cual: el área no manda sobre las que no
    # son suyas (regla 17), y por eso la diferencia sólo AÑADE las que faltan.
    if "/snmp" in leidos:
        ajustes = (leidos.get("/snmp") or {}).get("json")
        comunidades = _ros_lista((leidos.get("/snmp/community") or {}).get("json"))
        areas["snmp"] = {
            "habilitado": _ros_si((ajustes or {}).get("enabled")) if isinstance(ajustes, dict) else False,
            "comunidades": [str(c.get("name")) for c in comunidades],
            "lectura": [
                str(c.get("name")) for c in comunidades if _ros_si(c.get("read-access"))
            ],
        }

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
    # ¿Ya se le cambió la credencial al equipo en esta convergencia? (ver `llamada`)
    credencial_cambiada = False

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
        # Tras `set_engine_credential` --que va al final del área `identity`-- el equipo ya
        # sólo acepta la credencial del MOTOR: cualquier escritura que caiga DESPUÉS (hoy,
        # las áreas que convergen tras `identity`: `ip_services`, `routes` y --la última--
        # `firewall`) tiene que ir con ella. Sin esta marca viajaban con la de fábrica y el
        # RouterOS contestaba 401 a media convergencia.
        if credencial_cambiada:
            item["credencial"] = "motor"
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
            # A partir de aquí, la del motor es la única que vale (ver `llamada`).
            credencial_cambiada = True

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

        elif op == "add_filter_rule":
            regla = dict(operacion.get("regla") or {})
            cuerpo = {
                ros_key: str(regla[ros_key])
                for _, ros_key in CAMPOS_FILTRO
                if ros_key in regla
            }
            llamada(area, "POST", "/ip/firewall/filter/add", cuerpo,
                    f"poner la regla de filtrado ({operacion.get('descripcion') or 'sin descripción'})")

        elif op == "remove_filter_rule":
            llamada(area, "POST", "/ip/firewall/filter/remove",
                    {"numbers": str(operacion.get("id") or "")},
                    f"quitar la regla de filtrado que ya no se declara "
                    f"({operacion.get('descripcion') or ''})")

        elif op == "enable_snmp":
            llamada(area, "POST", "/snmp/set", {"enabled": "yes"},
                    "encender el agente SNMP para que se le pueda preguntar por sus datos")

        elif op == "add_snmp_community":
            llamada(area, "POST", "/snmp/community/add",
                    {"name": str(operacion.get("nombre") or COMUNIDAD_SNMP),
                     "read-access": "yes", "write-access": "no", "comment": MARCA_SNMP},
                    f"poner la comunidad de LECTURA '{operacion.get('nombre') or COMUNIDAD_SNMP}' "
                    "con la que el servidor de vigilancia le pregunta")

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


# ---------------------------------------------------------------------------
# El GUION: el mismo cálculo, pero en UNA sola llamada
# ---------------------------------------------------------------------------
# RouterOS ya se usa así para el intercambio de la dirección de gestión (`/execute` con un
# guion, ver `_intercambio_de_la_gestion`). Esto generaliza la idea al resto de las
# escrituras: lo que `escrituras_routeros` DECIDE se SERIALIZA en las líneas de consola
# equivalentes y se manda en UNA sola llamada a `/execute`.
#
# La decisión NO cambia --el diff sigue decidiendo--, cambia el TRANSPORTE de la escritura:
# N llamadas REST -> 1. El mismo driver ejecuta el guion igual que ejecutaba las llamadas
# (una llamada por la misma vía de acceso), y la RELECTURA sigue siendo la que prueba la
# convergencia: `/execute` es ASÍNCRONA y no devuelve la salida del script, así que el juez
# es leer otra vez, nunca el silencio.
def _ros_valor(valor):
    """Un valor de consola RouterOS: desnudo si es simple, entrecomillado si no.

    Un valor simple (`10.43.0.11/24`, `netlabs-uplink`, `*3`, `yes`) va tal cual, que es
    como lo escribió el propio RouterOS al inventar su sintaxis. Lo que trae espacios o
    caracteres que la consola partiría (una clave SSH, una contraseña) va entre comillas,
    con la barra invertida y las comillas escapadas y el `$` neutralizado --dentro de las
    comillas dobles RouterOS lo tomaría por una variable--.
    """
    texto = "" if valor is None else str(valor)
    if texto and not any(c in texto for c in ' \t"\\$;') and texto.strip() == texto:
        return texto
    escapado = (texto.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$"))
    return '"' + escapado + '"'


def _linea_de_llamada(llamada, tapar=False):
    """(una llamada REST de `escrituras_routeros`) -> la línea de consola que hace lo mismo.

    Traducción MECÁNICA, sin tabla: `/ip/dhcp-server/network/set` es la consola
    `/ip dhcp-server network set`, y del cuerpo, `numbers` va POSICIONAL (es a QUIÉN) y el
    resto `clave=valor`. Un `/execute` (el guion del intercambio) YA es consola: se copia
    entero. `tapar` sustituye por `···` el valor de los campos que son credenciales, para
    que el cuerpo del diario pueda llevar el guion sin llevar la contraseña.
    """
    ruta = str(llamada.get("ruta") or "")
    try:
        cuerpo = dict(llamada.get("cuerpo") or {})
    except (TypeError, ValueError):
        cuerpo = {}
    if ruta == "/execute":
        return str(cuerpo.get("script") or "")
    trozos = [t for t in ruta.strip("/").split("/") if t]
    if len(trozos) < 2:
        return ""
    verbo = trozos[-1]
    tabla = " ".join(trozos[:-1])
    argumentos = []
    if verbo in ("set", "remove"):
        numeros = cuerpo.pop("numbers", None)
        if numeros not in (None, ""):
            argumentos.append(_ros_valor(numeros))
    for clave, valor in cuerpo.items():
        if tapar and str(clave).lower() in CAMPOS_SECRETOS:
            valor = "···"
        argumentos.append(f"{clave}={_ros_valor(valor)}")
    return ("/" + tabla + " " + verbo + (" " + " ".join(argumentos) if argumentos else "")).strip()


def _llamada_lleva_secreto(llamada):
    """¿el cuerpo de esta llamada lleva algún valor que es una credencial?"""
    try:
        cuerpo = dict(llamada.get("cuerpo") or {})
    except (TypeError, ValueError):
        return False
    return any(str(clave).lower() in CAMPOS_SECRETOS for clave in cuerpo)


def _guion_de(run):
    """(un tramo de escrituras sin credencial) -> la llamada que las manda de una vez."""
    lineas = [_linea_de_llamada(l) for l in run]
    lineas_tapadas = [_linea_de_llamada(l, tapar=True) for l in run]
    guion = {
        "area": "varias",
        "accion": "escribir",
        "metodo": "POST",
        "ruta": "/execute",
        "cuerpo": {"script": "\n".join(lineas)},
        # El cuerpo del diario es el MISMO guion con las credenciales tapadas: hoy el guion
        # no lleva ninguna (las llamadas con credencial no se funden), pero si alguna vez
        # una se colara, `sin_secretos` tapa por NOMBRE de campo y un `script` es UN campo:
        # se tapa antes, aquí, para que la contraseña no pueda acabar escrita en el diario.
        "cuerpo_diario": {"script": "\n".join(lineas_tapadas)},
        "descripcion": (
            f"el interior de este RouterOS, en UNA llamada: "
            f"{len(run)} escritura(s) dentro de un mismo guion"
        ),
    }
    if any(bool(l.get("tolerar_sin_respuesta")) for l in run):
        guion["tolerar_sin_respuesta"] = True
    # La credencial con la que hay que mandar el tramo. Todos sus miembros son contiguos y
    # sin credencial, así que o todos van con la del motor o ninguno: basta con el primero.
    if run[0].get("credencial"):
        guion["credencial"] = run[0]["credencial"]
    return guion


def guion_routeros(llamadas, activado=False):
    """(las llamadas REST decididas) -> las mismas, con cada TRAMO sin credencial fundido.

    Se pide desde `vars/engine.yml` (`engine_routeros_guion`). Es un cambio de TRANSPORTE,
    no de decisión: la misma capa pura que decidía las N llamadas sigue decidiéndolas, y lo
    único que cambia es que un TRAMO de escrituras seguidas sin credencial se manda dentro
    de un solo `/execute`.

    Se funden TRAMOS CONTIGUOS, no todo de golpe, por una razón MEDIDA: la escritura de la
    CREDENCIAL es lo último que se toca, y en el diseño viejo era una llamada SÍNCRONA que
    TERMINABA antes de la relectura. Metida dentro de un guion ASÍNCRONO, la relectura (que
    ya usa la credencial nueva) se adelanta y recibe un 401 -- medido: 'set_identity' salía
    pendiente porque su relectura llegó antes de que el guion pusiera la credencial. Por eso
    las llamadas que llevan un campo de credencial NO se funden: se quedan como llamadas
    sueltas, en su sitio, y el orden entero se conserva.

    Un tramo de UNA sola escritura no se envuelve (un guion de una línea es más opaco sin
    ahorrar nada); así, si no hay nada que fundir, se devuelven las llamadas TAL CUAL. Y si
    la lista trae algo SIN TRADUCIR, también tal cual: quien para y lo dice es el driver
    (`ros_sin_traducir`), no este filtro.
    """
    if not _afirmativo(activado):
        return llamadas
    escrituras = [l for l in (llamadas or []) if str(l.get("accion")) == "escribir"]
    otras = [l for l in (llamadas or []) if str(l.get("accion")) != "escribir"]
    if not escrituras or otras:
        return llamadas
    resultante = []
    tramo = []

    def cerrar():
        if len(tramo) >= 2:
            resultante.append(_guion_de(tramo))
        else:
            resultante.extend(tramo)
        del tramo[:]

    for llamada in escrituras:
        if _llamada_lleva_secreto(llamada):
            cerrar()
            resultante.append(llamada)
        else:
            tramo.append(llamada)
    cerrar()
    if len(resultante) == len(escrituras):
        return llamadas
    return resultante


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
            "interior_lecturas_linux": lecturas_linux,
            "interior_escrituras_linux": escrituras_linux,
            "interior_lecturas_routeros": lecturas_routeros,
            "interior_leido_routeros": leido_routeros,
            "interior_escrituras_routeros": escrituras_routeros,
            "interior_guion_routeros": guion_routeros,
            "interior_sin_secretos": sin_secretos,
            "interior_pendiente_de_driver": pendiente_de_driver,
            "interior_leido": leido_de_lecturas,
            "interior_operaciones": operaciones_de_pasos,
            "interior_sin_driver": pasos_sin_driver,
            "interior_bastion": bastion,
            "interior_salida": salida_derivada,
            "interior_puerto_rest": puerto_rest_tunnel,
            "interior_permitlisten": permitlisten_de,
            "interior_interfaces_rest": interfaces_rest_del_bastion,
            "interior_guion_tunnel": guion_tunnel,
            "interior_linea_consola": linea_consola,
            "interior_marca_tunnel": marca_tunnel,
            "interior_pasos": pasos_de_convergencia,
            "interior_pruebas": pruebas_de,
            "interior_captura": captura_de,
            "interior_impairment": impairment_de,
            "interior_a_verificar": guests_a_verificar,
            "interior_informe_ok": informe_ok,
            "interior_sin_comprobar": sin_comprobar,
        }
