# This Python file uses the following encoding: utf-8
"""僵尸寮（阴阳寮 · 道馆）：沿用本地道馆 `tasks/Dokan` 的完整逻辑，只改「选寮」。

与普通道馆的差别只有两点：

1. **选寮**：只认「寮名在 `tasks/ZombieGuild/福利寮名单.txt` 里」的福利寮，不看赏金与
   人数系数；刷新次数用完仍未找到就直接结束本轮，不会退化为打普通寮。
2. **QQ 群消息门控**（可选）：群公告里匹配到关键词后才进入道馆流程，未匹配时按
   「未匹配后等待分钟数 / 每天最大未匹配次数」重试（见 QQ消息接入说明.md）。

集结、馆主战、换阵容、加油、放弃、今日次数与调度等全部继承自本地道馆。
"""
import re
from pathlib import Path
from time import sleep

from module.exception import TaskEnd
from module.logger import logger
from tasks.Dokan.script_task import ScriptTask as DokanScriptTask, position_offset
from tasks.ZombieGuild.assets import ZombieGuildAssets
from tasks.ZombieGuild.config import ZombieGuild
from tasks.ZombieGuild.qq_listener import QQListener


class ScriptTask(DokanScriptTask, ZombieGuildAssets):
    """僵尸寮：只打福利寮"""

    # 读本任务自己的配置段、把自己的调度写回自己（基类默认是 dokan / Dokan）
    CONFIG_KEY = 'zombie_guild'
    TASK_NAME = 'ZombieGuild'
    conf: ZombieGuild = None

    # 福利寮名单（归一化后缓存，只读一次）
    welfare_names = None

    # ------------------------------------------------------------------ 名单

    def welfare_name_list(self) -> list[str]:
        """读取任务目录下的 福利寮名单.txt：一行一个寮名，空行忽略。"""
        welfare_file = Path(__file__).parent / '福利寮名单.txt'
        try:
            with open(welfare_file, 'r', encoding='utf-8') as file:
                return [line.strip() for line in file if line.strip()]
        except FileNotFoundError:
            self.push_notify(content=f'福利寮名单文件未找到: {welfare_file}')
            logger.warning(f'福利寮名单文件未找到: {welfare_file}')
            return []
        except Exception as e:
            self.push_notify(content=f'读取福利寮名单时出错: {e}')
            logger.error(f'读取福利寮名单时出错: {e}')
            return []

    @staticmethod
    def normalize_name(name: str) -> str:
        """去掉 OCR 结果里的空白、括号等噪声，便于与名单比对。"""
        return re.sub(r'[\s·•・&＆:：,，.。\-—_()（）\[\]【】]', '', name or '')

    def is_welfare(self, dokan_name: str) -> bool:
        """寮名是否属于福利寮（OCR 结果与名单做双向包含匹配，容忍多识别出的字）。"""
        if self.welfare_names is None:
            self.welfare_names = [self.normalize_name(n) for n in self.welfare_name_list()]
        name = self.normalize_name(dokan_name)
        if not name:
            return False
        return any(w and (w == name or w in name or name in w) for w in self.welfare_names)

    # ------------------------------------------------------------- QQ 门控

    def run(self):
        # 基类是在 super().run() 里（before_run 之后）才给 self.conf 赋值，而 QQ 门控要用到它，
        # 所以这里先按基类同样的方式取一次，否则 self.conf 还是类属性 None。
        # （super().run() 里会再赋一次，幂等，不影响后续流程。）
        self.conf = getattr(self.config.model, self.CONFIG_KEY)
        # QQ 群消息未放行时，check_qq_gate 已经安排好下次运行时间
        if not self.check_qq_gate():
            raise TaskEnd('ZombieGuild')
        super().run()

    def check_qq_gate(self) -> bool:
        """QQ 群消息门控：返回 True 表示放行（或未启用检查）。

        未放行时按配置设置下次运行时间并返回 False，由 run() 结束本次任务。
        """
        cfg = self.conf.qq_message_config
        if not cfg.enable:
            return True
        listener = QQListener()
        # 调度器是执行时间的唯一来源，手动立即执行也使用新任务时间。
        result = listener.check(self.config.config_name, cfg,
                                scheduled_at=self.conf.scheduler.next_run)
        logger.info(f'QQ群消息未匹配次数 {result.attempts}/{cfg.max_checks}：{result.reason}')
        if result.allowed:
            return True
        if result.next_run is None:
            self.set_next_run(task=self.TASK_NAME)
        else:
            self.set_next_run(task=self.TASK_NAME,
                              target=result.next_run.astimezone().replace(tzinfo=None))
        return False

    # --------------------------------------------------------------- 选寮

    def find_dokan(self, score=4.6):
        """只挑福利寮：滑动/刷新流程与本地道馆一致，采纳条件换成「寮名在名单里」。

        - 不看赏金与系数（福利寮可能很穷），只看寮名 + 配置的人数下限
        - 没有「刷新用完就随便挑一个系数最低的」兜底，找不到返回 False，
          基类会按 DokanNotStartedError 走失败间隔重排

        :param score: 保留基类签名，本任务不使用
        :return: 是否找到福利寮并已点出挑战
        """
        self.found_dokan_cnt += 1
        num_fresh = 0
        backup = {'i_point_bounty': self.I_RIGHTPAD_POINT_BOUNTY.roi_back,
                  'i_point_people_num': self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back}

        def restore_roi():
            self.I_RIGHTPAD_POINT_BOUNTY.roi_back = backup['i_point_bounty']
            self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back = backup['i_point_people_num']

        def find_welfare() -> bool:
            """在当前列表（一般 4 个）里找名单内的福利寮，并点出挑战按钮"""
            restore_roi()
            self.screenshot()
            bounty_list = self.find_all_element(self.I_RIGHTPAD_POINT_BOUNTY, (0, 0, 0, 50))
            logger.info(f'福利寮查找：当前列表 {len(bounty_list)} 个')
            for idx, item in enumerate(bounty_list):
                self.device.click_record_clear()
                # 收起上一个寮残留的挑战按钮（动画较慢，等它稳定）
                self.screenshot()
                while self.appear(self.I_CENTER_CHALLENGE):
                    self.click(self.C_DOKAN_CANCEL_SELECT_DOKAN, interval=1.5)
                    self.wait_animate_stable(self.C_DOKAN_CANCEL_SELECT_DOKAN_CHECK_ANIMATE,
                                             interval=0.5, timeout=1.5)

                # 寮名不是福利寮直接跳过
                self.O_DOKAN_RIGHTPAD_NAME.roi = position_offset(item, (-37, 29, 127, 0))
                dokan_name = self.O_DOKAN_RIGHTPAD_NAME.detect_text(self.device.image)
                if not self.is_welfare(dokan_name):
                    logger.info(f'道馆 {dokan_name!r} 不在福利寮名单，跳过')
                    continue

                # 是福利寮：点出挑战按钮（被别的寮打了会点不出来）
                self.I_RIGHTPAD_POINT_BOUNTY.roi_back = position_offset(item, (-10, -10, 20, 20))
                if not self.ui_click_until_appear_or_timeout(
                        self.I_RIGHTPAD_POINT_BOUNTY, self.I_CENTER_CHALLENGE,
                        interval=1.5, timeout=8):
                    logger.info(f'福利寮 {dokan_name!r} 当前不可挑战，跳过')
                    continue

                # 人数下限（沿用道馆配置里的 min_people_num）
                self.screenshot()
                if self.appear(self.I_CENTER_POINT_PEOPLE_NUMBER):
                    self.O_DOKAN_CENTER_PEOPLE_NUMBER.roi = position_offset(
                        self.I_CENTER_POINT_PEOPLE_NUMBER.roi_front, (0, 0, 0, 30))
                    p_num = self.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text(self.device.image)
                    tmp = re.search(r'(\d+)', p_num)
                    if tmp and float(tmp.group()) < self.conf.dokan_config.min_people_num:
                        logger.info(f'福利寮 {dokan_name!r} 人数 {tmp.group()} 低于下限 '
                                    f'{self.conf.dokan_config.min_people_num}，跳过')
                        continue

                logger.info(f'找到福利寮: {dokan_name}')
                self.push_notify(content=f'开启福利道馆: {dokan_name}')
                return True
            return False

        while num_fresh < self.conf.dokan_config.find_dokan_refresh_count:
            for i in range(3):
                sleep(3)
                if find_welfare():
                    self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
                    self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
                    # 更新今日可挑战次数（与道馆共用同一份次数记账）
                    self.conf.attack_count_config.del_attack_count(1, self.config.save)
                    restore_roi()
                    return True
                # 滑动道馆列表
                self.swipe(self.S_DOKAN_LIST_UP)
            restore_roi()
            logger.info('=========refresh dokan list=========')
            self.ui_click(self.C_DOKAN_REFRESH, self.I_REFRESH_ENSURE, interval=1)
            self.ui_click_until_disappear(self.I_REFRESH_ENSURE, interval=1)
            logger.info('Refresh Done')
            num_fresh += 1

        # 刷新次数用完仍未找到福利寮：本任务只打福利寮，不退化为普通寮
        logger.warning('未找到福利寮，本轮结束')
        self.push_notify(content='未找到福利寮')
        restore_roi()
        return False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
