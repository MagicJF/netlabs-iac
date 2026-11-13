# PROPÓSITO:   leer el estado del mundo (lo que Proxmox dice que hay) y compararlo
#              con lo declarado. Aquí vive `estado_desde_api` (normaliza las
#              respuestas de la API) y `estado_verificar` (la comparación por
#              conjuntos EN LOS DOS SENTIDOS: falta algo = fallo, sobra algo =
#              también fallo). Para calcular el plan delega en tools/plan.py, para
#              que no exista una segunda lógica de decisión.
# INVARIANTES: el conjunto ESPERADO se DERIVA de la declaración; el test nunca
#              recorre la lista que él mismo trae. El estado es lo que dice la API
#              (o un fixture), nunca una caché propia: no hay estado en disco.
#              Un invitado que existe pero está en el pool de OTRO lab se reporta
#              como "de otro lab", no como propio.
# LÍMITES:     la dirección IP declarada de cada rol NO se puede verificar por
#              API: la IP vive dentro del invitado y la config del hipervisor no
#              la guarda. `verify` lo dice explícitamente en vez de callarse.
# VER:         README.md §Verificación; AGENTS.md §Identidad; ./lab check declaracion

import os
import sys

# `estado.py` es el filtro que Ansible ve; el cálculo del plan (mucho más grande)
# vive en tools/plan.py para poder probarse sin Ansible. El módulo se importa por
# ruta, no por PYTHONPATH: el motor no depende de variables de entorno (regla 4.4).
_DIRECTORIO_FILTROS = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.join(os.path.dirname(_DIRECTORIO_FILTROS), "tools")
for _ruta in (_TOOLS, _DIRECTORIO_FILTROS):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

import plan as modulo_plan  # noqa: E402  (la ruta se ajusta justo arriba)
import identidad as modulo_identidad  # noqa: E402

try:
    from ansible.errors import AnsibleFilterError as ErrorMotor
except ImportError:  # pragma: no cover - sólo ocurre fuera de Ansible
    class ErrorMotor(Exception):
        """Error del motor, con el mismo nombre que el de Ansible."""


def _red_de_net0(net0):
    """Saca (bridge, mac) de la cadena de red de la config de Proxmox.

    En una VM es `virtio=BC:24:11:00:00:64,bridge=vmbr0`; en un contenedor es
    `name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:00:64`. Las dos formas caen con
    este recorrido, que es por eso que está en un solo sitio.
    """
    bridge = None
    mac = None
    for trozo in str(net0 or "").split(","):
        clave, _, valor = trozo.partition("=")
        clave = clave.strip().lower()
        if clave == "bridge":
            bridge = valor.strip()
        elif clave == "hwaddr":
            mac = valor.strip().upper()
        elif ":" in valor and clave != "name":
            # En una VM la MAC va en la propia clave: `virtio=<mac>`.
            mac = valor.strip().upper()
    return bridge, mac


def _descripcion_sin_ruido(texto):
    """La descripción como la guarda Proxmox, sin el `\\n` que la API le pega al final.

    Proxmox trata `description` como campo de texto y le añade un salto de línea: si
    no se quita, la comparación de idempotencia ve "drift" donde no lo hay y dispara
    un PUT innecesario (rompiendo la regla de que dos ejecuciones seguidas no cambian
    nada). El `strip` sólo toca los extremos; el interior se respeta tal cual.
    """
    return (texto or "").strip()


def estado_vacio():
    """El mundo antes de que exista nada: un clúster sin invitados ni pools."""
    return {
        "nodo": "",
        "vmids_usados": [],
        "bridges_nodo": [],
        "pools": {},
        "invitados": {},
        "invitados_otros": {},
    }


def estado_normalizar(datos):
    """Completa un estado con las claves que el resto del motor espera.

    Sirve para que un fixture escrito a mano no tenga que declarar los campos
    vacíos: se rellenan aquí de forma explícita (nunca de forma implícita y
    sorprendente).
    """
    base = estado_vacio()
    if not isinstance(datos, dict):
        raise ErrorMotor("el estado del mundo no es un mapa")
    for clave, valor in datos.items():
        base[clave] = valor
    base["vmids_usados"] = sorted(int(v) for v in (base.get("vmids_usados") or []))
    base["pools"] = base.get("pools") or {}
    base["invitados"] = base.get("invitados") or {}
    base["invitados_otros"] = base.get("invitados_otros") or {}
    base["bridges_nodo"] = base.get("bridges_nodo") or []
    return base


