from unittest.mock import patch

from django.test import Client, SimpleTestCase


class ChatTests(SimpleTestCase):
    def test_chat_page_contains_the_form_and_static_assets(self):
        response = self.client.get("/")

        self.assertTemplateUsed(response, "agent_service/chat.html")
        self.assertContains(response, 'action="/ask/"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, "agent_service/chat.js")

    @patch("AgenticWorkflow.graph.app.invoke")
    def test_ask_invokes_the_graph_and_returns_answer_and_safe_sources(self, invoke):
        source = "https://www.rbi.org.in/Scripts/FAQView.aspx?Id=1"
        invoke.return_value = {
            "generation": "See the RBI guidance.",
            "sources": [source, "javascript:alert(1)", "https://", "http://["],
            "documents": [object()],
        }
        client = Client(enforce_csrf_checks=True)
        client.get("/")
        response = client.post(
            "/ask/",
            {"question": "  What are the rules?  "},
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )

        invoke.assert_called_once_with({"question": "What are the rules?"})
        self.assertEqual(response.json(), {"answer": "See the RBI guidance.", "sources": [source]})
        self.assertIn("no-store", response.headers["Cache-Control"])

    @patch("agent_service.views.invoke_agent")
    def test_ask_returns_the_agents_out_of_scope_reply(self, invoke):
        reply = "I can help with questions about the Reserve Bank of India."
        invoke.return_value = {"generation": reply, "sources": [], "is_rbi_related": False}

        response = self.client.post("/ask/", {"question": "Write a song."})

        self.assertEqual(response.json(), {"answer": reply, "sources": []})

    @patch("agent_service.views.invoke_agent")
    def test_ask_rejects_invalid_requests_before_invoking_the_agent(self, invoke):
        self.assertEqual(self.client.get("/ask/").status_code, 405)
        self.assertEqual(self.client.post("/ask/", {"question": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/ask/", {"question": "a" * 2001}).status_code, 400)
        self.assertEqual(Client(enforce_csrf_checks=True).post("/ask/").status_code, 403)
        invoke.assert_not_called()

    @patch("agent_service.views.invoke_agent", side_effect=RuntimeError("internal detail"))
    def test_ask_handles_agent_failures(self, invoke):
        with self.assertLogs("agent_service.views", level="ERROR"):
            response = self.client.post("/ask/", {"question": "What is the RBI?"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("try again", response.json()["error"])
        self.assertNotIn("internal detail", response.content.decode())
