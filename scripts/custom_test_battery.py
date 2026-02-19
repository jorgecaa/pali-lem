#!/usr/bin/env python3

import argparse
import contextlib
import io
import logging
import os
import sys
from dataclasses import dataclass
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
        tokenize_pali_with_separators,
    )

from scripts.compare_with_dpdict import run_check  # noqa: E402


@dataclass
class TestResult:
    name: str
    passed: bool
    details: str


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


def _find_entry(gloss_entries, word):
    for entry in gloss_entries:
        if entry.get("word") == word:
            return entry
    return None


def _build_gloss(text: str, dictionary_name: str, db_path_override: str = ""):
    dictionary = load_dictionary("dpd")
    source = ""

    db_path = db_path_override or get_dpd_db_path()
    if db_path:
        words = tuple(tokenize_pali_text(text))
        lookup_map = lookup_words_in_dpd(words, db_path)
        gloss_entries = process_pali_with_lookup_map(text, lookup_map, fallback_dictionary=dictionary)
        source = f"dpd.db ({db_path})"
    else:
        gloss_entries = process_pali_text(text, dictionary)
        source = "dpd_dictionary.json"

    total_words = sum(1 for entry in gloss_entries if entry.get("part_of_speech") != "SEP")
    found_words = sum(1 for entry in gloss_entries if _entry_has_lexical_data(entry))
    coverage = (found_words / total_words * 100) if total_words else 0.0
    return gloss_entries, source, coverage, found_words, total_words


def run_offline_tests(dictionary_name: str, db_path: str, min_coverage: float):
    results = []

    text_main = "buddha dhamma saṅgha"
    gloss_main, source_main, coverage_main, found_main, total_main = _build_gloss(
        text_main,
        dictionary_name,
        db_path_override=db_path,
    )

    results.append(
        TestResult(
            name="base_coverage",
            passed=coverage_main >= min_coverage,
            details=f"source={source_main}; coverage={coverage_main:.1f}% ({found_main}/{total_main}); expected>={min_coverage:.1f}%",
        )
    )

    required_words_ok = True
    missing_required = []
    for word in ["buddha", "dhamma", "saṅgha"]:
        entry = _find_entry(gloss_main, word)
        if not entry or not _entry_has_lexical_data(entry):
            required_words_ok = False
            missing_required.append(word)

    results.append(
        TestResult(
            name="required_words_found",
            passed=required_words_ok,
            details="ok" if required_words_ok else f"missing={','.join(missing_required)}",
        )
    )

    text_etym = "anicca dukkha anattā"
    gloss_etym, source_etym, _, _, _ = _build_gloss(
        text_etym,
        dictionary_name,
        db_path_override=db_path,
    )

    etym_issues = []
    for word in ["anicca", "dukkha", "anattā"]:
        entry = _find_entry(gloss_etym, word)
        if not entry:
            etym_issues.append(f"{word}:not_found")
            continue
        root = str(entry.get("root", "")).strip()
        etymology = str(entry.get("etymology", "")).strip()
        if root in {"", "N/A", "---", "—"}:
            etym_issues.append(f"{word}:root_empty")
        if etymology in {"", "N/A", "---", "—"}:
            etym_issues.append(f"{word}:etym_empty")

    results.append(
        TestResult(
            name="etymology_not_omitted",
            passed=len(etym_issues) == 0,
            details=f"source={source_etym}; issues={';'.join(etym_issues)}" if etym_issues else "ok",
        )
    )

    text_punct = "buddha, dhamma. saṅgha"
    token_stream = tokenize_pali_with_separators(text_punct)
    separators = [token for token in token_stream if token.get("kind") == "separator"]
    has_expected_separators = any(token.get("surface") == "," for token in separators) and any(
        token.get("surface") == "." for token in separators
    )

    results.append(
        TestResult(
            name="tokenizer_separators",
            passed=has_expected_separators,
            details=f"separator_count={len(separators)}",
        )
    )

    compact = generate_compact_gloss(gloss_main)
    rich = generate_rich_gloss_text(gloss_main)
    format_ok = (
        "buddha" in compact.lower()
        and "dhamma" in compact.lower()
        and "raíz" in rich.lower()
        and "categoría" in rich.lower()
    )

    results.append(
        TestResult(
            name="output_format_integrity",
            passed=format_ok,
            details="compact+rich fields present" if format_ok else "missing expected labels/words",
        )
    )

    return results


def run_online_tests(db_path: str, words: list[str], min_field_match: float):
    rows = run_check(Path(db_path), words)
    total = len(rows)
    presence_ok = sum(1 for row in rows if row["presence_consistent"])

    tested_fields = sum(len(row["field_hits"]) for row in rows)
    matched_fields = sum(sum(1 for hit in row["field_hits"].values() if hit) for row in rows)

    presence_ratio = (presence_ok / total) if total else 0.0
    field_ratio = (matched_fields / tested_fields) if tested_fields else 0.0

    return [
        TestResult(
            name="online_presence_consistency",
            passed=presence_ratio == 1.0,
            details=f"{presence_ok}/{total} ({presence_ratio*100:.1f}%)",
        ),
        TestResult(
            name="online_field_match_threshold",
            passed=field_ratio >= min_field_match,
            details=f"{matched_fields}/{tested_fields} ({field_ratio*100:.1f}%), expected>={min_field_match*100:.1f}%",
        ),
    ]


def print_summary(results: list[TestResult]):
    print("=" * 88)
    print("Batería personalizada de validación de salida")
    print("=" * 88)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.details}")

    failures = [result for result in results if not result.passed]
    print("-" * 88)
    print(f"Total: {len(results)} | PASS: {len(results)-len(failures)} | FAIL: {len(failures)}")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(
        description="Batería personalizada para probar y validar la salida de Pali Glosser"
    )
    parser.add_argument("--dict", choices=["dpd"], default="dpd", help="Diccionario a probar (solo dpd)")
    parser.add_argument("--db", default="", help="Ruta explícita a dpd.db")
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=90.0,
        help="Cobertura mínima esperada para test base (porcentaje)",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Activa pruebas online contra dpdict.net",
    )
    parser.add_argument(
        "--online-words",
        default="buddha,dhamma,saṅgha,anicca,dukkha,anattā",
        help="Palabras para test online separadas por coma",
    )
    parser.add_argument(
        "--min-online-field-match",
        type=float,
        default=0.75,
        help="Umbral mínimo de match de campos en test online (0-1)",
    )
    args = parser.parse_args()

    db_path = args.db or get_dpd_db_path()

    results = run_offline_tests(
        dictionary_name=args.dict,
        db_path=db_path,
        min_coverage=args.min_coverage,
    )

    if args.online:
        if not db_path:
            results.append(
                TestResult(
                    name="online_precondition_db",
                    passed=False,
                    details="No hay dpd.db disponible para comparación online",
                )
            )
        else:
            online_words = [item.strip() for item in args.online_words.split(",") if item.strip()]
            results.extend(run_online_tests(db_path=db_path, words=online_words, min_field_match=args.min_online_field_match))

    exit_code = print_summary(results)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
