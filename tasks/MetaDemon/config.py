# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import re
from datetime import timedelta, time
from difflib import SequenceMatcher

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.QuickLoadout.config import NamedQuickLoadoutConfig
from tasks.Component.config_base import ConfigBase, TimeDelta, Time, dynamic_hide
from pydantic import Field, model_validator
from enum import Enum, IntEnum
from tasks.Component.config_scheduler import Scheduler
from tasks.EvoZone.config import KirinType, Layer
from tasks.Exploration.config import ExplorationLevel


class BossType(IntEnum):
    ONE_STAR = 1
    TWO_STARS = 2
    THREE_STARS = 3
    FOUR_STARS = 4
    FIVE_STARS = 5
    SIX_STARS = 6
    MONEY = 7


# 一星到四星共用同一套阵容, 五星六星按鬼王名单独指定
LOW_STAR_TYPES: tuple[BossType, ...] = (
    BossType.ONE_STAR,
    BossType.TWO_STARS,
    BossType.THREE_STARS,
    BossType.FOUR_STARS,
)
LOW_STAR_NAMES: tuple[str, ...] = tuple(
    boss_type.name.lower() for boss_type in LOW_STAR_TYPES
)
# 需要按鬼王名单独上阵阵容的星级
HIGH_STAR_TYPES: tuple[BossType, ...] = (BossType.FIVE_STARS, BossType.SIX_STARS)


# 六星鬼王固定名单，用于把 OCR 结果对齐到标准写法
# 新增鬼王时直接往元组里加名字即可
SIX_STAR_BOSS_NAMES: tuple[str, ...] = (
    '雪御前',
    '祸津神',
    '纺愿缘结神',
    '蚀月吸血姬',
    '鬼王酒吞童子',
    '孔雀明王',
    '修罗鬼童丸',
    '市加美',
    '毗沙门天',
    '寻香行',
    '蟹姬',
)

# 五星鬼王固定名单
# 注意：五星是「酒吞童子」「鬼童丸」，六星才是「鬼王酒吞童子」「修罗鬼童丸」
FIVE_STAR_BOSS_NAMES: tuple[str, ...] = (
    '酒吞童子',
    '鬼童丸',
    '夜刀神',
    '禅心云外镜',
    '八岐大蛇',
    '妖刀姬',
    '缘结神',
    '月读',
    '鬼金羊',
    '梦山白藏主',
    '卑弥呼',
    '缘结神',
)

# 按星级索引的名单，避免五星名字被子串误配到六星
BOSS_NAMES_BY_TYPE: dict[int, tuple[str, ...]] = {
    5: FIVE_STAR_BOSS_NAMES,
    6: SIX_STAR_BOSS_NAMES,
}

# 名字规范化时认为命中名单的最低相似度
BOSS_NAME_MATCH_RATIO = 0.7


def normalize_boss_name(value: str) -> str:
    """去掉鬼王名里的空白与标点, 便于比对与拼 key。"""
    return re.sub(r'[\s·•,，.。:：_\-—]+', '', str(value or '')).strip()


def canonical_boss_name(value: str, boss_type=None) -> str:
    """把 OCR 结果对齐到名单里的标准写法；对不上就返回清洗后的原文。

    boss_type 给出时只在该星级的名单里匹配，避免五星「酒吞童子」
    被子串误配到六星「鬼王酒吞童子」。
    """
    key = normalize_boss_name(value)
    if not key:
        return ''
    names = _names_for(boss_type)
    if not names:
        return key
    # 完全一致直接命中
    if key in names:
        return key
    # 包含关系：仅当只有唯一候选时才采用，避免多义
    hits = [name for name in names if key in name or name in key]
    if len(hits) == 1:
        return hits[0]
    # 兜底按相似度
    best, best_score = '', 0.0
    for name in names:
        score = SequenceMatcher(None, key, name).ratio()
        if score > best_score:
            best, best_score = name, score
    if best_score >= BOSS_NAME_MATCH_RATIO:
        return best
    return key


def _names_for(boss_type) -> tuple[str, ...]:
    """按星级取名单；未指定星级时合并全部。"""
    if boss_type is None:
        merged: list[str] = []
        for names in BOSS_NAMES_BY_TYPE.values():
            merged.extend(names)
        return tuple(merged)
    raw = getattr(boss_type, 'value', boss_type)
    try:
        return BOSS_NAMES_BY_TYPE.get(int(raw), ())
    except (TypeError, ValueError):
        return ()


