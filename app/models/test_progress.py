import uuid

from django.db import models


class TestProgress(models.Model):
    """Незавершённый тест: ответы, данные до отправки результата.

    Раньше прогресс жил только в localStorage, и он терялся вместе с
    браузером: очистил данные, открыл приложение с другого устройства или
    зашёл через бота — тест начинался с нуля. Теперь черновик лежит на
    сервере и привязан к аккаунту.

    Строка одна на ученика: одновременно проходить два теста незачем, а
    завершённые прохождения хранит TestResult.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField("app.User", verbose_name="ученик", on_delete=models.CASCADE, related_name="+")
    # те же сырые ответы, что потом уйдут в TestResult.raw_answers
    answers = models.JSONField(verbose_name="ответы", default=dict, blank=True)
    # план блока B, если он уже подобран — иначе на другом устройстве
    # ученику достался бы другой набор предметов
    plan = models.JSONField(verbose_name="план блока B", default=dict, blank=True)
    updated_at = models.DateTimeField(verbose_name="обновлён", auto_now=True)

    class Meta:
        db_table = "test_progress"
        verbose_name = "черновик теста"
        verbose_name_plural = "черновики тестов"
