# Diario del proyecto ATUS

Registro continuo de cada problema encontrado al construir el pipeline y el tablero, y cómo se resolvió.

**Formato:** cada entrada cuenta qué pasó, por qué, cómo se corrigió y cómo se comprobó. Algunas siguen abiertas y lo dicen en el texto.

**Regla de mantenimiento:** todo problema nuevo encontrado durante el desarrollo recibe una entrada aquí antes de considerar terminada la tarea. Cuando una entrada abierta se resuelve, se actualiza en el mismo lugar en vez de agregar un duplicado.

---

## Problemas de los datos crudos (01–05, 09–11)

El DBF de 2020 ocupa 215 MB para 150,886 registros, mientras que el CSV con los mismos datos ocupa 24 MB. La causa es que `ID`, `CALLE1`, `CALLE2` y `CARRETERA` están declarados como campos de texto de 254 caracteres, lo que añade 1,016 bytes de relleno por registro, cerca del 68% del archivo. El diccionario de datos habla de 570 caracteres, pero dBase llega a 254, así que el DBF trunca en silencio. La solución fue ingerir desde el CSV y dejar el DBF para las lecturas con software GIS. La cabecera del DBF lo confirma: 150,886 registros de 1,496 bytes y cuatro campos de 254 caracteres.

Leer el CSV como UTF-8 corrompe cada acento porque los archivos están codificados en Windows-1252 / ISO-8859-1. Abrirlos con `encoding="latin-1"` resuelve el problema: los `.cpg` auxiliares ya indican la página de códigos `1252`. `CALLE MELQUÍADES MORENO` se decodifica correctamente con `latin-1`.

El archivo de 2021 contiene 31 apariciones del byte `0x8D`, que Windows-1252 deja indefinido, así que `cp1252` lanza `UnicodeDecodeError: byte 0x8d` al contar filas. Leer con `latin-1` mapea todos los bytes y permite reparar el texto por campo después (ver la entrada siguiente). El conteo completo de los seis años terminó correctamente.

Algunas filas de 2021–2024 contienen secuencias UTF-8 dentro de un archivo mayormente Latin-1, y los nombres aparecen como `SERAFIN PEÃ‘A`, `OCEANO Ã\x8dNDICO` o `PASEO DE LOS Ã‘ANDÃš`. La causa es que INEGI mezcló codificaciones: la mayoría de las filas son Latin-1 y algunas traen UTF-8 (`C3 91` = `Ñ`, `C3 8D` = `Í`). Se agregó `_text()`, que decodifica como Latin-1 preservando cada byte, vuelve a codificar y prueba UTF-8, luego CP1252, y como último recurso CP1252 con reemplazo. Las pruebas byte a byte convierten `b"SERAFIN PE\xc3\x91A"` en `SERAFIN PEÑA` y `b"OCEANO \xc3\x8dNDICO"` en `OCEANO ÍNDICO`, mientras que `MARÍN` queda intacto.

Confiar en el `.cpg` de 2024 habría decodificado mal el CSV: ese archivo describe la codificación del DBF/Shapefile, mientras que el CSV exportado usa Latin-1 y contiene bytes altos. Se ignoró el auxiliar, se verificaron los bytes reales y se mantuvo Latin-1 con reparación. Una muestra de 400 KB por archivo confirma que los seis CSV fallan la validación estricta de UTF-8.

Los valores de `ID` se repiten entre años y desde 2021 usan cadenas compuestas como `1009255-112-190821532`. Es un número de registro por archivo; la clave nacional se construye aparte. Se expone `record_key` como `ANIO-EDO-MPIO-ID` y se usa siempre la clave compuesta. La clave `2024-1-1-1170966-999-0` es única en el conjunto fusionado.

`HORA=99`, `MINUTOS=99`, `DIA=0/32`, `DIASEMANA=8`, `ALIENTO=6`, `CINTURON=9` y `EDAD=0/99` significan "desconocido". INEGI los codifica como números, así que tratarlos como valores reales contamina promedios y filtros. `_occurred_at()` valida rangos y devuelve `null` para fechas imposibles, y la interfaz muestra `—` en los campos faltantes. El mapa completo está en el diccionario de datos; un registro de 2024 con `HORA=2, MINUTOS=25` produce `2024-01-01T02:25`, y las combinaciones inválidas devuelven `null`.

