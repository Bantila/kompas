import uuid

from django.db import models


class BotAccount(models.Model):
    """Собеседник бота: связка «пользователь мессенджера — аккаунт Компаса».

    Платформа хранится отдельным полем, а не отдельной таблицей: логика бота
    одна на всех, различается только транспорт. Так добавление MAX не потребует
    ни новой таблицы, ни изменения сценариев.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.CharField(verbose_name="платформа", max_length=16, db_index=True)  # telegram | max
    external_id = models.CharField(verbose_name="id в мессенджере", max_length=64, db_index=True)
    chat_id = models.CharField(verbose_name="чат", max_length=64)
    # пока аккаунт не привязан — здесь None, а link_code ждёт ввода в приложении
    user = models.ForeignKey(
        "app.User", verbose_name="аккаунт", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    link_code = models.CharField(verbose_name="код привязки", max_length=8, unique=True, null=True, blank=True)
    # задача, которую бот сейчас спрашивает: ответ приходит следующим сообщением
    current_task_id = models.CharField(verbose_name="текущая задача", max_length=16, null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="создан", auto_now_add=True)

    class Meta:
        db_table = "bot_accounts"
        verbose_name = "собеседник бота"
        verbose_name_plural = "собеседники бота"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "external_id"], name="uq_bot_account_platform_user"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.platform}:{self.external_id}"
