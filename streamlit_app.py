import streamlit as st
import streamlit.components.v1 as components
import json
import re
import os
import sqlite3
import unicodedata
import html
from pathlib import Path

PUNCTUATION_LABELS = {
    ".": "<PUNTO>",
    ",": "<COMA>",
    ";": "<PUNTO_Y_COMA>",
    ":": "<DOS_PUNTOS>",
    "!": "<EXCLAMACION>",
    "?": "<INTERROGACION>",
    "—": "<RAYA>",
    "–": "<GUION>",
    "-": "<GUION>",
    "(": "<ABRE_PARENTESIS>",
    ")": "<CIERRA_PARENTESIS>",
    "«": "<ABRE_COMILLAS>",
    "»": "<CIERRA_COMILLAS>",
    '"': "<COMILLAS>",
    "'": "<APOSTROFE>",
    "“": "<ABRE_COMILLAS>",
    "”": "<CIERRA_COMILLAS>",
    "‘": "<ABRE_COMILLA_SIMPLE>",
    "’": "<CIERRA_COMILLA_SIMPLE>",
    "…": "<ELIPSIS>",
    "...": "<ELIPSIS>",
    "¶": "<FIN_SECCION>",
}

WORD_RE = re.compile(r"[^\W\d_]+", flags=re.UNICODE)
TOKEN_RE = re.compile(r"[^\W\d_]+|\.\.\.|[.,;:!?…—–\-()«»\"'“”‘’¶]", flags=re.UNICODE)

# Configurar página
st.set_page_config(
    page_title="Pali Glosser - DPD",
    page_icon="📚",
    layout="centered"
)

