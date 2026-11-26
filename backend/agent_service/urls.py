from django.urls import path

from . import views

app_name = "agent_service"

urlpatterns = [
    path("", views.chat, name="chat"),
    path("ask/", views.ask, name="ask"),
]