def boss_names_for(boss_type) -> tuple[str, ...]:
    """该星级已知的鬼王名清单。"""
    return _names_for(boss_type)


class MetaDemonConfig(ConfigBase):
    limit_time: Time = Field(default=Time(minute=45), description='limit_time_help')
    limit_count: int = Field(default=50, description='limit_count_help')
    auto_tea: bool = Field(
        default=False,
        description='疲劳度满时是否自动喝茶, 关闭则自动根据调度器等待间隔时间安排下一次调度',
    )
    fire_sequence: str = Field(
        default='1 2 3 4',
        description='攻击顺序:从左到右,空格分隔(1:一星鬼王,2:二星鬼王...)\n例:3 2(先攻击三星鬼王然后二星鬼王)',
    )
    powerful_list: str = Field(
        default='',
        description='开启强力追击的鬼王名列表(空格/逗号分隔),例:修罗鬼童丸 蟹姬\n'
                    '按鬼王名匹配; 兼容旧配置, 单个数字仍按星级处理',
    )
    synthesis_list: str = Field(
        default='1',
        description='鬼王合成列表(空格分隔),支持1-5星合成,例:1 2 3(合成一星,二星,三星鬼王)',
    )
    buy_daily_boss: bool = Field(
        default=False,
        description='在挑战页购买每日鬼王',
    )

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(
                hours=self.limit_time.hour,
                minutes=self.limit_time.minute,
                seconds=self.limit_time.second,
            )
        return self.limit_time

    @property
    def fire_sequence_v(self) -> list[BossType]:
        sequence_text = self.fire_sequence.strip()
        if sequence_text == '':
            return []
        fire_num_list = sequence_text.split(' ')
        fire_boss_type_list = [BossType(int(num_text)) for num_text in fire_num_list]
        return fire_boss_type_list

    @property
    def powerful_entries_v(self) -> tuple[list[str], list[BossType]]:
        """解析强力追击配置, 返回 (鬼王名列表, 兼容旧配置的星级列表)。

        鬼王名按空格/逗号分隔; 纯数字项沿用旧语义按星级处理, 保证老配置不失效。
        """
        text = self.powerful_list.replace('，', ' ').replace(',', ' ')
        names: list[str] = []
        boss_types: list[BossType] = []
        for token in text.split():
            if token.isdigit():
                try:
                    boss_types.append(BossType(int(token)))
                except ValueError:
                    continue
                continue
            names.append(token)
        return names, boss_types

    @property
    def powerful_list_v(self) -> list[BossType]:
        """兼容旧接口: 只返回配置里的星级项。"""
        return self.powerful_entries_v[1]

    @property
    def synthesis_list_v(self) -> list[BossType]:
        synthesis_list_text = self.synthesis_list.strip()
        if synthesis_list_text == '':
            return []
        synthesis_num_list = synthesis_list_text.split(' ')
        synthesis_boss_type_list = [
            BossType(int(num_text)) for num_text in synthesis_num_list
        ]
        return synthesis_boss_type_list


class TicketFarmMode(str, Enum):
    EXPLORATION = 'exploration'  # 探索 + 突破循环
    EVO_ZONE = 'evo_zone'  # 觉醒副本, 一次性刷完


# 超鬼王门票每天固定上限 50 张, 不给用户改
TICKET_DAILY_LIMIT = 50


class MetaDemonTicketFarmConfig(ConfigBase):
    """刷门票专用配置：是否刷、只刷不打、用什么方式刷。"""

    ticket_farm_enable: bool = Field(
        default=False, description='是否在打鬼王前自动刷门票, 刷满后自动开始正式活动'
    )
    ticket_only: bool = Field(
        default=False, description='只刷门票不打鬼王, 刷完就结束本次运行'
    )
    ticket_farm_mode: TicketFarmMode = Field(
        default=TicketFarmMode.EXPLORATION,
        description='刷票方式，其他配置去相应任务设置',
    )
    # 觉醒副本刷票参数
    layer: Layer = Field(default=Layer.TEN, description='layer_help')
    kirin_type: KirinType = Field(
        default=KirinType.LIGHTNINGKIRIN, description='kirin_type_help'
    )
    # 探索刷票参数
    exploration_level: ExplorationLevel = Field(
        default=ExplorationLevel.EXPLORATION_28, description='exploration_level_help'
    )
    exploration_skip_realm_raid: bool = Field(
        default=False,
        description='探索模式只打探索不打结界突破, 突破券攒再多也不去',
    )
    realm_raid_threshold: int = Field(
        default=25, ge=1, le=30, description='突破券攒到该数量就去打一轮个人突破'
    )


