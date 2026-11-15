#!/usr/bin/env python3
"""Analiza un perfil de `perfilar.sh` y dice DÓNDE se va el tiempo.

Ansible imprime `TASK [nombre]` justo cuando la tarea EMPIEZA, así que lo que tardó una
tarea es el hueco hasta la cabecera siguiente. No hace falta ningún plugin: el sello de
tiempo lo puso `perfilar.sh` línea a línea.

Uso:  analizar_perfil.py <perfil.tsv> [top_n]
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

RUTA = sys.argv[1]
TOPN = int(sys.argv[2]) if len(sys.argv) > 2 else 25

filas: list[tuple[float, str]] = []
with open(RUTA, encoding="utf-8", errors="replace") as fh:
    for linea in fh:
        if "\t" not in linea:
            continue
        sello, resto = linea.split("\t", 1)
        try:
            filas.append((float(sello), resto.rstrip("\n")))
        except ValueError:
            continue

if len(filas) < 3:
    sys.exit(f"perfil vacío o sin sellos: {RUTA}")

# Una marca por cada tarea que EMPIEZA.
marcas = [(t, m.group(1)) for t, l in filas
          if (m := re.match(r"^(?:TASK|RUNNING HANDLER) \[(.+?)\]", l))]
if not marcas:
    sys.exit("no hay cabeceras TASK en el perfil")

duraciones: list[tuple[float, str]] = []
for i, (t0, nombre) in enumerate(marcas):
    t1 = marcas[i + 1][0] if i + 1 < len(marcas) else filas[-1][0]
    duraciones.append((t1 - t0, nombre))

total = filas[-1][0] - filas[0][0]
cronometrado = sum(d for d, _ in duraciones)

print("=" * 78)
print(f"PERFIL: {RUTA}")
print(f"total de pared: {total:8.1f} s   ·   tareas con cabecera: {len(marcas)}")
print(f"suma de los huecos de tarea: {cronometrado:8.1f} s "
      f"(el resto es arranque de Ansible, inventario y huecos entre tareas)")
print("=" * 78)

print("\n--- DÓNDE SE VA (top por duración de UNA tarea) ---")
print(f"{'seg':>8}  {'%':>5}  tarea")
for d, nombre in sorted(duraciones, reverse=True)[:TOPN]:
    print(f"{d:8.1f}  {100 * d / total:5.1f}  {nombre[:110]}")

# Agrupado por PREFIJO: cuánto pesa cada familia de tareas (ESPERA, CAMINO, PUERTA...).
familias: dict[str, float] = defaultdict(float)
for d, nombre in duraciones:
    familias[nombre.split(" ·")[0].split(" [")[0][:40]] += d
print("\n--- POR FAMILIA (prefijo de la tarea) ---")
print(f"{'seg':>8}  {'%':>5}  familia")
for fam, d in sorted(familias.items(), key=lambda kv: -kv[1])[:15]:
    print(f"{d:8.1f}  {100 * d / total:5.1f}  {fam}")

# Las tareas de ESPERA, juntas: es el margen que el motor se da a sí mismo.
esperas = [(d, n) for d, n in duraciones
           if re.search(r"ESPERA|SONDA|CAMINO|CONSOLA|dormir|esperar|wait", n, re.I)]
print(f"\n--- SÓLO ESPERAS (lo que el motor se toma de margen) ---")
print(f"{sum(d for d, _ in esperas):8.1f} s en {len(esperas)} tarea(s) de espera "
      f"({100 * sum(d for d, _ in esperas) / total:.1f}% del total)")
for d, n in sorted(esperas, reverse=True)[:12]:
    print(f"{d:8.1f}  {n[:110]}")
