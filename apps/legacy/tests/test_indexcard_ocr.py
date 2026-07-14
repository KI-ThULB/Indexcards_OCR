import unittest
import sys
import os

# Add parent directory to path to import indexcard_ocr
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexcard_ocr import (
    validate_signature,
    extract_json_from_model_content,
    validate_extraction,
    format_time
)

class TestIndexcardOCR(unittest.TestCase):

    def test_validate_signature(self):
        self.assertTrue(validate_signature("Spez.12.345"))
        self.assertTrue(validate_signature("Spez.1.123 a"))
        self.assertTrue(validate_signature("RTSO 1234"))
        self.assertTrue(validate_signature("TOB 567"))
        self.assertFalse(validate_signature("Invalid Signature"))
        self.assertFalse(validate_signature(""))
        self.assertFalse(validate_signature(None))

    def test_extract_json_from_model_content(self):
        # Markdown fence
        content = "```json\n{\"key\": \"value\"}\n```"
        self.assertEqual(extract_json_from_model_content(content), "{\"key\": \"value\"}")
        
        # Raw JSON
        content = "{\"key\": \"value\"}"
        self.assertEqual(extract_json_from_model_content(content), "{\"key\": \"value\"}")
        
        # Text around JSON
        content = "Here is the result: {\"key\": \"value\"} hope it helps!"
        self.assertEqual(extract_json_from_model_content(content), "{\"key\": \"value\"}")

    def test_validate_extraction(self):
        valid_data = {
            "Komponist": "Bach",
            "Signatur": "Spez.1",
            "Titel": "Title",
            "Textanfang": "Start",
            "Verlag": "Publisher",
            "Material": "Ms.",
            "Textdichter": "Poet",
            "Bearbeiter": "Editor",
            "Bemerkungen": "Notes"
        }
        ok, errors = validate_extraction(valid_data)
        self.assertTrue(ok)
        self.assertEqual(len(errors), 0)

        invalid_data = {
            "Komponist": 123,  # Should be string
            "Signatur": "Spez.1"
        }
        ok, errors = validate_extraction(invalid_data)
        self.assertFalse(ok)
        self.assertIn("Field Komponist not a string", errors)

    def test_format_time(self):
        self.assertEqual(format_time(65), "0:01:05")
        self.assertEqual(format_time(3661), "1:01:01")

if __name__ == '__main__':
    unittest.main()
