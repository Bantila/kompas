import uuid

from django.db import models
from django.utils import timezone


class TaskAttempt(models.Model):
    """Одна попытка решения тренировочной задачи.

    Храним ответ ученика и разобранный тип ошибки — из этой истории строится
    статистика «где именно спотыкается» и прогресс по предметам.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("app.User", verbose_name="ученик", on_delete=models.CASCADE, related_name="+")
    # id задачи из банка (JSON-файл), а не FK — банк не живёт в БД
    task_id = models.CharField(verbose_name="задача", max_length=16, db_index=True)
    subject = models.CharField(verbose_name="предмет", max_length=32, db_index=True)
    difficulty = models.CharField(verbose_name="сложность", max_length=16)
    user_answer = models.CharField(verbose_name="ответ", max_length=500)
    is_correct = models.BooleanField(verbose_name="верно", default=False)
    error_type = models.CharField(verbose_name="тип ошибки", max_length=32)
    confidence = models.FloatField(verbose_name="уверенность", default=0.0)
    answered_at = models.DateTimeField(verbose_name="когда", default=timezone.now, db_index=True)

    class Meta:
        db_table = "task_attempts"
        verbose_name = "попытка решения"
        verbose_name_plural = "попытки решения"
        # сводка по заданию берёт попытки ученика после даты выдачи
        indexes = [
            models.Index(fields=["user", "answered_at"], name="ix_task_attempts_user_answered"),
        ]
