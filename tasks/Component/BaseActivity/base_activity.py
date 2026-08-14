from collections.abc import Callable

from module.logger import logger


class BaseActivity:
    """活动任务共享行为。"""

    @staticmethod
    def verify_zero_ticket(
        ticket_name: str,
        fallback_action: Callable[[], bool],
    ) -> bool:
        """门票 OCR 为零时执行一次真实入口操作确认门票是否耗尽。"""
        logger.warning(f'{ticket_name} OCR is zero, try one fallback action')
        if fallback_action():
            logger.info(f'{ticket_name} fallback succeeded')
            return True
        logger.info(f'{ticket_name} confirmed unavailable')
        return False
