import logging
from urllib.parse import urlsplit

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

logger = logging.getLogger(__name__)
QUESTION_LIMIT = 2000


def is_source_link(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return url.scheme in {"http", "https"} and bool(url.hostname)
    except ValueError:
        return False


def invoke_agent(question):
    from AgenticWorkflow.graph import app

    return app.invoke({"question": question})


@require_GET
def chat(request):
    return render(request, "agent_service/chat.html", {"question_limit": QUESTION_LIMIT})


@require_POST
@never_cache
def ask(request):
    question = request.POST.get("question", "").strip()
    if not question or len(question) > QUESTION_LIMIT:
        return JsonResponse(
            {"error": f"Enter a question between 1 and {QUESTION_LIMIT:,} characters."},
            status=400,
        )

    try:
        result = invoke_agent(question)
        answer = result.get("generation", "").strip()
        if not answer:
            raise ValueError("The RBI agent returned an empty answer")
        sources = [source for source in result.get("sources", []) if is_source_link(source)]
    except Exception:
        logger.exception("RBI agent request failed")
        return JsonResponse(
            {"error": "The RBI agent couldn’t answer right now. Check that Ollama is running and try again."},
            status=503,
        )

    return JsonResponse({"answer": answer, "sources": sources})
