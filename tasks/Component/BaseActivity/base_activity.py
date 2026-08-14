from collections.abc import Callable

from module.logger import logger


class BaseActivity:
    """活动任务共享行为。"""

    @staticmethod
    def verify_ocr_zero_resource(
        resource_name: str,
        fallback_action: Callable[[], bool],
    ) -> bool:
        """资源 OCR 为零时执行一次真实入口操作确认资源是否耗尽。"""
        logger.warning(f'{resource_name} OCR is zero, try one fallback action')
        if fallback_action():
            logger.info(f'{resource_name} fallback succeeded')
            return True
        logger.info(f'{resource_name} confirmed unavailable')
        return False
