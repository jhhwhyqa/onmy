# This Python file uses the following encoding: utf-8
# copy from alas https://github.com/LmeSzinc/AzurLaneAutoScript
from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import *


class ProcessManager(DeployConfig):
    @cached_property
    def process_folder(self):
        return [
            self.filepath("PythonExecutable"),
            self.root_filepath
        ]

    @cached_property
    def self_pid(self):
        return os.getpid()

    def iter_process_by_name(self, name):
        """
        Args:
            name (str): process name, such as 'alas.exe'

        Yields:
            str, str, str: executable_path, process_name, process_id
        """
        try:
            from win32com.client import GetObject
        except ModuleNotFoundError:
            logger.info('pywin32 not installed, skip')
            return False

        try:
            wmi = GetObject('winmgmts:')
            processes = list(wmi.InstancesOf('Win32_Process'))

            # 自身和祖先进程都不能杀。启动器(oas.exe)通常就是本进程的控制台宿主,
            # 强杀它会连带关掉整个控制台, 更新进程会以退出码 1 中途结束。
            parent_of = {}
            for p in processes:
                parent_of[p.Properties_["ProcessID"].Value] = p.Properties_["ParentProcessID"].Value
            protected = {self.self_pid}
            pid = self.self_pid
            while parent_of.get(pid):
                pid = parent_of[pid]
                if pid in protected:
                    break
                protected.add(pid)

            for p in processes:
                executable_path = p.Properties_["ExecutablePath"].Value
                process_name = p.Properties_("Name").Value
                process_id = p.Properties_["ProcessID"].Value

                if executable_path is not None and process_name == name and process_id not in protected:
                    executable_path = executable_path.replace(r'\\', '/').replace('\\', '/')
                    for folder in self.process_folder:
                        if folder in executable_path:
                            yield executable_path, process_name, process_id
        except Exception as e:
            # Possible exception
            # pywintypes.com_error: (-2147217392, 'OLE error 0x80041010', None, None)
            logger.info(str(e))
            return False

    def kill_by_name(self, name):
        """
        Args:
            name (str): Process name
        """
        logger.hr(f'Kill {name}', 1)
        for row in self.iter_process_by_name(name):
            logger.info(' '.join(map(str, row)))
            self.execute(f'taskkill /f /pid {row[2]}', allow_failure=True, output=False)

    def process_kill(self):
        logger.hr(f'Kill existing OAS', 0)
        self.kill_by_name('oas.exe')
        self.kill_by_name('python.exe')
        self.kill_by_name('pythonw.exe')


if __name__ == '__main__':
    ProcessManager().kill_by_name('pythonw')
