import streamlit as st


def inject_styles():
    st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
    
    .stApp {
        font-family: 'Roboto', sans-serif;
    }
    
    h1, h2, h3 {
        color: var(--text-color);
    }
    
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        background-color: #3498db;
        color: white;
    }
    
    .stTextInput>div>div>input, .stTextArea>div>div>textarea {
        border-radius: 10px;
    }
    
    .book-section {
        background-color: var(--background-color);
        border-left: 5px solid #3498db;
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 20px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    
    .book-section h3 {
        color: var(--text-color);
    }
    
    .book-section p {
        color: var(--text-color);
    }
    
    .status-message {
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    
    .info {
        background-color: rgba(209, 236, 241, 0.2);
        color: #d1ecf1;
    }
    
    .success {
        background-color: rgba(212, 237, 218, 0.2);
        color: #d4edda;
    }
    
    .error {
        background-color: rgba(248, 215, 218, 0.2);
        color: #f8d7da;
    }
    
    @media (max-width: 768px) {
        .stColumn {
            flex: 1 1 100% !important;
            width: 100% !important;
        }
    }
</style>

<script>
    // JavaScript to set CSS variables based on the current theme
    const doc = window.parent.document;
    const styleEl = doc.createElement("style");
    doc.head.appendChild(styleEl);
    const setColors = () => {
        const theme = doc.body.getAttribute("data-theme");
        if (theme === "dark") {
            styleEl.innerHTML = `
                :root {
                    --background-color: #2c3e50;
                    --text-color: #ecf0f1;
                }
            `;
        } else {
            styleEl.innerHTML = `
                :root {
                    --background-color: #f8f9fa;
                    --text-color: #2c3e50;
                }
            `;
        }
    };
    const observer = new MutationObserver(() => setColors());
    observer.observe(doc.body, { attributes: true, attributeFilter: ["data-theme"] });
    setColors();
</script>
""", unsafe_allow_html=True)
