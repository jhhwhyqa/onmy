# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class StoryConfig(ConfigBase):
    """
    主线剧情：一次=从庭院进入→播完→自动回庭院；可自定义次数，跑完自动再进下一段。
    """
    run_count: int = Field(
        title='剧情次数',
        default=1,
        ge=1,
        description=(
            '一次剧情 = 庭院点击进入 → 剧情播完 → 自动回到庭院。'
            '每完成一次会自动再次进入后续剧情，直到跑满本次数'
        ),
    )
    max_rounds: int = Field(
        title='单次最大推进轮次',
        default=200,
        ge=1,
        description=(
            '单段剧情内最多识别到的「有效推进动作」(进入剧情/跳过/对话/战斗)次数上限；'
            '达到即认定该段结束，防止卡死。完整剧情对话很多，建议设大一些'
        ),
    )
    limit_time: Time = Field(
        title='运行时间限制',
        default=Time(minute=30),
        description='达到限制时间后不再开始下一段剧情，已经开始的推进会正常完成',
    )


class StoryLine(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    story_config: StoryConfig = Field(default_factory=StoryConfig)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
