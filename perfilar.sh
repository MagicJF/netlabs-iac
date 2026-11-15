#!/usr/bin/env bash
# Perfila UN verbo del motor, sellando cada línea de su salida con el instante en que
# salió. NO toca el motor ni usa plugins de Ansible: es un `while read` sobre la salida
# de `./lab`, y de ahí se saca cuánto tarda cada tarea (delta entre dos cabeceras TASK).
#
# Uso:  perfilar.sh <fichero.tsv> <args de ./lab...>
#   ej: perfilar.sh /tmp/destroy.tsv --lab <lab> destroy --yes
set -uo pipefail
cd /home/hermes/repos/netlabs_v4_b || exit 1

salida="$1"; shift
: > "$salida"

# `stdbuf -oL -eL` para que no se acumule en un buffer de 4K (si no, los sellos de tiempo
# saldrían todos juntos al final y no medirían nada).
stdbuf -oL -eL ./lab "$@" 2>&1 | while IFS= read -r linea; do
    printf '%s\t%s\n' "$(date +%s.%3N)" "$linea"
done > "$salida"
