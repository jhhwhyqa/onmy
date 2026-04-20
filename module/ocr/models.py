from module.ocr.rpc import get_ocr_client
from module.server.setting import State


def get_ocr_model(lang: str = "ch"):
    _ = lang
    address = State.deploy_config.OcrClientAddress or "127.0.0.1:22268"
    return get_ocr_client(address=address)
