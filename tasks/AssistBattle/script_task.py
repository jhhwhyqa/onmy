from datetime import datetime, timedelta
from time import sleep

from module.base.timer import Timer
from module.logger import logger
from module.exception import TaskEnd
from tasks.Component.SwitchAccount.switch_account import SwitchAccount
from tasks.EvoZone.config import Layer, KirinType
from tasks.EvoZone.script_task import ScriptTask as EvoZoneScriptTask
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidScriptTask
from tasks.DailyTrifles.script_task import ScriptTask as DailyTriflesScriptTask
from tasks.KekkaiUtilize.script_task import ScriptTask as KekkaiUtilizeScriptTask
from tasks.KekkaiUtilize.page import page_guild_realm
from tasks.GameUi.page import page_main, page_assist_battle
from tasks.WantedQuests.assets import WantedQuestsAssets
from tasks.WantedQuests.config import CooperationType
from tasks.AssistBattle.assets import AssistBattleAssets
from tasks.AssistBattle.config import AssistBattleConfig


class ScriptTask(
    EvoZoneScriptTask,
    RealmRaidScriptTask,
    DailyTriflesScriptTask,
    KekkaiUtilizeScriptTask,
    AssistBattleAssets,
):

    conf: AssistBattleConfig

    def run(self):
        self.conf = self.config.model.assist_battle
        accounts = [account for account in self.conf.account_list if account.is_valid()]
        results = []
        if not accounts:
            logger.info('No AssistBattle account configured; run on current account')
            evozone_done, realmraid_done, evozone_final, realmraid_final, jade_flag = (
                self.run_current_account()
            )
            results.append(
                {
                    'account': account.account,
                    'character': account.character,
                    'svr': account.svr,
                    'evozone_done': evozone_done,
                    'realmraid_done': realmraid_done,
                    'evozone_final': evozone_final,
                    'realmraid_final': realmraid_final,
                    'jade_flag': jade_flag,
                }
            )
        else:
            for account in accounts:
                logger.hr(
                    'Run AssistBattle for %s-%s' % (account.character, account.svr), 2
                )
                if not SwitchAccount(self.config, self.device, account).switchAccount():
                    logger.warning(
                        'Switch to %s-%s failed; skip it',
                        account.character,
                        account.svr,
                    )
                    continue
                (
                    evozone_done,
                    realmraid_done,
                    evozone_final,
                    realmraid_final,
                    jade_flag,
                ) = self.run_current_account()
                results.append(
                    {
                        'account': account.account,
                        'character': account.character,
                        'svr': account.svr,
                        'evozone_done': evozone_done,
                        'realmraid_done': realmraid_done,
                        'evozone_final': evozone_final,
                        'realmraid_final': realmraid_final,
                        'jade_flag': jade_flag,
                    }
                )
        # 输出协战结果
        logger.hr('AssistBattle Result', 2)
        push_content = []
        push_content.append(f"本次执行任务：")
        for result in results:
            # 账号取前4位，服务器取后4位，角色名取后2位
            message = f"{result['account'][:4] + ('**' if len(result['account']) > 4 else '')}-{result['svr'][-4:]}-{'**' + result['character'][-2:]}:"
            if self.conf.assist_battle_config.evozone_enable:
                message += f"觉醒{result['evozone_done']}次"
            if self.conf.assist_battle_config.realmraid_enable:
                message += f"-个突{result['realmraid_done']}次"
            if self.conf.assist_battle_config.find_jade_enable:
                message += f"-{'有' if result['jade_flag'] else '无'}勾"
            logger.info(message)
            push_content.append(message)
        push_content.append(f"今日协战任务：")
        for result in results:
            message = f"{result['account'][:4] + ('…' if len(result['account']) > 4 else '')}-{result['svr'][-4:]}-{'…' + result['character'][-2:]}:"
            if self.conf.assist_battle_config.evozone_enable:
                message += f"觉醒{result['evozone_final']}次"
            if self.conf.assist_battle_config.realmraid_enable:
                message += f"-个突{result['realmraid_final']}次"
            push_content.append(message)
        # 推送协战完成结果
        if self.conf.assist_battle_config.result_push_enable:
            self.config.notifier.push(
                title='多号任务完成',
                content='<{}><br>{}'.format(
                    self.config.config_name,
                    '<br>'.join(push_content),
                ),
            )
        self.set_next_run(task='AssistBattle', success=True, finish=True)
        raise TaskEnd('AssistBattle')

    def run_current_account(self):
        # 执行任务前先获取本账号协战剩余次数以检查是否执行过前置任务，觉醒协战已做完将不再执行日常任务
        total_evozone, total_realmraid = 15, 3
        evozone_done, realmraid_done = 0, 0
        evozone_final, realmraid_final = 0, 0
        jade_flag = False
        # 不执行协战任务时，可以用来小号挂日常
        start_evozone = 1

        if (
            self.conf.assist_battle_config.evozone_enable
            or self.conf.assist_battle_config.realmraid_enable
        ):
            start_evozone, start_realmraid = self.get_assist_battle_count()

        # 结界寄养
        if self.conf.assist_battle_config.kekkaiutilize_enable and start_evozone > 0:
            # 进入寮结界
            self.goto_page(page_guild_realm)
            self.check_utilize_add()
            self.goto_page(page_main)

        # 庭院事务
        if (
            self.conf.assist_battle_config.courtyard_affairs_enable
            and start_evozone > 0
        ):
            self.run_courtyard_affairs()
            self.goto_page(page_main)

        # 邮件领取
        if self.conf.assist_battle_config.email_enable and start_evozone > 0:
            self.run_pickup_email()
            self.goto_page(page_main)

        # 商店签到
        if self.conf.assist_battle_config.store_sign_enable and start_evozone > 0:
            # 重置done状态
            self.config.daily_trifles.done_record.store_sign_dt = datetime(2023, 1, 1)
            self.run_store_sign()
            self.goto_page(page_main)

        # 寻找勾协
        if self.conf.assist_battle_config.find_jade_enable:
            jade_flag = self.find_jade()
            self.ui_click_until_disappear(self.I_UI_BACK_RED, interval=1)
            self.goto_page(page_main)

        # 执行觉醒副本任务
        if self.conf.assist_battle_config.evozone_enable and start_evozone > 0:
            self.run_evozone(start_evozone)
            self.goto_page(page_main)

        # 执行结界突破任务
        if self.conf.assist_battle_config.realmraid_enable and start_realmraid > 0:
            self.run_realmraid(start_realmraid)
            self.goto_page(page_main)

        # 统计本次执行完成的协战任务
        if (
            self.conf.assist_battle_config.evozone_enable
            or self.conf.assist_battle_config.realmraid_enable
        ):
            end_evozone, end_realmraid = self.get_assist_battle_count()
            evozone_done = start_evozone - end_evozone
            realmraid_done = start_realmraid - end_realmraid
            # 今天已经完成的任务
            evozone_final = total_evozone - end_evozone
            realmraid_final = total_realmraid - end_realmraid
            if self.conf.assist_battle_config.evozone_enable:
                logger.info(
                    "本次协战完成：觉醒 %s 次，结界突破 %s 次",
                    evozone_done,
                    realmraid_done,
                )
            if self.conf.assist_battle_config.realmraid_enable:
                logger.info(
                    "最终协战完成：觉醒 %s 次，结界突破 %s 次",
                    evozone_final,
                    realmraid_final,
                )

        return evozone_done, realmraid_done, evozone_final, realmraid_final, jade_flag

    def find_jade(self):
        """寻找勾协并标记"""
        if self.get_current_page() != page_main:
            self.goto_page(page_main)
        # 打开悬赏封印 界面
        done_timer = Timer(5)
        while 1:
            self.screenshot()
            if self.appear(WantedQuestsAssets.I_TRACE_ENABLE) or self.appear(
                WantedQuestsAssets.I_TRACE_DISABLE
            ):
                break
            if self.appear_then_click(WantedQuestsAssets.I_WQ_SEAL, interval=1):
                continue
            if self.appear_then_click(WantedQuestsAssets.I_WQ_DONE, interval=1):
                continue
            # 未适配特殊庭院，小号嘛，应该没这个情况
            # if self.special_main and self.click(WantedQuestsAssets.C_SPECIAL_MAIN, interval=3):
            #     logger.info('Click special main left to find wanted quests')
            #     continue
            if self.appear(self.I_UI_BACK_RED):
                if not done_timer.started():
                    done_timer.start()
            if done_timer.started() and done_timer.reached():
                self.ui_click_until_disappear(self.I_UI_BACK_RED)
                return False

        if not (
            self.appear(WantedQuestsAssets.I_WQ_INVITE_1)
            or self.appear(WantedQuestsAssets.I_WQ_INVITE_2)
            or self.appear(WantedQuestsAssets.I_WQ_INVITE_3)
        ):
            logger.info("there is no cooperation quest")
            return False
        # 存在勾协即返回true
        self.screenshot()
        if self.appear(WantedQuestsAssets.I_WQ_INVITE_1):
            if self.appear(WantedQuestsAssets.I_WQ_COOPERATION_TYPE_JADE_1):
                return True
        if self.appear(WantedQuestsAssets.I_WQ_INVITE_2):
            if self.appear(WantedQuestsAssets.I_WQ_COOPERATION_TYPE_JADE_2):
                return True
        if self.appear(WantedQuestsAssets.I_WQ_INVITE_3):
            if self.appear(WantedQuestsAssets.I_WQ_COOPERATION_TYPE_JADE_3):
                return True
        return False

    def get_assist_battle_count(self):
        """获取当前账号剩余的协战次数。"""
        self.goto_page(page_assist_battle)
        # 切换界面可能卡顿等个动画
        sleep(0.5)
        self.screenshot()
        _, evozone_res, _ = self.O_NORMAL_ASSIST_COUNT.ocr(self.device.image)
        _, realmraid_res, _ = self.O_REALMRAID_ASSIT_COUNT.ocr(self.device.image)

        return evozone_res, realmraid_res

    def run_evozone(self, count: int):
        """运行觉醒协战"""
        logger.hr('Run Evozone AssistBattle', 3)
        self.config.evo_zone.evo_zone_config.layer = Layer.FIVE
        self.config.evo_zone.evo_zone_config.kirin_type = KirinType.LIGHTNINGKIRIN
        self.config.evo_zone.general_battle_config.lock_team_enable = True
        self.current_count = 0
        self.limit_count = count
        self.limit_time = timedelta(hours=10)
        self.run_alone()

    def run_realmraid(self, count: int):
        """运行结界突破"""
        logger.hr('Run RealmRaid AssistBattle', 3)

        con = self.config.realm_raid

        con.raid_config.number_attack = count
        if self.conf.assist_battle_config.realmraid_easy_enable:
            con.raid_config.exit_four = False
            con.raid_config.order_attack = '0 > 1 > 2 > 3 > 4 > 5'
        con.general_battle_config.lock_team_enable = True
        con.switch_soul_config.enable = False
        if self.conf.assist_battle_config.switch_soul_enable:
            con.switch_soul_config.enable = True
        self.run_realmraid_core(con)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