Unir por `ID` desalinea los registros: el registro #1 del shapefile es la fila 0 del CSV aunque su `ID` sea 3, porque el número del shapefile es secuencial y `ID` es el número de origen, con huecos posibles. Al verificar conviene comparar por posición de fila; para el análisis, el CSV ya trae `LONGITUD` y `LATITUD` y el shapefile resulta innecesario. Los primeros tres puntos del shapefile coinciden con las primeras tres filas del CSV (`-102.29424, 21.89788`, …).

## Pipeline de Limpieza y Transformación

Una vez teniendo los datos legibles de forma individual, consideramos que sería bueno poner centralizarlos todos en una sola base de datos para agilizar el posterior procesamiento.

Para comenzar, tuvimos que encontrar los archivos de cada año, que llegaban con profundidades de carpeta y nombres distintos: 2019 y 2021 anidaban un nivel extra `ATUS_<year>/`, 2024 usaba guiones bajos y el resto espacios, y desde 2022 aparecía una columna `OID`. Resolvimos el descubrimiento con `data/raw/atus_*_shp/**/*.csv` y una expresión regular que extrae el año, y `csv.DictReader` absorbió la columna `OID`. Así encontramos exactamente 6 archivos y los conteos por año coincidieron con `wc -l`.

Al leerlos, `pandas` advirtió `DtypeWarning: Columns (0: ID) have mixed types` porque algunos años guardan `ID` como número y otros como cadena compuesta. Leímos siempre `ID` como texto (`dtype={"ID": "string"}`), y las claves quedaron intactas.

Con los archivos ya legibles, el siguiente paso fue unir el CSV anual con el shapefile. Los dos productos describen los mismos eventos con cobertura distinta: el CSV anual es el microdato completo (1997–2025, 46 columnas, 10,999,723 filas, 1,419–1,517 municipios, solo atributos, etiquetas en vez de códigos, `NEMUERTO`/`NEHERIDO`, `ESTATUS`), mientras que el shapefile es el subconjunto georreferenciado (2019–2024, 91–198 municipios, códigos numéricos, coordenadas y nombres de calle, `TOTMUERTOS`/`TOTHERIDOS`). La unión por `(año, CVEGEO, mes, día, hora, minuto, tipo, 10 conteos de víctimas)` coincidió con el 100% de las filas del shapefile para 2019 y 2023 en Aguascalientes (`2,681/2,681`, `2,948/2,948`) y Monterrey (`30,944/30,944`, `33,568/33,568`). 2024 coincidió al 99.3% en Aguascalientes (`3,054/3,074`; el resto son "Cifras Corregidas") y al 100% en Monterrey; el archivo anual también trae registros extra del mismo municipio que llegan solo con atributos (3,213 vs 3,074). La decisión fue tratar el CSV anual como tabla de hechos y el shapefile como enriquecimiento de ubicación, unidos por una tabla de enlace. La coincidencia relajada quedó pendiente.

La primera consulta de unión falló con `Table "g" does not have a column named "latitude"` porque `_geo_keys` solo llevaba las columnas de la clave y `rowid`, mientras la consulta siguiente pedía `g.latitude`, `g.longitude` y las columnas de calle. Unimos `_geo_raw` de vuelta por `rowid = geo_rowid` para traer la ubicación. Se procesaron las 1,317,810 filas del shapefile y 1,315,016 coincidieron.

Con la unión resuelta, la inserción masiva se volvió el cuello de botella: una prueba de 10,000 filas tardó 6.66 s y, extrapolada a 11 millones, habría llevado horas, porque `executemany` paga la sobrecarga de ejecución por fila. Agrupamos 50,000 filas en un DataFrame de pandas con tipos anulables y usamos `append` de DuckDB; el mismo `append` de 10,000 filas tardó 0.05 s y la construcción completa terminó en 5m27s.

