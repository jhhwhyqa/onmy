# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey


from tasks.base_task import BaseTask
from tasks.Script.config_device import ScreenshotMethod, ControlMethod
from module.logger import logger

class FastDevice(BaseTask):

    def fast_screenshot(self):
        if self.config.model.script.device.screenshot_method != ScreenshotMethod.WINDOW_BACKGROUND:
            raise
        if not hasattr(self.device, 'root_node'):
            logger.warning('root_node unavailable, falling back to standard screenshot')
            self.device.screenshot()
            return self.device.image
        self.device.image = self.device.screenshot_window_background()
        return self.device.image