def estado_desde_api(datos):
    """Normaliza las respuestas CRUDAS de la API en el estado que usa el motor.

    Entradas (todas tal cual las devuelve Proxmox):
      - `cluster_recursos`: GET /cluster/resources -- todos los invitados, con su
        `pool` y si están `running`. Es la fuente de "qué vmids están ocupados en
        TODO el clúster", que es lo que impide reutilizar un vmid de otro lab.
      - `pools_lista`: GET /pools -- los pools que existen (las fronteras de
        propiedad). Sin esto, un pool vacío parecería no existir y `apply` lo
        volvería a crear en cada ejecución: dejaría de ser idempotente.
      - `red_nodo`: GET /nodes/<nodo>/network -- los bridges que ya existen.
      - `configs`: {vmid: {config}} -- GET /nodes/<nodo>/<tipo>/<vmid>/config, para
        la descripción, los recursos y la red de los invitados DEL lab.
      - `lab`: el nombre del pool de este lab (su carpeta).
    """
    lab = datos["lab"]
    estado = estado_vacio()
    estado["nodo"] = datos.get("nodo") or ""

    configs = {str(k): v for k, v in (datos.get("configs") or {}).items()}
    recursos = datos.get("cluster_recursos") or []

    for pool in datos.get("pools_lista") or []:
        estado["pools"][pool.get("poolid")] = {"comment": pool.get("comment") or ""}

    for recurso in recursos:
        vmid = recurso.get("vmid")
        if vmid is None:
            continue
        estado["vmids_usados"].append(int(vmid))

    for interfaz in datos.get("red_nodo") or []:
        # El nodo devuelve interfaces de varios tipos; sólo interesan los bridges,
        # que son los que un lab puede necesitar crear.
        if interfaz.get("iface") and (
            interfaz.get("type") == "bridge" or str(interfaz["iface"]).startswith("vmbr")
        ):
            estado["bridges_nodo"].append(interfaz["iface"])

    for recurso in recursos:
        vmid = recurso.get("vmid")
        if vmid is None:
            continue
        vmid = int(vmid)
        tipo = recurso.get("type")
        pool = recurso.get("pool")
        nombre = recurso.get("name") or recurso.get("id") or str(vmid)
        if pool == lab:
            config = configs.get(str(vmid), {})
            bridge, mac = _red_de_net0(config.get("net0"))
            estado["invitados"][str(vmid)] = {
                "vmid": vmid,
                "nombre": config.get("name") or config.get("hostname") or nombre,
                "tipo": "lxc" if tipo == "lxc" else "qemu",
                "descripcion": _descripcion_sin_ruido(config.get("description")),
                "cores": config.get("cores"),
                "memoria": config.get("memory"),
                "bridge": bridge,
                "mac": mac,
                "arrancado": recurso.get("status") == "running",
                "pool": pool,
                "nodo": recurso.get("node"),
            }
            estado["pools"].setdefault(lab, {})
        else:
            # Está en el clúster pero NO es de este lab: puede ser de otro lab, o
            # de nadie. Se guarda aparte para poder decirlo en el informe.
            estado["invitados_otros"][nombre] = {
                "vmid": vmid,
                "pool": pool,
                "descripcion": _descripcion_sin_ruido((configs.get(str(vmid)) or {}).get("description")),
            }

    estado["vmids_usados"] = sorted(set(estado["vmids_usados"]))
    estado["bridges_nodo"] = sorted(set(estado["bridges_nodo"]))
    return estado


def estado_resumen(estado):
    """Una línea con lo esencial del estado del mundo, para el informe humano."""
    return (
        f"nodo={estado.get('nodo') or '?'} "
        f"vmids_usados={len(estado.get('vmids_usados') or [])} "
        f"pools={sorted((estado.get('pools') or {}).keys())} "
        f"invitados_del_pool={len(estado.get('invitados') or {})} "
        f"bridges={len(estado.get('bridges_nodo') or [])}"
    )