Quedó un último desajuste entre revisiones: 2,380 de 199,224 filas del shapefile de 2021 (1.2%) corresponden a otra revisión del archivo anual, mientras que otros años coinciden al 99.9–100%. El producto georreferenciado de 2021 se construyó a partir de una versión anterior: en las muestras, el archivo anual tiene el mismo día pero una hora desplazada (`03:00` vs `03:10`), o el registro aparece con otra hora. Mantuvimos solo la coincidencia exacta; esas filas del shapefile aportan ubicación cuando hay coincidencia y el registro anual conserva sus atributos. Cada fila proviene de un registro real y la tabla de hechos conserva todos los registros. Una coincidencia relajada (mismo día y tipo, ignorar hora) podría recuperar parte del hueco, con riesgo de falsos positivos. Las tasas por año son 2019: 99.98%, 2020: 99.95%, 2021: 98.81%, 2022: 100.00%, 2023: 100.00%, 2024: 99.89%.

## 21 · Los totales año contra año están confundidos por la cobertura municipal creciente
Los accidentes suben de 180,219 (2019) a 273,822 (2024), lo que se lee como un empeoramiento. La cobertura crece al mismo tiempo: el producto georreferenciado cubre 29 estados / 91 municipios en 2019, 31 / 169 en 2021 y 32 / 198 desde 2023, y los municipios que entran inflan los totales. Sigue abierto; la API expone sumas anuales crudas y el contexto de cobertura queda pendiente. La corrección propuesta es etiquetar cada año con su número de municipios y calcular tendencias sobre la intersección de municipios presentes en ambos años.

## 23 · Estructura del proyecto: entradas crudas movidas a `data/raw/`, salidas a `data/curated/`
Se creó `data/raw/` y se movió ahí cada entrada de INEGI: las seis carpetas `atus_20xx_shp/`, `conjunto_de_datos_atus_anual_csv/`, los siete ZIP y `ATUS_1.xlsx` (unos 5.1 GB). `data/curated/` quedó para las tablas limpias. La separación permite borrar y reconstruir lo curado con los archivos fuente protegidos. `server/app.py` usa `DATA_DIR = ROOT / "data" / "raw"`, y la interfaz se verificó con la nueva estructura. `data/` contiene solo `raw/` y `curated/`; `/api/health` sigue informando 6 fuentes y 1,317,810 filas, y `/api/years`, `/api/accidents/first?year=2024` y `/api/heatmap?year=2024` devuelven los mismos resultados.

## 29 · DBSCAN fusionó una ciudad entera en un solo punto crítico
La primera ejecución de clustering produjo un solo grupo de Monterrey con 126,679 choques — la ciudad completa, una escala que desborda cualquier intervención. DBSCAN encadena celdas densas contiguas, así que en una ciudad densa camina de intersección en intersección. Se reemplazó por puntos críticos codiciosos, separados entre sí: ordenar las celdas por severidad, elegir un centro, asignar todas las celdas dentro de 300 m, suprimir otros centros candidatos dentro de 600 m y limitar a 200 puntos. Los 200 puntos suman 126,598 choques, 321 muertes y 8,279 heridos; cada uno es una intersección o un corredor corto.

## 30 · El ranking de prioridades estaba dominado por el volumen de choques
Un corredor con 2,852 choques y 4 muertes superaba a un punto crítico con 14 muertes porque el puntaje sumaba choques crudos (`deaths*10 + injured*2 + crashes`), y el volumen pesaba más que la letalidad. Ahora se ordena por muertes, luego heridos, luego choques; `priority_score` quedó como `deaths*10 + injured*2` y solo se usa para mostrar. Las 10 prioridades principales quedaron ordenadas por muertes (14, 14, 11, 8, 7, 7, 6, 5, 5, 5).

## 31 · El modelo de severidad falló en los subconjuntos de peatones y motocicletas
El modelo lanzó `Found input variables with inconsistent numbers of samples` e `Input X contains NaN` porque filtrar el marco conservaba un índice repetido y `pd.concat` expandía el marco de características, mientras los valores categóricos faltantes producían NaN. Se aplicó `reset_index(drop=True)` al inicio de `build_features` y `fillna(0.0)` al final. Los tres modelos ajustan; el AUC de prueba es 0.830 para todos, 0.713 para peatones y 0.747 para motocicletas.

