"""Обновляет блок «Свежие ролики» в README.md из RSS-ленты YouTube-канала.

Шортсы пропускаем. В ленте только 15 последних загрузок, и после серии шортсов
длинные ролики из неё выпадают — поэтому найденные ролики копим в data/videos.json.

Запускается GitHub Action'ом по расписанию. Без зависимостей — только stdlib.
"""
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from html import escape
from pathlib import Path

CHANNEL_ID = "UCfLLZaPCriIR5YJovt4YPfQ"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
STORE = ROOT / "data" / "videos.json"

SHOW = 2   # сколько роликов показывать
KEEP = 20  # сколько хранить в data/videos.json

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
START, END = "<!-- videos:start -->", "<!-- videos:end -->"


def fetch(url: str, attempts: int = 3) -> bytes:
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return r.read()
        except Exception as e:
            if i == attempts - 1:
                raise
            print(f"Попытка {i + 1} не удалась: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))


def thumbnail(video_id: str) -> str:
    """maxresdefault есть не у всех роликов — тогда берём mqdefault (тоже 16:9)."""
    hi = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
    try:
        req = urllib.request.Request(hi, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                return hi
    except Exception:
        pass
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def ru_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def parse(feed: bytes) -> list[dict]:
    root = ET.fromstring(feed)
    videos = []
    for e in root.findall("atom:entry", NS):
        url = e.find("atom:link", NS).get("href")
        if "/shorts/" in url:
            continue
        videos.append({
            "id": e.find("yt:videoId", NS).text,
            "title": e.find("atom:title", NS).text.strip(),
            "url": url,
            "date": e.find("atom:published", NS).text,
        })
    return videos


def merge(fresh: list[dict]) -> list[dict]:
    """Свежие данные из ленты перекрывают сохранённые: название ролика могли поменять."""
    known = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
    by_id = {v["id"]: v for v in known} | {v["id"]: v for v in fresh}
    return sorted(by_id.values(), key=lambda v: v["date"], reverse=True)[:KEEP]


def render(videos: list[dict]) -> str:
    shown = videos[:SHOW]
    width = f"{100 // len(shown)}%"
    cells = []
    for v in shown:
        title = escape(v["title"])
        cells.append(
            f'<td width="{width}" valign="top">\n'
            f'<a href="{v["url"]}"><img src="{thumbnail(v["id"])}" alt="{title}" width="100%"></a>\n'
            f'<br><b><a href="{v["url"]}">{title}</a></b>\n'
            f'<br><sub>{ru_date(v["date"])}</sub>\n'
            f"</td>"
        )
    return "<table>\n<tr>\n" + "\n".join(cells) + "\n</tr>\n</table>"


def main() -> int:
    try:
        fresh = parse(fetch(FEED_URL))
    except Exception as e:
        # Лента YouTube иногда отвечает 404/500. Не роняем workflow и не трогаем README:
        # следующий запуск по расписанию попробует снова.
        print(f"::warning::Не удалось получить ленту: {e}")
        return 0

    videos = merge(fresh)
    if not videos:
        print("Длинных роликов пока нет — README не трогаем")
        return 0
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(videos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    block = f"{START}\n{render(videos)}\n{END}"
    updated = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda _: block, readme, flags=re.S)

    if updated == readme:
        print("Новых роликов нет")
    else:
        README.write_text(updated, encoding="utf-8")
        print("README обновлён")
    return 0


if __name__ == "__main__":
    sys.exit(main())
