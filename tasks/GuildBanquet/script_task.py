# This Python file uses the following encoding: utf-8
# @author ohspecial
# github https://github.com/ohspecial
from datetime import datetime, timedelta
import time

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_guild, page_main
from tasks.GuildBanquet.assets import GuildBanquetAssets
from tasks.GuildBanquet.config import Weekday


class ScriptTask(GameUi, GuildBanquetAssets):

    def run(self):
        if not self.check_date(datetime.now()):
            logger.warning("GuildBanquet is not available now")
            self.set_next_run(task='GuildBanquet', server=False, target=self.get_next_dt(datetime.now()))
            raise TaskEnd
        self.goto_page(page_guild)
        self.screenshot()
        if not self.appear(self.I_FLAG):
            self.set_next_run(task='GuildBanquet', server=False, target=self.get_next_dt(datetime.now()))
            self.goto_page(page_main)
            raise TaskEnd
        wait_count = 0
        wait_timer = Timer(230)
        wait_timer.start()
        logger.info("Start guild banquet!")
        self.device.stuck_record_add('BATTLE_STATUS_S')

        last_check_time = 0  # 记录上次实际检测时间
        last_log_time = 0  # 记录上次日志输出时间
        last_flag_status = False  # 记录上次真实检测结果

        while True:
            self.screenshot()
            # 条件1: 强制检测间隔管理
            current_time = time.time()
            if current_time - last_check_time >= 10:
                # 达到间隔要求时执行真实检测
                actual_status = self.appear(self.I_FLAG)
                last_flag_status = actual_status
                last_check_time = current_time
                logger.debug(f"Actual detection at {current_time}, status: {actual_status}")
                # 重置日志计时器
                last_log_time = current_time
            else:
                # 未达间隔时沿用上次结果
                logger.debug(f"Using cached status: {last_flag_status}")

            # 条件2: 状态判断逻辑
            if last_flag_status:
                if current_time - last_log_time >= 10:
                    logger.info("Banquet ongoing, waiting...")
                    last_log_time = current_time
            else:
                logger.info("Guild banquet end")
                break  # 退出循环

            # 条件3: 超时保护
            if wait_timer.reached():
                wait_timer.reset()
                if wait_count >= 3:
                    # 宴会最长15分钟
                    logger.info('Guild banquet timeout')
                    break
                wait_count += 1
                logger.info(f'Banquet ongoing, waiting... (Count: {wait_count})')
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')
        self.set_next_run(task='GuildBanquet', server=False, target=self.get_next_dt(datetime.now(), True))
        self.goto_page(page_main)
        raise TaskEnd

    def get_next_dt(self, now: datetime, success: bool = False) -> datetime:
        """获取下一次运行时间"""
        bt = self.config.model.guild_banquet.guild_banquet_time
        scheduler = self.config.model.guild_banquet.scheduler

        def get_candidate(target_day: Weekday, target_time):
            target_index = target_day.to_index()
            days_ahead = (target_index - now.weekday()) % 7
            target_date = (now + timedelta(days=days_ahead)).date()
            target_dt = datetime.combine(target_date, target_time)

            if days_ahead == 0:
                if now < target_dt:
                    return target_dt
                if success or now >= target_dt + timedelta(hours=1):
                    return target_dt + timedelta(days=7)
                if now <= target_dt + timedelta(hours=1):  # 1小时内则自动加上失败间隔
                    return now + scheduler.failure_interval

            return target_dt

        day_1_dt = get_candidate(bt.day_1, bt.run_time_1)
        day_2_dt = get_candidate(bt.day_2, bt.run_time_2)

        return min(day_1_dt, day_2_dt)

    def check_date(self, now: datetime) -> bool:
        """检查宴会今天是否可以运行"""
        bt = self.config.model.guild_banquet.guild_banquet_time
        return now.weekday() in [bt.day_1.to_index(), bt.day_2.to_index()]


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()

