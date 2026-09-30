"""Импорт всех моделей — Django ищет модели в app.models."""

from app.models.assignment import ClassAssignment
from app.models.bot_account import BotAccount
from app.models.consent import Consent
from app.models.gamification import UserAchievement, UserStats
from app.models.recommendation import Recommendation
from app.models.school_class import SchoolClass
from app.models.task_attempt import TaskAttempt
from app.models.teacher_invite import TeacherInvite
from app.models.test_progress import TestProgress
from app.models.test_result import TestResult
from app.models.user import User, UserRole

__all__ = [
    "BotAccount", "ClassAssignment", "Consent", "Recommendation", "SchoolClass",
    "TaskAttempt", "TeacherInvite", "TestProgress", "TestResult", "User",
    "UserAchievement",
    "UserRole", "UserStats",
]
