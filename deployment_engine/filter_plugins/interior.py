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
# VER:         docs/decisiones/0005-el-driver-del-interior.md; docs/camino-del-puesto-de-control.md;
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
#   * `direcciones` va ANTES de `cliente_dhcp` en RouterOS, y esto está MEDIDO, no
#     supuesto: al deshabilitar el cliente DHCP de fábrica, RouterOS se lleva la
#     dirección que ese cliente instaló, y con ella el REST --la escritura se queda
#     sin respuesta y el motor pierde el camino a mitad de faena-- (comprobado en un
#     CHR 7.25.1 sobre `ether1`: la llamada murió a los 34 s, el equipo se quedó sin
#     dirección y hubo que rehacer el lab). Poniendo primero la dirección declarada,
#     el equipo sigue alcanzable pase lo que pase después.
#   * `identidad` va la ÚLTIMA en RouterOS en la primera convergencia (ver
#     `identidad_al_final`), para no perder el camino de vuelta a mitad de faena:
#     primero se añade y se verifica lo nuevo, y sólo entonces se cambia la
#     identidad del equipo. v3 lo llamaba intercambio atómico.
#   * `cortafuegos` va al final: no se cierra una puerta antes de haber pasado por
#     ella.
AREAS = {
    # `direcciones` (Linux) no es un área con driver propio: es la forma LISTA de
    # `direccion` -- las patas extra del invitado, una por bridge del lab. Está aquí
    # porque el vocabulario es cerrado y hay que nombrarla, y `areas_de` la funde en
    # `direccion` para que la convergencia tenga un solo camino.
    "linux": ("camino", "direccion", "direcciones", "reenvio", "dhcp_servidor"),
    "routeros": ("identidad", "direcciones", "servicios", "cliente_dhcp", "rutas", "dhcp"),
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

# El puerto por el que se deja ver un RouterOS: su REST vive en el servicio `www` de
# fábrica. Es el MISMO que sondea la barrera de un escalón (`espera_de_servicio`), así
# que es una constante y no un número repetido en dos sitios que se puedan separar.
PUERTO_REST_ROUTEROS = 80


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
        # La de gestión sale del campo `direccion` del invitado (la de la pata por la que
        # el plan levanta el túnel), y va primero. Si el lab declara además `direcciones`
        # --una lista de `{interfaz, direccion}`--, son las OTRAS patas: un puesto de
        # control necesita una por cada bridge del lab, porque si no, un invitado que
        # cuelgue de ese bridge es inalcanzable para el motor (medido: el CHR del segundo
        # escalón no contesta y su convergencia no se puede ni empezar).
        propias = [dict(p) for p in (declaradas.get("direcciones") or [])]
        declaradas.pop("direcciones", None)
        propia = str(invitado.get("direccion") or "")
        if propia and propia != "dhcp":
            propias = [{"interfaz": "eth0", "direccion": propia}] + propias
        declaradas["direccion"] = propias or invitado.get("direccion")
    if tipo == "routeros":
        # En un RouterOS, la dirección de su pata de GESTIÓN no la pone nadie de fuera: la
        # escribe el motor por su REST. Va DENTRO del área `direcciones` (es la dirección
        # de una interfaz), en la primera pata -- que es donde vive el cliente DHCP de
        # fábrica que esta misma convergencia apaga (medido: `ether1`).
        #
        # Se DERIVA del `direccion:` del invitado, y por eso no se escribe dos veces ni se
        # puede olvidar: apagar el cliente de fábrica sin poner la dirección estática
        # dejaría al router sin dirección, o sea sin camino de vuelta para el motor que lo
        # configura. Es el mismo papel que la línea de arriba, con otro mecanismo: en un
        # Linux la dirección la pone el propio invitado; en un RouterOS, el motor.
        propia = str(invitado.get("direccion") or "")
        if propia and propia != "dhcp":
            declaradas["direcciones"] = list(declaradas.get("direcciones") or []) + [
                {"interfaz": INTERFAZ_GESTION_ROUTEROS, "direccion": propia}
            ]
    return {area: declaradas.get(area) for area in AREAS[tipo] if area in declaradas}


def areas_a_leer(invitado):
    """Las áreas que el driver tiene que LEER dentro del equipo (las declaradas)."""
    return list(areas_de(invitado).keys())


def es_direccion_dinamica(valor):
    """¿Esta dirección declarada es dinámica (`dhcp`)? (las otras formas son una
    estática `<ip>/<prefijo>` o ausente)."""
    return str(valor or "").strip().lower() == "dhcp"


def areas_que_piden_visita(invitado):
    """Las áreas declaradas que exigen ENTRAR en el invitado (leer o escribir dentro).

    Una dirección DINÁMICA no pide visita: su valor es un hecho que se lee del HOST
    (`GET /nodes/<nodo>/lxc/<vmid>/interfaces`, §6.3/§11) y, además, no se podría
    escribir desde dentro sin saber primero a qué dirección conectar — un círculo.
    Un invitado cuya ÚNICA área sea ésa (un `config: linux: {}` con `direccion: dhcp`,
    el caso de los puestos dinámicos) no se converge: no hay nada que hacer dentro y
    el motor no entra a ciegas (regla 16). `configurar_<tipo>.yml` sólo se despacha
    para un invitado con áreas que piden visita.
    """
    return {
        area for area, valor in areas_de(invitado).items()
        if not (area == "direccion" and es_direccion_dinamica(valor))
    }


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


def puerto_camino(vmid, parametros):
    """El puerto del nodo de control donde el puesto deja su sshd. DERIVADO del vmid."""
    return int(parametros.get("camino_puerto_base") or 20000) + int(vmid)


def puerto_rest_camino(vmid, parametros):
    """El puerto del nodo de control por el que se llega al REST de un invitado.

    El puesto de control reenvía, por el MISMO túnel del camino, el puerto 80 de cada
    equipo con el que el motor habla por REST (los que declaran `config.routeros`). Así
    el `uri` se ejecuta en la máquina del motor --una sola puerta, un solo sitio-- y el
    puesto sólo hace de camino, en vez de delegarle la llamada. Se DERIVA del vmid, como
    el puerto del camino: nada que guardar (regla 11). La banda (21000+) no pisa la del
    camino (20000+) para vmids de tres cifras, que es lo que usa un clúster normal.
    """
    return int(parametros.get("camino_rest_puerto_base") or 21000) + int(vmid)


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
    for invitado in (declaracion or {}).get("invitados") or []:
        if invitado.get("rol") == rol:
            return invitado
    return {}


def patas_rest_del_puesto_control(declaracion, identidad, parametros):
    """Los equipos por los que el puesto de control tiene que abrir camino de REST.

    Se pregunta a la DECLARACIÓN quién trae `config.routeros` --son los únicos con los
    que este motor habla por REST: el vocabulario es cerrado-- y al mapa de identidad
    por su vmid, que es de donde sale el puerto. Un equipo sin dirección declarada no
    entra: no hay a dónde reenviar, y un `dhcp` con interior de RouterOS ya lo rechaza
    la validación de la declaración. Sale ordenada por rol para que el guion del camino
    sea el mismo en cada pasada (si no, un `apply` lo reescribiría por nada).
    """
    patas = []
    for invitado in (identidad or {}).get("invitados") or []:
        declarado = _declarado_por_rol(declaracion, invitado.get("rol"))
        if "routeros" not in (declarado.get("config") or {}):
            continue
        # La dirección declarada, sin el prefijo: lo que viaja en `-R` es una dirección, no
        # una red. `dhcp` NO es una dirección --no se sabe a dónde reenviar--, así que un
        # equipo así no entra (la validación de la declaración ya lo rechaza cuando declara
        # interior; aquí se dice lo mismo por si llegara por otra vía).
        direccion = _sin_prefijo(declarado.get("direccion"))
        if not direccion or direccion == "dhcp":
            continue
        patas.append(
            {
                "rol": invitado.get("rol"),
                "direccion": direccion,
                "puerto": puerto_rest_camino(invitado.get("vmid"), parametros),
                "puerto_servicio": PUERTO_REST_ROUTEROS,
            }
        )
    return sorted(patas, key=lambda pata: str(pata["rol"]))


def guion_camino(clave_privada, host, puerto, usuario, puerto_local, patas_rest=None):
    """El texto que se manda por la consola: UNA sola vez, y queda puesto.

    Qué hace, y por qué esto y no otra cosa:

      1. deja la clave del camino dentro del invitado, con sus permisos;
      2. escribe un GUION que abre la salida hacia casa con `ssh -R`: el puesto de
         control se conecta al sshd del nodo de control y deja reenviado un puerto
         local SUYO hacia su propio sshd (por ahí se le lee la consola y de ahí cuelga
         el lab) y, por cada equipo con el que el motor habla por REST, OTRO puerto
         local hacia el puerto 80 de ese equipo: así el `uri` del motor se ejecuta en
         la máquina del motor, y el puesto sólo hace de camino;
      3. lo pone como UNIDAD de systemd con `Restart=always` y la habilita.

    El punto 3 es lo que hace que la consola se use UNA vez por vida del invitado y
    no en cada `apply`: si el invitado reinicia, el camino se levanta solo. Y es
    idempotente: volver a mandarlo reescribe lo mismo y reinicia el servicio.

    Va en base64 porque la consola no es un canal de datos fiable: una línea, sin
    heredocs ni comillas que escapar, sin nada que el eco pueda romper.
    """
    # `\` + salto de línea: lo que la shell lee como «la línea sigue». Se escribe con
    # chr() para que ningún nivel de escapes lo pueda romper por el camino.
    seguimos = chr(92) + "\n"
    reenvios = "".join(
        f"  -R {pata['puerto']}:{pata['direccion']}:{pata['puerto_servicio']} {seguimos}"
        for pata in (patas_rest or [])
    )
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
  -N -R {puerto_local}:localhost:22 \\
{reenvios}  -p {puerto} {usuario}@{host}
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
    return _afirmativo((estado or {}).get("camino", {}).get("responde"))


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


def pasos_del_camino(invitado, declaracion, estado, parametros, identidad=None):
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
    # Las patas de REST: una por equipo con el que el motor hablará por REST. Van dentro
    # del paso porque el puerto de cada una sale de su vmid, y el vmid sólo se conoce en
    # el plan (que los asigna todos de una vez), no al ejecutar el paso.
    patas_rest = patas_rest_del_puesto_control(declaracion, identidad, parametros)
    # Los puertos que el túnel dejará autorizados y reenviados: el suyo y el REST de cada
    # equipo. Es la MISMA lista que escribe `tasks/camino.yml` en `authorized_keys`.
    puertos_autorizados = permitlisten_de(
        [puerto_local] + [pata["puerto"] for pata in patas_rest]
    )
    if patas_rest:
        detalle_rest = "y, por el MISMO túnel, reenvía el puerto 80 de cada equipo de REST: " + (
            ", ".join(f"{pata['rol']}->127.0.0.1:{pata['puerto']}" for pata in patas_rest)
        )
    else:
        detalle_rest = "este lab no configura ningún RouterOS: por el túnel sólo va la consola"
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
                    "rest": patas_rest,
                },
                "detalle": [
                    "la clave pública del motor se deja en el invitado al CREARLO (ssh-public-keys):",
                    "  por ahí entra Ansible, y sin eso no habría forma de llegar a configurarlo",
                    f"en casa se añade UNA línea a authorized_keys con restrict,port-forwarding,"
                    f"{puertos_autorizados} (la clave del camino no da shell, sólo los reenvíos de este túnel)",
                    f"por la consola del invitado se manda UNA línea (base64) que levanta "
                    f"ssh -R {puerto_local}:127.0.0.1:22 hacia {host_salida}:{puerto_salida}",
                    detalle_rest,
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

    Son TRES cosas distintas y no se confunden (medido: un CHR nace con el usuario
    `admin` sin contraseña y sin ninguna clave): que el usuario exista, que la credencial
    del motor esté puesta en él, y que la clave pública esté importada. Si no se
    distinguieran, el motor daría por bueno un equipo con la puerta abierta.
    """
    operaciones = []
    esperado = str(declarado or "")
    actual = str((leido or {}).get("nombre") or "")
    if esperado and actual != esperado:
        operaciones.append({"op": "poner_identidad", "nombre": esperado})
    # La CLAVE primero y la CREDENCIAL al final, y esto está medido: cambiar la contraseña
    # invalida al instante la de fábrica, y la escritura siguiente --importar la clave-- se
    # queda sin credencial con la que hablar (401 sobre `/user/ssh-keys/add`, medido en un
    # CHR 7.25.1: la contraseña se cambió, la clave no llegó, y el paso se paró). Con la
    # clave ya importada, el motor entra con ella y la contraseña es lo ÚLTIMO que se toca.
    if not (leido or {}).get("clave_motor"):
        operaciones.append({"op": "importar_clave_motor"})
    if not (leido or {}).get("usuario_motor"):
        operaciones.append({"op": "crear_usuario_motor"})
    elif not (leido or {}).get("credencial_motor"):
        # `tolerar_sin_respuesta`: cambiar la contraseña del usuario con el que se está
        # hablando MATA la sesión, y RouterOS contesta 400 `Bad Request Session closed`
        # (medido en el CHR 7.25.1) aunque el cambio haya surtido efecto. Es un corte por
        # diseño, como apagar el cliente DHCP: se tolera, y la convergencia la dice la
        # REELECTURA (que ya entra con la credencial nueva).
        operaciones.append({"op": "poner_credencial_motor", "tolerar_sin_respuesta": True})
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
        # El prefijo no entra en la comparación: RouterOS guarda la dirección pelada
        # (`10.40.1.11`), y compararla con `10.40.1.11/24` haría que la reserva no
        # cuadrara NUNCA y se reescribiera en cada pasada.
        deseadas = {
            str(r["mac"]).upper(): str(r["direccion"]).split("/")[0] for r in reservas
        }
        actuales = {
            str(r.get("mac")).upper(): str(r.get("direccion"))
            for r in ((leido or {}).get("reservas") or [])
        }
        for mac, direccion in sorted(deseadas.items()):
            if actuales.get(mac) != direccion:
                operaciones.append(
                    {
                        "op": "poner_reserva",
                        "mac": mac,
                        # Una reserva es una DIRECCIÓN, no una red: RouterOS guarda
                        # `10.40.1.11` y no `10.40.1.11/24`, y comparar con el prefijo
                        # haría que la reserva no cuadrara nunca (reescritura eterna).
                        "direccion": direccion.split("/")[0],
                        # Y va atada al servidor de ESA interfaz: un router con dos LANs
                        # no puede reservar en la primera lo que vive en la segunda.
                        "interfaz": interfaz,
                    }
                )
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

    El área admite dos formas, y la segunda existe por una razón medida: un puesto de
    control necesita UNA dirección por cada bridge del lab para poder llegar a los
    invitados que cuelgan de él. Cuando el lab declara `direcciones` (lista de
    `{interfaz, direccion}`), se comparan una a una; la de gestión sigue viniendo del
    campo `direccion` del invitado, que es lo que el plan usa para el túnel.
    """
    if not declarado or str(declarado) == "dhcp":
        return []
    actuales = (leido or {}).get("direcciones") or []
    if isinstance(declarado, list):
        # Si la lectura no trae la lista de patas (un motor viejo, o una lectura parcial),
        # se usa la de gestión: es la única que se conocía antes de esta forma, y sin este
        # respaldo el área se creería sin hacer y volvería a escribir en cada pasada.
        if not actuales and (leido or {}).get("direccion"):
            actuales = [{"interfaz": "eth0", "direccion": (leido or {}).get("direccion")}]
        tengo = {(str(p.get("interfaz")), str(p.get("direccion"))) for p in actuales}
        return [
            {
                "op": "poner_direccion",
                "interfaz": str(p.get("interfaz")),
                "direccion": str(p.get("direccion")),
            }
            for p in declarado
            if (str(p.get("interfaz")), str(p.get("direccion"))) not in tengo
        ]
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
    if not areas_que_piden_visita(invitado):
        # Nada que hacer DENTRO: la única área es una dirección dinámica, que se lee del
        # HOST (§6.3). Entrar sería a ciegas (no se sabe a qué dirección conectar).
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
    """El paso que comprueba que un invitado CONTESTA --la barrera que va DELANTE de
    converger su interior-- y, con eso, que su escalón sirve antes de pasar al
    siguiente (regla 18: nunca se arranca un escalón antes de que el anterior esté
    convergido y sirviendo).

    Va antes del interior y no al final del escalón porque un invitado recién arrancado
    no contesta al instante: un CHR tarda en bootear y en pedir su dirección por DHCP,
    y convergerlo nada más arrancarlo aborta la pasada. La sonda le da ese tiempo.

    No es un `wait_for` sobre el invitado: es una petición a la dirección que la
    declaración promete, en el puerto por el que ese tipo se deja ver (el REST de
    RouterOS, el sshd de un Linux). No necesita identidad: la sonda va a la
    dirección declarada, que es lo que la declaración promete.
    """
    tipo = tipo_de(invitado)
    if tipo is None:
        return None
    # Sólo se sondea lo que la declaración PROMETE con una dirección fija: un equipo que
    # toma su dirección por DHCP (`direccion: dhcp`) no tiene dirección que preguntar hasta
    # que su router se la da, así que no hay sonda que valga -- y no se inventa una. El
    # escalón se arranca sin barrera y el lab lo dice en su prosa.
    if _a_entero(_sin_prefijo(invitado.get("direccion"))) is None:
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
            f"el interior de '{invitado['rol']}' no se toca hasta que contesta: un "
            f"invitado del escalón {invitado.get('escalon')} recién arrancado tarda en "
            f"dar señales en el puerto {puerto}"
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
        # TODAS las patas con dirección (no sólo eth0): el puesto de control declara una
        # dirección por cada bridge del lab, porque un CHR del segundo escalón cuelga de un
        # bridge al que el puesto sólo llega si tiene pata con dirección ahí (medido: sin
        # ella, el router no contesta y su convergencia es imposible).
        "comando": "ip -4 -o addr show scope global",
        "descripcion": "las direcciones de sus patas (gestión y bridges del lab)",
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
            # `ip -4 -o addr show scope global` -> "3: eth0    inet 10.40.0.10/24 ..."
            # Una línea por pata con dirección: la de gestión (eth0, la que el plan usa
            # para el túnel) y las que el lab declare para los bridges del lab.
            patas = []
            for linea in lineas:
                trozos = linea.split()
                if len(trozos) > 3 and trozos[2] == "inet":
                    patas.append({"interfaz": trozos[1], "direccion": trozos[3]})
            de_gestion = [p for p in patas if p["interfaz"] == "eth0"]
            leido["direccion"] = {
                "direccion": (de_gestion or patas or [{"direccion": ""}])[0]["direccion"],
                "direcciones": patas,
            }

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
# REST, que es la misma puerta (`tasks/ros_api.yml`). Igual que en Linux, las lecturas
# son DATOS y no lógica: el driver no decide qué preguntar, lo lee de aquí.
#
# Cada ruta se eligió midiendo un CHR real (7.25.1): `/system/identity` contesta un
# OBJETO (`{"name":"CHR"}`) y una tabla contesta una LISTA. El analizador sabe leer las
# dos formas porque las dos existen.
LECTURAS_ROUTEROS = {
    "identidad": (
        ("/system/identity", "el nombre del equipo"),
        ("/user", "los usuarios que tiene (el del motor, si está)"),
        ("/user/ssh-keys", "las claves autorizadas (la del motor, si está importada)"),
    ),
    "servicios": (("/ip/service", "qué servicios de gestión tiene abiertos"),),
    "cliente_dhcp": (("/ip/dhcp-client", "el cliente de fábrica, si sigue vivo"),),
    "direcciones": (("/ip/address", "sus direcciones, estáticas y dinámicas"),),
    "rutas": (("/ip/route", "sus rutas: estáticas, conectadas y las del DHCP"),),
    "dhcp": (
        ("/ip/dhcp-server", "los servidores DHCP que tiene"),
        ("/ip/pool", "los rangos de direcciones que reparte"),
        ("/ip/dhcp-server/network", "las redes que anuncia"),
        ("/ip/dhcp-server/lease", "sus concesiones y sus reservas"),
    ),
}

# El nombre del rango de direcciones que el motor crea en el router. Se deriva del rango
# declarado (`10.40.1.100-10.40.1.200` -> `netlabs-10.40.1.100`): el lab declara el
# rango, no el nombre de un objeto intermedio del equipo, y así no hay que guardar nada.
PREFIJO_POOL = "netlabs-"

# La pata de gestión de un RouterOS: la primera, y donde vive el cliente DHCP de fábrica
# (medido en un CHR: `ether1`, con su concesión dinámica). No es un valor de ningún lab:
# es cómo numera RouterOS sus interfaces ethernet (empieza en 1, y `net0` de Proxmox es
# `ether1` del router). El motor la usa para poner la dirección de gestión DERIVADA del
# `direccion:` del invitado, que es lo que impide dejarlo sin camino de vuelta.
INTERFAZ_GESTION_ROUTEROS = "ether1"

# Los campos que son credenciales: si alguno viaja en el cuerpo de una llamada, su valor
# se tapa en el diario. Por NOMBRE y no por confianza en el llamante: la contraseña del
# motor viaja de verdad en el cuerpo de `poner_credencial_motor`, y un descuido no puede
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


def lecturas_routeros(invitado):
    """Las lecturas que hay que hacer por REST en un RouterOS, por área declarada.

    Sólo se pregunta por lo que el lab DECLARA: fuera de las áreas declaradas el motor
    no opina (regla 17), así que tampoco pregunta.
    """
    lecturas = []
    for area in areas_a_leer(invitado):
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
    interfaz y la dirección; el destino y la pasarela), y en un router con dos patas la
    dirección sola no basta. Se unen en una CADENA y no en una tupla: esto viaja por
    hechos de Ansible, y una tupla como clave de un mapa se rompe en cuanto algo lo
    serializa a JSON.
    """
    return "|".join(str(parte) for parte in partes)


def leido_routeros(leidos, invitado=None, usuario_motor="", clave_publica="", credencial="motor"):
    """(lo que contestó el REST) -> el mapa `leído` que comen las diferencias.

    `leidos` es lo que acumula la puerta: `{ruta: {area, status, json, error}}`. Función
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

    # --- identidad: el nombre, el usuario del motor y su clave ---
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
        areas["identidad"] = {
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
        areas["servicios"] = {
            "deshabilitados": [str(s.get("name")) for s in servicios if _ros_si(s.get("disabled"))],
            "habilitados": [str(s.get("name")) for s in servicios if not _ros_si(s.get("disabled"))],
            "ids": _ros_ids(servicios, lambda s: s.get("name")),
        }

    # --- cliente_dhcp: el de fábrica ---
    cliente = []
    if "/ip/dhcp-client" in leidos:
        cliente = _ros_lista((leidos.get("/ip/dhcp-client") or {}).get("json"))
        areas["cliente_dhcp"] = {
            "habilitado": any(not _ros_si(c.get("disabled")) for c in cliente),
            "interfaces": [str(c.get("interface")) for c in cliente],
            "ids": _ros_ids(cliente, lambda c: c.get("interface")),
        }

    # --- direcciones: estáticas y dinámicas, separadas (la dinámica es RESIDUO) ---
    direcciones = []
    if "/ip/address" in leidos:
        direcciones = _ros_lista((leidos.get("/ip/address") or {}).get("json"))
        estaticas = [
            {"interfaz": str(d.get("interface")), "direccion": str(d.get("address"))}
            for d in direcciones
            if not _ros_si(d.get("dynamic"))
        ]
        dinamicas = [
            {"interfaz": str(d.get("interface")), "direccion": str(d.get("address"))}
            for d in direcciones
            if _ros_si(d.get("dynamic"))
        ]
        areas["direcciones"] = {
            "estaticas": estaticas,
            "dinamicas": dinamicas,
            # El `.id` es lo único con lo que se puede QUITAR una entrada, y se guarda
            # por interfaz Y dirección: en un router con dos patas, la dirección sola no
            # la identifica.
            "ids": {
                _ros_clave(d.get("interface"), d.get("address")): str(d.get(".id") or "")
                for d in direcciones
                if not _ros_si(d.get("dynamic"))
            },
        }

    # --- rutas: las que pone el motor son estáticas; las demás son del sistema ---
    if "/ip/route" in leidos:
        rutas = _ros_lista((leidos.get("/ip/route") or {}).get("json"))
        estaticas = [
            {"destino": str(r.get("dst-address")), "pasarela": str(r.get("gateway"))}
            for r in rutas
            if not _ros_si(r.get("dynamic"))
        ]
        areas["rutas"] = {
            "estaticas": estaticas,
            "ids": {
                _ros_clave(r.get("dst-address"), r.get("gateway")): str(r.get(".id") or "")
                for r in rutas
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
                        "prefijo": str(candidata.get("address")),
                        "pasarela": str(candidata.get("gateway")),
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
                    "interfaz": interfaz,
                    "rango": rango,
                    "nombre": str(servidor.get("name") or ""),
                    "id": str(servidor.get(".id") or ""),
                    "red": red,
                }
            )
        areas["dhcp"] = {
            "servidores": servidores,
            "pools": {
                str(p.get("name")): {"id": str(p.get(".id") or ""), "rango": str(p.get("ranges") or "")}
                for p in pools
            },
            # Las concesiones DINÁMICAS no son reservas: son equipos que pidieron
            # dirección, y el motor no las declara ni las quita (no son suyas).
            "reservas": [
                {
                    "mac": str(c.get("mac-address")),
                    "direccion": str(c.get("address")),
                    "servidor": str(c.get("server") or ""),
                    "id": str(c.get(".id") or ""),
                }
                for c in concesiones
                if not _ros_si(c.get("dynamic")) and str(c.get("mac-address") or "")
            ],
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
    cliente_vivo = bool((areas.get("cliente_dhcp") or {}).get("habilitado"))
    dinamicas = (areas.get("direcciones") or {}).get("dinamicas") or []
    declaradas = {
        f"{d['interfaz']}:{d['direccion']}"
        for d in (areas.get("direcciones") or {}).get("estaticas") or []
    }
    propia = str((invitado or {}).get("direccion") or "")
    if propia and propia != "dhcp":
        # La dirección con la que el invitado nace (`direccion:` del lab) también es
        # declarada: es la que el cliente de fábrica pidió por DHCP y la que se queda.
        declaradas.add(f"ether1:{propia}")
    residuo_direccion = (not cliente_vivo) and any(
        f"{d['interfaz']}:{d['direccion']}" in declaradas for d in dinamicas
    )
    rutas_crudas = _ros_lista((leidos.get("/ip/route") or {}).get("json"))
    residuo_ruta = (not cliente_vivo) and any(
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
        "invitado": (invitado or {}).get("rol"),
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


def _intercambio_de_la_gestion(operaciones, declaracion, invitado, leido):
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
    respuesta en el CHR del segundo escalón, con el MISMO cuerpo que en el primero contesta
    200). El guion va al final de todo y justo antes de la credencial --que es el
    intercambio que cierra--, porque es la escritura que puede dejar al equipo sin camino un
    instante: lo que se pueda dar hecho antes, hecho está. Y va declarando que puede no
    contestar (`tolerar_sin_respuesta`): quien prueba el efecto es la RELECTURA.

    Sin cliente que quitar y sin residuo dinámico no hay nada que ordenar, y se devuelven
    las operaciones tal cual: es el caso normal de una pasada ya convergida.
    """
    operaciones = [dict(operacion) for operacion in (operaciones or [])]
    areas = (leido or {}).get("areas") or {}
    direcciones_leidas = areas.get("direcciones") or {}
    dinamicas = {
        _sin_prefijo((entrada or {}).get("direccion"))
        for entrada in direcciones_leidas.get("dinamicas") or []
    }
    propia = _sin_prefijo((invitado or {}).get("direccion"))
    cliente_vivo = bool((areas.get("cliente_dhcp") or {}).get("habilitado"))

    apagones = [
        operacion for operacion in operaciones
        if operacion.get("op") == "deshabilitar_cliente_dhcp"
    ]
    choque = None
    for operacion in operaciones:
        if operacion.get("op") != "poner_direccion":
            continue
        if str(operacion.get("interfaz")) != INTERFAZ_GESTION_ROUTEROS:
            continue
        if _sin_prefijo(operacion.get("direccion")) in dinamicas:
            choque = operacion
    # El residuo: la entrada dinámica que dejó un cliente YA retirado. Sin cliente que
    # quitar, lo que hay que soltar es la entrada -- y lo dice la LECTURA, no la memoria.
    # Si la dirección ya está puesta como ESTÁTICA, no hay nada que soltar: pedirlo sería una
    # llamada de más en cada pasada, y la idempotencia vive de no tenerlas.
    estaticas = {
        _sin_prefijo((entrada or {}).get("direccion"))
        for entrada in direcciones_leidas.get("estaticas") or []
    }
    residuo = (
        bool(propia) and not cliente_vivo and propia in dinamicas and propia not in estaticas
    )
    if not apagones and not residuo:
        return operaciones

    lineas = [
        # Los clientes que hay que quitar, por interfaz: el op dice QUE hay que quitarlo y la
        # LECTURA dice dónde está (su mapa de `.id`s por interfaz), que es lo que el guion
        # necesita para encontrarlo.
        f"/ip dhcp-client remove [find interface={interfaz}]"
        for interfaz in (
            sorted(((areas.get("cliente_dhcp") or {}).get("ids") or {}).keys())
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
            f"/ip address add address={choque.get('direccion')} "
            f"interface={choque.get('interfaz')}"
        )

    guion = {
        "op": "ejecutar_guion", "area": "direcciones", "lineas": lineas,
        "tolerar_sin_respuesta": True,
        "descripcion": "el intercambio de la dirección de gestión, dentro del router y de una vez",
    }
    # De las escrituras se descartan las que van DENTRO del guion: el cliente que se quita
    # y la estática que se pone junto a él. Dejarlas fuera sería mandarlas dos veces --y la
    # segunda, con el duplicado que RouterOS rechaza--.
    fuera = [
        operacion for operacion in operaciones
        if operacion.get("op") != "deshabilitar_cliente_dhcp" and operacion is not choque
    ]
    # Y el guion, al final, pero por delante de la credencial: el cambio de credencial deja
    # sin credencial a cualquier escritura posterior (medido: un 401 tolerado que se queda
    # sin hacer), así que la credencial sigue siendo lo ÚLTIMO que se toca.
    donde = len(fuera)
    for posicion, operacion in enumerate(fuera):
        if operacion.get("op") == "poner_credencial_motor":
            donde = posicion
            break
    fuera.insert(donde, guion)
    return fuera


def escrituras_routeros(operaciones, invitado, declaracion, identidad, parametros, leido):
    """(operaciones decididas) -> llamadas al REST, en orden.

    Aquí está el ÚNICO sitio donde el vocabulario del lab se traduce a objetos de
    RouterOS (`/ip/address/add`, `/ip/dhcp-server/lease/set`...). El lab declara qué
    quiere; esto dice cómo se pide. Cada llamada sale con su `metodo`, su `ruta` y su
    `cuerpo`, y la puerta la diariza igual que cualquier otra.

    Trampas ya pagadas y no repetidas (medidas en v3 y re-medidas en esta fase):
      * escribir una ruta se hace con `POST /add` (un `PUT` a la ruta de las rutas
        responde 400 «no such command»: comprobado en un CHR 7.25.1);
      * RouterOS no tiene «crear o actualizar»: si el objeto no está, se AÑADE, y si
        está, se MODIFICA -- y eso se decide aquí, con lo que se leyó;
      * `www` no se deshabilita: es donde vive el REST, o sea el camino de vuelta;
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
            item["direccion"] = dirigirse_a
        if operacion.get("tolerar_sin_respuesta"):
            item["tolerar_sin_respuesta"] = True
        llamadas.append(item)
        # Se devuelve además de apuntarla: hay traducciones que necesitan retocar la llamada
        # después (la relectura que se marca como `accion: leer`).
        return item

    # La dirección de gestión la deriva el motor del `direccion:` del invitado (ver
    # `pasos_de_convergencia`), así que la capa pura ya la tiene en el invitado normalizado.
    operaciones = _intercambio_de_la_gestion(
        operaciones, declaracion, invitado, leido
    )

    for operacion in operaciones or []:
        op = str((operacion or {}).get("op") or "")
        area = str((operacion or {}).get("area") or "")
        dirigirse_a = str((operacion or {}).get("dirigirse_a") or "")

        if op == "ejecutar_guion":
            # El intercambio de la dirección de gestión, de UNA vez y dentro del router: él
            # quita su cliente DHCP, suelta la entrada dinámica que ese cliente dejó y pone
            # la estática, todo en la misma ejecución. Medido en un CHR 7.25.1: por pasos
            # desde fuera no se puede --quitar el cliente se lleva la dirección y la petición
            # muere sin contestar--, y un guion sí, porque corre entero dentro del equipo.
            llamada(area or "direcciones", "POST", "/execute",
                    {"script": "; ".join(operacion.get("lineas") or [])},
                    str(operacion.get("descripcion") or "el intercambio de la dirección de gestión"))

        elif op == "poner_identidad":
            llamada(area, "POST", "/system/identity/set",
                    {"name": str(operacion.get("nombre"))},
                    f"poner el nombre del equipo a '{operacion.get('nombre')}'")

        elif op == "crear_usuario_motor":
            # Se crea CON la credencial del motor puesta: crear un usuario sin contraseña
            # y ponérsela después deja una ventana en la que el equipo está abierto.
            llamada(area, "POST", "/user/add",
                    {"name": usuario, "group": "full", "password": clave},
                    f"crear el usuario del motor ('{usuario}') con su credencial")

        elif op == "poner_credencial_motor":
            llamada(area, "POST", "/user/set",
                    {"numbers": usuario, "password": clave},
                    "poner la credencial del motor en el usuario del motor")

        elif op == "importar_clave_motor":
            llamada(area, "POST", "/user/ssh-keys/add",
                    {"user": usuario, "key": clave_publica},
                    "importar la clave pública del motor (sólo para depurar: se converge por REST)")

        elif op in ("deshabilitar_servicio", "habilitar_servicio"):
            servicio = str(operacion.get("servicio"))
            identificador = ((areas.get("servicios") or {}).get("ids") or {}).get(servicio) or servicio
            apagado = "yes" if op == "deshabilitar_servicio" else "no"
            llamada(area, "POST", "/ip/service/set",
                    {"numbers": identificador, "disabled": apagado},
                    f"{'deshabilitar' if apagado == 'yes' else 'habilitar'} el servicio '{servicio}'")

        # (aquí no hay traducción de `deshabilitar_cliente_dhcp`, y es a propósito: al cliente
        # de fábrica no se le apaga desde fuera -- apagarlo se lleva la dirección y la petición
        # muere sin contestar --, se le QUITA dentro del guion del intercambio, junto a la
        # estática que hay que poner en su lugar: ver `_intercambio_de_la_gestion`)
        elif op == "poner_direccion":
            llamada(area, "POST", "/ip/address/add",
                    {"address": str(operacion.get("direccion")),
                     "interface": str(operacion.get("interfaz"))},
                    f"poner la dirección {operacion.get('direccion')} en {operacion.get('interfaz')}")

        elif op == "quitar_direccion":
            clave_id = _ros_clave(operacion.get("interfaz"), operacion.get("direccion"))
            identificador = ((areas.get("direcciones") or {}).get("ids") or {}).get(clave_id)
            llamada(area, "POST", "/ip/address/remove",
                    {"numbers": identificador or str(operacion.get("direccion"))},
                    f"quitar la dirección {operacion.get('direccion')} de {operacion.get('interfaz')}")

        elif op == "poner_ruta":
            llamada(area, "POST", "/ip/route/add",
                    {"dst-address": str(operacion.get("destino")),
                     "gateway": str(operacion.get("pasarela"))},
                    f"poner la ruta {operacion.get('destino')} por {operacion.get('pasarela')}")

        elif op == "quitar_ruta":
            clave_id = _ros_clave(operacion.get("destino"), operacion.get("pasarela"))
            identificador = ((areas.get("rutas") or {}).get("ids") or {}).get(clave_id)
            llamada(area, "POST", "/ip/route/remove",
                    {"numbers": identificador or str(operacion.get("destino"))},
                    f"quitar la ruta {operacion.get('destino')} por {operacion.get('pasarela')}")

        elif op == "poner_servidor_dhcp":
            interfaz = str(operacion.get("interfaz"))
            rango = str(operacion.get("rango") or "")
            nombre_pool = PREFIJO_POOL + rango.split("-")[0]
            pools = ((areas.get("dhcp") or {}).get("pools") or {})
            if nombre_pool in pools:
                llamada(area, "POST", "/ip/pool/set",
                        {"numbers": pools[nombre_pool]["id"] or nombre_pool, "ranges": rango},
                        f"ajustar el rango que reparte el router ({rango})")
            else:
                llamada(area, "POST", "/ip/pool/add",
                        {"name": nombre_pool, "ranges": rango},
                        f"declarar el rango que reparte el router ({rango})")
            existente = None
            for servidor in (areas.get("dhcp") or {}).get("servidores") or []:
                if str(servidor.get("interfaz")) == interfaz:
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

        elif op == "quitar_servidor_dhcp":
            interfaz = str(operacion.get("interfaz"))
            for servidor in (areas.get("dhcp") or {}).get("servidores") or []:
                if str(servidor.get("interfaz")) == interfaz:
                    llamada(area, "POST", "/ip/dhcp-server/remove",
                            {"numbers": servidor.get("id") or interfaz},
                            f"dejar de servir DHCP en {interfaz} (ya no se declara)")

        elif op == "poner_red_dhcp":
            dns = operacion.get("dns") or []
            cuerpo = {
                "address": str(operacion.get("prefijo")),
                "gateway": str(operacion.get("pasarela")),
                "dns-server": ",".join(str(d) for d in dns),
            }
            existente = None
            for servidor in (areas.get("dhcp") or {}).get("servidores") or []:
                if str((servidor.get("red") or {}).get("prefijo")) == str(operacion.get("prefijo")):
                    existente = (servidor.get("red") or {}).get("id")
                    break
            if existente:
                llamada(area, "POST", "/ip/dhcp-server/network/set",
                        dict(cuerpo, numbers=existente),
                        f"anunciar la red {operacion.get('prefijo')} con pasarela {operacion.get('pasarela')}")
            else:
                llamada(area, "POST", "/ip/dhcp-server/network/add", cuerpo,
                        f"anunciar la red {operacion.get('prefijo')} con pasarela {operacion.get('pasarela')}")

        elif op == "poner_reserva":
            mac = str(operacion.get("mac"))
            interfaz = str(operacion.get("interfaz"))
            # El servidor que reserva: el que ya está (leído), y si no, el que esta MISMA
            # pasada acaba de crear (su nombre es derivado, no hay que adivinarlo). Nunca
            # `all`: una reserva sin servidor la puede servir cualquiera de las dos LANs.
            servidor = PREFIJO_POOL + interfaz if interfaz else ""
            for candidato in (areas.get("dhcp") or {}).get("servidores") or []:
                if str(candidato.get("interfaz")) == interfaz:
                    servidor = str(candidato.get("nombre") or servidor)
                    break
            existente = None
            for reserva in (areas.get("dhcp") or {}).get("reservas") or []:
                if str(reserva.get("mac")).upper() == mac.upper():
                    existente = reserva.get("id")
                    break
            cuerpo = {
                "address": str(operacion.get("direccion")),
                "mac-address": mac,
                # La reserva se ata al servidor de ESA interfaz: un router con dos LANs
                # no puede reservar en la primera lo que vive en la segunda.
                "server": servidor or "all",
            }
            if existente:
                llamada(area, "POST", "/ip/dhcp-server/lease/set",
                        dict(cuerpo, numbers=existente),
                        f"reservar {operacion.get('direccion')} a la MAC derivada {mac}")
            else:
                llamada(area, "POST", "/ip/dhcp-server/lease/add", cuerpo,
                        f"reservar {operacion.get('direccion')} a la MAC derivada {mac}")

        elif op == "quitar_reserva":
            mac = str(operacion.get("mac"))
            identificador = None
            for reserva in (areas.get("dhcp") or {}).get("reservas") or []:
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


def invitados_a_verificar(declaracion):
    """Los invitados que hay que MIRAR por dentro, para `verify` (regla 11 del README de
    verificación): los que declaran `config` con áreas que piden visita.

    Es la MISMA frontera que usa el plan (`areas_que_piden_visita`): a un invitado al
    que no hay nada que preguntarle no se le abre una conexión -- ni siquiera para
    leer. Devuelve `[{'rol': …, 'tipo': …}]` en el orden de la declaración.
    """
    # La declaración normalizada trae `invitados` (una sola lista, con el tipo ya
    # resuelto); la cruda trae `vms` + `containers`. Se aceptan las dos para que la
    # función sirva igual desde `verify` (normalizada) y desde una prueba (cruda).
    if "invitados" in declaracion:
        candidatos = declaracion.get("invitados") or []
    else:
        candidatos = list(declaracion.get("vms") or []) + list(declaracion.get("containers") or [])
    fuera = []
    for invitado in candidatos:
        tipo = tipo_de(invitado)
        if tipo and areas_que_piden_visita(invitado):
            fuera.append({"rol": invitado.get("rol"), "tipo": tipo})
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
    """El informe del interior cuando NO se pudo mirar (p. ej. el camino del lab no
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
            "interior_tiene_camino": tiene_camino,
            "interior_puesto_control": puesto_control,
            "interior_direccion_libre": direccion_libre,
            "interior_patas": patas_del_puesto_control,
            "interior_puerto_camino": puerto_camino,
            "interior_puerto_rest": puerto_rest_camino,
            "interior_permitlisten": permitlisten_de,
            "interior_patas_rest": patas_rest_del_puesto_control,
            "interior_guion_camino": guion_camino,
            "interior_linea_consola": linea_consola,
            "interior_marca_camino": marca_camino,
            "interior_reservas": reservas_derivadas,
            "interior_residuo": residuo_dinamico,
            "interior_pasos": pasos_de_convergencia,
            "interior_espera": espera_de_servicio,
            "interior_a_verificar": invitados_a_verificar,
            "interior_informe_ok": informe_ok,
            "interior_sin_comprobar": sin_comprobar,
        }
