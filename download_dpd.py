#!/usr/bin/env python3
"""
Script mejorado para procesar el Digital Pali Dictionary
Extrae datos de los archivos JSON del DPD
"""

import json
import os
import sqlite3
from pathlib import Path

def extract_dpd_json_data():
    """Extrae datos de los archivos JSON del DPD (si existen)."""

    dictionary = {}
    dpd_base = Path(
        os.environ.get(
            "DPD_JSON_DIR",
            str(Path(__file__).parent / "dpd-db"),
        )
    )
    
    # El DPD almacena datos en JSON en varios lugares
    # Intentar encontrar archivos con datos de palabras
    
    print("Buscando archivos de datos del DPD...")
    
    # Buscar archivos JSON que contengan palabras Pali
    for json_file in dpd_base.rglob("*.json"):
        # Saltar archivos de prueba
        if "test" in str(json_file):
            continue
        if "db_tests" in str(json_file):
            continue
            
        try:
            print(f"  Procesando: {json_file.name}...")
            
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Procesar depending on structure
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'pali' in item:
                            pali = item.get('pali', '').lower()
                            if pali and pali not in dictionary:
                                dictionary[pali] = {
                                    "meaning": item.get('meaning', item.get('definition', 'N/A')),
                                    "part_of_speech": item.get('pos', item.get('part_of_speech', 'noun')),
                                    "morphology": item.get('morphology', item.get('grammar', 'nom. sg.')),
                                    "root": item.get('root', pali[:3]),
                                    "translation": item.get('translation', item.get('meaning', 'N/A'))
                                }
                elif isinstance(data, dict):
                    # Si es un diccionario directo
                    for key, value in data.items():
                        if isinstance(value, dict) and ('meaning' in value or 'definition' in value):
                            pali = key.lower()
                            if not pali in dictionary:
                                dictionary[pali] = {
                                    "meaning": value.get('meaning', value.get('definition', 'N/A')),
                                    "part_of_speech": value.get('pos', value.get('part_of_speech', 'noun')),
                                    "morphology": value.get('morphology', value.get('grammar', 'nom. sg.')),
                                    "root": value.get('root', pali[:3]),
                                    "translation": value.get('translation', value.get('meaning', 'N/A'))
                                }
        except json.JSONDecodeError:
            # Archivo no es JSON válido, saltar
            continue
        except Exception as e:
            print(f"    Error: {e}")
            continue
    
    return dictionary


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


def _build_etymology_label(derived_from, construction, stem, pattern):
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


