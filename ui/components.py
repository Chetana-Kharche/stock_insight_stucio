"""Reusable visual building blocks (page header, section titles, empty states, lists)."""
from __future__ import annotations

from html import escape

import streamlit as st


def _e(x) -> str:
    return escape(str(x if x is not None else ""))


def page_header(title: str, subtitle: str = "", eyebrow: str = "", chips: list[str] | None = None) -> None:
    chips_html = "".join(f'<span class="sis-chip">{_e(c)}</span>' for c in (chips or []))
    st.html(f"""<div class="sis-hero">
      {f'<div class="eyebrow">{_e(eyebrow)}</div>' if eyebrow else ''}
      <div class="title">{_e(title)}</div>
      {f'<div class="subtitle">{_e(subtitle)}</div>' if subtitle else ''}
      {f'<div class="chips">{chips_html}</div>' if chips_html else ''}
    </div>""")


def section(title: str, subtitle: str = "", color: str = "blue", step: int | None = None) -> None:
    """Coloured section heading with an accent bar. color: 'blue' | 'green'."""
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


def news_item(title: str, url: str, source: str = "", when: str = "") -> None:
    st.html(f"""<div class="sis-news"><a href="{_e(url)}" target="_blank">{_e(title)}</a>
      <div class="meta"><span class="src">{_e(source)}</span>{' · ' if source and when else ''}{_e(when)}</div></div>""")


def spacer(px: int = 12) -> None:
    st.html(f'<div style="height:{int(px)}px"></div>')


def unit(unit_text: str, detail: str = "") -> None:
    """Green 'Unit: ₹ crore' label placed above a chart or table."""
    if not unit_text:
        return
    st.html(f'<div class="sis-unit"><b>Unit: {_e(unit_text)}</b>{_e(detail)}</div>')


def unit_for(key: str) -> None:
    """Unit label for a known table key (see core.units.TABLE_UNITS)."""
    from core.units import unit_of

    unit(*unit_of(key))
