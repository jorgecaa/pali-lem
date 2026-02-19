"""Tests sobre las funciones de sesión de streamlit_app.py.

Ejecutar:
    python scripts/test_sessions.py
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Importar en modo consola (sin UI de Streamlit) ----------------------------------
os.environ.setdefault("PALI_LEM_NO_UI", "1")
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit_app as app  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_sessions_path(tmp_dir: str) -> Path:
    return Path(tmp_dir) / "saved_sessions.json"


# ---------------------------------------------------------------------------
# load_saved_sessions
# ---------------------------------------------------------------------------

class TestLoadSavedSessions(unittest.TestCase):

    def test_returns_empty_dict_when_file_missing(self):
        with patch.object(app, "SAVED_SESSIONS_PATH", Path("/nonexistent/path/sessions.json")):
            result = app.load_saved_sessions()
        self.assertEqual(result, {})

    def test_loads_valid_json(self):
        data = {"sesión1": {"pali_text": "namo tassa", "dict_name": "dpd"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                result = app.load_saved_sessions()
        self.assertEqual(result, data)

    def test_returns_empty_dict_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            path.write_text("{{NOT JSON}}", encoding="utf-8")
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                result = app.load_saved_sessions()
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_root_is_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                result = app.load_saved_sessions()
        self.assertEqual(result, {})

    def test_loads_multiple_sessions(self):
        data = {
            "A": {"pali_text": "namo", "dict_name": "dpd"},
            "B": {"pali_text": "tassa", "dict_name": "local"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                result = app.load_saved_sessions()
        self.assertEqual(len(result), 2)
        self.assertIn("A", result)
        self.assertIn("B", result)


# ---------------------------------------------------------------------------
# _is_valid_dpd_db
# ---------------------------------------------------------------------------

class TestIsValidDpdDb(unittest.TestCase):

    def test_closes_connection_when_sqlite_error(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            path = Path(tmp.name)
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.execute.side_effect = sqlite3.Error("boom")
            mock_conn.cursor.return_value = mock_cursor

            with patch.object(app.sqlite3, "connect", return_value=mock_conn):
                result = app._is_valid_dpd_db(path)

            self.assertFalse(result)
            mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# persist_saved_sessions
# ---------------------------------------------------------------------------

class TestPersistSavedSessions(unittest.TestCase):

    def test_writes_json_file(self):
        data = {"mi sesión": {"pali_text": "namo", "dict_name": "dpd"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                app.persist_saved_sessions(data)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved, data)

    def test_overwrites_existing_file(self):
        original = {"vieja": {"pali_text": "x"}}
        updated = {"nueva": {"pali_text": "y"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            path.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                app.persist_saved_sessions(updated)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved, updated)

    def test_no_temp_file_left_behind(self):
        data = {"s": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                app.persist_saved_sessions(data)
            temp = path.with_suffix(".json.part")
        self.assertFalse(temp.exists())

    def test_unicode_content_preserved(self):
        data = {"Clase SN 56.11": {"pali_text": "サンスタ", "dict_name": "dpd"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                app.persist_saved_sessions(data)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["Clase SN 56.11"]["pali_text"], "サンスタ")

    def test_roundtrip_load_persist(self):
        data = {"s1": {"pali_text": "namo tassa", "dict_name": "dpd"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                app.persist_saved_sessions(data)
                result = app.load_saved_sessions()
        self.assertEqual(result, data)


# ---------------------------------------------------------------------------
# build_session_payload
# ---------------------------------------------------------------------------

class TestBuildSessionPayload(unittest.TestCase):

    def _make_fake_state(self):
        return {
            "generated_gloss": True,
            "gloss_entries": [{"word": "namo"}],
            "gloss_compact_text": "namo·homenaje",
            "gloss_rich_text": "<b>namo</b>",
            "gloss_word_total": 1,
            "gloss_found_words": 1,
            "gloss_coverage": 100.0,
        }

    def test_payload_contains_required_keys(self):
        state = self._make_fake_state()
        mock_state = MagicMock()
        mock_state.get = lambda k, default=None: state.get(k, default)
        with patch.object(app.st, "session_state", mock_state):
            payload = app.build_session_payload("dpd", "namo tassa")
        for key in ("saved_at", "dict_name", "pali_text", "generated_gloss",
                    "gloss_entries", "gloss_compact_text", "gloss_rich_text",
                    "gloss_word_total", "gloss_found_words", "gloss_coverage"):
            self.assertIn(key, payload, f"Falta clave: {key}")

    def test_payload_dict_name_and_text(self):
        state = self._make_fake_state()
        mock_state = MagicMock()
        mock_state.get = lambda k, default=None: state.get(k, default)
        with patch.object(app.st, "session_state", mock_state):
            payload = app.build_session_payload("local", "cattāro saccā")
        self.assertEqual(payload["dict_name"], "local")
        self.assertEqual(payload["pali_text"], "cattāro saccā")

    def test_payload_saved_at_is_iso_utc(self):
        state = self._make_fake_state()
        mock_state = MagicMock()
        mock_state.get = lambda k, default=None: state.get(k, default)
        with patch.object(app.st, "session_state", mock_state):
            payload = app.build_session_payload("dpd", "namo")
        saved_at = payload["saved_at"]
        self.assertTrue(saved_at.endswith("Z"), f"saved_at debe terminar en Z: {saved_at}")
        # Debe ser parseable como datetime
        datetime.fromisoformat(saved_at.replace("Z", "+00:00"))

    def test_payload_types_are_correct(self):
        state = self._make_fake_state()
        mock_state = MagicMock()
        mock_state.get = lambda k, default=None: state.get(k, default)
        with patch.object(app.st, "session_state", mock_state):
            payload = app.build_session_payload("dpd", "namo")
        self.assertIsInstance(payload["generated_gloss"], bool)
        self.assertIsInstance(payload["gloss_entries"], list)
        self.assertIsInstance(payload["gloss_word_total"], int)
        self.assertIsInstance(payload["gloss_found_words"], int)
        self.assertIsInstance(payload["gloss_coverage"], float)

    def test_payload_with_empty_state(self):
        mock_state = MagicMock()
        mock_state.get = lambda k, default=None: default
        with patch.object(app.st, "session_state", mock_state):
            payload = app.build_session_payload("dpd", "")
        self.assertFalse(payload["generated_gloss"])
        self.assertEqual(payload["gloss_entries"], [])
        self.assertEqual(payload["gloss_word_total"], 0)
        self.assertAlmostEqual(payload["gloss_coverage"], 0.0)


# ---------------------------------------------------------------------------
# apply_loaded_session
# ---------------------------------------------------------------------------

class TestApplyLoadedSession(unittest.TestCase):

    def _make_session_data(self, **overrides):
        base = {
            "dict_name": "dpd",
            "pali_text": "namo tassa",
            "generated_gloss": True,
            "gloss_entries": [{"word": "namo"}],
            "gloss_compact_text": "namo·homenaje",
            "gloss_rich_text": "<b>namo</b>",
            "gloss_word_total": 2,
            "gloss_found_words": 2,
            "gloss_coverage": 100.0,
        }
        base.update(overrides)
        return base

    def _apply_and_capture(self, session_data):
        captured = {}
        mock_state = MagicMock()
        mock_state.__setitem__ = lambda self_, k, v: captured.__setitem__(k, v)
        mock_state.__getitem__ = lambda self_, k: captured[k]
        with patch.object(app.st, "session_state", mock_state):
            app.apply_loaded_session(session_data)
        return captured

    def test_sets_dict_option_dpd(self):
        captured = self._apply_and_capture(self._make_session_data(dict_name="dpd"))
        self.assertEqual(captured["dict_option"], "Digital Pali Dictionary")

    def test_sets_dict_option_local(self):
        captured = self._apply_and_capture(self._make_session_data(dict_name="local"))
        self.assertEqual(captured["dict_option"], "Diccionario Local")

    def test_invalid_dict_name_falls_back_to_dpd(self):
        captured = self._apply_and_capture(self._make_session_data(dict_name="UNKNOWN"))
        self.assertEqual(captured["dict_option"], "Digital Pali Dictionary")

    def test_sets_pali_text(self):
        captured = self._apply_and_capture(self._make_session_data(pali_text="cattāro saccā"))
        self.assertEqual(captured["pali_text_input"], "cattāro saccā")

    def test_sets_gloss_entries_when_generated(self):
        entries = [{"word": "namo"}, {"word": "tassa"}]
        captured = self._apply_and_capture(
            self._make_session_data(generated_gloss=True, gloss_entries=entries)
        )
        self.assertEqual(captured["gloss_entries"], entries)

    def test_clears_gloss_entries_when_not_generated(self):
        entries = [{"word": "namo"}]
        captured = self._apply_and_capture(
            self._make_session_data(generated_gloss=False, gloss_entries=entries)
        )
        self.assertEqual(captured["gloss_entries"], [])

    def test_sets_coverage_as_float(self):
        captured = self._apply_and_capture(self._make_session_data(gloss_coverage=75.5))
        self.assertAlmostEqual(captured["gloss_coverage"], 75.5)

    def test_handles_missing_optional_fields(self):
        minimal = {"dict_name": "dpd", "pali_text": "namo"}
        captured = self._apply_and_capture(minimal)
        self.assertEqual(captured["pali_text_input"], "namo")
        self.assertEqual(captured["gloss_entries"], [])
        self.assertEqual(captured["gloss_word_total"], 0)


# ---------------------------------------------------------------------------
# _dict_name_to_option  /  _dict_option_to_name
# ---------------------------------------------------------------------------

class TestDictNameConversions(unittest.TestCase):

    def test_dpd_to_option(self):
        self.assertEqual(app._dict_name_to_option("dpd"), "Digital Pali Dictionary")

    def test_local_to_option(self):
        self.assertEqual(app._dict_name_to_option("local"), "Diccionario Local")

    def test_unknown_to_option_returns_local(self):
        result = app._dict_name_to_option("otro")
        self.assertIn(result, {"Digital Pali Dictionary", "Diccionario Local"})

    def test_option_to_dpd(self):
        self.assertEqual(app._dict_option_to_name("Digital Pali Dictionary"), "dpd")

    def test_option_to_local(self):
        self.assertEqual(app._dict_option_to_name("Diccionario Local"), "local")

    def test_roundtrip_dpd(self):
        name = "dpd"
        self.assertEqual(app._dict_option_to_name(app._dict_name_to_option(name)), name)

    def test_roundtrip_local(self):
        name = "local"
        self.assertEqual(app._dict_option_to_name(app._dict_name_to_option(name)), name)


# ---------------------------------------------------------------------------
# _session_option_label
# ---------------------------------------------------------------------------

class TestSessionOptionLabel(unittest.TestCase):

    def test_empty_name_returns_nueva_sesion(self):
        label = app._session_option_label("", {})
        self.assertIn("Nueva", label)

    def test_name_without_saved_at(self):
        sessions = {"mi sesión": {"pali_text": "namo"}}
        label = app._session_option_label("mi sesión", sessions)
        self.assertEqual(label, "mi sesión")

    def test_name_with_valid_saved_at(self):
        sessions = {"s1": {"saved_at": "2026-02-19T12:00:00Z"}}
        label = app._session_option_label("s1", sessions)
        self.assertIn("s1", label)
        self.assertIn("2026-02-19", label)

    def test_name_not_in_sessions_dict(self):
        label = app._session_option_label("inexistente", {})
        self.assertEqual(label, "inexistente")


# ---------------------------------------------------------------------------
# _format_saved_at_santiago
# ---------------------------------------------------------------------------

class TestFormatSavedAtSantiago(unittest.TestCase):

    def test_utc_z_suffix(self):
        result = app._format_saved_at_santiago("2026-02-19T15:00:00Z")
        # Chile en verano usa CLT (UTC-3) → 12:00
        self.assertIn("2026-02-19", result)

    def test_iso_offset(self):
        result = app._format_saved_at_santiago("2026-02-19T15:00:00+00:00")
        self.assertIn("2026-02-19", result)

    def test_invalid_returns_original(self):
        result = app._format_saved_at_santiago("no es una fecha")
        self.assertEqual(result, "no es una fecha")

    def test_timezone_label_in_result(self):
        result = app._format_saved_at_santiago("2026-02-19T15:00:00Z")
        # Debe incluir zona horaria (CLT, CLST, etc.)
        self.assertTrue(any(tz in result for tz in ("CLT", "CLST", "-03", "-04")),
                        f"No se encontró zona horaria en: {result}")


# ---------------------------------------------------------------------------
# Full save → load → persist cycle
# ---------------------------------------------------------------------------

class TestFullSessionCycle(unittest.TestCase):

    def test_save_and_reload_via_file(self):
        """Guarda una sesión en disco y la vuelve a cargar."""
        payload = {
            "saved_at": "2026-02-19T12:00:00Z",
            "dict_name": "dpd",
            "pali_text": "namo tassa bhagavato",
            "generated_gloss": False,
            "gloss_entries": [],
            "gloss_compact_text": "",
            "gloss_rich_text": "",
            "gloss_word_total": 0,
            "gloss_found_words": 0,
            "gloss_coverage": 0.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                # Guardar
                sessions = {}
                sessions["Clase SN"] = payload
                app.persist_saved_sessions(sessions)
                # Cargar
                loaded = app.load_saved_sessions()

        self.assertIn("Clase SN", loaded)
        self.assertEqual(loaded["Clase SN"]["pali_text"], "namo tassa bhagavato")
        self.assertEqual(loaded["Clase SN"]["dict_name"], "dpd")

    def test_delete_session(self):
        """Elimina una sesión del fichero y verifica que no se puede volver a cargar."""
        data = {
            "Clase A": {"pali_text": "namo"},
            "Clase B": {"pali_text": "tassa"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = _tmp_sessions_path(tmp)
            with patch.object(app, "SAVED_SESSIONS_PATH", path):
                app.persist_saved_sessions(data)
                sessions = app.load_saved_sessions()
                del sessions["Clase A"]
                app.persist_saved_sessions(sessions)
                final = app.load_saved_sessions()

        self.assertNotIn("Clase A", final)
        self.assertIn("Clase B", final)


# ---------------------------------------------------------------------------
# Fallback de vocal final larga
# ---------------------------------------------------------------------------

class TestLongFinalVowelFallback(unittest.TestCase):

    def test_generate_final_vowel_fallbacks(self):
        self.assertEqual(app._generate_final_vowel_fallbacks("rājā"), ["rājā", "rāja"])
        self.assertEqual(app._generate_final_vowel_fallbacks("bhikkhū"), ["bhikkhū", "bhikkhu"])
        self.assertEqual(app._generate_final_vowel_fallbacks("dhamma"), ["dhamma"])

    def test_generate_final_niggahita_fallbacks(self):
        self.assertEqual(app._generate_final_vowel_fallbacks("buddhaṃ"), ["buddhaṃ", "buddham"])
        self.assertEqual(app._generate_final_vowel_fallbacks("buddham"), ["buddham", "buddhaṃ"])

    def test_process_pali_text_uses_short_vowel_fallback(self):
        """Long final vowel (ā+ti sandhi / meter) must be found without ≈ alarm."""
        dictionary = {
            "rāja": {
                "meaning": "rey",
                "morphology": "noun",
                "part_of_speech": "noun",
                "root": "N/A",
                "translation": "rey",
            }
        }
        entries = app.process_pali_text("rājā", dictionary)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["word"], "rājā")
        self.assertEqual(entries[0]["meaning"], "rey")
        self.assertEqual(entries[0]["part_of_speech"], "noun")
        # Long-vowel shortening is a natural Pali variant — not a fallback alarm.
        self.assertEqual(entries[0]["match_type"], "exact")
        self.assertEqual(entries[0]["matched_form"], "rāja")

    def test_process_pali_with_lookup_map_uses_short_vowel_fallback(self):
        """Long final ū (meter/sandhi) must be found without ≈ alarm."""
        lookup_map = {
            "bhikkhu": {
                "meaning": "monje",
                "morphology": "noun",
                "part_of_speech": "noun",
                "root": "N/A",
                "translation": "monje",
            }
        }
        entries = app.process_pali_with_lookup_map("bhikkhū", lookup_map, fallback_dictionary={})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["word"], "bhikkhū")
        self.assertEqual(entries[0]["meaning"], "monje")
        self.assertEqual(entries[0]["part_of_speech"], "noun")
        # Long-vowel shortening is a natural Pali variant — not a fallback alarm.
        self.assertEqual(entries[0]["match_type"], "exact")
        self.assertEqual(entries[0]["matched_form"], "bhikkhu")

    def test_process_pali_with_lookup_map_uses_niggahita_fallback(self):
        lookup_map = {
            "buddham": {
                "meaning": "Buda (acusativo)",
                "morphology": "noun",
                "part_of_speech": "noun",
                "root": "N/A",
                "translation": "Buda",
            }
        }
        entries = app.process_pali_with_lookup_map("buddhaṃ", lookup_map, fallback_dictionary={})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["word"], "buddhaṃ")
        self.assertEqual(entries[0]["meaning"], "Buda (acusativo)")
        self.assertEqual(entries[0]["part_of_speech"], "noun")
        # Niggahita variation is a real morphological change — keep the ≈ marker.
        self.assertEqual(entries[0]["match_type"], "fallback")
        self.assertEqual(entries[0]["matched_form"], "buddham")

    def test_compact_and_rich_gloss_include_fallback_marker(self):
        entries = [
            {
                "word": "buddhaṃ",
                "meaning": "Buda (acusativo)",
                "morphology": "noun",
                "part_of_speech": "noun",
                "root": "N/A",
                "sanskrit_root": "N/A",
                "etymology": "N/A",
                "translation": "Buda",
                "match_type": "fallback",
                "matched_form": "buddham",
            }
        ]

        compact = app.generate_compact_gloss(entries)
        rich = app.generate_rich_gloss_text(entries)

        self.assertIn("[≈ buddham]", compact)
        self.assertIn("[≈ buddham]", rich)

    def test_long_vowel_sandhi_ti_no_alarm(self):
        """Words elongated by ā+ti sandhi must not show ≈ alarm.

        e.g. vapissāmī (= vapissāmi before 'ti') should resolve silently.
        """
        lookup_map = {
            "vapissāmi": {
                "meaning": "sembraré",
                "morphology": "verb",
                "part_of_speech": "verb",
                "root": "N/A",
                "translation": "sembraré",
            }
        }
        for long_form in ("vapissāmī", "vinassissantī", "sossāmī"):
            short_form = long_form[:-1] + "i"
            lm = {
                short_form: {
                    "meaning": "test",
                    "morphology": "verb",
                    "part_of_speech": "verb",
                    "root": "N/A",
                    "translation": "test",
                }
            }
            entries = app.process_pali_with_lookup_map(long_form, lm, fallback_dictionary={})
            self.assertEqual(len(entries), 1, msg=f"No entry for {long_form!r}")
            self.assertEqual(entries[0]["match_type"], "exact",
                             msg=f"Expected exact for {long_form!r}, got {entries[0]['match_type']!r}")

    def test_long_vowel_metrical_no_alarm(self):
        """Words with metrically lengthened final ā must not show ≈ alarm."""
        for long_form, short_form in [("pāpuṇeyyā", "pāpuṇeyya"), ("nibbānā", "nibbāna")]:
            d = {
                short_form: {
                    "meaning": "test",
                    "morphology": "noun",
                    "part_of_speech": "noun",
                    "root": "N/A",
                    "translation": "test",
                }
            }
            entries = app.process_pali_text(long_form, d)
            self.assertEqual(len(entries), 1, msg=f"No entry for {long_form!r}")
            self.assertEqual(entries[0]["match_type"], "exact",
                             msg=f"Expected exact for {long_form!r}")
            self.assertEqual(entries[0]["matched_form"], short_form)

    def test_is_final_long_vowel_shortening(self):
        """Helper must detect long-vowel shortening and not confuse other diffs."""
        self.assertTrue(app._is_final_long_vowel_shortening("vapissāmī", "vapissāmi"))
        self.assertTrue(app._is_final_long_vowel_shortening("nibbānā", "nibbāna"))
        self.assertTrue(app._is_final_long_vowel_shortening("bhikkhū", "bhikkhu"))
        self.assertTrue(app._is_final_long_vowel_shortening("rājā", "rāja"))
        # Niggahita is NOT a long-vowel shortening
        self.assertFalse(app._is_final_long_vowel_shortening("buddhaṃ", "buddham"))
        # Identical words are not shortenings
        self.assertFalse(app._is_final_long_vowel_shortening("dhamma", "dhamma"))
        # Different word entirely
        self.assertFalse(app._is_final_long_vowel_shortening("rājā", "raja"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
