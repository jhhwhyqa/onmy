from time import sleep

from tasks.ActivityExploration.assets import ActivityExplorationAssets
from tasks.ActivityExploration.config import ActivityExplorationConfig
from tasks.ActivityExploration.page import page_act_exploration
from tasks.ActivityShikigami.page import page_act
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.GameUi.game_ui import GameUi
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul

from module.exception import TaskEnd
from module.logger import logger


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, ActivityExplorationAssets):

    conf: ActivityExplorationConfig

    def run(self):
        self.conf = self.config.model.activity_exploration
        # 自动换御魂
        if self.conf.switch_soul_config.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(self.conf.switch_soul_config.switch_group_team)
        if self.conf.switch_soul_config.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(
                self.conf.switch_soul_config.group_name,
                self.conf.switch_soul_config.team_name,
            )
        if self.get_current_page(fallback=True) != page_act_exploration:
            self.goto_page(page_act)
            self.goto_page(page_act_exploration)

        loop_count = 0
        while 1:
            # 等待上一次点击或滑动结果
            sleep(1)
            self.screenshot()
            # 跳过剧情对话
            if self.appear_then_click(self.I_ACT_SKIP, interval=1.5):
                sleep(0.5)
                self.screenshot()
                self.appear_then_click(self.I_ACT_CONFIRM_SKIP, interval=1.5)
                continue
            # 关闭剧情横幅
            if self.appear_then_click(self.I_ACT_RED_CLOSE, interval=1.5):
                continue
            # 开启宝箱
            if self.appear(self.I_BOX_EVENT):
                # 应该换成ui_get_reward()但能跑就懒得换了
                self.ocr_appear_click(self.O_ACT_OPEN, interval=1.5)
                continue
            # 进入战斗
            if self.appear(self.I_FIGHT_EVENT):
                # 关闭错误的战斗页面
                if (
                    not self.conf.activity_exploration_config.encounter_battle_enable
                    and self.appear(self.I_ENCOUNTER_BATTLE_EVENT)
                ):
                    self.appear_then_click(self.I_HARD_FIGHT_CLOSE, interval=1.5)
                    continue
                # 遭遇战战斗
                if self.appear(self.I_ENCOUNTER_BATTLE_EVENT):
                    if self.ocr_appear_click(self.O_ACT_CHALLENGE, interval=1.5):
                        self.run_general_battle(config=self.conf.general_battle_config)
                # 普通战斗
                elif self.ocr_appear_click(self.O_ACT_CHALLENGE, interval=1.5):
                    self.run_general_battle()
                continue
            # 获取新助战式神
            if self.appear_then_click(self.I_GET_ASSIST, interval=1.5):
                continue
            # 判定是否执行遭遇战
            if (
                self.conf.activity_exploration_config.encounter_battle_enable
                and self.appear_then_click(self.I_ENCOUNTER_BATTLE, interval=1.5)
            ):
                continue
            # 优先执行支线任务
            if self.appear_then_click(self.I_BRANCH_EVENT, interval=1.5):
                continue
            if loop_count >= 3:
                logger.hr("no event can do, exit")
                break
            # 判断是否可继续执行
            if self.appear(self.I_ACT_LOCKED):
                self.swipe(self.S_SWIPE_DOWN, interval=1)
                sleep(1)
                continue
            # 主线任务
            if self.appear_then_click(
                self.I_MAIN_EVENT, interval=1.5
            ) and not self.appear(self.I_ACT_LOCKED):
                continue
            # 检查可执行任务
            if (
                (self.appear(self.I_ACT_LOCKED) or not self.appear(self.I_MAIN_EVENT))
                and not self.appear(self.I_BRANCH_EVENT)
                and not (
                    self.conf.activity_exploration_config.encounter_battle_enable
                    and self.appear(self.I_ENCOUNTER_BATTLE)
                )
            ):
                logger.info("no event can do, try again")
                loop_count += 1

        self.screenshot()
        self.goto_page(page_main)
        self.set_next_run(task='ActivityExploration', success=True, finish=True)
        raise TaskEnd('ActivityExploration')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
