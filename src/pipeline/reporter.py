"""요약 결과를 Markdown 리포트로 변환합니다."""
from datetime import datetime


def build_report(session: dict, summary: dict) -> str:
    title = session.get("title", "제목 없음")
    channel = session.get("channel_title", "")
    video_id = session.get("video_id", "")
    started = session.get("started_at", "")
    ended = session.get("ended_at", "")
    peak = session.get("peak_viewers", 0)
    duration_secs = session.get("duration_secs", 0)

    h, m = divmod(duration_secs // 60, 60)
    s = duration_secs % 60
    duration_str = f"{h}시간 {m}분 {s}초" if h else f"{m}분 {s}초"
    video_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

    topics_md = "\n".join(f"- {t}" for t in summary.get("key_topics", []))

    highlights_md = ""
    for hl in summary.get("highlights", []):
        ts = hl.get("timestamp", "")
        desc = hl.get("description", "")
        if ts and ts != "null":
            link = f"{video_url}&t={_ts_to_seconds(ts)}s" if video_url else ""
            highlights_md += f"- [{ts}]({link}) {desc}\n" if link else f"- [{ts}] {desc}\n"
        else:
            highlights_md += f"- {desc}\n"

    report = f"""# 📺 라이브 방송 요약

## {title}

| 항목 | 내용 |
|------|------|
| 채널 | {channel} |
| 방송 시간 | {duration_str} |
| 최대 동시 시청자 | {peak:,}명 |
| 시작 | {_fmt_dt(started)} |
| 종료 | {_fmt_dt(ended)} |
| 링크 | {video_url} |

---

## 한줄 요약
> {summary.get("one_liner", "")}

---

## 전체 요약

{summary.get("summary_text", "")}

---

## 핵심 주제

{topics_md or "- 없음"}

---

## 주요 하이라이트

{highlights_md or "- 없음"}

---
*생성 시각: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}*
"""
    return report.strip()


def _ts_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        pass
    return 0


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M KST") if "09:00" in iso else dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso
