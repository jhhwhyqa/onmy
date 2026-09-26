import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from module.logger import logger


class OcrLogger:
    """Optional OCR image/text logger used by every OCR backend."""

    LOG_DIR = Path("./log/ocr")
    IMG_DIR = LOG_DIR / "images"
    TXT_DIR = LOG_DIR / "text"
    _state = threading.local()

    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        cls._state.enabled = bool(enabled)

    @classmethod
    def is_enabled(cls) -> bool:
        return bool(getattr(cls._state, "enabled", False))

    @classmethod
    def save(
        cls,
        image: np.ndarray,
        method: str,
        text: str,
        score: float,
        extra: str = "",
        *,
        pairs: list[tuple[str, float]] | None = None,
    ) -> None:
        if not cls.is_enabled():
            return

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S%f")[:9]
        image_dir = cls.IMG_DIR / date_str
        image_dir.mkdir(parents=True, exist_ok=True)
        cls.TXT_DIR.mkdir(parents=True, exist_ok=True)

        sequence = getattr(cls._state, "sequence", 0)
        cls._state.sequence = sequence + 1
        filename = f"{timestamp}_{sequence:04d}.png"
        relative_image = cls.IMG_DIR / date_str / filename
        try:
            cv2.imwrite(str(image_dir / filename), image)
        except Exception as exc:
            logger.warning(f"OCR image save failed: {exc}")

        fields = [
            now.strftime("%Y-%m-%d %H:%M:%S.%f")[:23],
            str(relative_image),
            method,
        ]
        if pairs:
            for item_text, item_score in pairs:
                fields.extend((str(item_text), f"{item_score:.6f}"))
        else:
            fields.extend((str(text), f"{score:.6f}"))
        if extra:
            fields.append(extra)

        try:
            with open(cls.TXT_DIR / f"{date_str}.txt", "a", encoding="utf-8-sig") as stream:
                stream.write(" | ".join(fields) + "\n")
        except Exception as exc:
            logger.warning(f"OCR log write failed: {exc}")


class BoxedResult:
    __slots__ = ("box", "text_img", "ocr_text", "score")

    def __init__(
        self,
        box: np.ndarray,
        text_img: Optional[np.ndarray],
        ocr_text: str,
        score: float,
    ) -> None:
        self.box = box
        self.text_img = text_img
        self.ocr_text = ocr_text
        self.score = score

    def __repr__(self) -> str:
        return f"BoxedResult[{self.ocr_text}, {self.score}]"

    __str__ = __repr__