def build_dpd_from_sqlite(dpd_db_path: Path):
    """Build a full dictionary using the official dpd.db SQLite database."""

    dictionary = {}
    headwords = {}

    conn = sqlite3.connect(str(dpd_db_path))
    try:
        conn.row_factory = sqlite3.Row

        for row in conn.execute(
            """
            SELECT id, lemma_1, pos, grammar, meaning_1, meaning_2, meaning_lit,
                     root_key, root_sign, sanskrit, derived_from, construction, stem, pattern
            FROM dpd_headwords
            """
        ):
            meaning = row["meaning_1"] or row["meaning_2"] or ""
            if row["meaning_lit"]:
                meaning = (
                    f"{meaning} ({row['meaning_lit']})" if meaning else row["meaning_lit"]
                )
            root_key = row["root_key"] or ""
            root_sign = row["root_sign"] or ""
            root = f"{root_sign}{root_key}" if root_key else ""
            etymology = _build_etymology_label(
                (row["derived_from"] or "").strip(),
                (row["construction"] or "").strip(),
                (row["stem"] or "").strip(),
                (row["pattern"] or "").strip(),
            )

            headwords[row["id"]] = {
                "lemma": (row["lemma_1"] or "").strip(),
                "pos": row["pos"] or "",
                "grammar": row["grammar"] or "",
                "meaning": meaning,
                "root": root,
                "sanskrit_root": (row["sanskrit"] or "").strip(),
                "etymology": etymology,
            }

        for data in headwords.values():
            key = data["lemma"].lower().strip()
            if not key or key in dictionary:
                continue
            meaning = data["meaning"] or "N/A"
            dictionary[key] = {
                "meaning": meaning,
                "morphology": data["grammar"] or "N/A",
                "part_of_speech": data["pos"] or "N/A",
                "root": data["root"] or data["etymology"] or "N/A",
                "sanskrit_root": data["sanskrit_root"] or "N/A",
                "etymology": data["etymology"] or "N/A",
                "translation": meaning,
            }

        for row in conn.execute("SELECT lookup_key, headwords, grammar FROM lookup"):
            key = (row["lookup_key"] or "").strip().lower()
            if not key or key in dictionary:
                continue

            headword_ids = _load_json_field(row["headwords"], [])
            grammar_list = _load_json_field(row["grammar"], [])

            pos_list = []
            morph_list = []
            for item in grammar_list:
                if isinstance(item, (list, tuple)) and len(item) >= 3:
                    if item[1]:
                        pos_list.append(str(item[1]))
                    if item[2]:
                        morph_list.append(str(item[2]))

            meanings = []
            lemmas = []
            root = ""
            sanskrit_root = ""
            etymology = ""
            for headword_id in headword_ids:
                hw = headwords.get(headword_id)
                if not hw:
                    continue
                if hw["meaning"]:
                    meanings.append(hw["meaning"])
                if hw["lemma"]:
                    lemmas.append(hw["lemma"])
                if not root and hw["root"]:
                    root = hw["root"]
                if not sanskrit_root and hw.get("sanskrit_root"):
                    sanskrit_root = hw["sanskrit_root"]
                if not etymology and hw.get("etymology"):
                    etymology = hw["etymology"]

            meaning = "; ".join(_dedupe(meanings)) or "; ".join(_dedupe(lemmas))
            pos = "; ".join(_dedupe(pos_list))
            morph = "; ".join(_dedupe(morph_list))

            dictionary[key] = {
                "meaning": meaning or "N/A",
                "morphology": morph or "N/A",
                "part_of_speech": pos or "N/A",
                "root": root or etymology or "N/A",
                "sanskrit_root": sanskrit_root or "N/A",
                "etymology": etymology or "N/A",
                "translation": meaning or "N/A",
            }
    finally:
        conn.close()
    return dictionary