## 32 · "Hora desconocida" parecía un factor de riesgo importante
La hora faltante tenía una razón de momios de 10.17, la tercera asociación más fuerte, pero es un artefacto de reporte: los choques fatales tienen más probabilidad de tener datos de hora incompletos. La columna `quality_flag` marca esas categorías y la API oculta las filas marcadas por defecto. Las asociaciones principales quedaron sustantivas: choque con tren (15.0), peatón (14.4), ciclista (8.4) y volcadura (6.4).

## 33 · Todas las prioridades tenían la misma confianza "alta"
Los 200 puntos críticos estaban marcados con confianza alta porque la etiqueta se basaba en el conteo de choques, y cada punto tenía al menos 144. La confianza ahora refleja las muertes: 5 o más es alta, 2–4 media y 0–1 baja. El resultado es 12 alta, 69 media y 119 baja.

## 34 · Se agregaron la capa de análisis y la página Prioridades
Se agregaron `analytics_hotspots`, `analytics_hotspot_profile`, `analytics_severity` y `analytics_priorities`, una exportación CSV, cuatro endpoints de API y una página Prioridades con filtros, mapa, tarjetas ordenadas y factores de riesgo. La validación dejó 200 puntos críticos en 14 estados, cada uno presente en 5–6 de los 6 años, con 126,598 choques, 321 muertes y 8,279 heridos; el servidor los devuelve y la página se dibuja. La fase 2 incluye sensibilidad al radio, denominadores de población y evaluación antes/después.

## 35 · El CSV de prioridades no tenía una vista propia
`priorities_top100.csv` vivía solo como archivo para llevar a la reunión, sin pantalla que lo mostrara tal cual. Se agregó `/report`, una página estilo Power BI que lee el CSV mediante el nuevo endpoint `/api/priorities/export` y lo presenta como un reporte: segmentadores de estado, tipo y confianza, cinco tarjetas KPI, barras de muertes por estado, mapa sincronizado con la tabla y una tabla detallada con barras de datos y ordenamiento por columna. El CSV se parsea en el cliente con un lector que respeta comillas y comas internas, porque el campo `place` trae nombres con comas y el `primary_action` contiene frases con puntuación. La validación con Chrome headless confirmó 100 registros, 279 muertes, 5,445 heridos y 70,287 choques, y el endpoint responde 200 con `text/csv`.

---

## Consultas Analíticas y Agregaciones

Tras haber combinado todas las tablas, nos quedamos con un gran total de 10,999,723 registros, de los cuales 1,315,016 contaban con coordenadas, por lo que estos los podíamos usar para perfilar detalles concretos de los accidentes.

Nos dimos cuenta de que los choques se concentran en unas pocas esquinas y corredores: la mayoría de las celdas acumula pocos casos y un grupo pequeño concentra cientos. Por eso agrupamos los choques en una cuadrícula de 0.001° (unos 110 m por celda en México). El tamaño sale de la precisión del dato: cada choque se guarda en la dirección o intersección reportada, con un margen de decenas de metros, así que 110 m unen los registros de una misma esquina. Una cuadrícula de 0.0001° (unos 11 m) dividiría una intersección en varias celdas y dejaría muchas celdas con un solo choque; una de 0.01° (unos 1.1 km) mezclaría calles distintas. El resultado fueron 242,115 celdas.

Tras ello, construimos puntos críticos de 300 m de radio, separados al menos 600 m entre sí, con un máximo de 200. Elegimos 300 m porque cubren una intersección y sus accesos, que es el área que un proyecto de cruce, semáforo o isla puede cambiar; 600 m de separación evitan que dos puntos generen proyectos traslapados en la misma esquina. El límite de 200 es operativo: es el largo de una lista que un presupuesto puede revisar, y los sitios más allá del 200 son menos severos. Antes probamos DBSCAN, pero el agrupamiento por densidad encadena manzanas contiguas y produjo un solo grupo de Monterrey con 126,679 choques, una escala que desborda cualquier intervención. La selección codiciosa evita eso: ordena las celdas por severidad, toma la peor, reclama todas las celdas dentro de 300 m y salta cualquier otro centro candidato dentro de 600 m.