def pve_invitados_del_pool(cluster_recursos, lab):
    """Los invitados que la API dice que están en el pool del lab.

    Es lo que se usa para pedir la configuración de cada uno (descripción, recursos,
    red). Sólo mira el pool: la frontera de propiedad, no un rango de vmids.
    """
    salida = []
    for recurso in cluster_recursos or []:
        if recurso.get("pool") != lab:
            continue
        if recurso.get("vmid") is None:
            continue
        salida.append(
            {
                "vmid": int(recurso["vmid"]),
                "tipo": "lxc" if recurso.get("type") == "lxc" else "qemu",
                "nodo": recurso.get("node"),
                "rol_o_nombre": recurso.get("name") or str(recurso.get("vmid")),
            }
        )
    return sorted(salida, key=lambda i: i["vmid"])


def estado_plan(declaracion, estado, identidad, parametros):
    """El plan ordenado. Delegado al módulo puro para que no haya dos decisiones."""
    return modulo_plan.construir_plan(declaracion, estado, identidad, parametros)


def estado_plan_texto(plan, declaracion, estado, identidad):
    """El plan, en texto, listo para imprimir."""
    return modulo_plan.formatear_plan(plan, declaracion, estado, identidad)


def estado_verificar(declaracion, estado, identidad):
    """Compara lo declarado con lo que hay, EN LOS DOS SENTIDOS.

    Devuelve un informe estructurado. `ok` es False si falta algo, sobra algo, un
    invitado está parado o un campo declarado no coincide.
    """
    lab = declaracion["lab"]
    invitados_pool = estado.get("invitados") or {}
    otros = estado.get("invitados_otros") or {}

    faltan = []
    sobran = []
    drift = []
    parados = []
    otros_lab = []
    conformes = []
    no_verificable = [
        "la dirección IP declarada de cada rol no es verificable por API: vive dentro "
        "del invitado y la config del hipervisor no la guarda",
    ]

    roles_declarados = set()

    # --- Lado esperado: lo DERIVA la declaración (entrada), no el resultado -----
    for esperado in identidad["invitados"]:
        rol = esperado["rol"]
        roles_declarados.add(rol)
        actual = invitados_pool.get(str(esperado["vmid"]))

        if actual is None:
            # ¿Existe un invitado con el mismo nombre canónico pero en otro pool?
            # Entonces no falta: está, pero no es nuestro. Decirlo así es lo honesto.
            gemelo = otros.get(esperado["nombre"])
            if gemelo is not None:
                otros_lab.append(
                    {
                        "rol": rol,
                        "nombre": esperado["nombre"],
                        "vmid": gemelo["vmid"],
                        "pool": gemelo["pool"],
                        "nota": f"existe con el nombre canónico del rol, pero su pool es "
                        f"'{gemelo['pool']}', no '{lab}'",
                    }
                )
            else:
                faltan.append({"rol": rol, "vmid": esperado["vmid"], "nombre": esperado["nombre"]})
            continue

        diferencias = modulo_plan.campos_que_difieren(esperado, actual)
        if diferencias:
            for campo, valores in sorted(diferencias.items()):
                drift.append(
                    {"rol": rol, "vmid": esperado["vmid"], "campo": campo,
                     "esperado": valores["esperado"], "encontrado": valores["encontrado"]}
                )
        if not actual.get("arrancado"):
            parados.append({"rol": rol, "vmid": esperado["vmid"]})
        if not diferencias and actual.get("arrancado"):
            conformes.append({"rol": rol, "vmid": esperado["vmid"]})

    # --- Lado real: lo que SOBRA en el pool del lab ----------------------------
    # Un invitado en el pool que ya no está declarado delata una copia a mano o un
    # borrado en la declaración que se quedó atrás. Es un fallo, no un aviso.
    for vmid, actual in sorted(invitados_pool.items(), key=lambda par: int(par[0])):
        rol = modulo_identidad.rol_de_descripcion(actual.get("descripcion"))
        if rol not in roles_declarados:
            sobran.append(
                {
                    "vmid": actual.get("vmid", vmid),
                    "nombre": actual.get("nombre"),
                    "rol": rol or "(sin descripción del motor)",
                    "nota": "está en el pool del lab pero no lo declara ningún rol"
                    if rol
                    else "está en el pool del lab sin descripción del motor: no lo puso este motor",
                }
            )

    ok = not (faltan or sobran or drift or parados or otros_lab)

    return {
        "lab": lab,
        "nodo": estado.get("nodo") or "",
        "ok": ok,
        "esperados": len(identidad["invitados"]),
        "encontrados_en_pool": len(invitados_pool),
        "conformes": conformes,
        "faltan": faltan,
        "sobran": sobran,
        "drift": drift,
        "parados": parados,
        "otros_lab": otros_lab,
        "no_verificable": no_verificable,
    }


