import uuid

from django.db import models


class TestResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("app.User", verbose_name="ученик", on_delete=models.CASCADE, related_name="test_results")
    # сырые ответы: {"a1": 4, "b1_k1": {"selected_index": 1, "time_spent_seconds": 12}, ...}
    raw_answers = models.JSONField(verbose_name="ответы", default=dict, blank=True)
    # результат calculate_scores()
    computed_scores = models.JSONField(verbose_name="баллы", default=dict, blank=True)
    # насколько ответам можно доверять: уровень и сработавшие признаки.
    # Ничего не блокирует — нужно, чтобы педагог не принимал решения по
    # цифрам, за которыми стоит прокликанный за минуту тест
    integrity = models.JSONField(verbose_name="доверие к ответам", default=dict, blank=True)
    completed_at = models.DateTimeField(verbose_name="пройден", auto_now_add=True)

    class Meta:
        db_table = "test_results"
        verbose_name = "результат теста"
        verbose_name_plural = "результаты тестов"
        # история ученика читается по дате — составной индекс отдаёт её уже упорядоченной
        indexes = [
            models.Index(fields=["user", "completed_at"], name="ix_test_results_user_completed"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.completed_at:%d.%m.%Y %H:%M}"
