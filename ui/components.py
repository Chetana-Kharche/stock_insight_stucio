"""Reusable visual building blocks (page heading, section titles, tiles, empty states, lists, news)."""
from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st


def _e(x) -> str:
    return escape(str(x if x is not None else ""))


def page_header(title: str, subtitle: str = "", eyebrow: str = "", chips: list[str] | None = None) -> None:
    chips_html = "".join(f'<span class="sis-chip">{_e(c)}</span>' for c in (chips or []))
    st.html(f"""<div class="vr-page"><div>
      {f'<div class="sis-hero-eyebrow" style="font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:#C77700;font-weight:700">{_e(eyebrow)}</div>' if eyebrow else ''}
      <div class="t">{_e(title)}</div>
      {f'<div class="s">{_e(subtitle)}</div>' if subtitle else ''}
      {f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">{chips_html}</div>' if chips_html else ''}
    </div></div>""")


def section(title: str, subtitle: str = "", color: str = "blue", step: int | None = None) -> None:
    """Section heading with an accent bar. color: 'blue' | 'green' (orange accent)."""
    step_html = f'<span class="sis-step">{step}</span>' if step else ""
    st.html(f"""<div class="sis-section {'green' if color == 'green' else ''}"><div class="bar"></div>
      <div><div class="t">{step_html}{_e(title)}</div>{f'<div class="s">{_e(subtitle)}</div>' if subtitle else ''}</div>
    </div>""")


def subheading(title: str, color: str = "blue") -> None:
    st.html(f'<div class="sis-h2 {"green" if color == "green" else ""}">{_e(title)}</div>')


def empty_state(title: str, text: str, steps: list[tuple[str, str]] | None = None) -> None:
    steps_html = ""
    if steps:
        steps_html = '<div class="sis-steps">' + "".join(
            f"<div><b>{_e(a)}</b>{_e(b)}</div>" for a, b in steps) + "</div>"
    st.html(f"""<div class="sis-empty"><div class="big">{_e(title)}</div>
      <div class="small">{_e(text)}</div>{steps_html}</div>""")


def bullet_list(items: list[str], kind: str = "ok") -> None:
    """kind: ok (green tick) | risk (red !) | watch (blue arrow)."""
    if not items:
        st.caption("–")
        return
    cls = {"risk": "risk", "watch": "watch"}.get(kind, "")
    st.html(f'<ul class="sis-list {cls}">' + "".join(f"<li>{_e(x)}</li>" for x in items) + "</ul>")


def tiles(items: list[tuple[str, str, str, Optional[str]]]) -> None:
    """items: (label, value, hint, tone) with tone None | 'up' | 'dn'."""
    html = "".join(f'<div class="vr-tile"><div class="l">{_e(l)}</div><div class="v {t or ""}">{_e(v)}</div>'
                   f'{f"<div class=h>{_e(h)}</div>" if h else ""}</div>' for l, v, h, t in items)
    st.html(f'<div class="vr-tiles">{html}</div>')


def when_text(ts) -> str:
    if not ts:
        return ""
    s = str(ts)
    return s[:16].replace("T", " ")


def news_item(title: str, url: str, source: str = "", when: str = "") -> None:
    st.html(f"""<div class="vr-newslist"><div class="vr-news">{f'<span class="src">{_e(source)}</span>' if source else ''}
      <a href="{_e(url)}" target="_blank">{_e(title)}</a>
      <div class="meta">{_e(when)}</div></div></div>""")


def news_list(items: list[dict], show_source: bool = True) -> None:
    """Website name, then the headline link, then the date."""
    if not items:
        st.caption("No headlines.")
        return
    rows = "".join(
        f"""<div class="vr-news">{f'<span class="src">{_e(n.get("source") or "")}</span>' if show_source else ''}
        <a href="{_e(n.get('url'))}" target="_blank">{_e(n.get('title'))}</a>
        <div class="meta">{_e(when_text(n.get('published_at')))}</div></div>""" for n in items)
    st.html(f'<div class="vr-newslist">{rows}</div>')


def news_grouped(groups: list[tuple[str, list[dict]]]) -> None:
    """One block per website: website name as the heading, then its headline links."""
    if not groups:
        st.caption("No headlines.")
        return
    blocks = []
    for src, items in groups:
        rows = "".join(f"""<div class="vr-news"><span class="src">{_e(src)}</span>
            <a href="{_e(n.get('url'))}" target="_blank">{_e(n.get('title'))}</a>
            <div class="meta">{_e(when_text(n.get('published_at')))}</div></div>""" for n in items)
        blocks.append(f'<div class="vr-newslist" style="margin-bottom:12px"><div class="vr-srchead">{_e(src)}</div>{rows}</div>')
    st.html("".join(blocks))


def spacer(px: int = 12) -> None:
    st.html(f'<div style="height:{int(px)}px"></div>')


def unit(unit_text: str, detail: str = "") -> None:
    """'Unit: ₹ crore' label placed above a chart or table."""
    if not unit_text:
        return
    st.html(f'<div class="sis-unit"><b>Unit: {_e(unit_text)}</b>{_e(detail)}</div>')


def unit_for(key: str) -> None:
    """Unit label for a known table key (see core.units.TABLE_UNITS)."""
    from core.units import unit_of

    unit(*unit_of(key))


def tabbar(label: str, options: list, key: str, default=None, format_func=None):
    """A row of tab-like buttons (st.segmented_control); always returns a value, never None.

    Falls back to a horizontal radio on Streamlit versions without segmented_control.
    """
    default = default if default is not None else options[0]
    last_key = f"_{key}_last"
    if st.session_state.get(key) not in options:
        st.session_state[key] = st.session_state.get(last_key) if st.session_state.get(last_key) in options else default
    fmt = format_func or str
    seg = getattr(st, "segmented_control", None)
    if seg is not None:
        val = seg(label, options, key=key, format_func=fmt, label_visibility="collapsed")
    else:  # older Streamlit
        val = st.radio(label, options, key=key, format_func=fmt, horizontal=True, label_visibility="collapsed")
    if val is None:  # user clicked the active button again
        val = st.session_state.get(last_key, default)
    st.session_state[last_key] = val
    return val