Posteriormente, puntuamos las celdas dando mayor peso a las muertes. Decidimos puntuarlas con `deaths*10 + injured*2 + crashes`, porque el objetivo es reducir muertes y una muerte pesa más que un choque con daños materiales. Los pesos son un juicio de valor: una muerte equivale a 10 unidades, un herido a 2 y un choque a 1. Con ellos, una esquina con muchas lesiones graves sigue compitiendo aunque tenga menos muertes, y el peso relativo se puede cambiar en una línea si la política prioriza otra cosa. Este puntaje solo decide qué celdas se vuelven centros; el orden final de la lista usa primero las muertes.

Tras esto, tomamos la decisión de conservar solo los puntos críticos persistentes porque un pico de un año puede ser un desvío por obra, un festival o un error de datos. Los definimos como aquellos presentes en al menos 3 de los 6 años y con al menos 10 choques: tres años cubren la mitad del periodo y descartan rachas aisladas, y diez choques evitan que un punto con dos o tres casos entre a la lista. Los 200 puntos conservados aparecen en 5 o 6 años.

Con los puntos críticos, perfilamos cada uno de acuerdo al tipo de choque dominante, la proporción de peatones, ciclistas y motocicletas, la proporción nocturna y de fin de semana, la superficie de rodamiento y los nombres de calle más comunes. El número de choques deja abierta la elección de la intervención; el perfil la concreta: un punto de peatones pide cruces y velocidades más bajas, uno de motocicletas pide separación y vigilancia, y uno de salida del camino pide acotamientos.

La coordenada es una dirección geocodificada (unos 50 m) y el punto es un círculo, así que el segmento de vía completo queda para el estudio de detalle. Solo 2019–2024 tiene coordenadas, y solo los 91–198 municipios del producto georreferenciado.

### Qué hace letal un choque

Una tabla simple de tasas de letalidad por tipo de choque engaña: los choques de peatones pueden ocurrir más de noche, en calles distintas o con conductores mayores. Para separar esos efectos usamos una regresión logística con desenlace fatal (`severity_code = 1`) frente al resto. Un resultado binario es estable y responde la pregunta de política: ¿murió alguien? La regresión estima cuánto multiplica cada factor los momios de un desenlace fatal cuando los demás se mantienen fijos; ese multiplicador es la razón de momios que se muestra en el tablero. Una regresión lineal predeciría probabilidades fuera del rango de 0 a 1.

Una razón de momios de 14.4 para peatones significa que, entre dos choques por lo demás similares, los momios de que el de peatón sea fatal son 14.4 veces los de un choque vehículo–vehículo. El intervalo del 95% (13.98 a 14.72) es el rango compatible con los datos; como todo el rango supera 1, la asociación difícilmente sea azar.

Conservamos todos los choques fatales y solo el 5% de los demás. Hay 11 millones de filas y los fatales son alrededor del 1.1%; cargar todo es lento y aporta poco. El 5% se elige con un hash del ID del accidente, así que las mismas filas se seleccionan en cada ejecución, y deja unos 627,000 registros: suficientes para estimar razones de momios estables sin procesar 11 millones. Este es un diseño de casos y controles: elegir registros por el resultado distorsiona la tasa global de muertes y conserva la comparación entre fatales y no fatales. Por eso reportamos razones de momios y dejamos fuera las probabilidades predichas.

Entrenamos con 2023 y antes y probamos con 2024, que el modelo ve por primera vez. El conjunto apartado comprueba si el patrón sigue vigente; la medida es AUC. Un AUC de 0.830 significa que, al elegir al azar un choque fatal y otro de los demás, el modelo clasifica el fatal como más riesgoso el 83% de las veces. Una moneda al aire da 0.5; 0.83 es útil y deja margen de error.

Usamos modelos separados para peatones y motocicletas porque sus mecanismos difieren (velocidad, edad del conductor, visibilidad, diseño del cruce) y el modelo general oculta esas diferencias. El modelo de peatones tiene un AUC más bajo (0.713), lo cual es esperable: los choques de peatones se parecen más entre sí, así que hay menos que separar.

Las características son tipo de choque, zona urbana/suburbana, superficie de rodamiento, alcohol, cinturón, hora, día de la semana, banda de edad del conductor, vehículos pesados y múltiples vehículos. Elegimos condiciones que un planificador puede cambiar o diseñar; el municipio queda para el análisis geográfico, los conteos de víctimas son parte del resultado y el año escapa al control de la política. Una hora faltante parece un factor de riesgo fuerte (razón de momios 10.2), pero es un artefacto de reporte: los choques fatales tienen más datos de hora incompletos. La categoría se conserva para preservar las demás estimaciones, se marca con `quality_flag` y el tablero la oculta.

