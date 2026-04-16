# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from tasks.Component.Login.service import LoginService


class LoginHandler(LoginService):
    """兼容旧导入路径，实际实现已迁移到共享登录 service。"""
    ...


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = LoginHandler(c, d)
    t.app_handle_login()
