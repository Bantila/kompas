import uuid

from django.db import models


class Recommendation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_result = models.OneToOneField(
        "app.TestResult", verbose_name="результат теста", on_delete=models.CASCADE, related_name="recommendation"
    )
    # сырой ответ LLM — для отладки и разбора спорных рекомендаций
    ai_response = models.JSONField(verbose_name="сырой ответ модели", default=dict, blank=True)
    # распарсенный список профессий
    professions = models.JSONField(verbose_name="профессии", default=list, blank=True)
    # slug модели либо "fallback:rule-based"
    model_used = models.CharField(verbose_name="модель", max_length=128)
    created_at = models.DateTimeField(verbose_name="создана", auto_now_add=True)

    class Meta:
        db_table = "recommendations"
        verbose_name = "рекомендация"
        verbose_name_plural = "рекомендации"
