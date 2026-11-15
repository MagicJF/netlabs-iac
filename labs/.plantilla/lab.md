<!-- PROPÓSITO:   el documento del lab. Dos regiones, dos escritores.
     INVARIANTES: la región generada (entre los marcadores) la reescribe
                  `./lab check docs --actualizar`; `./lab check docs` falla si el
                  fichero difiere de su render. La prosa de fuera NO la toca
                  ningún check: escribe lo que el YAML no puede decir.
     LÍMITES:     la prosa no repite valores que ya están en la tabla; los cita.
     VER:         AGENTS.md §Documentación; README.md §Documentación;
                  docs/crear-un-lab.md (la guía de campo: las decisiones, en orden) -->

# <NOMBRE>

Plantilla de documento. Sustituye este párrafo por qué topología es ésta, para qué
sirve y qué la hace distinta.

<!-- generado:inicio -->
<!-- generado:fin -->

## Por qué así

Qué topología es y por qué ésta y no otra: qué se quiere poder demostrar con ella.

## Qué se rompió (y cómo se arregló)

Lo que falló al desplegarla de verdad, y qué se hizo. Es lo que más vale del
documento: nadie más va a tropezar donde tú tropezaste (*filing back*).

## Qué está verificado, y qué no

Qué se comprobó y con qué salida; y qué no se puede comprobar todavía, dicho en
claro en vez de maquillado.

## Qué queda fuera

Los límites, y lo que este lab NO decide (porque es de otro lab, del motor o del
entorno).