class InviteAssistMode(str, Enum):
    """大小号协作模式：invite=大号召唤小号打, assist=小号拉大号打。"""

    INVITE = 'invite'  # 邀请模式：大号召唤并邀请小号
    ASSIST = 'assist'  # 协助模式：小号分享, 大号只打单拉目标


class MetaDemonInviteConfig(ConfigBase):
    """大小号邀请配置：邀请模式（大号拉小号打）与协助模式（小号拉大号打）。"""

    # 字段名避开全局词典的 enable/mode（它们的词条是调度器/通用语义，会盖掉任务级词条）
    invite_enable: bool = Field(
        default=False,
        description='启用后按下面的协作模式配合打鬼王；关闭则走普通单人流程',
    )
    coop_mode: InviteAssistMode = Field(
        default=InviteAssistMode.INVITE,
        description='invite=邀请模式(大号召唤集结邀请好友来打, 自己不挑战)\nassist=协助模式(小号单拉分享, 大号只打分享出来的五六星鬼王)',
    )
    # 邀请模式参数
    stars: str = Field(
        default='6 5',
        description='邀请的星级, 空格分隔按顺序优先, 例: "6 5"=先六星打完再五星',
    )
    friend_name: str = Field(default='', description='要邀请的好友昵称, 仅单个好友')
    name_match_ratio: int = Field(
        default=60,
        ge=40,
        le=100,
        description='好友名匹配相似度阈值(百分比), OCR 掉字时可适当调低',
    )
    wait_timeout: int = Field(
        default=10,
        ge=1,
        le=30,
        description='邀请后等待好友打完的超时(分钟), 超时则放弃该鬼王继续召唤',
    )
    poll_interval: int = Field(
        default=10,
        ge=3,
        le=60,
        description='等待结算时的轮询间隔(秒)',
    )
    # 协助模式参数
    assist_wait_minutes: int = Field(
        default=10, ge=1, le=60, description='assist_wait_minutes_help'
    )

    @property
    def invite_only(self) -> bool:
        """兼容旧调用：邀请模式生效中。"""
        return self.invite_enable and self.coop_mode == InviteAssistMode.INVITE

    @property
    def assist_only(self) -> bool:
        """兼容旧调用：协助模式生效中。"""
        return self.invite_enable and self.coop_mode == InviteAssistMode.ASSIST

    @property
    def stars_v(self) -> list[BossType]:
        """解析星级串成 BossType 列表, 按书写顺序即优先级。"""
        result: list[BossType] = []
        for text in self.stars.replace('，', ' ').replace(',', ' ').split():
            try:
                boss_type = BossType(int(text))
            except (ValueError, TypeError):
                continue
            if boss_type in HIGH_STAR_TYPES and boss_type not in result:
                result.append(boss_type)
        return result

    @property
    def name_match_ratio_v(self) -> float:
        return self.name_match_ratio / 100.0


