# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property
from pydantic import BaseModel, ValidationError, validator, Field

from module.config.utils import *


class ConfigMenu:
    # 手动的代码配置菜单
    def __init__(self) -> None:
        self.menu = {}
        # 总览
        self.menu["Overview"] = []
        self.menu['TaskList'] = []
        # 脚本设置
        self.menu['Script'] = ['Script', 'GlobalGame', 'Restart']
        # 刷御魂
        self.menu["Soul Zones"] = ['Orochi', 'Sougenbi', 'FallenSun', 'EternitySea', 'SixRealms', 'OtherWorldTwilight']
        # 日常的任务
        self.menu["Daily Task"] = ['DailyTrifles', 'AreaBoss', 'GoldYoukai', 'ExperienceYoukai', 'Nian',
                                   'TalismanPass', 'DemonEncounter', 'Pets', 'SoulsTidy', 'Delegation', 'WantedQuests',
                                   'Tako', 'AutoCheckinBigGod']
        # 其他副本
        self.menu["Other Dungeons"] = [
            "BondlingFairyland",
            "EvoZone",
            "GoryouRealm",
            "Exploration",
            "HeroTest",
            "FindJade",
            "MemoryScrolls",
            "AssistBattle",
            "AccountSwitch"
        ]
        # 寮任务
        self.menu["Guild Tasks"] = ['KekkaiUtilize', 'KekkaiActivation', 'RealmRaid', 'RyouToppa', 'Dokan', 'ZombieGuild',
                                    'CollectiveMissions',
                                    'Hunt' , 'AbyssShadows', 'GuildBanquet', 'DemonRetreat']
        # 每周任务
        self.menu["Weekly Task"] = ['TrueOrochi', 'RichMan', 'Secret', 'WeeklyTrifles', 'MysteryShop', 'Duel', 'Chess']
        # 活动的任务
        self.menu["Activity Task"] = ['ActivityShikigami', 'VersionActivity', 'LBS', 'MetaDemon', 'FrogBoss', 'FloatParade', 'DyeTrials', 'Quiz', 'GuguArtStudio', 'FrogChallenge', 'DemonDrill', 'IbukiArena']
        # 开发工具
        self.menu["Tools"] = ['Image Rule', 'Ocr Rule', 'Click Rule', 'Long Click Rule', 'Swipe Rule', 'List Rule']

    @cached_property
    def gui_menu_list(self) -> dict:
        del self.menu['TaskList']
        del self.menu['Tools']
        return self.menu


if __name__ == "__main__":
    try:
        m = ConfigMenu()
        print(m.gui_menu_list)
    except:
        print('weih')