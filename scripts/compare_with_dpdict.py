#!/usr/bin/env python3

import argparse
import html
import json
import re
import sqlite3
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_WORDS = [
    "buddha",
    "dhamma",
    "saṅgha",
    "bhikkhu",
    "nibbāna",
    "mettā",
    "dukkha",
    "anicca",
    "anattā",
    "sati",
    "paññā",
    "kamma",
    "evaṃ",
    "dhammassa",
    "buddhānaṃ",
]


def normalize_token(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip().lower()).replace("ṁ", "ṃ")


def load_json_field(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_text_for_match(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "").lower()
    text = text.replace("ṁ", "ṃ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_html_to_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_root_label(root_sign: str, root_key: str, root_group: str) -> str:
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
            return f"{base_root} ({group_label})" if group_label else base_root
        return f"{base_root} · {group_display}"
    return base_root


def fetch_root_group(conn, root_key, root_sign, cache):
    if not root_key:
        return ""
    cache_key = (str(root_sign or ""), str(root_key))
    if cache_key in cache:
        return cache[cache_key]

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
    value = str(row["root_group"]).strip() if row and row["root_group"] is not None else ""
    cache[cache_key] = value
    return value


def lookup_local_word(conn, word: str, root_group_cache: dict) -> dict:
    row = conn.execute(
        "SELECT lookup_key, headwords, grammar FROM lookup WHERE lookup_key = ?",
        (word,),
    ).fetchone()

    if not row:
        lemma_row = conn.execute(
            """
            SELECT lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit, sanskrit, root_key, root_sign
            FROM dpd_headwords
            WHERE lower(lemma_1) = ?
            LIMIT 1
            """,
            (word,),
        ).fetchone()
        if not lemma_row:
            return {}

        meaning = lemma_row["meaning_1"] or lemma_row["meaning_2"] or ""
        if lemma_row["meaning_lit"]:
            meaning = f"{meaning} ({lemma_row['meaning_lit']})" if meaning else lemma_row["meaning_lit"]
        root_group = fetch_root_group(
            conn,
            lemma_row["root_key"] or "",
            lemma_row["root_sign"] or "",
            root_group_cache,
        )
        return {
            "found": True,
            "meaning": meaning or "N/A",
            "part_of_speech": lemma_row["pos"] or "N/A",
            "morphology": lemma_row["grammar"] or "N/A",
            "root": build_root_label(lemma_row["root_sign"] or "", lemma_row["root_key"] or "", root_group) or "N/A",
            "sanskrit_root": (lemma_row["sanskrit"] or "").strip() or "N/A",
        }

    grammar_list = load_json_field(row["grammar"], [])
    pos_list = []
    morph_list = []
    if isinstance(grammar_list, list):
        for item in grammar_list:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                if item[1]:
                    pos_list.append(str(item[1]))
                if item[2]:
                    morph_list.append(str(item[2]))

    parsed_ids = load_json_field(row["headwords"], [])
    headword_ids = [item for item in dedupe(parsed_ids) if isinstance(item, int)]
    headwords_by_id = {}
    if headword_ids:
        placeholders = ",".join("?" for _ in headword_ids)
        rows = conn.execute(
            f"""
            SELECT id, lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit, sanskrit, root_key, root_sign
            FROM dpd_headwords
            WHERE id IN ({placeholders})
            """,
            headword_ids,
        ).fetchall()
        headwords_by_id = {hw["id"]: hw for hw in rows}

    meanings = []
    lemmas = []
    headword_pos_list = []
    headword_morph_list = []
    root_key_value = ""
    root_sign_value = ""
    sanskrit_root = ""
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

    root_group = fetch_root_group(conn, root_key_value, root_sign_value, root_group_cache)
    root_label = build_root_label(root_sign_value, root_key_value, root_group)
    merged_meaning = "; ".join(dedupe(meanings)) or "; ".join(dedupe(lemmas))
    final_pos = "; ".join(dedupe(pos_list) or dedupe(headword_pos_list))
    final_morph = "; ".join(dedupe(morph_list) or dedupe(headword_morph_list))

    return {
        "found": True,
        "meaning": merged_meaning or "N/A",
        "part_of_speech": final_pos or "N/A",
        "morphology": final_morph or "N/A",
        "root": root_label or "N/A",
        "sanskrit_root": sanskrit_root or "N/A",
    }


def fetch_remote(word: str) -> dict:
    url = "https://dpdict.net/search_json?q=" + urllib.parse.quote(word)
    request = urllib.request.Request(url, headers={"User-Agent": "pali-lem-consistency-check/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))

    summary_html = payload.get("summary_html", "") or ""
    dpd_html = payload.get("dpd_html", "") or ""
    remote_has_results = "No results found" not in dpd_html and bool(summary_html.strip() or dpd_html.strip())
    remote_text = normalize_text_for_match(strip_html_to_text(summary_html + " " + dpd_html))
    return {
        "has_results": remote_has_results,
        "summary_len": len(summary_html),
        "dpd_len": len(dpd_html),
        "text": remote_text,
    }


def tokenize_field_value(value: str):
    base = normalize_text_for_match(value)
    chunks = [chunk.strip() for chunk in re.split(r"[;,]", base) if chunk.strip()]
    probes = []
    for chunk in chunks:
        cleaned = re.sub(r"\([^\)]*\)", " ", chunk)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            probes.append(cleaned)
    if not probes and base:
        probes.append(base)
    return probes[:6]


def _root_candidates(local_value: str):
    normalized = normalize_text_for_match(local_value)
    if not normalized:
        return []

    first_chunk = normalized.split(";")[0]
    first_chunk = first_chunk.split("·")[0]
    first_chunk = re.sub(r"\([^\)]*\)", " ", first_chunk)
    first_chunk = first_chunk.replace("√", " ")
    first_chunk = re.sub(r"\s+", " ", first_chunk).strip()
    probes = []
    if first_chunk:
        probes.append(first_chunk)
    compact = re.sub(r"[^a-zāīūṅñṭḍṇḷṃ]+", "", first_chunk)
    if compact and compact not in probes:
        probes.append(compact)
    return [probe for probe in probes if len(probe) >= 2]


def field_matches_remote(field: str, local_value: str, remote_text: str) -> bool:
    if field == "root":
        for probe in _root_candidates(local_value):
            if probe in remote_text:
                return True
        return False

    probes = tokenize_field_value(local_value)
    if not probes:
        return False
    for probe in probes:
        if len(probe) >= 3 and probe in remote_text:
            return True
    return False


def run_check(db_path: Path, words):
    words = [normalize_token(word) for word in words if word.strip()]
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    root_group_cache = {}

    rows = []
    try:
        for word in words:
            local = lookup_local_word(conn, word, root_group_cache)
            local_found = bool(local)
            remote = fetch_remote(word)

            row = {
                "word": word,
                "local_found": local_found,
                "remote_found": remote["has_results"],
                "presence_consistent": local_found == remote["has_results"],
                "field_hits": {},
            }

            if local_found and remote["has_results"]:
                for field in ["part_of_speech", "morphology", "meaning", "root", "sanskrit_root"]:
                    value = (local.get(field) or "").strip()
                    if value and value not in {"N/A", "---"}:
                        row["field_hits"][field] = field_matches_remote(field, value, remote["text"])
                row["local_preview"] = {
                    "part_of_speech": local.get("part_of_speech", "N/A"),
                    "morphology": local.get("morphology", "N/A"),
                    "meaning": local.get("meaning", "N/A")[:160],
                    "root": local.get("root", "N/A"),
                    "sanskrit_root": local.get("sanskrit_root", "N/A"),
                }
            rows.append(row)
    finally:
        conn.close()

    return rows


def print_report(rows):
    total = len(rows)
    presence_ok = sum(1 for row in rows if row["presence_consistent"])
    tested_fields = 0
    matched_fields = 0

    for row in rows:
        tested_fields += len(row["field_hits"])
        matched_fields += sum(1 for hit in row["field_hits"].values() if hit)

    print("=" * 88)
    print("Comparación simple local (dpd.db) vs dpdict.net")
    print("=" * 88)
    print(f"Palabras probadas: {total}")
    print(f"Consistencia de presencia (hay/no hay resultado): {presence_ok}/{total} ({(presence_ok/total*100 if total else 0):.1f}%)")
    if tested_fields:
        print(f"Coincidencia de campos extraídos: {matched_fields}/{tested_fields} ({(matched_fields/tested_fields*100):.1f}%)")
    else:
        print("Coincidencia de campos extraídos: sin campos comparables")
    print("-" * 88)

    for row in rows:
        status = "OK" if row["presence_consistent"] else "DIFF"
        print(f"{row['word']:<14} | presencia: {status} | local={row['local_found']} remote={row['remote_found']}")
        if row["field_hits"]:
            hits = ", ".join(f"{k}:{'OK' if v else 'NO'}" for k, v in row["field_hits"].items())
            print(f"{'':14} | campos: {hits}")

    print("-" * 88)
    suspect = [row for row in rows if row["remote_found"] and not row["local_found"]]
    weak = [
        row
        for row in rows
        if row["field_hits"] and sum(1 for hit in row["field_hits"].values() if hit) < len(row["field_hits"])
    ]
    if suspect:
        print("Posibles faltantes de extracción (remoto sí, local no):")
        print(", ".join(row["word"] for row in suspect))
    else:
        print("No se detectaron faltantes obvios de presencia.")

    if weak:
        print("Palabras con campos parcialmente inconsistentes:")
        print(", ".join(row["word"] for row in weak))
    else:
        print("Todos los campos comparables coinciden en esta muestra.")


def main():
    parser = argparse.ArgumentParser(description="Compara extracción local de DPD con respuestas de dpdict.net")
    parser.add_argument(
        "--db",
        default="dpd-db/dpd.db",
        help="Ruta a dpd.db (por defecto: dpd-db/dpd.db)",
    )
    parser.add_argument(
        "--words",
        default=",".join(DEFAULT_WORDS),
        help="Lista de palabras separadas por coma",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"No se encontró la base: {db_path}")

    words = [item.strip() for item in args.words.split(",") if item.strip()]
    rows = run_check(db_path=db_path, words=words)
    print_report(rows)


if __name__ == "__main__":
    main()
