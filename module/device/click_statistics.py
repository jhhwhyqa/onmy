from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


class ClickStatistics:
    """
    记录一次任务运行期间的点击事件。

    设计：
    - start_session()：开始一次任务统计
    - record()：Control.click() 成功后记录
    - end_session()：任务结束后保存 JSON
    - 每次任务独立一个 JSON 文件
    - 不使用数据库，不上传任何数据
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # 当前 Session
        self._session_active = False
        self._task_name = ""
        self._session_id = ""
        self._start_time: float | None = None
        self._start_datetime: str | None = None

        # 当前任务的点击事件
        self._events: list[dict[str, Any]] = []

        # 当前任务最近一次点击，用于计算点击间隔
        self._last_perf: float | None = None

        # Session 序号
        self._session_counter = 0

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        清理文件名，避免任务名称里出现非法路径字符。
        """
        name = str(name).strip()
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
        name = name.rstrip(" .")
        return name or "Unknown"

    def start_session(
        self,
        task_name: str,
        config_name: str | None = None,
    ) -> None:
        """
        开始一次任务 Session。
        """

        # 如果上一个 Session 因异常没有正常结束，
        # 先尝试把它保存下来，避免数据直接丢失。
        with self._lock:
            if self._session_active:
                self._end_session_locked(
                    success=False,
                    status="replaced",
                )

            self._session_counter += 1

            now = time.time()

            self._session_active = True
            self._task_name = str(task_name)
            self._session_id = (
                f"{self._session_counter:06d}_"
                f"{datetime.fromtimestamp(now).strftime('%H%M%S_%f')[:-3]}"
            )

            self._start_time = now
            self._start_datetime = datetime.fromtimestamp(
                now
            ).isoformat(timespec="milliseconds")

            self._events.clear()
            self._last_perf = None

            # 用 config_name 区分多个 OAS 实例。
            self._config_name = str(config_name or "").strip()

    def record(
        self,
        x: int,
        y: int,
        control_name: str = "Click",
        method: str | None = None,
    ) -> None:
        """
        记录一次已经实际执行成功的点击。

        如果当前没有 Session，则忽略。
        这样可以避免启动阶段、手动调用等情况产生孤立统计。
        """

        with self._lock:
            if not self._session_active or self._start_time is None:
                return

            now = time.time()
            perf_now = time.perf_counter()

            interval = (
                None
                if self._last_perf is None
                else perf_now - self._last_perf
            )

            self._last_perf = perf_now

            self._events.append({
                "t": round(now - self._start_time, 4),
                "timestamp": datetime.fromtimestamp(
                    now
                ).isoformat(timespec="milliseconds"),
                "unix": now,
                "x": int(x),
                "y": int(y),
                "control_name": str(control_name),
                "method": method or "",
                "interval": (
                    round(interval, 4)
                    if interval is not None
                    else None
                ),
            })

    def clear(self) -> None:
        """
        清理当前 Session。
        """
        with self._lock:
            self._session_active = False
            self._task_name = ""
            self._session_id = ""
            self._start_time = None
            self._start_datetime = None
            self._events.clear()
            self._last_perf = None
            self._config_name = ""

    def events(self) -> list[dict[str, Any]]:
        """
        返回当前 Session 的事件副本。
        """
        with self._lock:
            return [dict(x) for x in self._events]

    @staticmethod
    def _stats(
        points: list[tuple[int, int]],
    ) -> dict[str, Any]:
        if not points:
            return {
                "count": 0,
                "unique_positions": 0,
            }

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        n = len(points)

        xm = sum(xs) / n
        ym = sum(ys) / n

        def sd(
            values: list[int],
            mean: float,
        ) -> float:
            return math.sqrt(
                sum((v - mean) ** 2 for v in values)
                / len(values)
            )

        counter = Counter(points)

        repeated = sum(
            count - 1
            for count in counter.values()
            if count > 1
        )

        max_streak = 1
        streak = 1

        for a, b in zip(points, points[1:]):
            if a == b:
                streak += 1
                max_streak = max(
                    max_streak,
                    streak,
                )
            else:
                streak = 1

        return {
            "count": n,
            "unique_positions": len(counter),
            "x_mean": round(xm, 3),
            "y_mean": round(ym, 3),
            "x_std": round(sd(xs, xm), 3),
            "y_std": round(sd(ys, ym), 3),
            "x_min": min(xs),
            "x_max": max(xs),
            "y_min": min(ys),
            "y_max": max(ys),
            "same_position_ratio": round(
                repeated / n,
                4,
            ),
            "max_same_position_streak": max_streak,
        }

    def summary(self) -> dict[str, Any]:
        """
        生成当前 Session 的统计摘要。
        """

        with self._lock:
            events = [dict(x) for x in self._events]

        groups: dict[
            str,
            list[tuple[int, int]],
        ] = defaultdict(list)

        for event in events:
            groups[event["control_name"]].append(
                (
                    event["x"],
                    event["y"],
                )
            )

        intervals = [
            event["interval"]
            for event in events
            if event["interval"] is not None
        ]

        interval_mean = (
            sum(intervals) / len(intervals)
            if intervals
            else None
        )

        interval_std = None

        if intervals and interval_mean is not None:
            interval_std = math.sqrt(
                sum(
                    (value - interval_mean) ** 2
                    for value in intervals
                )
                / len(intervals)
            )

        return {
            "total_clicks": len(events),
            "targets": {
                name: self._stats(points)
                for name, points in sorted(
                    groups.items()
                )
            },
            "interval": {
                "count": len(intervals),
                "mean": (
                    round(interval_mean, 4)
                    if interval_mean is not None
                    else None
                ),
                "std": (
                    round(interval_std, 4)
                    if interval_std is not None
                    else None
                ),
                "min": (
                    round(min(intervals), 4)
                    if intervals
                    else None
                ),
                "max": (
                    round(max(intervals), 4)
                    if intervals
                    else None
                ),
            },
        }

    def end_session(
        self,
        success: bool = True,
        status: str | None = None,
    ) -> Path | None:
        """
        结束当前 Session 并保存 JSON。

        返回保存的文件路径。
        """

        with self._lock:
            return self._end_session_locked(
                success=success,
                status=status,
            )

    def _end_session_locked(
        self,
        success: bool,
        status: str | None,
    ) -> Path | None:
        if not self._session_active:
            return None

        now = time.time()

        start_time = self._start_time or now

        duration = max(
            0.0,
            now - start_time,
        )

        final_status = (
            status
            if status is not None
            else (
                "success"
                if success
                else "failed"
            )
        )

        events = [
            dict(event)
            for event in self._events
        ]

        summary = self.summary()

        # 日期目录
        date_dir = datetime.fromtimestamp(
            start_time
        ).strftime("%Y-%m-%d")

        output_dir = (
            Path("log")
            / "click_statistics"
            / self._sanitize_filename(
                self._config_name or "oas"
            )
            / date_dir
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_name = (
            f"{self._session_id}_"
            f"{self._sanitize_filename(self._task_name)}"
            f".json"
        )

        path = output_dir / file_name

        data = {
            "version": 1,
            "task": self._task_name,
            "config_name": self._config_name,
            "session_id": self._session_id,
            "start_time": self._start_datetime,
            "end_time": datetime.fromtimestamp(
                now
            ).isoformat(timespec="milliseconds"),
            "duration": round(
                duration,
                4,
            ),
            "success": bool(success),
            "status": final_status,
            "summary": summary,
            "events": events,
        }

        # 先写临时文件，再替换正式文件，
        # 避免写文件过程中程序退出留下半截 JSON。
        temp_path = path.with_suffix(
            path.suffix + ".tmp"
        )

        try:
            temp_path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            temp_path.replace(path)

        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        # 清理当前 Session
        self._session_active = False
        self._task_name = ""
        self._session_id = ""
        self._start_time = None
        self._start_datetime = None
        self._events.clear()
        self._last_perf = None
        self._config_name = ""

        return path

    def export_svg(
        self,
        path: str | Path,
        width: int = 1280,
        height: int = 720,
        cell_size: int = 20,
    ) -> Path:
        """
        导出当前 Session 的点击密度 SVG。
        这个功能主要用于离线调试，OASX 后面可以直接读取 JSON 自己画热力图。
        """

        path = Path(path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        counts: Counter[
            tuple[int, int]
        ] = Counter()

        for event in self.events():
            x = max(
                0,
                min(
                    width - 1,
                    event["x"],
                ),
            )

            y = max(
                0,
                min(
                    height - 1,
                    event["y"],
                ),
            )

            counts[
                (
                    x // cell_size,
                    y // cell_size,
                )
            ] += 1

        max_count = max(
            counts.values(),
            default=1,
        )

        cells = []

        for (
            gx,
            gy,
        ), count in sorted(counts.items()):

            opacity = (
                0.08
                + 0.82
                * count
                / max_count
            )

            cells.append(
                f'<rect '
                f'x="{gx * cell_size}" '
                f'y="{gy * cell_size}" '
                f'width="{cell_size}" '
                f'height="{cell_size}" '
                f'fill="red" '
                f'fill-opacity="{opacity:.3f}">'
                f'<title>'
                f'clicks={count}'
                f'</title>'
                f'</rect>'
            )

        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg '
            'xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" '
            f'height="{height}" '
            f'viewBox="0 0 {width} {height}">\n'
            '<rect '
            'width="100%" '
            'height="100%" '
            'fill="#202020"/>\n'
            '<g>'
            + "".join(cells)
            + '</g>\n'
            f'<text '
            f'x="12" '
            f'y="24" '
            f'fill="white" '
            f'font-size="16">'
            f'Click density: '
            f'{len(self.events())} clicks'
            f'</text>\n'
            '</svg>\n'
        )

        path.write_text(
            svg,
            encoding="utf-8",
        )

        return path