El modelo muestra asociaciones. Velocidad, iluminación, volumen de tránsito y geometría de la vía son variables ausentes que pueden explicar parte de ellas.

### Qué conviene corregir primero

Un mapa con 200 círculos es el insumo; el plan requiere elegir una lista corta y saber qué hacer en cada lugar. Usamos reglas escritas a mano porque un modelo puede ordenar el riesgo y la elección de la intervención requiere juicio de ingeniería. Las reglas son explícitas y viven en una sola función, así que cualquiera puede rastrear qué disparó una recomendación: proporción de peatones → cruces, islas de refugio, iluminación y menor velocidad; proporción de ciclistas → carriles protegidos; proporción de motocicletas → separación de carriles y vigilancia; rural, no pavimentado o salida del camino → acotamientos y señales; vehículo–vehículo → semáforos y carriles de vuelta. Los umbrales (25% peatones, 15% ciclistas, 30% motocicletas) son heurísticas de partida: marcan cuándo un grupo domina el perfil y quedan sujetos a revisión de ingeniería; el perfil se muestra junto a la recomendación para que un ingeniero pueda estar en desacuerdo.

La acción principal se elige por la primera condición que se cumple, en este orden: si los peatones son al menos 25% de los choques, la recomendación es de cruces, islas de refugio, iluminación y reducción de velocidad; si los ciclistas llegan al 15%, carril protegido y rediseño de intersecciones; si las motocicletas alcanzan el 30%, separación de carriles, control de velocidad y uso de casco; si la zona suburbana supera el 40%, el suelo no pavimentado llega al 20% o el tipo dominante es salida del camino (7), acotamiento, señales preventivas y barreras; si el tipo dominante es colisión con vehículo (1), semáforos, carriles de vuelta y control de velocidad; y en cualquier otro caso, una revisión de ingeniería de detalle en el sitio. El orden va de lo más específico a lo más general: una proporción alta de usuarios vulnerables define mejor la intervención que el tipo de vía, así que se evalúa primero. Las acciones secundarias se suman de forma independiente: operativos nocturnos y control de alcohol cuando el alcohol supera el 8% y la noche el 30%; mejora de iluminación y visibilidad cuando la noche supera el 40%; revisión de cruces peatonales cuando los peatones están entre 15% y 25%; y revisión del espacio para bicicletas cuando los ciclistas están entre 10% y 15%. Los rangos superiores evitan repetir como secundaria una acción que ya salió como principal, y las secundarias se unen con punto y coma; si el perfil activa alguna, se agrega, y en caso contrario el campo queda vacío.

Ordenamos por muertes, luego heridos, luego choques. El objetivo son las muertes; un puntaje que incluye el volumen de choques deja que un corredor con 2,852 choques y 4 muertes supere a un punto crítico con 14 muertes. Una muerte pesa más que un parachoques dañado, y la elección se declara abiertamente en lugar de esconderse en una fórmula.

La confianza aquí significa fuerza del caso. Los conteos de choques son grandes en todos los puntos (144 o más), así que una etiqueta basada en choques marcaría todos los sitios como altos. Las muertes los separan: 5 o más es alta, 2–4 media y 0–1 baja. El resultado es 12 alta, 69 media y 119 baja.

Exportamos un CSV porque los tableros son para explorar y los presupuestos se deciden en reuniones y hojas de cálculo. Las primeras 100 filas se escriben en `data/curated/priorities_top100.csv` para que la lista salga del tablero y llegue a la reunión.

Las reglas son un punto de partida: costo, factibilidad y restricciones de construcción quedan para la visita de campo.

### Cómo encajan

```
dónde  → 200 ubicaciones críticas
riesgo → qué condiciones elevan el riesgo de muerte
qué    → lista ordenada con una acción y una etiqueta de confianza
```

Las tres consultas se ejecutan en orden y cada una imprime un resumen.

### Glosario en lenguaje sencillo

