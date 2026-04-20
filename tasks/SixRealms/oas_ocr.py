from module.base.utils import load_image
from module.image.operators import highlight_similar_color
from module.ocr.base_ocr import BaseCor


class VerticalText(BaseCor):
    def detect_and_ocr(self, image, logDisplay: bool = True, **kwargs):
        params = {"drop_score": 0.1, "box_thresh": 0.2, "vertical": True}
        params.update(kwargs)
        return super().detect_and_ocr(image, logDisplay=logDisplay, **params)


class StoneOcr(VerticalText):
    def pre_process(self, image):
        return highlight_similar_color(image, color=(234, 213, 181))


if __name__ == '__main__':
    from tasks.SixRealms.assets import SixRealmsAssets
    file = r'C:\Users\Ryland\Desktop\Desktop\20.png'
    image = load_image(file)
    ocr = StoneOcr(roi=(0,0,1280,720), area=(0,0,1280,720), mode="Full", method="Default", keyword="", name="ocr_map")
    results = ocr.detect_and_ocr(image)
    for r in results:
        print(r.box, r.ocr_text)
