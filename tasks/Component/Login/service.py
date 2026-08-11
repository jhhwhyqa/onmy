# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from module.base.timer import Timer
from module.exception import RequestHumanTakeover, GameTooManyClickError, GameStuckError
from module.logger import logger
from tasks.GameUi.assets import GameUiAssets
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask


class LoginService(BaseTask, RestartAssets, GameUiAssets):
    character: str

    def __init__(self, *wargs, **kwargs):
        super().__init__(*wargs, **kwargs)
        self.character = self.config.restart.login_character_config.character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = self.character

    def _app_handle_login(self) -> bool:
        """
        最终是在庭院界面
        :return:
        """
        logger.hr('App login')
        self.device.stuck_record_add('LOGIN_CHECK')

        confirm_timer = Timer(1.5, count=2).start()
        orientation_timer = Timer(10)
        login_animation = True
        login_animation_timer = Timer(5)
        login_animation_timeout_timer = Timer(30)
        center_click_count = 0
        login_animation_timeout_logged = False
        login_success = False

        def reset_login_animation_timers():
            if login_animation_timer.started():
                login_animation_timer.reset()
            if login_animation_timeout_timer.started():
                login_animation_timeout_timer.reset()

        def disable_login_animation():
            nonlocal login_animation
            login_animation = False
            reset_login_animation_timers()

        while 1:
            if not login_success and orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

            self.screenshot()
            if self.appear_then_click(self.I_CANCEL_BATTLE, interval=0.8):
                logger.info('Cancel continue battle')
                disable_login_animation()
                continue
            if self.appear(self.I_CHECK_MAIN, interval=0.2) and not self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS):
                logger.info('The main had already appeared, but shikigami records had not yet appeared')
                if self.click(self.C_LOGIN_SCROLL_CLOSE_AREA, interval=2):
                    disable_login_animation()
                    continue
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.2):
                if confirm_timer.reached():
                    logger.info('Login to main confirm (shikigami records button appears)')
                    break
            else:
                confirm_timer.reset()
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.5):
                logger.info('Login success: shikigami records button appears')
                login_success = True
            if self.appear(self.I_HARVEST_ZIDU, interval=1):
                self.I_HARVEST_ZIDU.roi_front[0] -= 200
                self.I_HARVEST_ZIDU.roi_front[1] -= 200
                if self.click(self.I_HARVEST_ZIDU, interval=2):
                    logger.info('Close zidu')
                    disable_login_animation()
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2.5):
                logger.info('Soul overflow confirm')
                disable_login_animation()
                continue
            if self.appear_then_click(self.I_LOGIN_LOAD_DOWN, interval=1):
                logger.info('Download inbetweening')
                disable_login_animation()
                continue
            if self.appear_then_click(self.I_WATCH_VIDEO_CANCEL, interval=0.6):
                logger.info('Close video')
                disable_login_animation()
                continue
            if self.appear_then_click(self.I_LOGIN_RED_CLOSE, interval=0.6):
                logger.info('Close red close')
                disable_login_animation()
                continue
            if self.appear_then_click(self.I_LOGIN_YELLOW_CLOSE, interval=0.6):
                logger.info('Close yellow close')
                disable_login_animation()
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_GOTO_BIND_PHONE):
                while 1:
                    self.screenshot()
                    if self.appear_then_click(self.I_LOGIN_LOGIN_CANCEL_BIND_PHONE):
                        logger.info("Close bind phone")
                        break
                disable_login_animation()
                continue
            from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
            if self.appear_then_click(gia.I_I_REJECT, interval=0.8):
                logger.info("reject invites")
                disable_login_animation()
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_ONMYOJI_GENIE):
                logger.info("click onmyoji genie")
                disable_login_animation()
                continue
            if self.appear(self.I_LOGIN_SPECIFIC_SERVE, interval=0.6) \
                    and self.ocr_appear_click(self.O_LOGIN_SPECIFIC_SERVE, interval=0.6):
                while True:
                    self.screenshot()
                    if self.appear(self.I_LOGIN_SPECIFIC_SERVE):
                        self.click(self.C_LOGIN_ENSURE_LOGIN_CHARACTER_IN_SAME_SVR, interval=2)
                        continue
                    break
                logger.info('login specific user')
                disable_login_animation()
                continue

            if self.appear(self.I_CREATE_ACCOUNT):
                logger.warning('Appear create account')
                raise GameStuckError('Appear create account')

            if self.appear(self.I_CHARACTARS, interval=1):
                logger.info('误入区服设置')
                self.device.click(x=106, y=535)
                disable_login_animation()

            login_screen_appeared = self.appear(self.I_LOGIN_8)
            if login_animation and not login_screen_appeared:
                if not login_animation_timer.started():
                    login_animation_timer.start()
                if not login_animation_timeout_timer.started():
                    login_animation_timeout_timer.start()
                if login_animation_timeout_timer.reached():
                    if not login_animation_timeout_logged:
                        logger.warning('Login animation: fallback timeout, continue with normal login flow')
                        login_animation_timeout_logged = True
                    continue
                if not login_animation_timer.reached():
                    continue
                if self.click(self.C_LOGIN_ANIMATION_CENTER, interval=3):
                    center_click_count += 1
                    logger.info(f'Login animation: clicked center area (attempt {center_click_count})')
                    continue
                if self.ocr_appear_click(self.O_LOGIN_ANIMATION_SKIP, interval=1):
                    logger.info('Login animation: detected 跳过, clicked skip button')
                continue

            if login_animation and login_screen_appeared:
                disable_login_animation()
            if not login_screen_appeared:
                continue

            if self.appear(self.I_EARLY_SERVER):
                if self.appear_then_click(self.I_EARLY_SERVER_CANCEL):
                    logger.info('Cancel switch from early server to normal server')
                    disable_login_animation()
                    continue
            if self.ocr_appear_click(self.O_LOGIN_ENTER_GAME, interval=3):
                disable_login_animation()
                self.wait_until_appear(self.I_LOGIN_SPECIFIC_SERVE, True, wait_time=5)
                continue

        return login_success

    def app_handle_login(self) -> bool:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            self._app_handle_login()
            return True
        except (GameTooManyClickError, GameStuckError) as e:
            logger.warning(e)
            self.device.app_stop()
            self.device.app_start()

        logger.critical('Login failed')
        logger.critical('Onmyoji server may be under maintenance, or you may lost network connection')
        raise RequestHumanTakeover

    def set_specific_usr(self, character: str):
        self.character = character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = character
