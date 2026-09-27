"""协同对弈每周任务配置。"""

from enum import Enum

from pydantic import Field

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class DraftMatchMode(str, Enum):
    SOLO = '单人'
    TEAM = '组队'


class DraftDuelConfig(ConfigBase):
    match_mode: DraftMatchMode = Field(
        title='匹配模式', default=DraftMatchMode.SOLO,
        description='单人直接匹配队友；组队等待大厅内已有队友后开战。',
    )
    start_timeout_seconds: int = Field(
        title='进入选人时间（秒）', default=120, ge=30, le=300,
        description='点击“战”后等待第一轮选人出现的最长时间。',
    )
    teammate_timeout_seconds: int = Field(
        title='等待队友时间（秒）', default=180, ge=30, le=600,
        description='组队模式下等待大厅队友加入的最长时间。',
    )
    pick_timeout_seconds: int = Field(
        title='等待下一轮选人时间（秒）', default=60, ge=20, le=180,
        description='等待对方选择和下一轮出现的最长时间。',
    )
    battle_timeout_seconds: int = Field(
        title='等待整局结束时间（秒）', default=3600, ge=120, le=7200,
        description='五轮选人后继续本局各场战斗，直到最终结算。',
    )


class DraftDuel(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    draft_duel_config: DraftDuelConfig = Field(default_factory=DraftDuelConfig)
