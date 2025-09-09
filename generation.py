import json
import streamlit as st

from stats import GenerationStatistics
from book import Book
from llm import generate_book_structure, generate_section


def generate_book(topic_text, stats_placeholder):
    with st.spinner("Generating book structure..."):
        structure_stats, book_structure = generate_book_structure(topic_text)
        stats_placeholder.markdown(str(structure_stats), unsafe_allow_html=True)

    try:
        book_structure_json = json.loads(book_structure)
        book = Book(book_structure_json)
        st.session_state.book = book

        total_stats = GenerationStatistics(model_name="Combined")

        def stream_section_content(sections):
            for title, content in sections.items():
                if isinstance(content, str):
                    with st.spinner(f"Generating content for: {title}"):
                        content_stream = generate_section(f"{title}: {content}")
                        for chunk in content_stream:
                            if isinstance(chunk, GenerationStatistics):
                                total_stats.add(chunk)
                                stats_placeholder.markdown(str(total_stats), unsafe_allow_html=True)
                            elif chunk is not None:
                                st.session_state.book.update_content(title, chunk)
                elif isinstance(content, dict):
                    stream_section_content(content)

        stream_section_content(book_structure_json)
        st.success("Book generation completed!")

    except json.JSONDecodeError:
        st.error("Failed to decode the book structure. Please try again.")
