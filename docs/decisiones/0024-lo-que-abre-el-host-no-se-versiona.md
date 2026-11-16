# 0024 — Lo que abre el HOST no se versiona

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: QUÉ credenciales pueden estar en un
repositorio público, y con qué se vigila*

## El problema

El repositorio es **público**, y el motor necesita credenciales de dos clases que no se parecen en
nada: las de los **labs** (los CHR y los LXC que despliega, de un banco de pruebas) y las del
**nodo** (el token de la API, que equivale a root y no caduca). Las primeras ya se citaban en claro
en los documentos de los labs; las segundas no pueden estar ahí, porque son el host entero.

Hasta hoy esa frontera la sostenía un `.gitignore` y la disciplina. Un `.gitignore` no es una
política: `git add -f` lo salta. Una auditoría de todo el historial (commits, ramas y tags) salió
limpia, pero eso es un resultado, no una garantía.

## La decisión

**1. La política es explícita y ASIMÉTRICA.** Las credenciales de los labs son de sandbox, y lo que
abre el NODO no entra jamás en lo versionado: ni el token, ni una contraseña, ni una clave privada,
ni un ticket de sesión.

> **Corrección (16-nov-2026, al añadir el CI del informe §6.5).** «Se citan en claro en sus
> documentos» dejó de ser cierto, y con razón: la región generada de un lab citaba el VALOR de
> `routeros_clave` leyéndolo de `secrets.yml`, y eso hacía que **no fuera función de la
> declaración** — en un clon sin credenciales (el CI) rendía otra cosa, `./lab check docs` no
> podía pasar nunca, y el `.md` publicado llevaba la contraseña dentro. Ahora la tabla de acceso
> cita la credencial **por su origen** (`secrets.yml` → `routeros_clave`), nunca por su valor. La
> asimetría sigue: un secreto de LAB citado a mano en la prosa de un lab no se bloquea; lo que no
> entra es un valor en la región generada.

**2. Se vigila con un CHECK, no con un `.gitignore`.** `./lab check secretos` busca las cuatro
formas que dan acceso al host —el token de la API con su valor, un ticket de sesión, una clave
privada y el propio `secrets.yml`— más las tres claves del host que no pueden llevar valor en un
fichero versionado. **No** busca contraseñas en general: bloquearía la prosa de los labs, que es
legítima, y una regla que cierra lo que no debe no protege de lo que sí.

**3. El candado BLOQUEA, y mira el ÍNDICE.** En el hook de pre-commit corre en modo `--staged`: lo
que se juzga es lo que va a entrar en el commit, no el árbol de trabajo, así que corregir el
fichero después de `git add` no lo cuela. Bloquear es lo coherente con la casa: un ticket en un
fichero es un hecho mecánico, como que la región generada de un documento no cuadre.

**4. El valor no se imprime.** Un check de secretos que escupe el secreto en el diario de un hook
lo deja en el diario. Dice fichero, línea y qué forma; nunca el contenido.

## La trampa: el candado no juzga el pasado ni adivina

`git` no reescribe el historial por un hook, y un secreto de formato desconocido (el token de otro
sistema, una contraseña suelta) no lo detecta una lista. El candado cubre lo que este motor de
verdad usa; la auditoría del historial se hace a mano cuando toca. No es un escáner de entropía y
no pretende serlo.

## Qué NO se toca

Las credenciales de los labs en sus documentos, ni el `.gitignore`. Esto no sustituye al
`.gitignore`: lo respalda. Y no se versiona ningún fichero de ejemplo con valores rellenos: la
plantilla vive en el README, con huecos.

## Cómo se comprueba

- `./lab check secretos` sobre el repositorio: en verde, con los 126 ficheros versionados.
- `test/test_secretos.py`: trece casos — caza las cuatro formas y las tres claves con valor, y deja
  pasar los huecos (`<...>`, `{{ ... }}`), la contraseña de un lab y la palabra «ticket» en prosa.
  Los casos del modo `--staged` corren contra un repositorio git desechable, no contra el de uno.
- El propio fichero del check arma sus patrones por piezas, así que no se cae a sí mismo.

## VER

`deployment_engine/tools/framework_check.py` §`check_secretos`; `.githooks/pre-commit` (paso 2);
`test/test_secretos.py`; `README.md` §Las credenciales.
