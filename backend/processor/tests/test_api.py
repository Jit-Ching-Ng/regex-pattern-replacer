"""End-to-end API tests (Django test client, temporary storage, fake LLM)."""
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from processor.models import Dataset
from processor.tests.fakes import FakeLLM, echo_transform

CSV = (
    b"ID,Name,Email\n"
    b"1,John Doe,john.doe@example.com\n"
    b"2,Jane Smith,jane_smith@domain.com\n"
    b"3,Alice Brown,alice.brown@website.org\n"
)
EMAIL = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
LLM_EMAIL_ANSWER = {
    "pattern": EMAIL,
    "flags": [],
    "columns": ["Email"],
    "replacement": "REDACTED",
    "explanation": "Email addresses.",
}


class ApiTestCase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media, LLM_API_KEY="test")
        self.settings_override.enable()
        self.client = APIClient()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def upload(self, content=CSV, name="people.csv"):
        response = self.client.post(
            "/api/datasets/", {"file": SimpleUploadedFile(name, content)}, format="multipart"
        )
        return response

    def fake_llm(self, *replies):
        llm = FakeLLM(*replies)
        patcher = mock.patch("processor.services.datasets.get_llm_client", return_value=llm)
        patcher.start()
        self.addCleanup(patcher.stop)
        return llm

    def rows(self, dataset_id, **params):
        return self.client.get(f"/api/datasets/{dataset_id}/rows/", params).json()


class UploadTests(ApiTestCase):
    def test_upload_and_read_rows(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.content)
        dataset = response.json()["dataset"]
        self.assertEqual(dataset["row_count"], 3)
        self.assertEqual(
            [c["kind"] for c in dataset["columns"]], ["numeric", "text", "text"]
        )
        page = self.rows(dataset["id"], page_size=2)
        self.assertEqual(page["total_rows"], 3)
        self.assertEqual(page["total_pages"], 2)
        self.assertEqual(page["rows"][0], ["1", "John Doe", "john.doe@example.com"])

    def test_rejects_unsupported_and_broken_files(self):
        response = self.upload(b"%PDF-1.4", name="doc.pdf")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_file")
        self.assertEqual(Dataset.objects.count(), 0)

    def test_missing_dataset_is_404(self):
        response = self.client.get("/api/datasets/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_health(self):
        body = self.client.get("/api/health/").json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["llm"]["configured"])


class RegexFlowTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dataset_id = self.upload().json()["dataset"]["id"]
        self.base = f"/api/datasets/{self.dataset_id}"

    def test_brief_scenario_in_one_request(self):
        """Natural language in, replaced data out - exactly the brief's example."""
        self.fake_llm(LLM_EMAIL_ANSWER)
        response = self.client.post(
            f"{self.base}/regex/apply/",
            {"instruction": "Find email addresses in the Email column and replace them with 'REDACTED'."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        operation = response.json()["operation"]
        self.assertEqual(operation["pattern"], EMAIL)
        self.assertEqual(operation["replacement"], "REDACTED")
        self.assertEqual(operation["stats"]["cells_changed"], 3)

        page = self.rows(self.dataset_id, highlight="true")
        self.assertEqual([row[2] for row in page["rows"]], ["REDACTED"] * 3)
        self.assertEqual(page["changed"], [[0, 2], [1, 2], [2, 2]])

    def test_suggest_then_preview_then_apply(self):
        self.fake_llm(LLM_EMAIL_ANSWER)
        suggest = self.client.post(
            f"{self.base}/regex/suggest/", {"instruction": "find email addresses"}, format="json"
        ).json()
        self.assertEqual(suggest["suggestion"]["columns"], ["Email"])
        self.assertEqual(suggest["preview"]["cells_changed"], 3)
        self.assertEqual(suggest["preview"]["samples"][0]["after"], "REDACTED")

        preview = self.client.post(
            f"{self.base}/regex/preview/",
            {"pattern": r"@\w+", "replacement": "@corp", "columns": ["Email"]},
            format="json",
        ).json()["preview"]
        self.assertEqual(preview["samples"][0]["after"], "john.doe@corp.com")

        applied = self.client.post(
            f"{self.base}/regex/apply/",
            {"pattern": r"@\w+", "replacement": "@corp", "columns": ["Email"]},
            format="json",
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(len(applied.json()["dataset"]["operations"]), 1)

    def test_invalid_pattern_returns_422(self):
        response = self.client.post(f"{self.base}/regex/preview/", {"pattern": "(oops"}, format="json")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_pattern")

    def test_unknown_column_returns_400(self):
        response = self.client.post(
            f"{self.base}/regex/preview/", {"pattern": "a", "columns": ["Nope"]}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_column")

    def test_missing_llm_key_returns_503(self):
        with override_settings(LLM_API_KEY="", LLM_BASE_URL=""):
            response = self.client.post(f"{self.base}/regex/suggest/", {"instruction": "emails"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "llm_not_configured")

    def test_undo_reset_and_export(self):
        for pattern in ["John", "Jane"]:
            self.client.post(
                f"{self.base}/regex/apply/", {"pattern": pattern, "replacement": "X"}, format="json"
            )
        self.assertEqual(self.rows(self.dataset_id)["rows"][1][1], "X Smith")

        undo = self.client.post(f"{self.base}/undo/").json()
        self.assertEqual(undo["undone"]["sequence"], 2)
        self.assertEqual(self.rows(self.dataset_id)["rows"][1][1], "Jane Smith")
        self.assertEqual(self.rows(self.dataset_id)["rows"][0][1], "X Doe")

        export = self.client.get(f"{self.base}/export/", {"format": "csv"})
        self.assertEqual(export.status_code, 200)
        self.assertIn("people_processed.csv", export["Content-Disposition"])
        self.assertIn("X Doe", export.content.decode("utf-8-sig"))

        self.client.post(f"{self.base}/reset/")
        self.assertEqual(self.rows(self.dataset_id)["rows"][0][1], "John Doe")
        self.assertEqual(self.client.post(f"{self.base}/undo/").status_code, 409)


class TransformTests(ApiTestCase):
    def test_derive_column(self):
        dataset_id = self.upload().json()["dataset"]["id"]
        self.fake_llm(echo_transform(lambda email: email.split("@")[1]))
        response = self.client.post(
            f"/api/datasets/{dataset_id}/transform/",
            {"kind": "derive", "column": "Email", "instruction": "the domain", "new_column": "Domain"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        names = [c["name"] for c in response.json()["dataset"]["columns"]]
        self.assertEqual(names, ["ID", "Name", "Email", "Domain"])
        page = self.rows(dataset_id, highlight="true")
        self.assertEqual(page["rows"][2][3], "website.org")
        self.assertIn([0, 3], page["changed"])

    def test_derive_requires_a_column_name(self):
        dataset_id = self.upload().json()["dataset"]["id"]
        response = self.client.post(
            f"/api/datasets/{dataset_id}/transform/",
            {"kind": "derive", "column": "Email", "instruction": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