class MetaDemonSwitchSoulConfig(ConfigBase):
    enable: bool = Field(
        default=False,
        description='是否启用自动切换御魂,清空则不会切换对应御魂\n若是数字,则以编号方式切换御魂(组号,队伍号),组1-7,队伍1-4\n若非数字,则以ocr方式切换御魂(组名,队伍名)',
    )
    switch_once: bool = Field(
        default=False,
        description='启用该项会一次性切换所有需要攻击的鬼王御魂(建议全部独立御魂再启用), 否则当鬼王级别变更时会自动切换对应级别御魂',
    )
    # 一星到四星鬼王共用这一套阵容
    low_star: str = Field(default='', description='一至四星鬼王共用御魂配置')
    enable_low_star_preset: bool = Field(
        default=False,
        description='是否战斗内切换一至四星鬼王预设,仅限数字切换御魂可用,否则无效',
    )
    five_stars: str = Field(default='', description='五星鬼王切换御魂配置')
    enable_five_stars_preset: bool = Field(
        default=False, description='是否战斗内切换五星鬼王预设'
    )
    six_stars: str = Field(default='', description='六星鬼王切换御魂配置')
    enable_six_stars_preset: bool = Field(
        default=False, description='是否战斗内切换六星鬼王预设'
    )
    # money: str = Field(default='', description='氪金鬼王切换御魂配置')
    # enable_money_preset: bool = Field(default=False, description='是否切换氪金鬼王预设')

    @model_validator(mode='before')
    @classmethod
    def migrate_low_star(cls, value):
        """把旧版分开配置的一至四星御魂合并到 low_star, 保留用户已填内容。"""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        # 旧配置里一至四星可能是分开填的, 按星级顺序取第一个非空值
        if not str(data.get('low_star', '') or '').strip():
            for legacy_key in LOW_STAR_NAMES:
                legacy_value = str(data.get(legacy_key, '') or '').strip()
                if legacy_value:
                    data['low_star'] = legacy_value
                    break
        # 旧版任一一至四星预设开关打开过, 就视作打开共用预设开关
        if any(
            bool(data.get(f'enable_{name}_preset', False)) for name in LOW_STAR_NAMES
        ):
            data['enable_low_star_preset'] = True
        for legacy_key in LOW_STAR_NAMES:
            data.pop(legacy_key, None)
            data.pop(f'enable_{legacy_key}_preset', None)
        return data

    @staticmethod
    def preset_key(boss_type: BossType) -> str:
        """返回该星级在配置里使用的字段名前缀, 一至四星统一为 low_star。"""
        if boss_type in LOW_STAR_TYPES:
            return 'low_star'
        return boss_type.name.lower()

    def get_switch_by_enum(
        self, boss_type: BossType
    ) -> tuple[str, tuple[str | int, str | int]]:
        """根据枚举获取对应的 切换类型, (group,team)"""
        return self.get_switch_by_name(self.preset_key(boss_type))

    def get_switch_by_name(
        self, switch_name: str
    ) -> tuple[str, tuple[str | int, str | int]]:
        """根据名称获取对应的御魂预设"""
        group_team = getattr(self, switch_name, None)
        if (
            group_team is None
            or group_team.strip() == ''
            or ',' not in group_team
            or len(group_team.split(',')) != 2
        ):
            return None, (None, None)
        group, team = group_team.split(',')
        if group.isdigit() and team.isdigit():
            return 'int', (int(group), int(team))
        return 'str', (group, team)

    def get_general_battle_conf(self, boss_type: BossType) -> GeneralBattleConfig:
        """获取通用战斗配置"""
        if boss_type is None:
            return GeneralBattleConfig()
        enable_preset = getattr(
            self, f'enable_{self.preset_key(boss_type)}_preset', False
        )
        if not enable_preset:
            return GeneralBattleConfig()
        switch_type, (group, team) = self.get_switch_by_enum(boss_type)
        if switch_type is None or switch_type == 'str':
            return GeneralBattleConfig()
        if switch_type == 'int':
            return GeneralBattleConfig(
                lock_team_enable=False,
                preset_enable=True,
                preset_group=group,
                preset_team=team,
            )
        return GeneralBattleConfig()


class MetaDemonScheduler(Scheduler):
    wait_interval: TimeDelta = Field(
        default=TimeDelta(hours=1, minutes=40),
        description='疲劳度满时等多长时间后再次运行本任务,建议设置等待完全恢复疲劳度所需的时间\n例:100分钟恢复100点疲劳度,再次运行必定可以继续战斗',
    )

    hide_fields = dynamic_hide('server_update', 'delay_date')


class MetaDemon(ConfigBase):
    scheduler: MetaDemonScheduler = Field(default_factory=MetaDemonScheduler)
    meta_demon_config: MetaDemonConfig = Field(default_factory=MetaDemonConfig)
    # 刷门票配置(独立 tab, 位置在超鬼王配置之后)
    meta_demon_ticket_farm: MetaDemonTicketFarmConfig = Field(
        default_factory=MetaDemonTicketFarmConfig
    )
    # 大小号邀请配置(独立 tab, 位置在刷票配置与切换御魂之间)
    meta_demon_invite: MetaDemonInviteConfig = Field(
        default_factory=MetaDemonInviteConfig
    )
    switch_soul: MetaDemonSwitchSoulConfig = Field(
        default_factory=MetaDemonSwitchSoulConfig
    )
    # 五星六星鬼王按鬼王名选择不同的一键配置预设
    boss_quick_loadout_config: NamedQuickLoadoutConfig = Field(
        default_factory=NamedQuickLoadoutConfig
    )