def estado_informe_texto(informe):
    """El informe de verificación en texto, con la conclusión la primera."""
    lineas = []
    estado_txt = "CORRECTO" if informe["ok"] else "CON DRIFT"
    lineas.append("=" * 60)
    lineas.append(f"VERIFICACIÓN del lab '{informe['lab']}' — {estado_txt}")
    lineas.append("=" * 60)
    lineas.append(
        f"esperados={informe['esperados']}  encontrados_en_el_pool={informe['encontrados_en_pool']}"
    )
    lineas.append("")

    if informe["faltan"]:
        lineas.append(f"FALTAN ({len(informe['faltan'])}): lo declarado y no desplegado")
        for item in informe["faltan"]:
            lineas.append(f"  - rol={item['rol']} (le correspondería el vmid {item['vmid']}, {item['nombre']})")
        lineas.append("")

    if informe["sobran"]:
        lineas.append(f"SOBRAN ({len(informe['sobran'])}): en el pool del lab y no declarados")
        for item in informe["sobran"]:
            lineas.append(f"  - vmid={item['vmid']} nombre={item['nombre']} rol={item['rol']}: {item['nota']}")
        lineas.append("")

    if informe["drift"]:
        lineas.append(f"DRIFT ({len(informe['drift'])}): existe pero no coincide")
        for item in informe["drift"]:
            lineas.append(
                f"  - rol={item['rol']} vmid={item['vmid']} campo={item['campo']}: "
                f"declarado={item['esperado']} encontrado={item['encontrado']}"
            )
        lineas.append("")

    if informe["parados"]:
        lineas.append(f"PARADOS ({len(informe['parados'])}): existen pero no están arrancados")
        for item in informe["parados"]:
            lineas.append(f"  - rol={item['rol']} vmid={item['vmid']}")
        lineas.append("")

    if informe["otros_lab"]:
        lineas.append(f"DE OTRO LAB ({len(informe['otros_lab'])}): existen, pero no son de este lab")
        for item in informe["otros_lab"]:
            lineas.append(f"  - rol={item['rol']}: {item['nota']}")
        lineas.append("")

    if informe["conformes"]:
        lineas.append(f"CONFORMES ({len(informe['conformes'])}): existen, coinciden y están arrancados")
        for item in informe["conformes"]:
            lineas.append(f"  - rol={item['rol']} vmid={item['vmid']}")
        lineas.append("")

    if informe["no_verificable"]:
        lineas.append("LÍMITES de esta verificación (dicho, no maquillado):")
        for linea in informe["no_verificable"]:
            lineas.append(f"  - {linea}")
        lineas.append("")

    return "\n".join(lineas)


class FilterModule:
    """Filtros que Ansible ve como `| estado_desde_api`, `| estado_verificar`…"""

    def filters(self):
        return {
            "estado_vacio": estado_vacio,
            "estado_normalizar": estado_normalizar,
            "estado_desde_api": estado_desde_api,
            "estado_resumen": estado_resumen,
            "pve_invitados_del_pool": pve_invitados_del_pool,
            "estado_plan": estado_plan,
            "estado_plan_texto": estado_plan_texto,
            "estado_verificar": estado_verificar,
            "estado_informe_texto": estado_informe_texto,
        }
