"""Market News tab: latest general stock-market headlines from 11 Indian business news websites."""
from __future__ import annotations

from collections import Counter

import streamlit as st

from analysis.news import MEDIA_SOURCES, ai_insights, fetch_market_news
from ui import components as C

SOURCE_NAMES = [x["name"] for x in MEDIA_SOURCES]


@st.cache_data(ttl=600, show_spinner=False)
def cached_market_news() -> dict:
    return fetch_market_news(days=3)


def render() -> None:
    C.page_header("Market News", "Latest stock-market headlines from " + ", ".join(SOURCE_NAMES) +
                  ". Click a headline to read it on the website.")
    with st.spinner("Loading headlines…"):
        data = cached_market_news()
    items = data["items"]

    f1, f2, f3 = st.columns([2.4, 1.6, 0.8], vertical_alignment="bottom")
    with f1:
        chosen = st.multiselect("Websites", SOURCE_NAMES, default=SOURCE_NAMES, key="mn_sources")
    with f2:
        q = st.text_input("Search headlines", placeholder="e.g. RBI, IPO, Reliance", key="mn_q")
    with f3:
        if st.button("⟳ Refresh", use_container_width=True):
            cached_market_news.clear()
            st.session_state.pop("mn_insights", None)
            st.rerun()

    shown = [i for i in items if i["source"] in chosen and (not q.strip() or q.lower() in i["title"].lower())]
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        if not shown:
            C.empty_state("No headlines", "No headlines match, or the websites could not be reached right now.")
        else:
            C.news_list(shown[:80])
            st.caption(f"Showing {min(len(shown), 80)} of {len(shown)} headlines · loaded "
                       f"{data['fetched_at'][:16].replace('T', ' ')} UTC")
    with right:
        with st.container(border=True):
            C.subheading("Key points from today's news")
            if st.button("Summarise these headlines", type="primary", use_container_width=True, disabled=not shown):
                with st.spinner("Reading the headlines…"):
                    st.session_state["mn_insights"] = ai_insights(shown[:40])
            ins = st.session_state.get("mn_insights")
            if ins:
                C.bullet_list(ins[0], "watch")
                st.caption(f"Written by: {ins[1]} · from headlines only, not investment advice")
            else:
                st.caption("Get 4–6 key points from the headlines shown.")
        with st.container(border=True):
            C.subheading("Headlines per website", color="green")
            counts = Counter(i["source"] for i in items)
            for s in MEDIA_SOURCES:
                st.html(f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
                        f'border-bottom:1px dashed #E8E4DD"><span>{s["name"]}</span>'
                        f'<b>{counts.get(s["name"], 0)}</b></div>')
            if data.get("errors"):
                with st.expander("Feeds that did not answer"):
                    for e in data["errors"]:
                        st.caption(e)
