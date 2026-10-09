# This Python file uses the following encoding: utf-8
"""僵尸寮配置：沿用道馆（`tasks/Dokan`）的全部配置项，另加 QQ 群消息门控。

- 求寮参数沿用道馆同名同义字段：`dokan_config.find_dokan_refresh_count`（刷新次数）、
  `dokan_config.min_people_num`（人数下限）、`attack_count_config`（今日次数记账）、
  `dokan_owner_*` / `dokan_member_*`（两套阵容与御魂）等
- 福利寮名单不在配置里，直接维护 `tasks/ZombieGuild/福利寮名单.txt`
"""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tasks.Dokan.config import Dokan


class QQMessageConfig(BaseModel):
    enable: bool = Field(default=False, title='启用QQ群消息检查',
                         description='用QQ群公告判断福利寮是否开启；未启用时直接按福利寮名单搜索')
    group_id: str = Field(default='', title='监听群号')
    member_id: str = Field(default='', title='监听成员QQ号', description='按QQ号筛选，不使用昵称或群名片')
    keywords: str = Field(default='', title='放行关键词',
                          description='多个关键词用换行或英文竖线分隔，包含任意一个即满足')
    excluded_keywords: str = Field(default='', title='排除关键词',
                                   description='同一条消息包含任意排除词时不放行；换行或英文竖线分隔')
    retry_minutes: int = Field(default=3, ge=1, le=1440, title='未匹配后等待分钟数')
    max_checks: int = Field(default=10, ge=1, le=1000, title='每天最大未匹配次数',
                            description='未匹配或接口失败才计次；匹配不消耗次数，重启或立即执行不清零')
    reset_today_checks: bool = Field(default=False, title='重置当天检查次数为0次',
                                     description='勾选保存后立即清零当天的未匹配次数；保存后自动恢复关闭')
    callback_secret: str = Field(default='', title='事件上报签名密钥（可选）',
                                 description='仅使用历史查询时留空；实时上报时与NapCat HTTP客户端Token一致')
    history_api_url: str = Field(default='', title='群历史消息API地址',
                                 description='NapCat HTTP服务端地址，例如 http://127.0.0.1:3000；不要填WebUI管理端口')
    history_api_token: str = Field(default='', title='历史消息API访问令牌',
                                   description='填写NapCat HTTP服务端的Token，不是WebUI登录密码')
    history_page_size: int = Field(default=100, ge=1, le=500, title='每页历史消息数量')
    history_max_pages: int = Field(default=5, ge=1, le=20, title='每次最多读取历史页数',
                                   description='分页有上限；未读到匹配消息时仍按未放行重试')

    model_config = ConfigDict(validate_assignment=True)

    @field_validator('reset_today_checks', mode='before')
    @classmethod
    def keep_reset_action_off(cls, value):
        """一次性操作只由配置保存入口执行，读取/复制配置不能重复触发。"""
        return False


class ZombieGuild(Dokan):
    """道馆的全部配置 + QQ 群消息门控。"""
    qq_message_config: QQMessageConfig = Field(default_factory=QQMessageConfig, title='QQ群消息检查')
