from celery import Celery
from app.config import settings
import os

celery_app = Celery("codesense", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
eager = settings.CELERY_EAGER or not settings.REDIS_URL
celery_app.conf.update(task_always_eager=eager, task_eager_propagates=True)
