# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum
from datetime import datetime, time
from pydantic import BaseModel, ValidationError, validator, Field

from tasks.Component.config_base import Time, MultiLine


class FindMode(str, Enum):
    AUTO_FIND = 'auto_find'
    RECENT_FRIEND = 'recent_friend'


class InviteConfig(BaseModel):
    friend_list: MultiLine = Field(default='', description='invite_friend_list_help')
    find_mode: FindMode = Field(default=FindMode.AUTO_FIND, description='find_mode_help')
    wait_time: Time = Field(default=Time(minute=2), description='wait_time_help')
    default_invite: bool = Field(default=True, description='default_invite_help')

    @property
    def friend_list_v(self) -> list[str]:
        return [line.strip() for line in self.friend_list.split('\n') if line.strip()]


if __name__ == "__main__":
    i = InviteConfig()
    print(isinstance(i.wait_time, time))
    i.wait_time = "00:05:00"
    print(i.wait_time)
    print(isinstance(i.wait_time, time))

