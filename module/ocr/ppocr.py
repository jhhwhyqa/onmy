import numpy as np
from paddleocr import PaddleOCR

from module.ocr.common import BoxedResult, OcrLogger


class TextSystem:
    """
    PaddleOCR with ONNX Runtime inference engine.
    Compatible interface with the original ppocronnx-based TextSystem.

    The `text_recognizer` attribute can be monkey-patched (by rpc._detect_and_ocr_vertical)
    to support vertical text recognition. When set to a custom callable, it receives
    a list of cropped image arrays and returns list of (text, score) tuples.
    """
    def __init__(
            self,
            use_angle_cls=False,
            box_thresh=0.8,
            unclip_ratio=1.6,
            rec_model_path=None,
            det_model_path=None,
            ort_providers=None,
            model_size='medium',
    ):
        # Map legacy parameter names to paddleocr 3.x parameters
        self._box_thresh = box_thresh
        self._unclip_ratio = unclip_ratio
        self._use_angle_cls = use_angle_cls
        if model_size not in ('medium', 'small'):
            raise ValueError(f'Unsupported OCR model size: {model_size}')
        model_prefix = f'PP-OCRv6_{model_size}'
        self._ocr = PaddleOCR(
            text_detection_model_name=f'{model_prefix}_det' if det_model_path is None else None,
            text_detection_model_dir=det_model_path,
            text_recognition_model_name=f'{model_prefix}_rec' if rec_model_path is None else None,
            text_recognition_model_dir=rec_model_path,
            engine='onnxruntime',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=use_angle_cls,
        )

        # text_recognizer can be monkey-patched for vertical text support.
        # If None, the built-in OCR pipeline is used by detect_and_ocr.
        # When set to a callable(img_crop_list) -> list[(text, score)], it
        # replaces only the recognition step after detection.
        self.text_recognizer = None

    def recognize_batch(self, images):
        """Compatibility recognizer used by vertical-text RPC handling."""
        return [self.ocr_single_line(image) for image in images]

    def ocr_single_line(self, img):
        """Recognize a single line of text from a cropped image.
        若检测到多个文字块，按从左到右顺序拼接。
        """
        result = list(self._ocr.predict(img, use_textline_orientation=self._use_angle_cls))
        if not result or not result[0].get('rec_texts'):
            OcrLogger.save(img, "ocr_single_line", "", 0.0, extra="no_text_detected")
            return "", 0.0
        page = result[0]
        texts = page.get('rec_texts', []) or []
        scores = page.get('rec_scores', []) or []
        polys = page.get('rec_polys', []) or page.get('dt_polys', []) or []

        if texts:
            # 按 x 坐标排序（从左到右）
            if polys:
                combined = sorted(zip(texts, scores, polys), key=lambda x: x[2][0][0])
                texts_sorted = [t for t, _, _ in combined]
                scores_sorted = [s for _, s, _ in combined]
            else:
                texts_sorted = texts
                scores_sorted = scores

            full_text = "".join(texts_sorted)
            avg_score = sum(scores_sorted) / len(scores_sorted)
            OcrLogger.save(img, "ocr_single_line", full_text, avg_score)
            return full_text, avg_score

        OcrLogger.save(img, "ocr_single_line", "", 0.0, extra="no_text_detected")
        return "", 0.0

    def detect_and_ocr(self, img: np.ndarray, drop_score=0.5, unclip_ratio=None, box_thresh=None):
        """Detect text regions and recognize text."""
        kwargs = {}
        if box_thresh is not None:
            kwargs['text_det_box_thresh'] = box_thresh
        elif self._box_thresh is not None:
            kwargs['text_det_box_thresh'] = self._box_thresh
        if unclip_ratio is not None:
            kwargs['text_det_unclip_ratio'] = unclip_ratio
        elif self._unclip_ratio is not None:
            kwargs['text_det_unclip_ratio'] = self._unclip_ratio
        kwargs['text_rec_score_thresh'] = drop_score

        # If text_recognizer is monkey-patched, use custom recognition pipeline
        if self.text_recognizer is not None:
            results = self._detect_and_ocr_custom_rec(
                img, drop_score, unclip_ratio, box_thresh
            )
            self._log_detect_results(img, results)
            return results

        result = list(self._ocr.predict(
            img,
            use_textline_orientation=self._use_angle_cls,
            **kwargs,
        ))
        if not result:
            OcrLogger.save(img, "detect_and_ocr", "", 0.0, extra="no_result")
            return []
        page = result[0]
        items = self._build_results(page, drop_score)
        self._log_detect_results(img, items)
        return items

    def _log_detect_results(self, img: np.ndarray, items: list) -> None:
        """记录 detect_and_ocr 的全部识别结果。"""
        if not items:
            OcrLogger.save(img, "detect_and_ocr", "", 0.0)
            return
        pairs = [(r.ocr_text, r.score) for r in items]
        # 只存第一张图 + 展开所有 text/score 对
        OcrLogger.save(img, "detect_and_ocr", items[0].ocr_text, items[0].score, pairs=pairs)

    def _detect_and_ocr_custom_rec(self, img, drop_score, unclip_ratio, box_thresh):
        """Run detection with OCR pipeline, then use custom recognizer."""
        # First run detection to get boxes
        kwargs = {}
        if box_thresh is not None:
            kwargs['text_det_box_thresh'] = box_thresh
        elif self._box_thresh is not None:
            kwargs['text_det_box_thresh'] = self._box_thresh
        if unclip_ratio is not None:
            kwargs['text_det_unclip_ratio'] = unclip_ratio
        elif self._unclip_ratio is not None:
            kwargs['text_det_unclip_ratio'] = self._unclip_ratio

        result = list(self._ocr.predict(
            img,
            use_textline_orientation=self._use_angle_cls,
            **kwargs,
        ))
        if not result:
            OcrLogger.save(img, "detect_and_ocr(custom)", "", 0.0, extra="no_result")
            return []
        page = result[0]

        dt_polys = page.get('dt_polys', []) or []
        if not dt_polys:
            OcrLogger.save(img, "detect_and_ocr(custom)", "", 0.0, extra="no_polys")
            return []

        # Crop each detected region from the original image
        img_crop_list = []
        for poly in dt_polys:
            poly = np.array(poly, dtype=np.int32)
            x_min = max(0, int(poly[:, 0].min()))
            y_min = max(0, int(poly[:, 1].min()))
            x_max = min(img.shape[1], int(poly[:, 0].max()))
            y_max = min(img.shape[0], int(poly[:, 1].max()))
            crop = img[y_min:y_max, x_min:x_max]
            if crop.size > 0:
                img_crop_list.append(crop)

        # Use the monkey-patched recognizer
        rec_results = self.text_recognizer(img_crop_list)

        items = []
        for i, poly in enumerate(dt_polys):
            if i < len(rec_results):
                text, score = rec_results[i]
                score = float(score)
                if score >= drop_score:
                    box = np.array(poly, dtype=np.float32)
                    items.append(BoxedResult(box, None, text, score))
        self._log_detect_results(img, items)
        return items

    @staticmethod
    def _build_results(page: dict, drop_score: float) -> list:
        """Build BoxedResult list from a page dict returned by paddleocr predict."""
        items = []
        rec_texts = page.get('rec_texts', []) or []
        rec_scores = page.get('rec_scores', []) or []
        rec_polys = page.get('rec_polys', []) or []
        dt_polys = page.get('dt_polys', []) or []

        # Use rec_polys if available (aligned with rec_texts), otherwise dt_polys
        polys = rec_polys if rec_polys else dt_polys

        for i, text in enumerate(rec_texts):
            score = float(rec_scores[i]) if i < len(rec_scores) else 0.0
            if score >= drop_score:
                if i < len(polys):
                    box = np.array(polys[i], dtype=np.float32)
                else:
                    box = np.zeros((4, 2), dtype=np.float32)
                items.append(BoxedResult(box, None, text, score))
        return items


def sorted_boxes(dt_boxes):
    """
    Sort text boxes in order from top to bottom, left to right
    args:
        dt_boxes(array):detected text boxes with shape [4, 2]
    return:
        sorted boxes(array) with shape [4, 2]
    """
    num_boxes = dt_boxes.shape[0]
    sorted_boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))
    _boxes = list(sorted_boxes)

    for i in range(num_boxes - 1):
        for j in range(i, -1, -1):
            if abs(_boxes[j + 1][0][1] - _boxes[j][0][1]) < 10 and \
                    (_boxes[j + 1][0][0] < _boxes[j][0][0]):
                tmp = _boxes[j]
                _boxes[j] = _boxes[j + 1]
                _boxes[j + 1] = tmp
            else:
                break
    return _boxes
