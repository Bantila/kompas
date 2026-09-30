"""Код приглашения педагога.

Сводка по классу — это данные о детях, пусть и обезличенные. Пока регистрация
была открытой, любой человек с почтой заводил себе роль teacher и получал к ним
доступ. Код приглашения делает роль подтверждённой: её выдаёт тот, кто уже
работает в школе, а не сам заявитель.

Код одноразовый. Многоразовый рано или поздно расходится по переписке и
перестаёт что-либо подтверждать.
"""

import uuid

from django.db import models


class TeacherInvite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(verbose_name="код", max_length=32, unique=True)

    # Кем выдан. NULL — загрузочный код из консоли сервера: первого педагога
    # пригласить некому, а открывать ради него дыру в регистрации нельзя.
    created_by = models.ForeignKey(
        "app.User", verbose_name="выдал", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # для кого выписан — чтобы в списке было видно, чей это код
    note = models.CharField(verbose_name="для кого", max_length=120, default="", blank=True)

    created_at = models.DateTimeField(verbose_name="выдан", auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name="действует до", )

    used_by = models.ForeignKey(
        "app.User", verbose_name="использовал", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    used_at = models.DateTimeField(verbose_name="использован", null=True, blank=True)

    class Meta:
        db_table = "teacher_invites"
        verbose_name = "приглашение педагога"
        verbose_name_plural = "приглашения педагогов"

    def __str__(self) -> str:
        return self.code
