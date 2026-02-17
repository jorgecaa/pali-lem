 📚 Pali Glosser - Digital Pali Dictionary

Una aplicación Streamlit que analiza textos en Pali proporcionando información morfológica detallada usando la base de datos del **Digital Pali Dictionary (DPD)** localmente.

## Características

- **Interfaz Minimalista Mobile-First**: Diseño limpio, simple y optimizado para smartphone
- **Digital Pali Dictionary Local**: Base de datos académica del DPD funcionando de forma local
- **Lectura Fiable desde SQLite**: Consulta directa de `dpd.db` (`lookup` + `dpd_headwords`) para mayor precisión
- **Análisis Morfológico Completo**: Información de categoría gramatical, raíz, morfología
- **Glosa Profesional**: Significados precisos con información etimológica
- **Salida Compacta Única**: Una línea por palabra, ideal para lectura rápida en móvil
- **Descarga Rápida**: Exportación directa en archivo de texto plano

## Diccionarios

### Digital Pali Dictionary (DPD)
- Base de datos académica profesional
- Términos clave del budismo Theravada
- Información etimológica y morfológica precisa

### Diccionario Local
- Base de datos integrada con términos comunes
- Respaldo cuando el DPD tiene cobertura limitada
- Fácil de extender

## Cómo usar

### Instalación

```bash
pip install -r requirements.txt
```

### Ejecutar la aplicación

```bash
streamlit run streamlit_app.py
```

La aplicación se abrirá en `http://localhost:8501`

## Deploy en Streamlit Community Cloud (`streamlit.app`)

Prerequisitos:
- Repositorio subido a GitHub
- Archivo principal: `streamlit_app.py`
- Dependencias en `requirements.txt`
- Versión de Python definida en `runtime.txt`

Pasos:
1. Entra a https://share.streamlit.io/
2. Inicia sesión con GitHub
3. Click en **Create app**
4. Selecciona:
    - **Repository**: `jorgecaa/pali-lem`
    - **Branch**: `main`
    - **Main file path**: `streamlit_app.py`
5. Click en **Deploy**

Notas:
- Si cambias dependencias, haz push a `requirements.txt` y redeploy.
- Si usas una rama distinta, selecciónala en el formulario.
- La app usa caché con límites (`ttl` + `max_entries`) para reducir consumo de memoria en Streamlit Cloud.

## Generar el DPD completo

Para usar todas las entradas del DPD, descarga la base oficial `dpd.db` desde los releases del proyecto y genera el JSON local:

1. Descarga `dpd.db.tar.bz2` desde https://github.com/digitalpalidictionary/dpd-db/releases
2. Extrae `dpd.db` en `dpd-db/` (ruta final: `dpd-db/dpd.db`)
3. Ejecuta:

```bash
python3 download_dpd.py
```

Opcional: puedes definir `DPD_DB_PATH` si la base esta en otra ruta.

Si `dpd.db` no está disponible, la app usa `dpd_dictionary.json` como fallback.

## Uso

1. **Ingresa un párrafo en Pali** en el área de texto principal
2. **Selecciona el diccionario**: Digital Pali Dictionary o Diccionario Local
3. **Visualiza** el análisis compacto con:
   - Categoría gramatical (noun, adj, verb, etc.)
   - Información morfológica (caso, número, género)
   - Significado en español
   - Traducción al inglés
   - Raíz etimológica
4. **Descarga** el resultado en `.txt`

## Ejemplo

**Entrada:**
```
dhammo buddha sangha
```

**Salida (Formato Compacto):**
```
dhammo (noun) (masc. nom. sg.): doctrina, ley, fenómeno, verdad
buddha (noun) (masc. nom. sg.): el Despierto, el Iluminado
sangha (noun) (masc. nom. sg.): comunidad, congregación, asamblea
```

## Estructura de archivos

```
pali-lem/
├── streamlit_app.py          # Aplicación principal
├── download_dpd.py            # Script para procesar DPD
├── pali_dictionary.json       # Diccionario local
├── dpd_dictionary.json        # Digital Pali Dictionary procesado
├── requirements.txt           # Dependencias
├── dpd-db/                    # Repositorio DPD descargado (opcional)
└── README.md                  # Este archivo
```

## Extensión del diccionario

Para agregar nuevas palabras, edita `pali_dictionary.json` o `dpd_dictionary.json`:

```json
"palabra": {
    "meaning": "significado en español",
    "morphology": "descripción morfológica (e.g., masc. nom. sg.)",
    "part_of_speech": "categoría (noun, adj, verb, etc.)",
    "root": "raíz etimológica",
    "translation": "traducción al inglés"
}
```

## Información adicional

### Categorías gramaticales (part_of_speech)
- `noun` - Sustantivo
- `adj` - Adjetivo
- `verb` - Verbo
- `adv` - Adverbio
- `prep` - Preposición
- `conj` - Conjunción
- `part` - Partícula

### Morfología
- `nom.` - Nominativo
- `acc.` - Acusativo
- `gen.` - Genitivo
- `dat.` - Dativo
- `abl.` - Ablativo
- `loc.` - Locativo
- `voc.` - Vocativo
- `inst.` - Instrumental
- `sg.` - Singular
- `pl.` - Plural

## Tecnologías

- **Streamlit**: Framework web interactivo
- **Python 3**: Lenguaje de programación
- **JSON**: Almacenamiento de datos
- **Digital Pali Dictionary**: Base de datos académica

## Fuentes

- [Digital Pali Dictionary - GitHub](https://github.com/digitalpalidictionary/dpd-db)
- Texto Pali Canónico (Canon Pali)

## Licencia

Ver archivo LICENSE
