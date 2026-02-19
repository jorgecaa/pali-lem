import streamlit as st
import streamlit.components.v1 as components
import json
import re
import os
import sqlite3
import threading
import unicodedata
import html
import gzip
import tarfile
from pathlib import Path
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

IS_CONSOLE_MODE = os.environ.get("PALI_LEM_NO_UI") == "1"
SAVED_SESSIONS_PATH = Path(__file__).parent / "saved_sessions.json"

# Configurar página
if not IS_CONSOLE_MODE:
    st.set_page_config(
        page_title="Pali Glosser - DPD",
        page_icon="📚",
        layout="centered"
    )

# Cargar diccionario DPD
@st.cache_data(ttl=3600, max_entries=1, show_spinner="Cargando diccionario DPD...")
def load_dictionary():
    """Carga únicamente `dpd_dictionary.json`."""
    ensure_dpd_json_available()
    dict_path = Path(__file__).parent / "dpd_dictionary.json"

    if not dict_path.exists():
        raise FileNotFoundError(
            "No se encontró dpd_dictionary.json. Configura DPD_JSON_URL o añade dpd_dictionary.json.gz/local."
        )

    with open(dict_path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=3600, show_spinner="Preparando diccionario por primera vez...")
def ensure_dpd_json_available():
    """Asegura `dpd_dictionary.json` desde archivo local comprimido o URL remota."""
    dict_path = Path(__file__).parent / "dpd_dictionary.json"
    gz_path = Path(__file__).parent / "dpd_dictionary.json.gz"
    if dict_path.exists():
        return str(dict_path)

    if gz_path.exists():
        temp_path = dict_path.with_suffix(".json.part")
        try:
            with gzip.open(gz_path, "rb") as input_file, open(temp_path, "wb") as output_file:
                while True:
                    chunk = input_file.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
            temp_path.replace(dict_path)
            return str(dict_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            return ""

    dpd_json_url = os.environ.get("DPD_JSON_URL", "").strip()
    if not dpd_json_url:
        return ""

    temp_path = dict_path.with_suffix(".json.part")
    try:
        with urllib.request.urlopen(dpd_json_url, timeout=180) as response, open(
            temp_path, "wb"
        ) as output_file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output_file.write(chunk)
        temp_path.replace(dict_path)
        return str(dict_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        return ""


def _is_valid_dpd_db(path):
    if not path or not path.exists() or not path.is_file():
        return False
    conn = None
    try:
        conn = sqlite3.connect(str(path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lookup' LIMIT 1"
        )
        result = cursor.fetchone()
        return result is not None
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def _build_dpd_db_candidates():
    module_dir = Path(__file__).resolve().parent
    env_path = os.environ.get("DPD_DB_PATH", "").strip()

    candidate_paths = []
    if env_path:
        candidate_paths.append(Path(env_path).expanduser())

    search_roots = [module_dir, Path.cwd(), *module_dir.parents]
    for root in search_roots:
        candidate_paths.append(root / "dpd-db" / "dpd.db")
        candidate_paths.append(root / "dpd.db")
    return candidate_paths


def _resolve_dpd_db_download_url():
    db_url = os.environ.get("DPD_DB_URL", "").strip()
    if db_url:
        return db_url

    release_tag = os.environ.get("DPD_DB_RELEASE_TAG", "").strip()
    if release_tag:
        return (
            "https://github.com/digitalpalidictionary/dpd-db/"
            f"releases/download/{release_tag}/dpd.db.tar.bz2"
        )

    return os.environ.get(
        "DPD_DB_TARBZ2_URL",
        "https://github.com/digitalpalidictionary/dpd-db/releases/latest/download/dpd.db.tar.bz2",
    ).strip()


def _as_bool(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _load_json_file(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception:
        return default


def _save_json_file(path, payload):
    temp_path = path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()


def _utcnow():
    return datetime.now(ZoneInfo("UTC"))


def _should_check_update(last_checked_at, interval_hours):
    if interval_hours <= 0:
        return True
    if not last_checked_at:
        return True
    try:
        parsed = datetime.fromisoformat(last_checked_at)
    except ValueError:
        return True
    return _utcnow() - parsed >= timedelta(hours=interval_hours)


def _fetch_remote_signature(download_url, timeout):
    def build_signature(response):
        return {
            "resolved_url": response.geturl(),
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "content_length": response.headers.get("Content-Length", ""),
        }

    try:
        request = urllib.request.Request(download_url, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return build_signature(response)
    except Exception:
        return {}


def _download_dpd_db(download_url, target_dir, target_db, timeout):
    if download_url.endswith(".db"):
        temp_path = target_db.with_suffix(".db.part")
        try:
            with urllib.request.urlopen(download_url, timeout=timeout) as response, open(
                temp_path, "wb"
            ) as output_file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
            temp_path.replace(target_db)
            return True
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            return False

    archive_path = target_dir / "dpd.db.tar.bz2.part"
    temp_db_path = target_dir / "dpd.db.part"
    try:
        with urllib.request.urlopen(download_url, timeout=timeout) as response, open(
            archive_path, "wb"
        ) as output_file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output_file.write(chunk)

        with tarfile.open(archive_path, mode="r:bz2") as archive:
            member = None
            for item in archive.getmembers():
                if item.isfile() and Path(item.name).name == "dpd.db":
                    member = item
                    break
            if member is None:
                return False

            with archive.extractfile(member) as source_file, open(
                temp_db_path, "wb"
            ) as output_file:
                while True:
                    chunk = source_file.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)

        temp_db_path.replace(target_db)
        return True
    except Exception:
        if temp_db_path.exists():
            temp_db_path.unlink()
        return False
    finally:
        if archive_path.exists():
            archive_path.unlink()


def _start_background_db_download(download_url, target_dir, target_db, timeout, meta, meta_path, remote_signature):
    """Descarga dpd.db en un hilo de fondo para no bloquear el script de Streamlit."""
    in_progress_file = target_dir / ".dpd_db_downloading"
    try:
        in_progress_file.open("x").close()
    except FileExistsError:
        return

    def _worker():
        try:
            if _download_dpd_db(download_url, target_dir, target_db, timeout) and _is_valid_dpd_db(
                target_db
            ):
                meta.update(
                    {
                        "download_url": download_url,
                        "updated_at": _utcnow().isoformat(),
                        "last_checked_at": _utcnow().isoformat(),
                        "remote_signature": remote_signature,
                    }
                )
                _save_json_file(meta_path, meta)
                get_dpd_db_path.clear()
        finally:
            if in_progress_file.exists():
                in_progress_file.unlink()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def ensure_dpd_db_available():
    """Asegura `dpd.db` local y lo actualiza periódicamente desde releases remotos."""
    module_dir = Path(__file__).resolve().parent
    target_dir = module_dir / "dpd-db"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_db = target_dir / "dpd.db"
    meta_path = target_dir / ".dpd_db_meta.json"

    valid_candidates = []
    seen = set()
    for candidate in _build_dpd_db_candidates():
        resolved = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_valid_dpd_db(candidate):
            valid_candidates.append(candidate.resolve())

    managed_db = target_db.resolve()
    selected_db = valid_candidates[0] if valid_candidates else None
    if selected_db and selected_db != managed_db:
        return str(selected_db)

    download_url = _resolve_dpd_db_download_url()
    if not download_url:
        return str(selected_db) if selected_db else ""

    timeout = int(os.environ.get("DPD_DB_DOWNLOAD_TIMEOUT", "300"))
    head_timeout = int(os.environ.get("DPD_DB_HEAD_TIMEOUT", "10"))
    auto_update = _as_bool(os.environ.get("DPD_DB_AUTO_UPDATE", "1"), default=True)
    interval_hours = int(os.environ.get("DPD_DB_UPDATE_INTERVAL_HOURS", "24"))

    meta = _load_json_file(meta_path, default={})
    remote_signature = _fetch_remote_signature(download_url, head_timeout)
    should_download = selected_db is None

    if selected_db is not None and auto_update:
        if _should_check_update(meta.get("last_checked_at", ""), interval_hours):
            if remote_signature:
                previous_signature = meta.get("remote_signature", {})
                should_download = previous_signature != remote_signature

    if not should_download:
        if auto_update:
            meta.update(
                {
                    "download_url": download_url,
                    "last_checked_at": _utcnow().isoformat(),
                    "remote_signature": remote_signature or meta.get("remote_signature", {}),
                }
            )
            _save_json_file(meta_path, meta)
        return str(selected_db)

    _start_background_db_download(
        download_url, target_dir, target_db, timeout, meta.copy(), meta_path, remote_signature
    )
    return str(selected_db) if selected_db else ""


@st.cache_data(ttl=604800, max_entries=1, show_spinner=False)
def get_dpd_db_path():
    """Encuentra una base `dpd.db` válida usando referencias relativas al proyecto.

    El resultado se cachea durante 1 hora para evitar re-escaneos, peticiones HEAD
    y posibles descargas en cada rerun de Streamlit (por ejemplo, al pulsar 'Cargar sesión').
    """
    return ensure_dpd_db_available()


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


def _dedupe_normalized(values):
    seen = set()
    result = []
    for value in values:
        if not value:
            continue
        normalized_key = re.sub(r"\s+", " ", str(value).strip()).lower()
        if normalized_key and normalized_key not in seen:
            seen.add(normalized_key)
            result.append(value)
    return result


def _normalize_token(token):
    normalized = unicodedata.normalize("NFC", token.strip().lower())
    return normalized.replace("ṁ", "ṃ")


ROOT_GROUP_NAMES = {
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

FINAL_LONG_VOWEL_MAP = {
    "ā": "a",
    "ī": "i",
    "ū": "u",
}

FINAL_NIGGAHITA_MAP = {
    "ṃ": "m",
    "m": "ṃ",
}


def _generate_final_vowel_fallbacks(word):
    normalized_word = _normalize_token(word)
    if not normalized_word:
        return []

    candidates = [normalized_word]
    for long_vowel, short_vowel in FINAL_LONG_VOWEL_MAP.items():
        if normalized_word.endswith(long_vowel):
            candidates.append(f"{normalized_word[:-1]}{short_vowel}")
            break

    for source_char, target_char in FINAL_NIGGAHITA_MAP.items():
        if normalized_word.endswith(source_char):
            candidates.append(f"{normalized_word[:-1]}{target_char}")
            break

    return _dedupe(candidates)


def _is_final_long_vowel_shortening(original, candidate):
    """True when candidate is original with its final long vowel (ā/ī/ū) shortened.

    Pali words frequently end in a lengthened vowel due to ā+ti sandhi or
    metrical requirements.  That is a natural phonological variant of the same
    word, not a different lexical form, so it should not be flagged as an
    approximate ('fallback') match.
    """
    for long_v, short_v in FINAL_LONG_VOWEL_MAP.items():
        if original.endswith(long_v) and candidate == original[:-1] + short_v:
            return True
    return False


def _resolve_entry_with_fallback(word, dictionary):
    normalized_word = _normalize_token(word)
    for candidate in _generate_final_vowel_fallbacks(normalized_word):
        entry = dictionary.get(candidate)
        if entry:
            is_fallback = (
                candidate != normalized_word
                and not _is_final_long_vowel_shortening(normalized_word, candidate)
            )
            return entry, is_fallback, candidate
    return None, False, ""


def _build_root_label(root_sign, root_key, root_group):
    if not root_key:
        return ""

    base_root = f"{root_sign or ''}{root_key}"
    group_text = str(root_group).strip() if root_group is not None else ""
    if group_text and group_text not in {"N/A", "---"}:
        group_label = ROOT_GROUP_NAMES.get(group_text, "")
        group_display = f"{group_text} ({group_label})" if group_label else group_text
        if base_root.strip().endswith(f" {group_text}"):
            if group_label:
                return f"{base_root} ({group_label})"
            return base_root
        return f"{base_root} · {group_display}"
    return base_root


def _build_etymology_label(derived_from_values, construction_values, stem_values, pattern_values):
    derived_from = "; ".join(_dedupe(derived_from_values))
    construction = "; ".join(_dedupe(construction_values))
    stem = "; ".join(_dedupe(stem_values))
    pattern = "; ".join(_dedupe(pattern_values))

    parts = []
    if derived_from:
        parts.append(f"deriva de {derived_from}")
    if construction:
        parts.append(f"construcción: {construction}")
    if stem:
        parts.append(f"tema: {stem}")
    if pattern:
        parts.append(f"patrón: {pattern}")

    return " · ".join(parts)


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
    word_candidates = {
        word: _generate_final_vowel_fallbacks(word)
        for word in unique_words
    }
    query_words = [
        candidate
        for candidate in _dedupe(
            item
            for candidates in word_candidates.values()
            for item in candidates
        )
        if candidate
    ]

    if not query_words:
        return {}

    conn = sqlite3.connect(dpd_db_path)
    try:
        conn.row_factory = sqlite3.Row
        root_group_cache = {}
        placeholders = ",".join("?" for _ in query_words)

        lookup_rows = conn.execute(
            f"SELECT lookup_key, headwords, grammar FROM lookup WHERE lookup_key IN ({placeholders})",
            query_words,
        ).fetchall()
        # Parsear headwords JSON una sola vez y almacenarlo junto a la fila
        lookup_map = {}
        headword_ids = []
        for row in lookup_rows:
            parsed_ids = _load_json_field(row["headwords"], [])
            if not isinstance(parsed_ids, list):
                parsed_ids = []
            lookup_map[row["lookup_key"]] = (row, parsed_ids)
            headword_ids.extend(parsed_ids)
        unique_headword_ids = [item for item in _dedupe(headword_ids) if isinstance(item, int)]

        headwords_by_id = {}
        if unique_headword_ids:
            hw_placeholders = ",".join("?" for _ in unique_headword_ids)
            hw_rows = conn.execute(
                f"""
                SELECT id, lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit, sanskrit,
                       root_key, root_sign, derived_from, construction, stem, pattern
                FROM dpd_headwords
                WHERE id IN ({hw_placeholders})
                """,
                unique_headword_ids,
            ).fetchall()
            headwords_by_id = {row["id"]: row for row in hw_rows}

        # Bulk-load root_group para todas las raíces únicas encontradas en headwords
        # evitando N queries individuales a dpd_roots
        all_root_keys = set()
        for hw in headwords_by_id.values():
            if hw["root_key"]:
                all_root_keys.add(str(hw["root_key"]))
        if all_root_keys:
            rk_placeholders = ",".join("?" for _ in all_root_keys)
            root_rows = conn.execute(
                f"SELECT root, root_sign, root_group FROM dpd_roots WHERE root IN ({rk_placeholders})",
                list(all_root_keys),
            ).fetchall()
            for rr in root_rows:
                cache_key = (str(rr["root_sign"] or ""), str(rr["root"] or ""))
                if cache_key not in root_group_cache:
                    root_group_cache[cache_key] = str(rr["root_group"]).strip() if rr["root_group"] is not None else ""

        missing_words = []
        for word in unique_words:
            row = None
            parsed_ids = []
            matched_candidate = word
            for candidate in word_candidates.get(word, [word]):
                entry = lookup_map.get(candidate)
                if entry:
                    row, parsed_ids = entry
                    matched_candidate = candidate
                    break
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
            derived_from_values = []
            construction_values = []
            stem_values = []
            pattern_values = []
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
                    if hw["derived_from"]:
                        derived_from_values.append(str(hw["derived_from"]).strip())
                    if hw["construction"]:
                        construction_values.append(str(hw["construction"]).strip())
                    if hw["stem"]:
                        stem_values.append(str(hw["stem"]).strip())
                    if hw["pattern"]:
                        pattern_values.append(str(hw["pattern"]).strip())

            final_pos_list = _dedupe(pos_list) or _dedupe(headword_pos_list)
            final_morph_list = _dedupe(morph_list) or _dedupe(headword_morph_list)
            root_group = _fetch_root_group(
                conn,
                root_key_value,
                root_sign_value,
                root_group_cache,
            )
            root_label = _build_root_label(root_sign_value, root_key_value, root_group)
            etymology_label = _build_etymology_label(
                derived_from_values,
                construction_values,
                stem_values,
                pattern_values,
            )
            merged_meaning = "; ".join(_dedupe_normalized(meanings)) or "; ".join(_dedupe_normalized(lemmas))
            result[word] = {
                "meaning": merged_meaning or "N/A",
                "morphology": "; ".join(final_morph_list) or "N/A",
                "part_of_speech": "; ".join(final_pos_list) or "N/A",
                "root": root_label or etymology_label or "N/A",
                "sanskrit_root": sanskrit_root or "N/A",
                "etymology": etymology_label or "N/A",
                "translation": merged_meaning or "N/A",
                "match_type": (
                    "exact"
                    if matched_candidate == word
                    or _is_final_long_vowel_shortening(word, matched_candidate)
                    else "fallback"
                ),
                "matched_form": matched_candidate,
            }

        if missing_words:
            lemma_candidates = [
                candidate
                for candidate in _dedupe(
                    item
                    for word in missing_words
                    for item in word_candidates.get(word, [word])
                )
                if candidate
            ]
            if not lemma_candidates:
                return result

            missing_placeholders = ",".join("?" for _ in lemma_candidates)
            lemma_rows = conn.execute(
                f"""
                SELECT lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit, sanskrit, root_key, root_sign
                     , derived_from, construction, stem, pattern
                FROM dpd_headwords
                WHERE lower(lemma_1) IN ({missing_placeholders})
                """,
                lemma_candidates,
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
                etymology = _build_etymology_label(
                    [str(row["derived_from"] or "").strip()],
                    [str(row["construction"] or "").strip()],
                    [str(row["stem"] or "").strip()],
                    [str(row["pattern"] or "").strip()],
                )
                lemma_map[lemma_key] = {
                    "meaning": meaning or "N/A",
                    "morphology": row["grammar"] or "N/A",
                    "part_of_speech": row["pos"] or "N/A",
                    "root": root or etymology or "N/A",
                    "sanskrit_root": (row["sanskrit"] or "").strip() or "N/A",
                    "etymology": etymology or "N/A",
                    "translation": meaning or "N/A",
                }

            for word in missing_words:
                for candidate in word_candidates.get(word, [word]):
                    if candidate in lemma_map:
                        lemma_entry = dict(lemma_map[candidate])
                        lemma_entry["match_type"] = (
                            "exact"
                            if candidate == word
                            or _is_final_long_vowel_shortening(word, candidate)
                            else "fallback"
                        )
                        lemma_entry["matched_form"] = candidate
                        result[word] = lemma_entry
                        break
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
        entry, used_fallback, matched_form = _resolve_entry_with_fallback(word, dictionary)
        if entry:
            gloss_entries.append({
                "word": word,
                "meaning": entry.get("meaning", "N/A"),
                "morphology": entry.get("morphology", "N/A"),
                "part_of_speech": entry.get("part_of_speech", "N/A"),
                "root": entry.get("root", "N/A"),
                "sanskrit_root": entry.get("sanskrit_root", "N/A"),
                "etymology": entry.get("etymology", "N/A"),
                "translation": entry.get("translation", "N/A"),
                "match_type": entry.get("match_type", "fallback" if used_fallback else "exact"),
                "matched_form": entry.get("matched_form", matched_form or word),
            })
        else:
            gloss_entries.append({
                "word": word,
                "meaning": "[No encontrado en diccionario]",
                "morphology": "---",
                "part_of_speech": "---",
                "root": "---",
                "sanskrit_root": "---",
                "etymology": "---",
                "translation": "---"
            })

    return gloss_entries


def process_pali_with_lookup_map(text, lookup_map, fallback_dictionary=None):
    token_stream = tokenize_pali_with_separators(text)
    gloss_entries = []
    fallback_dictionary = fallback_dictionary or {}

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
        entry, used_fallback, matched_form = _resolve_entry_with_fallback(word, lookup_map)
        if not entry:
            entry, used_fallback, matched_form = _resolve_entry_with_fallback(word, fallback_dictionary)
        if entry:
            gloss_entries.append({
                "word": word,
                "meaning": entry.get("meaning", "N/A"),
                "morphology": entry.get("morphology", "N/A"),
                "part_of_speech": entry.get("part_of_speech", "N/A"),
                "root": entry.get("root", "N/A"),
                "sanskrit_root": entry.get("sanskrit_root", "N/A"),
                "etymology": entry.get("etymology", "N/A"),
                "translation": entry.get("translation", "N/A"),
                "match_type": entry.get("match_type", "fallback" if used_fallback else "exact"),
                "matched_form": entry.get("matched_form", matched_form or word),
            })
        else:
            gloss_entries.append({
                "word": word,
                "meaning": "[No encontrado en diccionario]",
                "morphology": "---",
                "part_of_speech": "---",
                "root": "---",
                "sanskrit_root": "---",
                "etymology": "---",
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
                rf"(?<!\w){re.escape(source)}(?!\w)",
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
        
        fallback_suffix = ""
        if entry.get("match_type") == "fallback" and entry.get("matched_form") and entry.get("matched_form") != entry.get("word"):
            fallback_suffix = f" [≈ {entry.get('matched_form')}]"

        if pos and morph:
            line = f"{entry['word']}{fallback_suffix} ({pos}) ({morph}): {meaning}"
        elif pos:
            line = f"{entry['word']}{fallback_suffix} ({pos}): {meaning}"
        else:
            line = f"{entry['word']}{fallback_suffix}: {meaning}"
        
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


def _entry_has_lexical_data(entry):
    if entry.get("part_of_speech") == "SEP":
        return False

    placeholders = {"", "---", "N/A", "—", "[No encontrado en diccionario]"}
    fields = [
        entry.get("part_of_speech"),
        entry.get("morphology"),
        entry.get("meaning"),
        entry.get("root"),
        entry.get("sanskrit_root"),
        entry.get("etymology"),
    ]
    for value in fields:
        normalized = str(value or "").strip()
        if normalized and normalized not in placeholders:
            return True
    return False


def render_philological_gloss(gloss_entries):
    def _row(label, value, extra_class=""):
        if value == "—":
            val_html = f'<span class="gloss-dash">—</span>'
        else:
            val_html = html.escape(value)
        return (
            f'<div class="gloss-row {extra_class}">'
            f'<span class="gloss-label">{label}</span>'
            f'<span class="gloss-value">{val_html}</span>'
            f'</div>'
        )

    entry_number = 0
    for entry in gloss_entries:
        if entry.get("part_of_speech") == "SEP":
            symbol = _display_value(entry.get("separator_symbol"), "")
            st.markdown(
                f'<span class="sep-chip">{html.escape(symbol)}</span>',
                unsafe_allow_html=True,
            )
            continue

        entry_number += 1
        word       = _display_value(entry.get("word"))
        pos        = _display_value(humanize_part_of_speech(entry.get("part_of_speech")))
        morphology = _display_value(entry.get("morphology"))
        meaning    = _display_value(entry.get("meaning"))
        translation = _display_value(entry.get("translation"))
        show_translation = translation != "—" and not _same_content(meaning, translation)
        root         = _display_value(entry.get("root"))
        sanskrit_root = _display_value(entry.get("sanskrit_root"))
        etymology    = _display_value(entry.get("etymology"))

        has_data = _entry_has_lexical_data(entry)
        card_class = "gloss-card" if has_data else "gloss-card not-found"

        fallback_html = ""
        if entry.get("match_type") == "fallback":
            mf = _display_value(entry.get("matched_form"), "")
            if mf and mf != word:
                fallback_html = f'<span class="gloss-fallback"> ≈ {html.escape(mf)}</span>'

        not_found_html = "" if has_data else ' <span title="No encontrado en el diccionario">⚠️</span>'
        pos_badge = f'<span class="pos-badge">{html.escape(pos)}</span>' if pos != "—" else ""

        rows_html = "".join([
            _row("Morfología", morphology, "gloss-morph"),
            _row("Significado", meaning, "gloss-meaning"),
            (_row("Traducción", translation) if show_translation else ""),
            _row("Raíz", root, "gloss-root"),
            _row("Sánscrito", sanskrit_root),
            _row("Etimología", etymology, "gloss-etym"),
        ])

        st.markdown(
            f"""<div class="{card_class}">
  <div class="gloss-card-header">
    <span class="gloss-num">{entry_number}.</span>
    <span class="gloss-word">{html.escape(word)}</span>{fallback_html}{not_found_html}
    {pos_badge}
  </div>
  <div class="gloss-fields">{rows_html}</div>
</div>""",
            unsafe_allow_html=True,
        )


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
        fallback_suffix = ""
        if entry.get("match_type") == "fallback":
            matched_form = _display_value(entry.get("matched_form"), "")
            if matched_form and matched_form != word:
                fallback_suffix = f" [≈ {matched_form}]"
        pos = _display_value(humanize_part_of_speech(entry.get("part_of_speech")))
        morphology = _display_value(entry.get("morphology"))
        meaning = _display_value(entry.get("meaning"))
        translation = _display_value(entry.get("translation"))
        show_translation = translation != "—" and not _same_content(meaning, translation)
        root = _display_value(entry.get("root"))
        sanskrit_root = _display_value(entry.get("sanskrit_root"))
        etymology = _display_value(entry.get("etymology"))

        lines.extend(
            [
                f"{entry_number}. {word}{fallback_suffix}",
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
                f"  Etimología: {etymology}",
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
            border: 1px solid rgba(49,51,63,0.2);
            border-radius: 8px;
            padding: 0.38rem 0.6rem;
            background: white;
            cursor: pointer;
            font-size: 0.88rem;
            font-family: inherit;
            color: #374151;
            transition: background 0.15s;
        "
        onmouseover="this.style.background='#f9fafb'"
        onmouseout="this.style.background='white'"
        onclick="{function_name}()"
    >
        {button_label}
    </button>
    <div id="{status_id}" style="font-size:0.78rem;margin-top:0.25rem;color:#6b7280;text-align:center;"></div>
</div>
<script>
function {function_name}() {{
    const text = {encoded_text};
    const status = document.getElementById('{status_id}');
    navigator.clipboard.writeText(text)
        .then(() => {{ status.textContent = '\u2713 Copiado'; setTimeout(()=>status.textContent='',2000); }})
        .catch(() => {{ status.textContent = 'Error al copiar'; }});
}}
</script>
""",
        height=68,
    )


def _dict_name_to_option(dict_name):
    return "Digital Pali Dictionary"


def _dict_option_to_name(dict_option):
    return "dpd"


def _session_option_label(session_name, sessions):
    if not session_name:
        return "(Nueva sesión)"

    session = sessions.get(session_name, {})
    saved_at = str(session.get("saved_at", "")).strip()
    if saved_at:
        return f"{session_name} · {_format_saved_at_santiago(saved_at)}"
    return session_name


def _format_saved_at_santiago(saved_at):
    try:
        iso_value = saved_at
        if iso_value.endswith("Z"):
            iso_value = iso_value[:-1] + "+00:00"
        dt_utc = datetime.fromisoformat(iso_value)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
        dt_santiago = dt_utc.astimezone(ZoneInfo("America/Santiago"))
        return dt_santiago.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return saved_at


def load_saved_sessions():
    if not SAVED_SESSIONS_PATH.exists():
        return {}

    try:
        with open(SAVED_SESSIONS_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def persist_saved_sessions(sessions):
    _save_json_file(SAVED_SESSIONS_PATH, sessions)


def build_session_payload(dict_name, pali_text):
    return {
        "saved_at": _utcnow().isoformat(timespec="seconds"),

        "dict_name": dict_name,
        "pali_text": pali_text,
        "generated_gloss": bool(st.session_state.get("generated_gloss", False)),
        "gloss_entries": st.session_state.get("gloss_entries", []),
        "gloss_compact_text": st.session_state.get("gloss_compact_text", ""),
        "gloss_rich_text": st.session_state.get("gloss_rich_text", ""),
        "gloss_word_total": int(st.session_state.get("gloss_word_total", 0)),
        "gloss_found_words": int(st.session_state.get("gloss_found_words", 0)),
        "gloss_coverage": float(st.session_state.get("gloss_coverage", 0.0)),
    }


def apply_loaded_session(session_data):
    dict_name = "dpd"

    st.session_state["dict_option"] = _dict_name_to_option(dict_name)
    st.session_state["pali_text_input"] = str(session_data.get("pali_text", ""))

    generated_gloss = bool(session_data.get("generated_gloss", False))
    st.session_state["generated_gloss"] = generated_gloss
    st.session_state["gloss_entries"] = session_data.get("gloss_entries", []) if generated_gloss else []
    st.session_state["gloss_compact_text"] = str(session_data.get("gloss_compact_text", ""))
    st.session_state["gloss_rich_text"] = str(session_data.get("gloss_rich_text", ""))
    st.session_state["gloss_word_total"] = int(session_data.get("gloss_word_total", 0))
    st.session_state["gloss_found_words"] = int(session_data.get("gloss_found_words", 0))
    st.session_state["gloss_coverage"] = float(session_data.get("gloss_coverage", 0.0))

if not IS_CONSOLE_MODE:
    if "dict_option" not in st.session_state:
        st.session_state["dict_option"] = "Digital Pali Dictionary"
    if "pali_text_input" not in st.session_state:
        st.session_state["pali_text_input"] = ""
    if "generated_gloss" not in st.session_state:
        st.session_state.generated_gloss = False
        st.session_state.gloss_entries = []
        st.session_state.gloss_compact_text = ""
        st.session_state.gloss_rich_text = ""
        st.session_state.gloss_word_total = 0
        st.session_state.gloss_found_words = 0
        st.session_state.gloss_coverage = 0.0
    if "show_save_session_form" not in st.session_state:
        st.session_state["show_save_session_form"] = False
    if "save_session_name_input" not in st.session_state:
        st.session_state["save_session_name_input"] = ""
    if "pending_reset_save_input" not in st.session_state:
        st.session_state["pending_reset_save_input"] = False
    if "session_picker_name" not in st.session_state:
        st.session_state["session_picker_name"] = ""
    if "pending_session_picker_name" not in st.session_state:
        st.session_state["pending_session_picker_name"] = None
    if "pending_delete_session_name" not in st.session_state:
        st.session_state["pending_delete_session_name"] = ""

    st.markdown(
        """
        <style>
            /* ── Layout ── */
            .main .block-container {
                max-width: 720px;
                padding-top: 1.6rem;
                padding-bottom: 3rem;
                padding-left: 1.1rem;
                padding-right: 1.1rem;
            }

            /* ── Tipografía ── */
            h1 { font-size: 1.7rem !important; margin-bottom: 0.15rem !important; letter-spacing: -0.02em; }
            h2 { font-size: 1.15rem !important; }
            .stTextArea textarea { font-size: 1rem; line-height: 1.55; border-radius: 10px !important; }

            /* ── Header badge fuente ── */
            .source-badge {
                display: inline-block;
                background: #eef2ff;
                color: #3b4fa8;
                border: 1px solid #c7d2fe;
                border-radius: 20px;
                padding: 0.18rem 0.75rem;
                font-size: 0.78rem;
                font-weight: 500;
                margin-top: 0.25rem;
            }

            /* ── Tarjeta entrada de glosa ── */
            .gloss-card {
                background: #fff;
                border: 1px solid #e2e8f0;
                border-left: 4px solid #4f6ef7;
                border-radius: 10px;
                padding: 0.9rem 1.1rem 0.75rem 1.1rem;
                margin-bottom: 0.85rem;
                box-shadow: 0 1px 4px rgba(0,0,0,0.06);
            }
            .gloss-card.not-found {
                border-left-color: #f87171;
                background: #fff9f9;
            }
            .gloss-card-header {
                display: flex;
                align-items: baseline;
                gap: 0.5rem;
                margin-bottom: 0.5rem;
                flex-wrap: wrap;
            }
            .gloss-num {
                font-size: 0.78rem;
                color: #9ca3af;
                font-weight: 600;
                min-width: 1.4rem;
            }
            .gloss-word {
                font-size: 1.25rem;
                font-weight: 800;
                color: #1e3a6e;
                letter-spacing: 0.01em;
            }
            .gloss-fallback {
                font-size: 0.8rem;
                color: #6b7280;
                font-style: italic;
            }
            .pos-badge {
                display: inline-block;
                background: #dbeafe;
                color: #1d4ed8;
                border-radius: 6px;
                padding: 0.1rem 0.55rem;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }
            .not-found .pos-badge { background: #fee2e2; color: #b91c1c; }

            /* ── Filas de datos ── */
            .gloss-fields { display: grid; gap: 0.28rem; }
            .gloss-row {
                display: flex;
                gap: 0.4rem;
                font-size: 0.92rem;
                line-height: 1.45;
                flex-wrap: wrap;
            }
            .gloss-label {
                color: #6b7280;
                font-weight: 600;
                white-space: nowrap;
                min-width: 6.5rem;
                font-size: 0.82rem;
                text-transform: uppercase;
                letter-spacing: 0.03em;
                padding-top: 0.07rem;
            }
            .gloss-value { color: #1f2937; flex: 1; }
            .gloss-meaning .gloss-value { color: #111827; font-weight: 500; }
            .gloss-morph  .gloss-label { color: #7c3aed; }
            .gloss-morph  .gloss-value { color: #5b21b6; font-style: italic; }
            .gloss-root   .gloss-label { color: #065f46; }
            .gloss-root   .gloss-value { color: #047857; font-style: italic; }
            .gloss-etym   .gloss-label { color: #92400e; }
            .gloss-etym   .gloss-value { color: #78350f; font-style: italic; }
            .gloss-dash   { color: #d1d5db; }

            /* ── Separadores sintácticos ── */
            .sep-chip {
                display: inline-block;
                background: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 999px;
                padding: 0.07rem 0.55rem;
                font-size: 0.78rem;
                color: #9ca3af;
                margin: 0.25rem 0.1rem;
            }

            /* ── Barra de cobertura ── */
            .coverage-bar-wrap {
                background: #f3f4f6;
                border-radius: 999px;
                height: 6px;
                margin-top: 0.3rem;
                overflow: hidden;
            }
            .coverage-bar-fill {
                height: 100%;
                border-radius: 999px;
                background: linear-gradient(90deg, #4f6ef7, #06b6d4);
                transition: width 0.4s ease;
            }

            /* ── Métricas ── */
            [data-testid="stMetric"] {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 0.7rem 0.9rem !important;
            }
            [data-testid="stMetricValue"] { font-size: 1.35rem !important; color: #1e3a6e; }
            [data-testid="stMetricLabel"] { font-size: 0.75rem !important; color: #6b7280; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("📚 Pali Glosser")
    st.markdown("<span style='color:#6b7280;font-size:0.97rem;'>Glosa morfológica de textos pali · Digital Pali Dictionary</span>", unsafe_allow_html=True)

    # ── Carga de recursos ──────────────────────────────────────────────────
    dict_name = "dpd"
    with st.status("Cargando recursos DPD…", expanded=False) as status:
        dpd_db_path = get_dpd_db_path()
        try:
            dictionary = load_dictionary()
        except Exception as exc:
            status.update(label="Error cargando Digital Pali Dictionary", state="error")
            st.error(f"No se pudo cargar el diccionario DPD: {exc}")
            st.stop()

        if not isinstance(dictionary, dict) or not dictionary:
            status.update(label="Error cargando Digital Pali Dictionary", state="error")
            st.error("El diccionario DPD está vacío o inválido. Revisa `dpd_dictionary.json`.")
            st.stop()

        status.update(label="Digital Pali Dictionary listo", state="complete")

    if dpd_db_path:
        total_words = get_dpd_lookup_count(dpd_db_path)
        src_label = f"📦 dpd.db · {total_words:,} entradas lookup"
    else:
        total_words = len(dictionary)
        src_label = f"📄 DPD JSON · {total_words:,} entradas"
    st.markdown(f'<span class="source-badge">{src_label}</span>', unsafe_allow_html=True)

    st.write("")

    # ── Sesiones guardadas (colapsadas) ───────────────────────────────────
    saved_sessions = load_saved_sessions()
    session_options = [""] + sorted(saved_sessions.keys())

    pending_picker = st.session_state.get("pending_session_picker_name")
    if pending_picker is not None:
        st.session_state["session_picker_name"] = pending_picker if pending_picker in session_options else ""
        st.session_state["pending_session_picker_name"] = None

    if st.session_state.get("session_picker_name") not in session_options:
        st.session_state["session_picker_name"] = ""

    sessions_label = f"🗂 Sesiones guardadas ({len(saved_sessions)})" if saved_sessions else "🗂 Sesiones guardadas"
    with st.expander(sessions_label, expanded=False):
        session_col, load_col, delete_col = st.columns([3, 1, 1])
        with session_col:
            st.selectbox(
                "Seleccionar sesión",
                session_options,
                key="session_picker_name",
                format_func=lambda session_name: _session_option_label(session_name, saved_sessions),
                label_visibility="collapsed",
            )
        with load_col:
            load_clicked = st.button(
                "↩ Cargar",
                use_container_width=True,
                disabled=st.session_state.get("session_picker_name") == "",
            )
        with delete_col:
            delete_clicked = st.button(
                "🗑 Borrar",
                use_container_width=True,
                disabled=st.session_state.get("session_picker_name") == "",
            )

        if load_clicked:
            selected_name = st.session_state.get("session_picker_name")
            selected_session = saved_sessions.get(selected_name)
            if selected_session:
                apply_loaded_session(selected_session)
                st.toast(f"Sesión cargada: {selected_name}", icon="✅")
                st.rerun()
            else:
                st.toast("No se pudo cargar la sesión seleccionada.", icon="⚠️")

        if delete_clicked:
            selected_name = st.session_state.get("session_picker_name")
            if selected_name in saved_sessions:
                st.session_state["pending_delete_session_name"] = selected_name
                st.rerun()
            else:
                st.toast("No se pudo borrar la sesión seleccionada.", icon="⚠️")

        pending_delete_name = st.session_state.get("pending_delete_session_name", "")
        if pending_delete_name:
            st.warning(f"¿Seguro que deseas borrar **{pending_delete_name}**?")
            confirm_delete_col, cancel_delete_col = st.columns(2)
            with confirm_delete_col:
                confirm_delete_clicked = st.button("Sí, borrar", use_container_width=True, type="primary")
            with cancel_delete_col:
                cancel_delete_clicked = st.button("Cancelar", use_container_width=True)

            if confirm_delete_clicked:
                sessions = load_saved_sessions()
                sessions.pop(pending_delete_name, None)
                persist_saved_sessions(sessions)
                st.session_state["pending_delete_session_name"] = ""
                st.session_state["pending_session_picker_name"] = ""
                st.toast(f"Sesión borrada: {pending_delete_name}", icon="🗑️")
                st.rerun()

            if cancel_delete_clicked:
                st.session_state["pending_delete_session_name"] = ""
                st.rerun()

    # ── Entrada de texto ───────────────────────────────────────────────────
    pali_text = st.text_area(
        "✍️ Texto Pali",
        placeholder="Ej: namo tassa bhagavato arahato sammāsambuddhassa…",
        height=160,
        key="pali_text_input",
    )

    btn_col, example_col = st.columns([3, 1])
    with btn_col:
        generate_clicked = st.button("⚡ Generar glosa", use_container_width=True, type="primary")
    with example_col:
        if not pali_text.strip():
            if st.button("Ejemplo", use_container_width=True):
                st.session_state["pali_text_input"] = "namo tassa bhagavato arahato sammāsambuddhassa"
                st.rerun()

    if generate_clicked:
        if pali_text.strip():
            with st.spinner("Analizando texto pali…"):
                if dpd_db_path:
                    words = tuple(tokenize_pali_text(pali_text))
                    lookup_map = lookup_words_in_dpd(words, dpd_db_path)
                    gloss_entries = process_pali_with_lookup_map(
                        pali_text,
                        lookup_map,
                        fallback_dictionary=dictionary,
                    )
                else:
                    gloss_entries = process_pali_text(pali_text, dictionary)

                found_words = sum(
                    1
                    for entry in gloss_entries
                    if _entry_has_lexical_data(entry)
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
            st.toast("Glosa generada", icon="✨")
        else:
            st.session_state.generated_gloss = False
            st.session_state.gloss_entries = []
            st.session_state.gloss_rich_text = ""
            st.info("Ingresa texto en Pali para generar la glosa.")

    if st.session_state.generated_gloss:
        # ── Métricas de cobertura ──────────────────────────────────────────
        st.write("")
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Palabras", st.session_state.gloss_word_total)
        mc2.metric("Encontradas", st.session_state.gloss_found_words)
        mc3.metric("Cobertura", f"{st.session_state.gloss_coverage:.1f}%")
        cov = st.session_state.gloss_coverage
        st.markdown(
            f'<div class="coverage-bar-wrap"><div class="coverage-bar-fill" style="width:{min(cov,100):.1f}%"></div></div>',
            unsafe_allow_html=True,
        )
        st.write("")

        # ── Glosa filológica ───────────────────────────────────────────────
        st.subheader("📖 Glosa filológica")
        render_philological_gloss(st.session_state.gloss_entries)

        # ── Exportar ──────────────────────────────────────────────────────
        st.write("")
        st.markdown("**Exportar**")
        exp_col1, exp_col2, exp_col3 = st.columns(3)
        with exp_col1:
            st.download_button(
                label="⬇ Descargar .txt",
                data=st.session_state.gloss_compact_text,
                file_name="pali_gloss_compact.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with exp_col2:
            render_copy_button(
                st.session_state.gloss_rich_text,
                "📋 Copiar enriquecida",
                "rich",
            )
        with exp_col3:
            render_copy_button(
                st.session_state.gloss_compact_text,
                "📋 Copiar compacta",
                "compact",
            )

        # ── Guardar sesión ─────────────────────────────────────────────────
        st.divider()
        save_session_clicked = st.button("💾 Guardar sesión", use_container_width=True)
        if save_session_clicked:
            st.session_state["show_save_session_form"] = True

        if st.session_state.get("show_save_session_form", False):
            if st.session_state.get("pending_reset_save_input", False):
                st.session_state["save_session_name_input"] = ""
                st.session_state["pending_reset_save_input"] = False
            st.text_input(
                "Nombre de la sesión",
                key="save_session_name_input",
                placeholder="Ej: Clase SN 56.11",
            )
            save_col, cancel_col = st.columns(2)
            with save_col:
                confirm_save_clicked = st.button("Confirmar guardado", use_container_width=True, type="primary")
            with cancel_col:
                cancel_save_clicked = st.button("Cancelar", use_container_width=True)

            if cancel_save_clicked:
                st.session_state["show_save_session_form"] = False
                st.session_state["pending_reset_save_input"] = True
                st.rerun()

            if confirm_save_clicked:
                session_name = st.session_state.get("save_session_name_input", "").strip()
                if not session_name:
                    st.toast("Escribe un nombre para guardar la sesión.", icon="⚠️")
                else:
                    sessions = load_saved_sessions()
                    sessions[session_name] = build_session_payload(dict_name, pali_text)
                    persist_saved_sessions(sessions)
                    st.session_state["pending_session_picker_name"] = session_name
                    st.session_state["show_save_session_form"] = False
                    st.session_state["pending_reset_save_input"] = True
                    st.toast(f"Sesión guardada: {session_name}", icon="💾")
                    st.rerun()
    elif not pali_text.strip():
        st.info("✍️ Ingresa texto en Pali para comenzar.")

