import streamlit as st

class Book:
    def __init__(self, structure):
        self.structure = structure
        self.contents = {title: "" for title in self.flatten_structure(structure)}
        self.placeholders = {title: st.empty() for title in self.flatten_structure(structure)}

    def flatten_structure(self, structure):
        sections = []
        for title, content in structure.items():
            sections.append(title)
            if isinstance(content, dict):
                sections.extend(self.flatten_structure(content))
        return sections

    def update_content(self, title, new_content):
        self.contents[title] += new_content
        self.display_content(title)

    def display_content(self, title):
        if self.contents[title].strip():
            self.placeholders[title].markdown(
                f"""
                <div class='book-section'>
                    <h3>{title}</h3>
                    <div>{self.contents[title]}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    def display_structure(self, structure=None, level=2):
        if structure is None:
            structure = self.structure
        
        for title, content in structure.items():
            if self.contents[title].strip():
                st.markdown(f"<h{level} style='color: var(--text-color);'>{title}</h{level}>", unsafe_allow_html=True)
                self.display_content(title)
            if isinstance(content, dict):
                self.display_structure(content, level + 1)

    def get_markdown_content(self, structure=None, level=1):
        if structure is None:
            structure = self.structure
        
        markdown_content = ""
        for title, content in structure.items():
            if self.contents[title].strip():
                markdown_content += f"{'#' * level} {title}\n{self.contents[title]}\n\n"
            if isinstance(content, dict):
                markdown_content += self.get_markdown_content(content, level + 1)
        return markdown_content
