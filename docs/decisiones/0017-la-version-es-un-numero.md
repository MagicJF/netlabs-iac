# 0017 — La versión es un número y se publica con un tag; el trabajo, en ramas cortas

*Fecha: 15-nov-2026 — Estado: aceptada y aplicada — Ámbito: la forma de entregar
(ramas, tags, `VERSION` y `CHANGELOG.md`), no el motor*

## El problema

Hasta hoy la historia del repositorio vivía en la única rama que existía: decenas de
commits directos a `main` cada día, sin ramas, sin tags y sin ningún sitio donde leer
**qué cambió entre dos estados**. Tres consecuencias, todas reales:

1. **Nadie sabe qué versión está corriendo.** Un lab desplegado la semana pasada y el
   motor de hoy no se pueden comparar: no hay nombre para ninguno de los dos estados.
2. **Un cambio que rompe la declaración de un lab no se distingue de uno que no.** Quien
   actualiza el motor y ve que su lab ya no aplica igual no tiene dónde leer que ese cambio
   era el esperado, ni cómo quedarse en el estado anterior.
3. **No hay puerta antes de `main`.** El único freno era el pre-commit y los checks, y
   ninguno sabe decir «esto todavía no está listo para publicarse».

Y una cuarta, que no se arregla con ramas: la versión estaba en el **nombre**
(`-v4`, `_b`). Un nombre no puede cambiar, así que una versión dentro del nombre se queda
ahí para siempre y no dice nada de lo que hay dentro.

## La decisión

**1. La versión es un número, y el número es SemVer: `MAYOR.MENOR.PARCHE`.**

- **MAYOR** sube cuando un cambio **rompe** algo que alguien de fuera usaba: la declaración
  de un lab, un verbo, el nombre de un diario, lo que un check exige.
- **MENOR** sube cuando se **añade** capacidad sin romper lo de antes.
- **PARCHE** sube cuando se **arregla** algo sin añadir ni romper nada.

Si algún día hace falta enseñar algo a medias, SemVer tiene etiquetas de pre-release
(`0.2.0-beta.1`, `1.0.0-rc.1`): se publican como *pre-release* en GitHub y **no** son la
versión publicada — `VERSION` no las lleva.

**2. Mientras la MAYOR sea `0`, romper es legítimo y barato; lo que no vale es romper en
silencio.** Es la regla de SemVer para la serie 0.x: el producto está en desarrollo y
cualquier versión MENOR puede traer un cambio incompatible. Por eso la primera entrega es
`0.1.0`, no `1.0.0`. La `1.0.0` se publicará el día que haya algo que prometer: una
declaración de lab que no queramos volver a tocar, y terceros usándola. Ese día, romper
pasa a costar una MAYOR.

**3. La versión vive en tres sitios, y los tres tienen que contar lo mismo.**

| Sitio | Qué es | Quién lo escribe |
| --- | --- | --- |
| `VERSION` | la última versión **publicada** (una línea: `0.1.0`) | a mano, al publicar |
| el tag `vX.Y.Z` | la marca en la historia de `main` | `./lab` / `git tag` |
| `CHANGELOG.md` | lo que entró en ella, en castellano y para leer | a mano, al publicar |

Lo que entra en `main` y todavía no se ha publicado se apunta bajo `[No publicado]`. El
día que se publica, esa sección se convierte en `## [X.Y.Z] - fecha`, se sube `VERSION` y
se ponen el tag y la *release*. **Se escribe a mano**: un generador a partir de los
commits contaría lo que se hizo, no lo que cambió para quien lo usa, y además obligaría a
una dependencia más (aquí no entra ninguna).

**4. El trabajo va en ramas cortas, una por cambio, y `main` es el tronco.**

- La rama se llama por el **tipo de Conventional Commits** que ya se usa, en minúsculas y
  con guiones: `feat/<algo>`, `fix/<algo>`, `refactor/<algo>`, `docs/<algo>`,
  `chore/<algo>`, `test/<algo>`.
- Se abre **para un cambio**, no para «lo de esta semana»: se abre, se cierra con un PR y
  se borra. Una rama que vive más de unos días es una señal de que el cambio debería ser
  tres.
- `main` es lo publicado. **Siempre verde**: lo que se mezcla en `main` ha pasado
  `./lab check` (todo) y la suite de pruebas. Un commit roto en `main` es un fallo de
  método, no mala suerte.
- El PR es donde se cuenta **qué cambia, por qué y cómo se ha comprobado**. Se mezcla con
  *squash*: un cambio, un commit en `main`, con el título del PR. Así `git log --oneline`
  de `main` se lee como una lista de cambios, no como un dietario.
- Los commits pequeños y seguros (una línea, una errata) siguen pudiendo ir directos: lo
  que no se sostiene es *todo* directo.

**5. Publicar es un acto explícito, no un efecto secundario de commitear.**

```sh
git switch main && git pull                 # main verde, con lo que va a esta versión
./lab check                                 # verde, y la suite de pruebas también
# 1. `CHANGELOG.md`: `## [No publicado]` pasa a `## [X.Y.Z] - AAAA-MM-DD` (con su sección)
# 2. `VERSION`: sube a X.Y.Z
# 3. commit "chore: publica la X.Y.Z"
git tag -a vX.Y.Z -m "X.Y.Z"                # tag ANOTADO: lleva fecha y mensaje
git push --follow-tags
gh release create vX.Y.Z --title "X.Y.Z" --notes-file <(la sección del CHANGELOG)
```

Una versión del motor que no ha pasado **el ciclo completo contra un Proxmox real**
(`destroy` → `apply` → `verify`) no se publica: sería una promesa sin respaldo. La entrega
`0.1.0` es la única excepción razonable y está dicha en su entrada: nace como **punto de
partida**, marcando el estado que ya estaba verificado, para tener de dónde comparar.

## Lo que esto NO cambia

- **El motor**, ni una línea: la versión es una propiedad del **repositorio**, como el
  número de antigüedad de los labs (ADR 0016). Por eso el check vive en el wrapper `./lab`
  y no en la herramienta de checks del motor, que sigue sin saber en qué repositorio está.
- Los **verbos** ni la declaración de ningún lab: `./lab` sigue siendo el único punto de
  entrada y no aparece ningún verbo nuevo de despliegue.
- Los **diarios**: no se versiona nada de `labs/*/logs/`.

## Cómo se comprueba

- **`./lab check version`** es el check, y corre también dentro de `./lab check` (todo).
  Falla si: `VERSION` no es `MAYOR.MENOR.PARCHE`; el CHANGELOG no tiene su entrada; la
  entrada de `VERSION` no está; o el último tag `vX.Y.Z` no coincide con `VERSION` (es
  decir, se publicó el tag y no se subió el fichero, o al revés). Se ha visto fallar con
  las cuatro roturas, a propósito.
- **`./lab version`** dice en una línea qué versión es la publicada y cuál es el último tag.
- Los PR #1 y #2 de la historia del repositorio son el primer uso del método: rama corta,
  checks en verde, PR con el porqué, *squash* a `main`, tag `v0.1.0` y su *release*.
