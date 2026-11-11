# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

import random
from datetime import datetime, timedelta
from module.atom.image import RuleImage

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import (
    BattleAction,
    BattleContext,
    GeneralBattle,
)
from tasks.Component.QuickLoadout.config import (
    QuickLoadoutConfig,
    QuickLoadoutMode,
)
from tasks.Component.QuickLoadout.quick_loadout import QuickLoadout
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.MetaDemon.config import (
    HIGH_STAR_TYPES,
    LOW_STAR_TYPES,
    MetaDemon,
    BossType,
    boss_names_for,
    canonical_boss_name,
    normalize_boss_name,
)
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.friend_invite import FriendInviter
from tasks.MetaDemon.ticket_farm import TicketFarmMixin
import tasks.MetaDemon.page as ipages

from module.logger import logger
from module.exception import TaskEnd


class ScriptTask(GeneralBattle, SwitchSoul, GameUi, QuickLoadout, FriendInviter, TicketFarmMixin, MetaDemonAssets):
    """超鬼王"""

    class State:
        done: bool = False
        synthesis_done: bool = False
        # 上一次已经切到的御魂目标(星级粒度, 一至四星统一为 low_star)
        soul_key: str = ''
        # 上一次已经上阵的阵容标识, 用于避免同一鬼王重复切换
        lineup_key: str = ''
        # 一键配置连续失败次数, 达到上限就收工
        lineup_fail_count: int = 0
        # 邀请连续失败次数, 同一只鬼王反复邀请达到上限就收工
        invite_fail_count: int = 0
        # 仅协战: 点击「已分享」后战斗准备连续失败次数(条目已死/鬼王已过期), 达上限收工
        assist_dead_count: int = 0
        # 召唤偶发失败次数: 弹窗点完却没召出鬼王, 达上限收工
        summon_fail_count: int = 0
        # 最近一次读到的疲劳上限, 用于弹窗遮挡时估算恢复时间
        fatigue_total: int = 0

    # 一键配置连续失败上限, 防止素材/预设异常时空转
    LINEUP_FAIL_LIMIT = 3
    # 同一只鬼王邀请连续失败上限
    INVITE_FAIL_LIMIT = 3
    # 仅协战: 点击「已分享」后准备连续失败上限(标记残留的已死条目)
    ASSIST_DEAD_LIMIT = 3
    # 召唤无进展超时(秒): 超过就当本次召唤失败, 回挑战页重试
    SUMMON_STALL_TIMEOUT = 20.0
    # 召唤连续失败上限
    SUMMON_FAIL_LIMIT = 3
    # switch_once 模式下御魂只切一次的哨兵值
    SOUL_KEY_ALL = '__all__'
    # 仅协战模式：轮询界面的间隔（秒）
    ASSIST_POLL_INTERVAL = 5.0

    conf: MetaDemon = None
    cur_boss_type: BossType = None
    boss_name: str = ''
    total_count: int = 0

    def _boss_name_key(self) -> str:
        """把鬼王名归一化成 battle_key / 阵容标识可用的片段。"""
        return normalize_boss_name(self.boss_name) or 'unknown'

    @property
    def lineup_by_boss_name(self) -> bool:
        """只有启用一键配置时才能按鬼王名细分阵容，切御魂做不到。"""
        return bool(self.conf.boss_quick_loadout_config.enable and self._quick_loadout_assets())

    @property
    def current_lineup_key(self) -> str:
        """当前鬼王应使用的阵容标识；粒度必须与实际能区分的粒度一致。"""
        if self.cur_boss_type is None:
            return ''
        preset_key = self.conf.switch_soul.preset_key(self.cur_boss_type)
        if self.cur_boss_type in HIGH_STAR_TYPES and self.lineup_by_boss_name:
            return f'{preset_key}:{self._boss_name_key()}'
        return preset_key

    def _meta_demon_battle_key(self) -> str:
        """返回当前鬼王对应的战斗分组键；五星六星按鬼王名区分以重放切预设。"""

        if self.cur_boss_type is None:
            return "meta_demon_default"
        preset_key = self.conf.switch_soul.preset_key(self.cur_boss_type)
        if self.cur_boss_type in HIGH_STAR_TYPES and self.lineup_by_boss_name:
            return f"meta_demon_{preset_key}_{self._boss_name_key()}"
        return f"meta_demon_{preset_key}"

    def before_run(self):
        self.navigator.add_unknown_closer(self.I_MD_GET_YESTERDAY_REWARD)
        self.conf = self.config.meta_demon
        self.limit_time = self.conf.meta_demon_config.limit_time_v
        self.limit_count = self.conf.meta_demon_config.limit_count
        page_shikigami_records = self.navigator.resolve_page(ipages.page_shikigami_records)
        page_meta_demon_boss = self.navigator.resolve_page(ipages.page_meta_demon_boss)
        page_main = self.navigator.resolve_page(ipages.page_main)
        if page_shikigami_records is None or page_meta_demon_boss is None or page_main is None:
            raise RuntimeError("MetaDemon 页面 session 初始化失败")

        # 仅修改当前任务 session 内的跳转图，不污染全局页面定义
        page_shikigami_records.clear_transitions()
        page_shikigami_records.connect(
            page_meta_demon_boss,
            self.I_UI_BACK_YELLOW,
            key="page_shikigami_records->page_meta_demon_boss",
        )
        page_meta_demon_boss.connect(
            page_shikigami_records,
            MetaDemonAssets.I_MD_SHIKIGAMI,
            key="page_meta_demon_boss->page_shikigami_records",
        )
        page_main.remove_transition(key="page_main->page_shikigami_records")

    def run(self):
        self.before_run()
        # 门票不足时先刷票（探索/觉醒），刷满再开始正式活动
        if not self.ensure_tickets():
            logger.warning('Ticket farm did not finish, retry later')
            self.set_next_run(task='MetaDemon', success=False)
            self.finish_task()
        # 只刷门票模式：刷完就收工，不进活动打鬼王
        if self.conf.meta_demon_ticket_farm.ticket_only:
            if not self.conf.meta_demon_ticket_farm.ticket_farm_enable:
                logger.warning('ticket_only is on but ticket_farm_enable is off, nothing to farm')
            logger.info('Ticket only mode, stop before MetaDemon')
            self.set_next_run(task='MetaDemon', success=True)
            self.finish_task()
        # 战斗时限只算打鬼王阶段；start_time 从任务实例创建就定死，
        # 不重置的话刷票耗掉的时间会把战斗 45 分钟吃光，打一两场就收工
        self.start_time = datetime.now()
        logger.info(f'Battle phase starts, limit_time resets to now '
                    f'({self.limit_time.total_seconds() / 60:.0f}min)')
        self.goto_page(ipages.page_meta_demon_boss)
        # 大小号协作：邀请模式(大号拉小号)与协助模式(小号拉大号)互斥，由 mode 决定
        assist_only = self.conf.meta_demon_invite.assist_only
        invite_only = self.conf.meta_demon_invite.invite_only
        invite_sequence = self.conf.meta_demon_invite.stars_v if invite_only else None
        while True:
            self.update_global_state()
            if self.State.done:
                break
            self.screenshot()
            current_page = self.get_current_page()
            match current_page:
                case ipages.page_meta_demon:
                    self.goto_page(ipages.page_meta_demon_boss)
                case ipages.page_meta_demon_boss:
                    if invite_only:
                        # 邀请模式：召唤 → 集结邀请 → 等结算 → 循环，自己不挑战
                        if not self.run_invite_round(invite_sequence):
                            self.State.done = True
                            break
                    elif assist_only:
                        # 仅协战：等列表出现单拉目标 -> 点击切到该鬼王 -> 验星级 -> 上阵 -> 打
                        if not self.assist_wait_for_target():
                            self.State.done = True
                            break
                        if not self._assist_boss_acceptable():
                            # 低星/未识别的目标不碰，回列表继续等
                            time.sleep(self.ASSIST_POLL_INTERVAL)
                            continue
                        if self.check_and_prepare_battle():
                            self.start_battle()
                            self.State.assist_dead_count = 0
                        else:
                            # 准备失败多为标记残留的已死条目(好友已打完)，等标记退场再继续
                            self.State.assist_dead_count += 1
                            if self.State.assist_dead_count >= self.ASSIST_DEAD_LIMIT:
                                logger.error(
                                    f'Assist target keeps failing after click '
                                    f'({self.ASSIST_DEAD_LIMIT} times), finish this run'
                                )
                                self.State.done = True
                                break
                            self._assist_wait_marker_gone()
                    elif self.check_and_prepare_battle():
                        self.start_battle()
                case ipages.page_battle:
                    # 超鬼王配置里没有 general_battle 分组, 取不到就按不随机滑动处理,
                    # 避免这里抛 AttributeError 把任务打断
                    general_battle = getattr(self.conf, 'general_battle', None)
                    self.battle_wait(
                        bool(getattr(general_battle, 'random_click_swipt_enable', False))
                    )
                case ipages.page_reward | ipages.page_battle_result:
                    self.click(ipages.random_click(), interval=0.6)
                case _:
                    time.sleep(random.uniform(0.7, 1.4))
        self.set_next_run(task="MetaDemon", success=True)
        self.finish_task()

    def current_battle_conf(self) -> GeneralBattleConfig:
        """当前鬼王的战斗配置；一键配置启用时关掉战斗内预设，避免互相覆盖。"""
        conf = self.conf.switch_soul.get_general_battle_conf(self.cur_boss_type)
        if self.conf.boss_quick_loadout_config.enable and conf.preset_enable:
            logger.info('Quick loadout enabled, disable battle preset for this battle')
            conf = conf.model_copy(update={'preset_enable': False})
        return conf

    def _handle_reward(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        """奖励页顺手读门票进度；战斗中不走 goto_page，hook 收不到。"""
        # 先让父类点一下奖励页，进度条才会显示出来
        action = super()._handle_reward(context, config)
        # 只有真的读到才标记完成，读不到就留到下一帧重试
        if 'ticket_progress' not in context.call_behavior_state.done:
            if self._capture_ticket_progress(screenshot=True):
                context.call_behavior_state.done.add('ticket_progress')
        return action

    def start_battle(self):
        logger.hr('Click fire, start battle')
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                self.total_count += 1
                logger.info(
                    f'Battle {self.total_count}/{self.limit_count} on '
                    f'{self.cur_boss_type.name.lower() if self.cur_boss_type else "None"}'
                    f' [{self.boss_name or "unknown"}]'
                )
                self.run_general_battle(
                    self.current_battle_conf(),
                    battle_key=self._meta_demon_battle_key(),
                )
                break
            # 出战/挑战前的「御魂与预设不一致」弹窗会吞掉后面的点击, 先处理掉
            if self.appear_then_click(self.I_CONFIRM_CLOSE_DIFF_SOUL, interval=0.6):
                logger.info('Confirm auto equip souls and start battle')
                continue
            if self.appear(self.I_MD_DRINK_TEA, interval=1.2):  # 出现喝茶弹窗
                if self.conf.meta_demon_config.auto_tea:
                    self.click(self.I_MD_DRINK_TEA)  # 喝茶
                    continue
                # 不喝茶则结束任务安排下一次运行
                current, _, total = self.O_MD_FATIGUE.ocr(self.device.image)
                self.notify_fatigue_full(current, total)
                self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
                self.set_next_run('MetaDemon', target=datetime.now() + self.conf.scheduler.wait_interval)
                self.finish_task()
            if self.appear_then_click(self.I_MD_FIRE, interval=0.8):
                continue

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        logger.info(f"Start battle process on {self.cur_boss_type.name if self.cur_boss_type else 'None'}")
        win = False
        while True:
            self.screenshot()
            if self.appear(self.I_MD_SUMMON_BOSS, interval=0.8) or \
                    self.appear(self.I_MD_SWITCH_TICKET, interval=0.8) or \
                    self.appear(self.I_MD_FIRE, interval=0.8):
                break
            if self.appear(self.I_WIN, interval=0.8):
                win = True
                self.click(ipages.random_click())
                continue
            if self.appear(self.I_FALSE, interval=0.8):
                win = False
                self.click(ipages.random_click())
                continue
            if self.appear(self.I_MD_SETTLING, interval=3.5):
                logger.info('wait result')
                time.sleep(random.uniform(3, 5))
                continue
        total_run_time = datetime.now() - self.start_time
        logger.info(f'battle win: {win}')
        logger.info(f'battle count: {self.total_count}/{self.limit_count}')
        logger.info(f'time count: {total_run_time.total_seconds():.1f}s/{self.limit_time.total_seconds()}s')
        return win

    def update_global_state(self):
        if datetime.now() - self.start_time >= self.limit_time or \
                self.total_count >= self.limit_count:
            self.State.done = True

    # ---------------------------------------------------------------- 邀请好友模式

    def run_invite_round(self, sequence: list[BossType]) -> bool:
        """一轮邀请：召唤 → 集结邀请指定好友 → 等结算；返回 False 收工。"""
        # 召唤目标星级（六星优先）：鬼王已在界面上则跳过召唤直接邀请
        if not self.appear(self.I_MD_FIRE):
            # 鬼王不在界面 = 上轮已打完，邀请失败计数作废
            self.State.invite_fail_count = 0
            if not self.check_and_switch_ticket(sequence=sequence):
                return False
        self.update_boss_name()
        if not self.invite_friend():
            self.State.invite_fail_count += 1
            if self.State.invite_fail_count >= self.INVITE_FAIL_LIMIT:
                logger.error('Invite keeps failing, stop this run')
                self.State.done = True
                return False
            logger.warning(
                f'Invite failed, skip this boss and continue '
                f'({self.State.invite_fail_count}/{self.INVITE_FAIL_LIMIT})'
            )
            self.State.lineup_key = ''
            # 关掉弹窗回鬼王界面，重新召唤下一只
            self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
            return True
        if not self.wait_friend_finish():
            return False
        logger.info('Invite round done, continue summon next')
        self.State.lineup_key = ''
        return True

    # ---------------------------------------------------------------- 仅协战模式

    def _assist_click_target(self) -> bool:
        """点击「已分享」标记所在条目，切换到对应鬼王。"""
        if self.appear_then_click(self.I_MD_ASSIST_ALONE, interval=1.0):
            logger.info('Click shared boss entry, switch to it')
            return True
        return False

    def _assist_wait_marker_gone(self, timeout: float = 30.0):
        """好友打完后「已分享」标记会残留，等它退场避免立刻重点同一条目。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.device.stuck_record_clear()
            self.screenshot()
            if not self.appear(self.I_MD_ASSIST_ALONE):
                return
            time.sleep(self.ASSIST_POLL_INTERVAL)

    def assist_wait_for_target(self) -> bool:
        """仅协战模式：鬼王列表等单拉目标，扫到「已分享」就点击切过去；超时收工。"""
        minutes = self.conf.meta_demon_invite.assist_wait_minutes
        deadline = datetime.now() + timedelta(minutes=minutes)
        logger.hr(f'Assist only: wait for shared boss (up to {minutes}min)', 2)
        while datetime.now() < deadline:
            if self.State.done:
                return False
            # 长等待不点击, stuck 看门狗 60 帧无操作就抛 GameStuckError, 必须定期清记录
            self.device.stuck_record_clear()
            self.screenshot()
            if self._assist_click_target():
                return True
            remain = (deadline - datetime.now()).total_seconds()
            logger.info(f'No assist target yet, {remain:.0f}s left')
            time.sleep(self.ASSIST_POLL_INTERVAL)
        logger.warning('No assist target within wait time, finish this run')
        return False

    def _assist_boss_acceptable(self) -> bool:
        """协战目标只打五六星名单里的鬼王，星级靠名字精确匹配推断。"""
        # 清掉上一个协战目标残留的星级, 避免五星名被子串匹配进六星名单
        self.cur_boss_type = None
        self.update_boss_name()
        if self.cur_boss_type is not None and self.cur_boss_type in HIGH_STAR_TYPES:
            return True
        # 协战目标不是自己召唤的，没有门票星级，只能在五六星名单里找名字
        if not self.boss_name:
            logger.warning('Assist target boss name unknown, skip')
            return False
        for boss_type in HIGH_STAR_TYPES:
            # 精确匹配，不做包含推断，避免五星名字被子串带进六星名单
            if self.boss_name in boss_names_for(boss_type):
                self.cur_boss_type = boss_type
                logger.info(f'Assist boss "{self.boss_name}" -> {boss_type.name}')
                return True
        logger.info(f'Assist boss "{self.boss_name}" not in five/six star lists, skip')
        return False

    def check_and_prepare_battle(self) -> bool:
        """战斗前准备；返回 True 可以开打。"""
        logger.hr('battle prepare', 2)
        assist_only = self.conf.meta_demon_invite.assist_only
        if not assist_only:
            # 正常模式才检查疲劳/合成/召唤；仅协战打的不是自己的鬼王
            if not self.check_fatigue():
                return False
            self.synthesis_boss_ticket()
            if not self.check_and_switch_ticket():
                return False
        # 门票切换完成后才知道当前鬼王星级, 此时再读取鬼王名并上阵对应阵容
        self.update_boss_name()
        if not self.check_and_switch_powerful():
            return False
        return self.check_and_switch_lineup()

    def synthesis_boss_ticket(self):
        """合成鬼王"""
        if self.State.synthesis_done:
            return
        logger.hr('synthesis boss ticket')
        self.State.synthesis_done = True
        if len(self.conf.meta_demon_config.synthesis_list_v) <= 0:
            return
        type_ticket_dict: dict[BossType, tuple[RuleImage, int]] = {
            BossType.ONE_STAR: (self.I_MD_SYNTHESIS_ONE_STAR, 3),
            BossType.TWO_STARS: (self.I_MD_SYNTHESIS_TWO_STAR, 3),
            BossType.THREE_STARS: (self.I_MD_SYNTHESIS_THREE_STAR, 3),
            BossType.FOUR_STARS: (self.I_MD_SYNTHESIS_FOUR_STAR, 3),
            BossType.FIVE_STARS: (self.I_MD_SYNTHESIS_FIVE_STAR, 2),
        }
        synthesis_list = self.conf.meta_demon_config.synthesis_list_v
        self.ui_click(self.I_MD_SYNTHESIS, self.I_MD_START_SYNTHESIS, interval=0.6)
        for boss_type in synthesis_list:
            self.do_synthesis(type_ticket_dict[boss_type][0], type_ticket_dict[boss_type][1])
        self.ui_click(self.I_MD_CLOSE_POPUP, self.I_MD_SHIKIGAMI, interval=0.6)  # 关闭弹窗退回到鬼王界面

    def do_synthesis(self, target_boss_ticket: RuleImage, need_ticket: int):
        """合成指定级别的鬼王，need_ticket 为所需门票数。"""
        if not self.appear(target_boss_ticket):
            logger.info(f'{target_boss_ticket} not recognized, skip synthesis')
            return
        click_cnt, max_cnt = 0, random.randint(2, 3)
        while True:
            self.screenshot()
            if click_cnt >= max_cnt:  # 兜底,多次点击开始合成都没有出现获得奖励则退出
                break
            if self.appear(self.I_MD_SYNTHESIS_NEED_MONEY, interval=0.8):  # 出现花钱购买合成券
                self.ui_click(self.I_MD_CLOSE_POPUP, self.I_MD_START_SYNTHESIS, interval=0.6)  # 关闭购买弹窗
                break
            if self.appear(self.I_UI_REWARD, interval=0.8):  # 出现获得奖励说明合成成功
                self.click(ipages.random_click(), interval=0.6)
                click_cnt = 0  # 清空点击标志
                continue
            if self.appear(self.I_MD_SYNTHESIS_EMPTY, interval=0.8):  # 有空位
                empty_list = self.I_MD_SYNTHESIS_EMPTY.match_all(self.device.image, frame_id=self.device.image_frame_id)
                if len(empty_list) < need_ticket:  # 空位数量小于需要的门票数量->门票不够则退出
                    logger.info(f'{target_boss_ticket} ticket not enough, skip synthesis')
                    break
            if self.appear_then_click(target_boss_ticket, interval=2):  # 点击对应级别鬼王门票
                if self.appear_then_click(self.I_MD_START_SYNTHESIS, interval=2.5):  # 点击开始合成
                    click_cnt += 1
                continue
        logger.info(f'{target_boss_ticket} synthesis done')

    def _fatigue_recover_minutes(self, current: int, total: int) -> int:
        """按 1 疲劳值 1 分钟估算满值后的恢复时间。"""
        value = max(int(current or 0), int(total or 0))
        if value <= 0:
            # 弹窗遮挡等情况下 OCR 可能读不到, 用最近一次读到的上限兜底
            value = int(self.State.fatigue_total or 0)
        return value

    @staticmethod
    def _format_fatigue_minutes(minutes: int) -> str:
        if minutes <= 0:
            return '未知'
        hours, mins = divmod(minutes, 60)
        if hours and mins:
            return f'{hours}小时{mins}分钟'
        if hours:
            return f'{hours}小时'
        return f'{mins}分钟'

    def notify_fatigue_full(self, current: int = 0, total: int = 0) -> None:
        """疲劳值满时推送恢复所需时间。"""
        minutes = self._fatigue_recover_minutes(current, total)
        content = f'疲劳值已满，恢复满值所需时间为：{self._format_fatigue_minutes(minutes)}'
        logger.warning(content)
        self.config.notifier.push(title='超鬼王疲劳值已满', content=content)

    def check_fatigue(self):
        logger.hr('Check fatigue')
        current, remain, total = self.O_MD_FATIGUE.ocr(self.device.image)
        if total > 0:
            self.State.fatigue_total = total
        # 不喝茶且当前疲劳度已满
        if not self.conf.meta_demon_config.auto_tea and (current > total or remain < 0):
            self.notify_fatigue_full(current, total)
            self.set_next_run('MetaDemon', target=datetime.now() + self.conf.scheduler.wait_interval)
            self.finish_task()
        return True

    def check_and_switch_ticket(self, sequence: list[BossType] | None = None):
        """切换鬼王门票并更新当前鬼王级别；sequence 为空时用配置的攻击顺序。"""
        logger.hr('Summon boss')
        # 打开切换门票弹窗
        while True:
            self.screenshot()
            if self.appear(self.I_MD_FIRE, interval=1.2):  # 可以直接挑战鬼王则退出
                # 上一轮已经召唤好鬼王时走这里，星级还没确定，补一次识别
                if self.cur_boss_type is None:
                    self._detect_deployed_boss_type()
                return True
            if self.appear(self.I_MD_GET_BOSS, interval=0.6):  # 打开弹窗了
                break
            if self.appear(self.I_MD_TICKET_EMPTY, interval=0.6):  # 任何门票都没有了
                self.State.done = True
                logger.info('Not have any boss ticket, exit')
                return False
            if self.appear_then_click(self.I_MD_SWITCH_TICKET, interval=0.6):
                continue
        type_ticket_dict: dict[BossType, RuleImage] = {
            BossType.ONE_STAR: self.I_MD_ONE_STAR,
            BossType.TWO_STARS: self.I_MD_TWO_STARS,
            BossType.THREE_STARS: self.I_MD_THREE_STARS,
            BossType.FOUR_STARS: self.I_MD_FOUR_STARS,
            BossType.FIVE_STARS: self.I_MD_FIVE_STARS,
            BossType.SIX_STARS: self.I_MD_SIX_STARS,
        }
        # 获取所有存在的鬼王门票
        can_fire_list = [boss_type for boss_type, ticket_rule_image in type_ticket_dict.items() if
                         self.appear(ticket_rule_image)]
        if len(can_fire_list) <= 0:
            self.State.done = True
            logger.info('No remain boss ticket, exit')
            self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
            return False
        # 根据存在的鬼王门票和召唤优先级过滤出需要召唤的鬼王门票
        if sequence:
            need_fire_list = [boss_type for boss_type in sequence
                              if boss_type in can_fire_list]
        else:
            need_fire_list = [boss_type for boss_type in self.conf.meta_demon_config.fire_sequence_v if
                              boss_type in can_fire_list]
        if len(need_fire_list) <= 0:
            self.State.done = True
            logger.info('There is no boss that needs to be attacked, exit')
            self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
            return False
        # 鬼王级别变了: 阵容标识作废, 等确认新鬼王后重新上阵
        if self.cur_boss_type is None or self.cur_boss_type != need_fire_list[0]:
            self.State.lineup_key = ''
            self.current_count = 0
        self.cur_boss_type = need_fire_list[0]  # 更新当前鬼王级别
        self.boss_name = ''  # 鬼王级别变了, 旧的鬼王名作废, 等召唤后再识别
        target_ticket_rule_image = type_ticket_dict[self.cur_boss_type]
        selected = False
        logger.info(f'Summon {self.cur_boss_type.name.lower()} boss')
        # 游戏偶发点了召唤却没召出鬼王: 挑战/选中/门票都不在, 循环空转只截图
        # 会被 stuck 看门狗 60 帧杀掉, 所以无进展超时就关弹窗返回 False 重试
        last_progress = time.time()
        while True:
            self.screenshot()
            if self.appear(self.I_MD_FIRE):  # 可以挑战鬼王则退出
                self.State.summon_fail_count = 0
                return True
            if selected and self.appear(self.I_MD_CHECK_SELECTED, interval=0.6):
                selected_x, selected_y = self.I_MD_CHECK_SELECTED.coord()
                x, y, w, h = target_ticket_rule_image.roi_front
                if x <= selected_x <= x + w:  # 确定选中目标鬼王门票, 召唤鬼王
                    self.ui_click_until_disappear(self.I_MD_GET_BOSS, interval=0.6)
                    selected = False
                    last_progress = time.time()
                    continue
            if self.appear_then_click(target_ticket_rule_image, interval=0.6):  # 选择对应鬼王门票
                selected = True
                last_progress = time.time()
                continue
            if time.time() - last_progress > self.SUMMON_STALL_TIMEOUT:
                # 召唤失败: 弹窗已关且鬼王没出来, 从挑战页面重新走一遍
                self.State.summon_fail_count += 1
                if self.State.summon_fail_count >= self.SUMMON_FAIL_LIMIT:
                    logger.error('Summon keeps failing, stop this run')
                    self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
                    self.State.done = True
                    return False
                logger.warning(
                    f'Summon stalled for {self.SUMMON_STALL_TIMEOUT:.0f}s, retry '
                    f'({self.State.summon_fail_count}/{self.SUMMON_FAIL_LIMIT})'
                )
                self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
                return self.check_and_switch_ticket(sequence=sequence)

    def check_and_switch_powerful(self) -> bool:
        """检查并切换是否开启强力"""
        logger.hr('process power fire')
        if not self.appear(self.I_MD_FIRE):
            self.goto_page(ipages.page_meta_demon_boss)
            self.screenshot()
            if not self.appear(self.I_MD_FIRE):  # 处于boss界面但是没有挑战按钮
                return False
        # 低星鬼王不会强力追击
        if self.cur_boss_type is not None and self.cur_boss_type not in HIGH_STAR_TYPES:
            self.ui_click(self.I_MD_ENABLE_POWERFUL_FIRE, self.I_MD_DISABLE_POWERFUL_FIRE, interval=0.6)
            return True
        names, legacy_types = self.conf.meta_demon_config.powerful_entries_v
        boss_name = normalize_boss_name(self.boss_name)
        name_hit = bool(
            boss_name
            and any(normalize_boss_name(name) == boss_name for name in names)
        )
        # 旧配置里的星级项继续生效, 避免已有配置失效
        type_hit = self.cur_boss_type is not None and self.cur_boss_type in legacy_types
        if not name_hit and not type_hit:
            logger.info(
                f'Boss "{self.boss_name or "unknown"}" not in powerful list, '
                f'use normal fire'
            )
            self.ui_click(self.I_MD_ENABLE_POWERFUL_FIRE, self.I_MD_DISABLE_POWERFUL_FIRE, interval=0.6)
            return True
        reason = f'name "{boss_name}"' if name_hit else f'star {self.cur_boss_type.name}'
        logger.info(f'Enable powerful fire by {reason}')
        self.ui_click(self.I_MD_DISABLE_POWERFUL_FIRE, self.I_MD_ENABLE_POWERFUL_FIRE, interval=0.6)
        return True

    def _detect_deployed_boss_type(self) -> None:
        """鬼王已召唤好（挑战按钮可见）时补星级：按鬼王名反查五星/六星名单。

        遗留鬼王不一定是高星（低星召唤后没打完也会留在场上），
        所以先按名字反查星级；名字不在任何高星名单里时按低星处理。
        名字识别为空时无法判断，沿用旧行为按六星兜底。
        """
        logger.info('Boss already deployed, resolving star by boss name')
        name_ocr = getattr(self, 'O_MD_BOSS_NAME', None)
        value = ''
        if name_ocr is not None:
            for _ in range(3):
                self.screenshot()
                value = str(name_ocr.ocr(self.device.image) or '').strip()
                if normalize_boss_name(value):
                    break
                time.sleep(0.3)

        if not normalize_boss_name(value):
            # 读不到名字就没有依据, 保持旧行为走高星流程
            self.cur_boss_type = BossType.SIX_STARS
            logger.warning(
                'Deployed boss name is empty, fall back to six star handling'
            )
            return

        for boss_type in HIGH_STAR_TYPES:
            matched = canonical_boss_name(value, boss_type)
            if matched in boss_names_for(boss_type):
                self.cur_boss_type = boss_type
                self.boss_name = matched
                logger.info(f'Deployed boss "{value}" -> {boss_type.name}')
                return

        # 不在五六星名单: 遗留鬼王按低星处理, 星级由配置的 low_star 预设决定
        self.cur_boss_type = LOW_STAR_TYPES[0]
        self.boss_name = value
        logger.warning(
            f'Deployed boss "{value}" is not in five/six star lists, '
            f'treat as low star ({self.cur_boss_type.name})'
        )

    def update_boss_name(self) -> str:
        """识别挑战浮窗上的鬼王名，并按当前星级对齐到标准写法。

        低星只有低星阵容、也不会强力追击, 不需要鬼王名。
        """
        if self.cur_boss_type is not None and self.cur_boss_type not in HIGH_STAR_TYPES:
            self.boss_name = ''
            return ''
        name_ocr = getattr(self, 'O_MD_BOSS_NAME', None)
        if name_ocr is None:
            self.boss_name = ''
            return ''
        names = boss_names_for(self.cur_boss_type)
        attempts = 3
        best = ''
        best_hit = False
        for attempt in range(1, attempts + 1):
            self.screenshot()
            raw = str(name_ocr.ocr(self.device.image) or '').strip()
            value = canonical_boss_name(raw, self.cur_boss_type)
            logger.info(f'MetaDemon boss name OCR {attempt}/{attempts}: {raw} -> {value}')
            # 一次识别到鬼王名就停止, 不再重复 OCR; 只有读空时才重试
            if value:
                best = value
                best_hit = value in names
                break
            time.sleep(0.3)
        self.boss_name = best
        if not best:
            logger.warning('MetaDemon boss name OCR is empty, fallback to star-only lineup')
        elif names and not best_hit:
            logger.warning(f'Boss name "{best}" not in known list, use it as is')
        return best

    def _quick_loadout_assets(self) -> tuple:
        """返回鬼王战一键配置所需的素材, 任一缺失则返回空元组。"""
        entry = getattr(self, 'I_MD_GOTO_QUICK_LOADOUT', None)
        fight_anchor = getattr(self, 'I_MD_QUICK_LOADOUT_FIGHT', None)
        dismiss = getattr(self, 'C_MD_QUICK_LOADOUT_CLOSE', None)
        if entry is None or fight_anchor is None or dismiss is None:
            return ()
        return entry, fight_anchor, dismiss

    def run_boss_quick_loadout(self, quick_conf, entry, fight_anchor, dismiss) -> bool:
        """上阵鬼王阵容；官方协战组（第 1 组）没有御魂可装配，直接上阵。"""
        name_ocr = getattr(self, 'O_MD_BOSS_NAME', None)
        # 先按规范化鬼王名定好预设，避免组件用 OCR 原文做包含匹配误配
        quick_conf = self._resolve_boss_preset(quick_conf)
        # 官方组点"装备御魂"会被切进队伍详情页，面板随即消失，必须跳过这一步
        if self._is_official_group(quick_conf) and name_ocr is not None:
            return self._deploy_official_group(quick_conf, entry, fight_anchor, dismiss, name_ocr)
        # 预设已按规范化名确定，关掉按关卡名二次解析，避免组件再读一次原始 OCR
        if getattr(quick_conf, 'custom_preset_enable', False):
            quick_conf = quick_conf.model_copy(update={'custom_preset_enable': False})
        return self.run_quick_loadout(
            quick_conf,
            entry=entry,
            fight_anchor=fight_anchor,
            dismiss=dismiss,
            name_ocr=None,
        )

    @staticmethod
    def _is_official_group(quick_conf) -> bool:
        """第 1 组是官方协战阵容，只按编号模式判定。"""
        return (
            getattr(quick_conf, 'mode', None) == QuickLoadoutMode.NUMBER
            and getattr(quick_conf, 'group_number', None) == 1
        )

    # 星级通配键 -> 该键覆盖的星级集合（低星:(2,1) 之类）
    _STAR_STAGE_KEYS: dict[str, tuple[BossType, ...]] = {
        '低星': LOW_STAR_TYPES,
        '5星': (BossType.FIVE_STARS,),
        '6星': (BossType.SIX_STARS,),
        '高星': HIGH_STAR_TYPES,
    }

    def _star_preset_target(self, presets: dict) -> tuple | None:
        """按星级通配键（低星/5星/6星/高星）取预设；命中返回 (group, preset)。

        一至四星没有鬼王名单，星级必须直接取 cur_boss_type，不能靠名字反查。
        """
        boss_type = self.cur_boss_type
        if boss_type is None:
            return None
        for key, types in self._STAR_STAGE_KEYS.items():
            if boss_type not in types:
                continue
            target = presets.get(key)
            if target is not None:
                return target
        return None

    def _resolve_boss_preset(self, quick_conf) -> QuickLoadoutConfig:
        """用规范化鬼王名精确选预设，绕开组件双向包含会误配短名的问题。"""
        if not getattr(quick_conf, 'custom_preset_enable', False):
            return quick_conf
        stage = normalize_boss_name(self.boss_name)
        if not stage:
            # 鬼王名读空时仍可按星级通配选预设，比直接用默认更准
            logger.warning('Boss name empty, try star wildcard preset')
            stage = ''
        try:
            presets = self._parse_custom_presets(quick_conf.custom_preset)
        except ValueError as exc:
            logger.warning(str(exc))
            return quick_conf
        # 先精确命中，再退回相似度；不做双向包含，避免短名吃掉长名
        target = presets.get(stage) if stage else None
        if target is None and stage:
            for name, value in presets.items():
                if name.upper() == 'ALL':
                    continue
                if normalize_boss_name(name) == stage:
                    target = value
                    break
        if target is None and stage:
            for name, value in presets.items():
                if name.upper() == 'ALL':
                    continue
                if self._name_similarity(stage, normalize_boss_name(name)) >= 0.9:
                    target = value
                    break
        if target is None:
            # 名单匹配失败再试星级通配（低星/5星/6星/高星），最后才是 ALL
            target = self._star_preset_target(presets)
        if target is None:
            logger.info(f'No preset for boss {stage}, use ALL')
            return quick_conf
        group, preset = target
        logger.info(f'Boss {stage} -> preset ({group}, {preset})')
        if isinstance(group, int) and isinstance(preset, int):
            return quick_conf.model_copy(
                update={
                    'mode': QuickLoadoutMode.NUMBER,
                    'group_number': group,
                    'preset_number': preset,
                }
            )
        return quick_conf.model_copy(
            update={
                'mode': QuickLoadoutMode.OCR,
                'group_name': group,
                'preset_name': preset,
            }
        )

    def _deploy_official_group(self, quick_conf, entry, fight_anchor, dismiss, name_ocr) -> bool:
        """官方协战阵容：选组选预设后直接上阵，不碰装备御魂。"""
        logger.info('Official group, skip equip souls')
        resolved = self._resolve_boss_preset(quick_conf)
        resolved.validate_target()
        logger.hr('Quick loadout (official)', 2)
        if not self._open_quick_loadout(entry, fight_anchor):
            return False
        try:
            layout = self._build_quick_loadout_layout(fight_anchor)
            if not self._select_group(layout, resolved):
                self._dismiss_quick_loadout(fight_anchor, dismiss)
                return False
            row_y = self._select_preset_row(layout, resolved)
            if row_y is None:
                self._dismiss_quick_loadout(fight_anchor, dismiss)
                return False
            return self._deploy_quick_loadout(layout, fight_anchor, dismiss, row_y)
        except Exception:
            self._dismiss_quick_loadout(fight_anchor, dismiss)
            raise

    def check_and_switch_lineup(self) -> bool:
        """按当前鬼王上阵阵容；同一套阵容只上阵一次，换鬼王才重上。"""
        if self.cur_boss_type is None:
            logger.error('cur_boss_type is None, cannot decide lineup')
            return False
        lineup_key = self.current_lineup_key
        quick_conf = self.conf.boss_quick_loadout_config
        quick_assets = self._quick_loadout_assets() if quick_conf.enable else ()
        # 一次性切换模式下, 首次进入就把所有星级御魂切好, 之后不再重复上阵
        if self.conf.switch_soul.switch_once and not quick_assets:
            return self.check_and_switch_soul()
        if lineup_key and lineup_key == self.State.lineup_key:
            logger.info(f'Lineup already deployed: {lineup_key}')
            return True

        if quick_assets:
            entry, fight_anchor, dismiss = quick_assets
            if not self.appear(self.I_MD_FIRE):
                self.goto_page(ipages.page_meta_demon_boss)
                self.screenshot()
            logger.hr(f'Deploy lineup by quick loadout ({lineup_key})', 2)
            try:
                ok = self.run_boss_quick_loadout(quick_conf, entry, fight_anchor, dismiss)
            except Exception as exc:
                # 面板布局由"出战"锚点推导, 超鬼王若与武道大会布局不同会在这里抛错
                logger.warning(f'Quick loadout raised on {lineup_key}: {type(exc).__name__}: {exc}')
                ok = False
            if not ok:
                self.State.lineup_fail_count += 1
                logger.warning(
                    f'Quick loadout failed on {lineup_key} '
                    f'({self.State.lineup_fail_count}/{self.LINEUP_FAIL_LIMIT})'
                )
                if self.State.lineup_fail_count >= self.LINEUP_FAIL_LIMIT:
                    # 连续失败说明素材或预设有问题, 收工交给调度器重试, 避免空转
                    logger.error('Quick loadout keeps failing, stop this run')
                    self.State.done = True
                return False
            self.State.lineup_fail_count = 0
            self.State.lineup_key = lineup_key
            return True

        if not self.check_and_switch_soul():
            return False
        self.State.lineup_key = lineup_key
        return True

    def check_and_switch_soul(self) -> bool:
        """切换御魂；一至四星共用一套，按御魂目标去重避免重复切换。"""
        if self.cur_boss_type is None:
            logger.error('cur_boss_type is None, cannot switch soul')
            return False
        preset_key = self.conf.switch_soul.preset_key(self.cur_boss_type)
        # switch_once 已把所有御魂切完, 任何星级都直接复用
        if self.State.soul_key in (preset_key, self.SOUL_KEY_ALL):
            return True
        logger.hr(f'Switch soul ({preset_key})')
        self.goto_page(ipages.page_shikigami_records)
        if self.conf.switch_soul.switch_once:  # 只切换一次则将配置的鬼王御魂全部切换
            done: set[str] = set()
            for boss_type in self.conf.meta_demon_config.fire_sequence_v:
                # 一至四星共用一套御魂, 去重避免同一目标重复切换
                target_key = self.conf.switch_soul.preset_key(boss_type)
                if target_key in done:
                    continue
                switch_type, (group, team) = self.conf.switch_soul.get_switch_by_enum(boss_type)
                if switch_type is None:
                    continue
                done.add(target_key)
                if switch_type == 'int':
                    self.run_switch_soul((group, team))
                if switch_type == 'str':
                    self.run_switch_soul_by_name(group, team)
            # 一次性模式已把所有御魂切好, 之后任何星级都不再进式神录
            self.State.soul_key = self.SOUL_KEY_ALL
            self.goto_page(ipages.page_meta_demon_boss)
            return True
        switch_type, (group, team) = self.conf.switch_soul.get_switch_by_enum(self.cur_boss_type)
        if switch_type is None:
            # 该星级没配置御魂, 不算失败, 直接沿用当前阵容
            logger.info(f'No switch soul config on {preset_key}')
            self.goto_page(ipages.page_meta_demon_boss)
            return True
        if switch_type == 'int':
            self.run_switch_soul((group, team))
        if switch_type == 'str':
            self.run_switch_soul_by_name(group, team)
        self.State.soul_key = preset_key
        self.goto_page(ipages.page_meta_demon_boss)
        return True

    def finish_task(self):
        self.goto_page(ipages.page_main)
        raise TaskEnd


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
