import streamlit as st

st.set_page_config(
    page_title="Pali Lemmatizer",
    page_icon="📖",
    layout="wide"
)

st.title("📖 Pali Language Lemmatizer")

st.markdown("""
Welcome to the Pali Language Lemmatizer! This tool helps you analyze Pali text by identifying the base forms (lemmas) of words.

**About Pali:**
Pali is a classical language of Theravada Buddhism, used in many Buddhist scriptures and commentaries.
Lemmatization helps identify the dictionary form of inflected words, which is essential for textual analysis and research.
""")

# Create two columns for better layout
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Input Pali Text")
    
    # Text input area
    pali_text = st.text_area(
        "Enter Pali text to analyze:",
        height=200,
        placeholder="Enter Pali words or sentences here...",
        help="Enter the Pali text you want to lemmatize"
    )
    
    # Processing options
    st.subheader("Options")
    show_word_breakdown = st.checkbox("Show word-by-word breakdown", value=True)
    show_statistics = st.checkbox("Show text statistics", value=True)
    
    # Process button
    if st.button("Analyze Text", type="primary"):
        if pali_text.strip():
            st.subheader("Analysis Results")
            
            # Basic word tokenization
            words = pali_text.split()
            unique_words = set(words)
            
            if show_word_breakdown:
                st.markdown("#### Word Breakdown")
                st.info("""
                **Note:** This is a demonstration version. A complete lemmatization system would require 
                a comprehensive Pali morphological analyzer and dictionary database.
                """)
                
                # Display each word
                for i, word in enumerate(words, 1):
                    with st.expander(f"Word {i}: {word}"):
                        st.write(f"**Original form:** {word}")
                        st.write(f"**Lemma:** *(requires Pali dictionary)*")
                        st.write(f"**Part of speech:** *(requires morphological analysis)*")
            
            if show_statistics:
                st.markdown("#### Text Statistics")
                col_stat1, col_stat2, col_stat3 = st.columns(3)
                
                with col_stat1:
                    st.metric("Total Words", len(words))
                
                with col_stat2:
                    st.metric("Unique Words", len(unique_words))
                
                with col_stat3:
                    avg_length = sum(len(w) for w in words) / len(words) if words else 0
                    st.metric("Avg Word Length", f"{avg_length:.1f}")
        else:
            st.warning("Please enter some Pali text to analyze.")

with col2:
    st.subheader("Resources")
    st.markdown("""
    **Useful Links:**
    - [Pali Text Society](https://palitextsociety.org/)
    - [Digital Pali Dictionary](https://digitalpalidictionary.github.io/)
    - [SuttaCentral](https://suttacentral.net/)
    
    **About Lemmatization:**
    Lemmatization is the process of grouping together inflected forms of a word 
    so they can be analyzed as a single item, identified by the word's lemma (base form).
    
    For example, in English:
    - "running", "ran", "runs" → lemma: "run"
    
    In Pali, this is essential due to the language's rich inflectional morphology.
    """)

# Footer
st.divider()
st.caption("Pali Lemmatizer - A tool for Pali language text analysis")
