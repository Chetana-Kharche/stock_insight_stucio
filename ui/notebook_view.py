"""Notebook tab: the user's notes and full history, saved in Supabase so it is there at every login."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import repository as repo
from ui import components as C
from ui import history_view
from ui import html as H
from ui.company_view import cached_companies, open_company

TYPE_LABEL = {None: "All", "text": "Text Note", "outlook": "Outlook", "action": "Action", "activity": "Activity"}


def _uid():
    return (st.session_state.get("user") or {}).get("id")


def _notes_table(notes: list[dict]) -> str:
    rows = []
    for n in notes:
        badge = f'<td><span class="vr-badge {H.e(n["note_type"])}">{H.e(TYPE_LABEL.get(n["note_type"]))}</span></td>'
        when = pd.to_datetime(n["created_at"]).strftime("%d %b %Y, %H:%M")
        rows.append([n.get("company_name") or "General", badge, n["content"], when])
    return H.generic_table(["Company", "Type", "Note", "Date"], rows, raw_html_cols=(1,), cls="wrap")


def render() -> None:
    uid = _uid()
    C.page_header("Notebook", "Your notes and everything you did in the app: fetches, reports, watchlist and "
                  "portfolio changes. Saved to your account, so it is here every time you sign in.")
    t_notes, t_fetch, t_rep, t_query = st.tabs(["Notes & activity", "Fetch history", "Report history",
                                                "Query stored data"])
    with t_notes:
        try:
            left, right = st.columns([2.6, 1], gap="large")
            with right:
                with st.container(border=True):
                    C.subheading("Filter")
                    nt = st.radio("By note type", list(TYPE_LABEL), format_func=TYPE_LABEL.get, key="nb_type")
                with st.container(border=True):
                    C.subheading("Add a note", color="green")
                    companies = cached_companies()
                    labels = {c["id"]: f"{c['name']} · {c['nse_symbol'] or c['screener_slug']}" for c in companies}
                    with st.form("nb_add", clear_on_submit=True, border=False):
                        cid = st.selectbox("Company (optional)", [c["id"] for c in companies], index=None,
                                           format_func=lambda i: labels.get(i, i), placeholder="General note")
                        kind = st.selectbox("Type", ["text", "outlook", "action"], format_func=TYPE_LABEL.get)
                        txt = st.text_area("Note")
                        if st.form_submit_button("Save note", type="primary", use_container_width=True):
                            if txt.strip():
                                repo.add_note(uid, cid, txt, kind)
                                st.rerun()
                            else:
                                st.warning("Write something first.")
            with left:
                a, b = st.columns([3, 1], vertical_alignment="bottom")
                q = a.text_input("Search notes", placeholder="Search by company or text", key="nb_q",
                                 label_visibility="collapsed")
                notes = repo.list_notes(uid, note_type=nt, search=q)
                b.download_button("⤓ Download", pd.DataFrame(notes).to_csv(index=False).encode() if notes else b"",
                                  file_name="notebook.csv", mime="text/csv", use_container_width=True,
                                  disabled=not notes)
                if not notes:
                    C.empty_state("No notes here yet", "Add a note on the right or with “✎ Add note” on any company "
                                  "page. Fetches, reports and watchlist changes are recorded automatically.")
                else:
                    st.html(_notes_table(notes))
                    st.caption(f"{len(notes)} note(s)")
                    opts = {n["id"]: f"{n.get('company_name') or 'General'} · {n['content'][:60]}" for n in notes}
                    c1, c2, c3 = st.columns([2.4, 1, 1], vertical_alignment="bottom")
                    sel = c1.selectbox("Select a note", list(opts), format_func=opts.get, key="nb_sel")
                    chosen = next(n for n in notes if n["id"] == sel)
                    if c2.button("Open company", use_container_width=True, disabled=not chosen.get("company_id")):
                        open_company(chosen["company_id"])
                        st.rerun()
                    if c3.button("Delete", use_container_width=True):
                        repo.delete_note(uid, sel)
                        st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"Notebook tables are missing. Restart the app so it can create them, or run sql/schema.sql in the Supabase SQL Editor. ({e})")
    everyone = False
    history_view.render(user_filter=None if everyone else uid, tabs=(t_fetch, t_rep, t_query))