- **Punto crítico (hotspot):** un círculo de 300 m alrededor de un lugar donde los choques se repiten.
- **Razón de momios (OR):** cuánto multiplica una condición los momios de un resultado fatal en comparación con una categoría de referencia. Por encima de 1 significa más riesgo; por debajo de 1, menos.
- **Intervalo del 95%:** el rango de valores compatible con los datos. Si excluye el 1, la asociación difícilmente sea azar.
- **AUC:** qué tan a menudo el modelo clasifica un choque fatal al azar por encima de uno no fatal al azar. 0.5 es azar; 1.0 es perfecto.
- **Muestra de casos y controles:** conservar todos los casos (fatales) y una muestra de controles (no fatales). Sirve para razones de momios; la frecuencia del resultado requiere otra muestra.
- **Categoría de referencia:** la base contra la que se compara una variable dummy. Para el tipo de choque es "colisión con vehículo automotor"; para el cinturón es "Sí".

---

## Decisiones anteriores

**Guardar los datos limpios en DuckDB.**
La API responde agregaciones sobre 11 millones de filas. Leer los CSV tardaba unos 6 segundos por petición; DuckDB responde en milisegundos. Postgres también funcionaría, pero agrega un servidor que instalar, operar y respaldar. DuckDB es un solo archivo, está hecho para agregación columnar y la API lo puede abrir en solo lectura. Si varias personas llegan a necesitar escribir al mismo tiempo, Postgres es el siguiente paso.

**Usar scripts numerados.**
Los notebooks son buenos para explorar, pero las celdas pueden ejecutarse fuera de orden y el resultado depende de lo que corrió antes. Los scripts son reproducibles, revisables en git, ejecutables desde cron y testeables. El pipeline es un paso de construcción; los notebooks sirven para explorar.

**Hacer del CSV anual la tabla de hechos y del shapefile la capa de ubicación.**
El archivo anual tiene 11 millones de registros con atributos; las coordenadas viven en el shapefile. El shapefile tiene coordenadas para 1.3 millones. Concatenarlos contaría el mismo choque dos veces. En cambio, una fila por registro anual, con coordenadas adjuntas cuando existe una coincidencia. Los registros con coordenadas ausentes se quedan en la tabla.

**Unir por una clave compuesta.**
Cada producto trae su propio identificador. La clave es año, municipio, mes, día, hora, minuto, tipo de choque y los diez conteos de víctimas. Dos choques pueden compartir todo eso, así que cada lado recibe un contador dentro de su grupo de clave y la unión usa clave más contador. El contador evita que las claves duplicadas multipliquen filas.

**Usar un hash md5 como ID del accidente.**
El ID de la fuente cambia entre archivos, y un número autoincremental cambiaría con cada entrada nueva. Un hash de la fila normalizada se mantiene igual entre reconstrucciones. Las filas exactamente duplicadas reciben un sufijo de contador para que el ID siga siendo único.

**Convertir los códigos centinela en NULL.**
INEGI usa `99` para una hora desconocida y `32` para un día desconocido. Tratados como números, arrastrarían promedios y romperían los filtros de tiempo. NULL significa "desconocido" y las agregaciones lo ignoran, que es el comportamiento correcto.

**Abrir una conexión DuckDB de solo lectura por petición.**
FastAPI ejecuta los endpoints síncronos en un grupo de hilos, y DuckDB recomienda una conexión por hilo. Abrir una conexión de solo lectura es barato y evita bloqueos. Los scripts de escritura corren por separado, mientras la API atiende solo lecturas.

**Separar `data/raw` de `data/curated`.**
Los archivos crudos son la fuente de verdad y se abren en modo de solo lectura. La base curada es desechable: borrarla y volver a ejecutar los scripts 01–03 la reproduce. Mantenerlas separadas hace que eso sea seguro.

---

## Retrospectiva de la fusión de datos — CSV anual + shapefile

Objetivo: una tabla con todos los choques, más coordenadas donde existan.
Entradas: 10,999,723 registros anuales, 1,317,810 registros georreferenciados.

