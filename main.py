import streamlit as st
from exporting import create_markdown_file, create_pdf_file
from generation import generate_book
from ui import inject_styles

st.set_page_config(page_title="Groqbook", page_icon="📚", layout="wide")
inject_styles()

def main():
    st.title("📚 Groqbook: Write Full Books using LLaMa3 on Groq")

    with st.sidebar:
        st.header("Generation Statistics")
        stats_placeholder = st.empty()

    col1, col2 = st.columns([3, 1])

    with col1:
        topic_text = st.text_area("What do you want the book to be about?", "", height=100)
        if st.button("Generate Book", use_container_width=True):
            if len(topic_text) < 10:
                st.error("Book topic must be at least 10 characters long")
            else:
                generate_book(topic_text, stats_placeholder)

    with col2:
        if 'book' in st.session_state:
            markdown_file = create_markdown_file(st.session_state.book.get_markdown_content())
            st.download_button(
                label='Download as Text',
                data=markdown_file,
                file_name='generated_book.txt',
                mime='text/plain',
                use_container_width=True
            )
            
            pdf_file = create_pdf_file(st.session_state.book.get_markdown_content())
            st.download_button(
                label='Download as PDF',
                data=pdf_file,
                file_name='generated_book.pdf',
                mime='application/pdf',
                use_container_width=True
            )

    if 'book' in st.session_state:
        st.header("Generated Book Content")
        st.session_state.book.display_structure()


if __name__ == "__main__":
    main()
