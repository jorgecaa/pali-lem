#!/usr/bin/env python3

import argparse
import contextlib
import io
import logging
import os
import sys
from pathlib import Path

os.environ["PALI_LEM_NO_UI"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for logger_name in ["streamlit", "streamlit.runtime", "streamlit.runtime.caching", "streamlit.runtime.scriptrunner_utils"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

with contextlib.redirect_stderr(io.StringIO()):
    from streamlit_app import (  # noqa: E402
        generate_compact_gloss,
        generate_rich_gloss_text,
        get_dpd_db_path,
        load_dictionary,
        lookup_words_in_dpd,
        process_pali_text,
        process_pali_with_lookup_map,
        tokenize_pali_text,
    )


    def _entry_has_lexical_data(entry: dict) -> bool:
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
        return any(str(value or "").strip() not in placeholders for value in fields if str(value or "").strip())


def read_input_text(args) -> str:
    if args.text and args.file:
        raise SystemExit("Usa solo una de estas opciones: --text o --file")

    if args.text:
        return args.text

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            raise SystemExit(f"No existe el archivo: {file_path}")
        return file_path.read_text(encoding="utf-8")

    stdin_data = sys.stdin.read()
    if stdin_data.strip():
        return stdin_data

    raise SystemExit("Debes pasar texto por --text, --file o stdin")


def run_gloss(text: str, dictionary_name: str, db_path_override: str = "", debug: bool = False):
    with contextlib.redirect_stderr(io.StringIO()):
        dictionary = load_dictionary(dictionary_name)

        if dictionary_name == "dpd":
            dpd_db_path = db_path_override or get_dpd_db_path()
            if dpd_db_path:
                words = tuple(tokenize_pali_text(text))
                lookup_map = lookup_words_in_dpd(words, dpd_db_path)
                local_fallback = load_dictionary("local")
                combined_fallback = {**local_fallback, **dictionary}
                gloss_entries = process_pali_with_lookup_map(
                    text,
                    lookup_map,
                    fallback_dictionary=combined_fallback,
                )
                source = f"dpd.db ({dpd_db_path})"
            else:
                gloss_entries = process_pali_text(text, dictionary)
                source = "dpd_dictionary.json (fallback)"
        else:
            gloss_entries = process_pali_text(text, dictionary)
            source = "pali_dictionary.json"

    found_words = sum(1 for entry in gloss_entries if _entry_has_lexical_data(entry))
    total_words = sum(1 for entry in gloss_entries if entry.get("part_of_speech") != "SEP")
    coverage = (found_words / total_words * 100) if total_words else 0.0

    if debug:
        print(f"[debug] source={source}")
        print(f"[debug] tokens_total={total_words} tokens_found={found_words} coverage={coverage:.1f}%")
        missing = [e.get("word") for e in gloss_entries if e.get("part_of_speech") != "SEP" and not _entry_has_lexical_data(e)]
        if missing:
            print(f"[debug] missing_words={','.join(missing)}")

    return gloss_entries, coverage


def main():
    parser = argparse.ArgumentParser(
        description="Prueba Pali Glosser por consola con argv y modo debug"
    )
    parser.add_argument("--text", help="Texto Pali directo")
    parser.add_argument("--file", help="Archivo UTF-8 con texto Pali")
    parser.add_argument(
        "--dict",
        dest="dictionary_name",
        choices=["dpd", "local"],
        default="dpd",
        help="Fuente de diccionario (default: dpd)",
    )
    parser.add_argument("--db", default="", help="Ruta explícita a dpd.db")
    parser.add_argument(
        "--format",
        choices=["compact", "rich"],
        default="compact",
        help="Formato de salida (default: compact)",
    )
    parser.add_argument("--debug", action="store_true", help="Imprime información de depuración")
    args = parser.parse_args()

    text = read_input_text(args)
    gloss_entries, coverage = run_gloss(
        text=text,
        dictionary_name=args.dictionary_name,
        db_path_override=args.db,
        debug=args.debug,
    )

    if args.format == "rich":
        output = generate_rich_gloss_text(gloss_entries)
    else:
        output = generate_compact_gloss(gloss_entries)

    print(output)
    if args.debug:
        print(f"[debug] final_coverage={coverage:.1f}%")


if __name__ == "__main__":
    main()
