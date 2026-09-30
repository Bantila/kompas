"""Согласие на обработку персональных данных.

152-ФЗ требует не «галочку где-то нажали», а подтверждаемый факт: кто, когда и
на какую редакцию документа согласился, и возможность согласие отозвать.
Сводка по классу обезличена, но сами прохождения — данные конкретного ребёнка.

Таблица — журнал, а не текущее состояние: строка на каждое данное согласие,
дата отзыва проставляется в ней же. Состояние выводится как последняя строка
без отзыва.

Так и должно быть: при проверке спрашивают не «согласен ли сейчас», а «когда
и на что соглашался, когда отзывал». Перезапись одной строки эту историю
стирала — а вместе с ней и доказательство, что данные обрабатывались законно.
"""

import uuid

from django.db import models
from django.utils import timezone


class Consent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # не unique: у человека столько строк, сколько раз он давал согласие
    user = models.ForeignKey("app.User", verbose_name="ученик", on_delete=models.CASCADE, related_name="+")

    # Редакция документа. Без неё согласие бессмысленно: текст меняется, и надо
    # знать, с чем именно человек соглашался.
    document_version = models.CharField(verbose_name="редакция документа", max_length=32)

    # Кто дал согласие: сам ученик или законный представитель. Для детей до 14
    # согласие даёт родитель, и это должно быть видно в реестре.
    granted_by = models.CharField(verbose_name="кем дано", max_length=16, default="self")

    # Возраст на момент согласия — то, чем обоснован выбор «сам» или «родитель».
    # Возраст назван самим учеником и ничем не подтверждён; храним именно
    # возраст, а не дату рождения: для проверки достаточно, а данных меньше.
    age_at_consent = models.IntegerField(verbose_name="возраст", null=True, blank=True)

    granted_at = models.DateTimeField(verbose_name="дано", default=timezone.now)
    # NULL — согласие действует. Дата — отозвано, обработка прекращена.
    revoked_at = models.DateTimeField(verbose_name="отозвано", null=True, blank=True)

    class Meta:
        db_table = "consents"
        verbose_name = "согласие"
        verbose_name_plural = "согласия"
