import re

# from module.base.mask import Mask
# from module.ui.page import *
#
# MASK_MAIN = Mask('./assets/mask/MASK_MAIN.png')
# MASK_PLAYER = Mask('./assets/mask/MASK_PLAYER.png')


def handle_sensitive_image(image):
    """
    Args:
        image:

    Returns:
        np.ndarray:
    """
    # if PLAYER_CHECK.match(image, offset=(30, 30)):
    #     image = MASK_PLAYER.apply(image)
    # if MAIN_CHECK.match(image, offset=(30, 30)):
    #     image = MASK_MAIN.apply(image)

    return image


def handle_sensitive_text(text):
    """
    Args:
        text (str):

    Returns:
        str:
    """
    text = re.sub('File \"(.*?)OnmyojiAutoScript', 'File \"C:\\\\fakepath\\\\OnmyojiAutoScript', text)
    text = re.sub('\[Adb_binary\] (.*?)OnmyojiAutoScript', '[Adb_binary] C:\\\\fakepath\\\\OnmyojiAutoScript', text)
    return text


def handle_sensitive_logs(logs):
    return [handle_sensitive_text(line) for line in logs]
