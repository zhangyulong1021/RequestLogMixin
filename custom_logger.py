from django.conf import settings
from loguru import logger

location = settings.ADMIN_CUSTOM_OPERATE_LOG_LOCATION
logger.add(
    f"{location}" + "/operator_log_{time:YYYY-MM-DD}.log",
    encoding="utf-8",
    enqueue=True,
    format="{message}",
    rotation="00:00",
)
