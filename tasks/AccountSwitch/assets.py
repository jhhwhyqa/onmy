from module.atom.image import RuleImage
from module.atom.click import RuleClick
from module.atom.long_click import RuleLongClick
from module.atom.swipe import RuleSwipe
from module.atom.ocr import RuleOcr
from module.atom.list import RuleList


# 账号切换任务不依赖任何图片/OCR 资源，仅复用 SwitchAccount 组件完成切号。
class AccountSwitchAssets:
    pass