def use_backup_dpd():
    """Usa un diccionario de respaldo basado en DPD con términos comunes"""
    
    print("Usando diccionario extendido con términos DPD...")
    
    # Este es un subconjunto importante del DPD
    dictionary = {
        # Tres Joyas / Triple Refuge
        "buddha": {
            "meaning": "el Despierto, el Iluminado",
            "morphology": "masc. nom. sg.",
            "part_of_speech": "noun",
            "root": "budh",
            "translation": "The Awakened One, Buddha"
        },
        "dhammo": {
            "meaning": "doctrina, ley, fenómeno, verdad",
            "morphology": "masc. nom. sg.",
            "part_of_speech": "noun",
            "root": "dham",
            "translation": "Doctrine, Truth, Law, Phenomenon"
        },
        "dhamma": {
            "meaning": "doctrina, ley, fenómeno, verdad",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "dham",
            "translation": "Doctrine, Truth, Law, Phenomenon"
        },
        "sangha": {
            "meaning": "comunidad, congregación, asamblea",
            "morphology": "masc. nom. sg.",
            "part_of_speech": "noun",
            "root": "sang",
            "translation": "Community, Congregation, Assembly"
        },
        
        # Tres Características
        "anicca": {
            "meaning": "impermanencia, lo impermanente",
            "morphology": "adj. nom. sg.",
            "part_of_speech": "adj.",
            "root": "nic",
            "translation": "Impermanence, Impermanent"
        },
        "dukkha": {
            "meaning": "sufrimiento, insatisfacción, malestar",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "dukh",
            "translation": "Suffering, Unsatisfactoriness"
        },
        "anatta": {
            "meaning": "no-yo, insubstancialidad, ausencia de ser",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "att",
            "translation": "Non-self, No-soul, Insubstantiality"
        },
        
        # Cuatro Nobles Verdades
        "dukkhasacca": {
            "meaning": "verdad del sufrimiento",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "dukh",
            "translation": "Truth of Suffering"
        },
        "samudayasacca": {
            "meaning": "verdad del origen del sufrimiento",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "sam",
            "translation": "Truth of the Origin of Suffering"
        },
        "nirodhasacca": {
            "meaning": "verdad de la cesación del sufrimiento",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "nir",
            "translation": "Truth of the Cessation of Suffering"
        },
        "maggasacca": {
            "meaning": "verdad del camino hacia la cesación",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "mag",
            "translation": "Truth of the Path"
        },
        
        # Conceptos principales
        "tanha": {
            "meaning": "sed, deseo, apego, ansia",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "tanh",
            "translation": "Craving, Thirst, Desire"
        },
        "karma": {
            "meaning": "acción, acto, conducta",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "kar",
            "translation": "Action, Deed, Karma"
        },
        "nirvana": {
            "meaning": "nirvana, extinción, paz",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "nir",
            "translation": "Nirvana, Extinction, Enlightenment"
        },
        "sila": {
            "meaning": "virtud, moralidad, conducta ética",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "sil",
            "translation": "Morality, Virtue, Precept"
        },
        "samadhi": {
            "meaning": "concentración, meditación profunda",
            "morphology": "masc. nom. sg.",
            "part_of_speech": "noun",
            "root": "samadh",
            "translation": "Concentration, Mental Unification"
        },
        "panna": {
            "meaning": "sabiduría, discernimiento, comprensión",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "paj",
            "translation": "Wisdom, Discernment, Insight"
        },
        "bhikkhu": {
            "meaning": "monje", 
            "morphology": "masc. nom. sg.",
            "part_of_speech": "noun",
            "root": "bhik",
            "translation": "Monk, Mendicant"
        },
        "bhikkhuni": {
            "meaning": "monja",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "bhik",
            "translation": "Nun"
        },
        "sutta": {
            "meaning": "discurso, sutra, sección",
            "morphology": "neut. nom. sg.",
            "part_of_speech": "noun",
            "root": "sut",
            "translation": "Discourse, Sutra"
        },
        "vinaya": {
            "meaning": "disciplina, reglamentación monástica",
            "morphology": "masc. nom. sg.",
            "part_of_speech": "noun",
            "root": "vin",
            "translation": "Discipline, Monastic Code"
        },
        "metta": {
            "meaning": "benevolencia, amor compasivo",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "met",
            "translation": "Loving-kindness, Goodwill"
        },
        "mudita": {
            "meaning": "alegría compasiva, simpatía",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "mud",
            "translation": "Sympathetic Joy"
        },
        "karuna": {
            "meaning": "compasión, simpatía",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "kar",
            "translation": "Compassion"
        },
        "upekkha": {
            "meaning": "ecuanimidad, indiferencia imparcial",
            "morphology": "fem. nom. sg.",
            "part_of_speech": "noun",
            "root": "upekh",
            "translation": "Equanimity, Impartiality"
        },
        "brahmaviharas": {
            "meaning": "cuatro moradas divinas",
            "morphology": "fem. nom. pl.",
            "part_of_speech": "noun",
            "root": "brahm",
            "translation": "Brahma Viharas, Divine Abodes"
        },
    }
    
    return dictionary

if __name__ == "__main__":
    dpd_db_path = os.environ.get("DPD_DB_PATH", "").strip()
    candidate_paths = [
        Path(dpd_db_path) if dpd_db_path else None,
        Path(__file__).parent / "dpd-db" / "dpd.db",
        Path(__file__).parent / "dpd.db",
    ]

    selected_db_path = None
    for candidate in candidate_paths:
        if candidate and candidate.exists():
            selected_db_path = candidate
            break

    if selected_db_path:
        print(f"Using dpd.db at: {selected_db_path}")
        dictionary = build_dpd_from_sqlite(selected_db_path)
    else:
        # Fallback: try JSON extraction, then backup list
        dictionary = extract_dpd_json_data()
        if len(dictionary) < 100:
            print(
                f"Only {len(dictionary)} terms found via JSON. Using backup list."
            )
            dictionary = use_backup_dpd()

    output_path = str(Path(__file__).parent / "dpd_dictionary.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=2)

    print(f"Dictionary ready: {len(dictionary)} terms")
    print(f"Location: {output_path}")
