# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime, timedelta

from pathlib import Path
from module.exception import TaskEnd

from tasks.SixRealms.config import SixRealmsType
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.SixRealms.moon_sea.moon_sea import MoonSea
from module.logger import logger
from tasks.SixRealms.peacock_kingdom.peacock_kingdom import PeacockKingdom


class ScriptTask(SwitchSoul, MoonSea, PeacockKingdom):

    def run(self):
        _config = self.config.model.six_realms
        if _config.switch_soul_config.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(_config.switch_soul_config.switch_group_team)
        if _config.switch_soul_config.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(_config.switch_soul_config.group_name, _config.switch_soul_config.team_name)
        cnt = 0
        while True:
            if cnt >= _config.six_realms_gate.limit_count:
                logger.info('Run out of count, exit')
                break
            if datetime.now() - self.start_time >= _config.six_realms_gate.limit_time_v:
                logger.info('Run out of time, exit')
                break
            start_time = datetime.now()
            match _config.six_realms_gate.six_realms_type:
                case SixRealmsType.MOON_SEA:
                    self.run_moon_sea()
                case SixRealmsType.PEACOCK_KINGDOM:
                    self.run_peacock_kingdom()
                case _:
                    logger.warning('Unknown six realms type')
                    self.run_moon_sea()
            cnt += 1
            logger.info(f'Battle count: {cnt}')
            elapsed = datetime.now() - start_time
            logger.info(f'Battle time: {elapsed.seconds//60}m{elapsed.seconds%60}s')
        self.goto_page(page_main)
        self.set_next_run('SixRealms', success=True, finish=True)
        raise TaskEnd

if __name__ == '__main__':
    path = Path(r'D:\dev\OnmyojiAutoScript\tasks\SixRealms\moon_sea\ms')

    for file in path.iterdir():
        # 只处理文件，并且文件名以 gate1_ 开头
        if file.is_file() and file.name.startswith('gate1_'):
            new_name = 'ms_' + file.name[len('gate1_'):]
            new_path = file.with_name(new_name)

            print(f'{file.name} -> {new_name}')
            file.rename(new_path)