| Desafío | Qué pasó | Cómo se resolvió |
|---|---|---|
| Identificadores distintos | El archivo anual identifica registros por su contenido; el `ID` del shapefile pertenece solo a ese producto. | Se construyó una clave compuesta: `year + CVEGEO + month + day + hour + minute + type + 10 victim counts`. |
| Claves duplicadas | Dos choques distintos pueden compartir lugar, minuto, tipo y conteos de víctimas. | Se agregó `row_number()` dentro de cada grupo de clave en ambos lados y se unió por clave + ordinal. |
| Sistemas de códigos distintos | El anual usa etiquetas en español (`"Fatal"`, `"Colisión con motocicleta"`); el shapefile usa números (`1`, `10`). | Mapas explícitos de etiqueta→código en `01_normalize_data.py`. Los códigos del shapefile se usan tal cual. |
| Claves de ubicación distintas | El anual identifica un lugar con `CVEGEO` (`01001`); el shapefile con `EDO` + `MPIO` (`1`, `1`). | Se construyó `CVEGEO` con ceros a la izquierda desde ambos lados antes de unir. |
| Codificaciones distintas | El anual es UTF-8 y está limpio. El shapefile es Latin-1 con fragmentos UTF-8 mezclados. | `utf-8-sig` para el anual; Latin-1 más reparación UTF-8/CP1252 por campo para el shapefile. |
| Columnas de víctimas distintas | El anual desglosa las víctimas por categoría (`NEMUERTO`/`NEHERIDO`); el shapefile trae totales (`TOTMUERTOS`/`TOTHERIDOS`). | Se unió solo por los 10 conteos de categoría compartidos. Los totales se calculan a partir de las categorías en la tabla de hechos. |
| Cobertura muy distinta | El anual cubre 1,419–1,517 municipios; el shapefile cubre 91–198. | El anual es la tabla de hechos. El shapefile solo agrega ubicación. Todas las filas anuales se conservan. |
| Riesgo de doble conteo | El mismo choque existe en ambos productos. Concatenarlos lo contaría dos veces. | Mantener los dos productos en tablas separadas. Una fila por registro anual; las columnas de ubicación son anulables. |
| Revisiones de datos distintas | Las horas del shapefile de 2021 difieren del archivo anual; 2024 tiene cifras corregidas; 2025 llega hasta el CSV anual. | Solo coincidencia exacta. Cada fila conserva su estado: `has_location = true` con ubicación y `false` en los demás casos. |
| Valores centinela | `99`, `32`, `0` significan "desconocido" en distintas columnas. | Se normalizaron a NULL en ambos lados. La unión usa `COALESCE(..., -1)` para que los NULL también coincidan. |
| Identidad estable del hecho | La tabla necesitaba una clave que sobreviviera a una reconstrucción. | `accident_id` = md5 de la fila normalizada completa más un contador de duplicados. |
| Inserciones lentas | `executemany` tardaba 6.66 s para 10,000 filas. | Lotes de 50,000 filas en pandas con `append` de DuckDB. La construcción completa tardó 5m27s. |
| Columnas faltantes en el bug de unión | La consulta de unión pedía `latitude` de una tabla que solo tenía claves y fallaba. | Se unió `_geo_raw` de vuelta por `rowid`. |

**Resultado:** 1,315,016 de 1,317,810 filas del shapefile coincidieron (99.79%). La tabla de hechos conserva los 10,999,723 registros anuales; 1,315,016 tienen coordenadas.

**Estado actual:** 2,794 filas del shapefile quedan pendientes de coincidencia (principalmente la revisión de 2021 y las correcciones de 2024); 1997–2018 corresponde a años previos al producto georreferenciado.

---

## Comandos de verificación usados

```bash
# construir la base curada
python3 scripts/01_normalize_data.py
python3 scripts/02_match_locations.py
python3 scripts/03_build_aggregates.py

# servidor
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8010
curl -s localhost:8010/api/health | python3 -m json.tool
curl -s "localhost:8010/api/heatmap?year=2024" | python3 -m json.tool
curl -s "localhost:8010/api/temporal?year=2019" | python3 -m json.tool

# sintaxis
python3 -m py_compile server/app.py
node --check web/app.js

# visual
google-chrome --headless=new --disable-gpu --no-sandbox \
  --window-size=1440,900 --virtual-time-budget=15000 \
  --screenshot=shot.png "http://127.0.0.1:8010/heatmap?year=2024"
```