# Cargar diccionarios locales (fallback)
@st.cache_data(ttl=3600, max_entries=8)
def load_dictionary(dict_name="dpd"):
    """Carga el diccionario especificado"""
    if dict_name == "dpd":
        dict_file = "dpd_dictionary.json"
    else:
        dict_file = "pali_dictionary.json"
    
    dict_path = Path(__file__).parent / dict_file
    
    if not dict_path.exists():
        # Si no existe, usar el otro
        dict_path = Path(__file__).parent / ("pali_dictionary.json" if dict_file == "dpd_dictionary.json" else "dpd_dictionary.json")
    
    with open(dict_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_dpd_db_path():
    """Encuentra la ruta de dpd.db siguiendo rutas conocidas y variable de entorno."""
    env_path = os.environ.get("DPD_DB_PATH", "").strip()
    candidate_paths = [
        Path(env_path) if env_path else None,
        Path(__file__).parent / "dpd-db" / "dpd.db",
        Path(__file__).parent / "dpd.db",
    ]
    for candidate in candidate_paths:
        if candidate and candidate.exists():
            return str(candidate)
    return ""


def _load_json_field(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize_token(token):
    normalized = unicodedata.normalize("NFC", token.strip().lower())
    return normalized.replace("ṁ", "ṃ")


def _build_root_label(root_sign, root_key, root_group):
    if not root_key:
        return ""

    root_group_names = {
        "1": "bhvādi",
        "2": "adādi",
        "3": "juhotyādi",
        "4": "divādi",
        "5": "svādi",
        "6": "tudādi",
        "7": "rudhādi",
        "8": "tanādi",
        "9": "kryādi",
        "10": "curādi",
    }

    base_root = f"{root_sign or ''}{root_key}"
    group_text = str(root_group).strip() if root_group is not None else ""
    if group_text and group_text not in {"N/A", "---"}:
        group_label = root_group_names.get(group_text, "")
        group_display = f"{group_text} ({group_label})" if group_label else group_text
        if base_root.strip().endswith(f" {group_text}"):
            if group_label:
                return f"{base_root} ({group_label})"
            return base_root
        return f"{base_root} · {group_display}"
    return base_root


def _fetch_root_group(conn, root_key, root_sign, root_group_cache):
    if not root_key:
        return ""

    cache_key = (str(root_sign or ""), str(root_key))
    if cache_key in root_group_cache:
        return root_group_cache[cache_key]

    row = conn.execute(
        """
        SELECT root_group
        FROM dpd_roots
        WHERE root = ?
        ORDER BY CASE WHEN root_sign = ? THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (root_key, root_sign or ""),
    ).fetchone()

    root_group = ""
    if row and row["root_group"] is not None:
        root_group = str(row["root_group"]).strip()

    root_group_cache[cache_key] = root_group
    return root_group


def tokenize_pali_with_separators(text):
    normalized_text = unicodedata.normalize("NFC", text)
    token_stream = []
    for raw_token in TOKEN_RE.findall(normalized_text):
        if WORD_RE.fullmatch(raw_token):
            normalized_word = _normalize_token(raw_token)
            if normalized_word:
                token_stream.append(
                    {
                        "kind": "word",
                        "surface": raw_token,
                        "norm": normalized_word,
                    }
                )
        else:
            token_stream.append(
                {
                    "kind": "separator",
                    "surface": raw_token,
                    "separator": PUNCTUATION_LABELS.get(
                        raw_token, f"<SIMBOLO:{raw_token}>"
                    ),
                }
            )
    return token_stream


def tokenize_pali_text(text):
    token_stream = tokenize_pali_with_separators(text)
    return [token["norm"] for token in token_stream if token["kind"] == "word"]


@st.cache_data(ttl=1800, max_entries=2)
def get_dpd_lookup_count(dpd_db_path):
    conn = sqlite3.connect(dpd_db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM lookup").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


@st.cache_data(show_spinner=False, ttl=900, max_entries=128)
def lookup_words_in_dpd(words, dpd_db_path):
    """Busca palabras en `lookup` y `dpd_headwords` usando dpd.db."""
    unique_words = [word for word in _dedupe(words) if word]
    if not unique_words or not dpd_db_path:
        return {}

    result = {}
    conn = sqlite3.connect(dpd_db_path)
    try:
        conn.row_factory = sqlite3.Row
        root_group_cache = {}
        placeholders = ",".join("?" for _ in unique_words)

        lookup_rows = conn.execute(
            f"SELECT lookup_key, headwords, grammar FROM lookup WHERE lookup_key IN ({placeholders})",
            unique_words,
        ).fetchall()
        lookup_map = {row["lookup_key"]: row for row in lookup_rows}

        headword_ids = []
        for row in lookup_rows:
            parsed_ids = _load_json_field(row["headwords"], [])
            if isinstance(parsed_ids, list):
                headword_ids.extend(parsed_ids)
        unique_headword_ids = [item for item in _dedupe(headword_ids) if isinstance(item, int)]

        headwords_by_id = {}
        if unique_headword_ids:
            hw_placeholders = ",".join("?" for _ in unique_headword_ids)
            hw_rows = conn.execute(
                f"""
                SELECT id, lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit, sanskrit, root_key, root_sign
                FROM dpd_headwords
                WHERE id IN ({hw_placeholders})
                """,
                unique_headword_ids,
            ).fetchall()
            headwords_by_id = {row["id"]: row for row in hw_rows}

        missing_words = []
        for word in unique_words:
            row = lookup_map.get(word)
            if not row:
                missing_words.append(word)
                continue

            grammar_list = _load_json_field(row["grammar"], [])
            pos_list = []
            morph_list = []
            if isinstance(grammar_list, list):
                for item in grammar_list:
                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                        if item[1]:
                            pos_list.append(str(item[1]))
                        if item[2]:
                            morph_list.append(str(item[2]))

            meanings = []
            lemmas = []
            headword_pos_list = []
            headword_morph_list = []
            root_key_value = ""
            root_sign_value = ""
            sanskrit_root = ""
            parsed_ids = _load_json_field(row["headwords"], [])
            if isinstance(parsed_ids, list):
                for headword_id in parsed_ids:
                    hw = headwords_by_id.get(headword_id)
                    if not hw:
                        continue
                    meaning = hw["meaning_1"] or hw["meaning_2"] or ""
                    if hw["meaning_lit"]:
                        meaning = f"{meaning} ({hw['meaning_lit']})" if meaning else hw["meaning_lit"]
                    if meaning:
                        meanings.append(meaning)
                    if hw["lemma_1"]:
                        lemmas.append(hw["lemma_1"])
                    if hw["pos"]:
                        headword_pos_list.append(str(hw["pos"]))
                    if hw["grammar"]:
                        headword_morph_list.append(str(hw["grammar"]))
                    if not root_key_value and hw["root_key"]:
                        root_key_value = str(hw["root_key"])
                        root_sign_value = str(hw["root_sign"] or "")
                    if not sanskrit_root and hw["sanskrit"]:
                        sanskrit_root = str(hw["sanskrit"]).strip()

            final_pos_list = _dedupe(pos_list) or _dedupe(headword_pos_list)
            final_morph_list = _dedupe(morph_list) or _dedupe(headword_morph_list)
            root_group = _fetch_root_group(
                conn,
                root_key_value,
                root_sign_value,
                root_group_cache,
            )
            root_label = _build_root_label(root_sign_value, root_key_value, root_group)
            merged_meaning = "; ".join(_dedupe(meanings)) or "; ".join(_dedupe(lemmas))
            result[word] = {
                "meaning": merged_meaning or "N/A",
                "morphology": "; ".join(final_morph_list) or "N/A",
                "part_of_speech": "; ".join(final_pos_list) or "N/A",
                "root": root_label or "N/A",
                "sanskrit_root": sanskrit_root or "N/A",
                "translation": merged_meaning or "N/A",
            }

        if missing_words:
            missing_placeholders = ",".join("?" for _ in missing_words)
            lemma_rows = conn.execute(
                f"""
                SELECT lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit, sanskrit, root_key, root_sign
                FROM dpd_headwords
                WHERE lower(lemma_1) IN ({missing_placeholders})
                """,
                missing_words,
            ).fetchall()

            lemma_map = {}
            for row in lemma_rows:
                lemma_key = _normalize_token(row["lemma_1"] or "")
                if not lemma_key or lemma_key in lemma_map:
                    continue
                meaning = row["meaning_1"] or row["meaning_2"] or ""
                if row["meaning_lit"]:
                    meaning = f"{meaning} ({row['meaning_lit']})" if meaning else row["meaning_lit"]
                root_group = _fetch_root_group(
                    conn,
                    row["root_key"] or "",
                    row["root_sign"] or "",
                    root_group_cache,
                )
                root = _build_root_label(
                    row["root_sign"] or "",
                    row["root_key"] or "",
                    root_group,
                )
                lemma_map[lemma_key] = {
                    "meaning": meaning or "N/A",
                    "morphology": row["grammar"] or "N/A",
                    "part_of_speech": row["pos"] or "N/A",
                    "root": root or "N/A",
                    "sanskrit_root": (row["sanskrit"] or "").strip() or "N/A",
                    "translation": meaning or "N/A",
                }

            for word in missing_words:
                if word in lemma_map:
                    result[word] = lemma_map[word]
    finally:
        conn.close()

    return result


# Procesar texto Pali
def process_pali_text(text, dictionary):
    token_stream = tokenize_pali_with_separators(text)
    gloss_entries = []

    for token in token_stream:
        if token["kind"] == "separator":
            gloss_entries.append({
                "word": token["separator"],
                "meaning": "[Separador sintáctico]",
                "morphology": "---",
                "part_of_speech": "SEP",
                "root": "---",
                "translation": token["surface"],
                "separator_symbol": token["surface"],
            })
            continue

        word = token["norm"]
        entry = dictionary.get(word)
        if entry:
            gloss_entries.append({
                "word": word,
                "meaning": entry.get("meaning", "N/A"),
                "morphology": entry.get("morphology", "N/A"),
                "part_of_speech": entry.get("part_of_speech", "N/A"),
                "root": entry.get("root", "N/A"),
                "sanskrit_root": entry.get("sanskrit_root", "N/A"),
                "translation": entry.get("translation", "N/A")
            })
        else:
            gloss_entries.append({
                "word": word,
                "meaning": "[No encontrado en diccionario]",
                "morphology": "---",
                "part_of_speech": "---",
                "root": "---",
                "sanskrit_root": "---",
                "translation": "---"
            })

    return gloss_entries


def process_pali_with_lookup_map(text, lookup_map):
    token_stream = tokenize_pali_with_separators(text)
    gloss_entries = []

    for token in token_stream:
        if token["kind"] == "separator":
            gloss_entries.append({
                "word": token["separator"],
                "meaning": "[Separador sintáctico]",
                "morphology": "---",
                "part_of_speech": "SEP",
                "root": "---",
                "translation": token["surface"],
                "separator_symbol": token["surface"],
            })
            continue

        word = token["norm"]
        entry = lookup_map.get(word)
        if entry:
            gloss_entries.append({
                "word": word,
                "meaning": entry.get("meaning", "N/A"),
                "morphology": entry.get("morphology", "N/A"),
                "part_of_speech": entry.get("part_of_speech", "N/A"),
                "root": entry.get("root", "N/A"),
                "sanskrit_root": entry.get("sanskrit_root", "N/A"),
                "translation": entry.get("translation", "N/A")
            })
        else:
            gloss_entries.append({
                "word": word,
                "meaning": "[No encontrado en diccionario]",
                "morphology": "---",
                "part_of_speech": "---",
                "root": "---",
                "sanskrit_root": "---",
                "translation": "---"
            })
    
    return gloss_entries


def humanize_part_of_speech(pos_value):
    if not pos_value or pos_value == "---":
        return ""

    pos_map = {
        "noun": "sustantivo",
        "adj": "adjetivo",
        "adjective": "adjetivo",
        "verb": "verbo",
        "adv": "adverbio",
        "adverb": "adverbio",
        "prep": "preposición",
        "preposition": "preposición",
        "conj": "conjunción",
        "conjunction": "conjunción",
        "pron": "pronombre",
        "pronoun": "pronombre",
        "num": "numeral",
        "numeral": "numeral",
        "part": "partícula",
        "particle": "partícula",
        "prefix": "prefijo",
        "suffix": "sufijo",
        "interj": "interjección",
        "interjection": "interjección",
        "idiom": "modismo",
        "loc": "locativo",
        "locative": "locativo",
        "indeclinable": "indeclinable",
        "ind": "indeclinable",
    }

    parts = [part.strip() for part in str(pos_value).split(";")]
    mapped = []
    for part in parts:
        if not part:
            continue
        normalized_part = part
        for source, target in pos_map.items():
            normalized_part = re.sub(
                rf"(?<!\\w){re.escape(source)}(?!\\w)",
                target,
                normalized_part,
                flags=re.IGNORECASE,
            )
        mapped.append(normalized_part)
    return "; ".join(mapped)

# Generar formato compacto de glosa (una línea por palabra)
def generate_compact_gloss(gloss_entries):
    lines = []
    for entry in gloss_entries:
        if entry["part_of_speech"] == "SEP":
            symbol = entry.get("separator_symbol", "")
            line = f"{entry['word']} {symbol}".strip()
            lines.append(line)
            continue

        pos = humanize_part_of_speech(entry.get('part_of_speech'))
        morph = entry['morphology'] if entry['morphology'] != "---" else ""
        meaning = entry['meaning']
        
        if pos and morph:
            line = f"{entry['word']} ({pos}) ({morph}): {meaning}"
        elif pos:
            line = f"{entry['word']} ({pos}): {meaning}"
        else:
            line = f"{entry['word']}: {meaning}"
        
        lines.append(line)
    
    return "\n".join(lines)


def _display_value(value, fallback="—"):
    if value is None:
        return fallback
    normalized = str(value).strip()
    if not normalized or normalized in {"---", "N/A"}:
        return fallback
    return normalized


def _same_content(value_a, value_b):
    norm_a = re.sub(r"\s+", " ", str(value_a or "").strip()).lower()
    norm_b = re.sub(r"\s+", " ", str(value_b or "").strip()).lower()
    return bool(norm_a and norm_b and norm_a == norm_b)


def render_philological_gloss(gloss_entries):
    entry_number = 0
    for entry in gloss_entries:
        if entry.get("part_of_speech") == "SEP":
            symbol = _display_value(entry.get("separator_symbol"), "")
            label = _display_value(entry.get("word"), "<SEP>")
            st.caption(f"{label} {symbol}".strip())
            continue

        entry_number += 1
        word = _display_value(entry.get("word"))
        pos = _display_value(humanize_part_of_speech(entry.get("part_of_speech")))
        morphology = _display_value(entry.get("morphology"))
        meaning = _display_value(entry.get("meaning"))
        translation = _display_value(entry.get("translation"))
        show_translation = translation != "—" and not _same_content(meaning, translation)
        root = _display_value(entry.get("root"))
        sanskrit_root = _display_value(entry.get("sanskrit_root"))

        safe_word = html.escape(word)
        safe_pos = html.escape(pos)
        safe_morphology = html.escape(morphology)
        safe_meaning = html.escape(meaning)
        safe_translation = html.escape(translation)
        safe_root = html.escape(root)
        safe_sanskrit_root = html.escape(sanskrit_root)

        translation_html = (
            f'<div><strong>Traducción:</strong> {safe_translation}</div>' if show_translation else ""
        )

        st.markdown(
            f"""
<div class="lemma-line">{entry_number}. {safe_word}</div>
<div class="gram-line"><strong>Categoría:</strong> <span>{safe_pos}</span></div>
<div class="gram-line"><strong>Morfología:</strong> <span>{safe_morphology}</span></div>
<div><strong>Significado:</strong> {safe_meaning}</div>
{translation_html}
<div><strong>Raíz:</strong> {safe_root}</div>
<div><strong>Raíz sánscrita:</strong> {safe_sanskrit_root}</div>
""",
            unsafe_allow_html=True,
        )
        st.divider()

def generate_rich_gloss_text(gloss_entries):
    lines = []
    entry_number = 0
    for entry in gloss_entries:
        if entry.get("part_of_speech") == "SEP":
            symbol = _display_value(entry.get("separator_symbol"), "")
            label = _display_value(entry.get("word"), "<SEP>")
            lines.append(f"{label} {symbol}".strip())
            continue

        entry_number += 1
        word = _display_value(entry.get("word"))
        pos = _display_value(humanize_part_of_speech(entry.get("part_of_speech")))
        morphology = _display_value(entry.get("morphology"))
        meaning = _display_value(entry.get("meaning"))
        translation = _display_value(entry.get("translation"))
        show_translation = translation != "—" and not _same_content(meaning, translation)
        root = _display_value(entry.get("root"))
        sanskrit_root = _display_value(entry.get("sanskrit_root"))

        lines.extend(
            [
                f"{entry_number}. {word}",
                f"  Categoría: {pos}",
                f"  Morfología: {morphology}",
                f"  Significado: {meaning}",
            ]
        )
        if show_translation:
            lines.append(f"  Traducción: {translation}")
        lines.extend(
            [
                f"  Raíz: {root}",
                f"  Raíz sánscrita: {sanskrit_root}",
                "",
            ]
        )

    return "\n".join(lines).strip()


def render_copy_button(text_to_copy, button_label, key_suffix):
    encoded_text = json.dumps(text_to_copy)
    safe_suffix = re.sub(r"[^a-zA-Z0-9_-]", "", str(key_suffix)) or "copy"
    status_id = f"copy-status-{safe_suffix}"
    function_name = f"copyGlossText_{safe_suffix}"
    components.html(
        f"""
<div>
    <button
        style="
            width: 100%;
            border: 1px solid rgba(49, 51, 63, 0.2);
            border-radius: 8px;
            padding: 0.45rem 0.75rem;
            background: white;
            cursor: pointer;
            font-size: 0.95rem;
        "
        onclick="{function_name}()"
    >
        {button_label}
    </button>
    <div id="{status_id}" style="font-size:0.85rem; margin-top:0.35rem; color:#555;"></div>
</div>
<script>
function {function_name}() {{
    const text = {encoded_text};
    const status = document.getElementById('{status_id}');
    navigator.clipboard.writeText(text)
        .then(() => {{ status.textContent = 'Copiado al portapapeles'; }})
        .catch(() => {{ status.textContent = 'No se pudo copiar automáticamente'; }});
}}
</script>
""",
        height=74,
    )

st.markdown(
    """
    <style>
        .main .block-container {
            max-width: 680px;
            padding-top: 1rem;
            padding-bottom: 2rem;
            padding-left: 0.9rem;
            padding-right: 0.9rem;
        }
        h1 {
            font-size: 1.55rem !important;
            margin-bottom: 0.4rem !important;
        }
        .stTextArea textarea {
            font-size: 1rem;
        }
        [data-testid="stMetricValue"] {
            font-size: 1rem;
        }
        .lemma-line {
            font-size: 1.2rem;
            font-weight: 700;
            color: #0b2e6b;
            margin-bottom: 0.2rem;
        }
        .gram-line {
            color: #1f5fbf;
            font-style: italic;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Título y descripción minimalista
st.title("📚 Pali Glosser")
st.caption("Glosa morfológica de Pali con enfoque mobile-first.")

# Controles compactos
dict_option = st.selectbox(
    "Diccionario",
    ["Digital Pali Dictionary", "Diccionario Local"],
    index=0,
)
dict_name = "dpd" if dict_option == "Digital Pali Dictionary" else "local"

# Cargar fuente seleccionada
dpd_db_path = get_dpd_db_path() if dict_name == "dpd" else ""
dictionary = load_dictionary(dict_name)
if dict_name == "dpd" and dpd_db_path:
    total_words = get_dpd_lookup_count(dpd_db_path)
    st.caption(f"Fuente: dpd.db (SQLite oficial) · Entradas lookup: {total_words}")
else:
    total_words = len(dictionary)
    if dict_name == "dpd":
        st.caption(
            f"Fuente: JSON local (fallback) · Entradas: {total_words}. Para mejor precisión usa dpd.db"
        )
    else:
        st.caption(f"Entradas disponibles: {total_words}")

# Entrada principal
pali_text = st.text_area(
    "Texto Pali",
    placeholder="Ej: dhammo buddho sangha...",
    height=170,
)

# Acción explícita
if "generated_gloss" not in st.session_state:
    st.session_state.generated_gloss = False
    st.session_state.gloss_entries = []
    st.session_state.gloss_compact_text = ""
    st.session_state.gloss_rich_text = ""
    st.session_state.gloss_word_total = 0
    st.session_state.gloss_found_words = 0
    st.session_state.gloss_coverage = 0.0

generate_clicked = st.button("Generar glosa", use_container_width=True, type="primary")

if generate_clicked:
    if pali_text.strip():
        with st.spinner("Generando glosa… por favor espera"):
            if dict_name == "dpd" and dpd_db_path:
                words = tuple(tokenize_pali_text(pali_text))
                lookup_map = lookup_words_in_dpd(words, dpd_db_path)
                gloss_entries = process_pali_with_lookup_map(pali_text, lookup_map)
            else:
                gloss_entries = process_pali_text(pali_text, dictionary)

            found_words = sum(
                1
                for entry in gloss_entries
                if entry["part_of_speech"] not in ("---", "SEP")
            )
            word_total = sum(1 for entry in gloss_entries if entry["part_of_speech"] != "SEP")
            coverage = (found_words / word_total * 100) if word_total else 0
            compact_text = generate_compact_gloss(gloss_entries)
            rich_text = generate_rich_gloss_text(gloss_entries)

        st.session_state.generated_gloss = True
        st.session_state.gloss_entries = gloss_entries
        st.session_state.gloss_compact_text = compact_text
        st.session_state.gloss_rich_text = rich_text
        st.session_state.gloss_word_total = word_total
        st.session_state.gloss_found_words = found_words
        st.session_state.gloss_coverage = coverage
    else:
        st.session_state.generated_gloss = False
        st.session_state.gloss_entries = []
        st.session_state.gloss_rich_text = ""
        st.info("Ingresa texto en Pali para generar la glosa.")

if st.session_state.generated_gloss:
    st.caption(
        f"Palabras: {st.session_state.gloss_word_total} · Encontradas: {st.session_state.gloss_found_words} · Cobertura: {st.session_state.gloss_coverage:.1f}%"
    )
    st.divider()

    st.subheader("Glosa filológica")
    render_philological_gloss(st.session_state.gloss_entries)

    st.download_button(
        label="Descargar compacto (.txt)",
        data=st.session_state.gloss_compact_text,
        file_name="pali_gloss_compact.txt",
        mime="text/plain",
        use_container_width=True,
    )
    render_copy_button(
        st.session_state.gloss_rich_text,
        "Copiar glosa enriquecida",
        "rich",
    )
    render_copy_button(
        st.session_state.gloss_compact_text,
        "Copiar glosa compacta",
        "compact",
    )
elif not pali_text.strip():
    st.info("Ingresa texto en Pali para comenzar.")

