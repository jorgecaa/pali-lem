import streamlit as st
import re

# Basic Pali lemmatization rules
# These are simplified rules for demonstration purposes
PALI_SUFFIXES = {
    # Nominative singular masculine/neuter endings
    'o': '',      # masculine nom. sg.
    'ā': '',      # feminine nom. sg.
    'aṃ': 'a',    # neuter nom./acc. sg.
    'ṃ': '',      # accusative marker
    # Accusative
    'ena': 'a',   # instrumental
    'assa': 'a',  # genitive
    'āya': 'a',   # dative
    'ānaṃ': 'a',  # genitive plural
    # Verb endings
    'ti': '',     # present 3rd person
    'nti': '',    # present 3rd person plural
    'āmi': '',    # present 1st person
    'si': '',     # present 2nd person
    'ati': 'a',   # present 3rd person
    'anti': 'a',  # present 3rd person plural
    'āti': 'a',   # present 3rd person
}

def lemmatize_pali_word(word):
    """
    Simple rule-based Pali lemmatizer.
    Removes common suffixes to find the root/lemma.
    
    Args:
        word (str): The Pali word to lemmatize.
    
    Returns:
        str: The lemmatized word or original word if no suffix matches.
    """
    word = word.strip()
    original_word = word
    
    # Sort suffixes by length (longest first) to match longer patterns first
    sorted_suffixes = sorted(PALI_SUFFIXES.items(), key=lambda x: len(x[0]), reverse=True)
    
    # Try to match suffixes
    for suffix, replacement in sorted_suffixes:
        if word.endswith(suffix):
            lemma = word[:-len(suffix)] + replacement
            return lemma if lemma else original_word
    
    return original_word

def lemmatize_text(text):
    """
    Lemmatize a full text by processing each word.
    
    Args:
        text (str): The Pali text to lemmatize.
    
    Returns:
        list[dict]: List of dictionaries containing 'original', 'word', 
                    'lemma', 'prefix', 'suffix', and 'changed' keys for each word.
    """
    # Split text into words, preserving punctuation
    words = re.findall(r'\S+', text)
    results = []
    
    for word in words:
        # Separate punctuation: (1) leading non-word chars, (2) core word, (3) trailing non-word chars
        match = re.match(r'^([^\w]*)([\w]+)([^\w]*)$', word, re.UNICODE)
        if match:
            prefix, core_word, suffix = match.groups()
            lemma = lemmatize_pali_word(core_word)
            results.append({
                'original': word,
                'word': core_word,
                'lemma': lemma,
                'prefix': prefix,
                'suffix': suffix,
                'changed': core_word != lemma
            })
        else:
            results.append({
                'original': word,
                'word': word,
                'lemma': word,
                'prefix': '',
                'suffix': '',
                'changed': False
            })
    
    return results

# Streamlit UI
st.title("🔤 Pali Lemmatizer")
st.write("A simple tool for lemmatizing Pali language text.")

st.markdown("""
### About Pali Lemmatization
Pali is an ancient Indo-Aryan language used in Theravada Buddhist scriptures. 
Lemmatization reduces inflected words to their base or dictionary form (lemma).

This tool uses basic rule-based lemmatization to identify root forms of Pali words.
""")

# Input section
input_method = st.radio("Input method:", ["Single word", "Full text"])

if input_method == "Single word":
    word_input = st.text_input("Enter a Pali word:", placeholder="e.g., buddho, dhammā, saṅgho")
    
    if word_input:
        lemma = lemmatize_pali_word(word_input)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Original Word", word_input)
        with col2:
            st.metric("Lemma", lemma)
        
        if word_input != lemma:
            st.success(f"✓ Lemmatized: **{word_input}** → **{lemma}**")
        else:
            st.info("ℹ️ Word appears to be already in base form")

else:
    text_input = st.text_area(
        "Enter Pali text:", 
        placeholder="e.g., buddho dhammo saṅgho",
        height=150
    )
    
    if text_input:
        results = lemmatize_text(text_input)
        
        st.subheader("Lemmatization Results")
        
        # Display statistics
        total_words = len(results)
        changed_words = sum(1 for r in results if r['changed'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Words", total_words)
        with col2:
            st.metric("Lemmatized", changed_words)
        
        # Display results in a table
        if results:
            st.markdown("#### Word-by-Word Analysis")
            for result in results:
                if result['changed']:
                    st.markdown(f"- **{result['word']}** → *{result['lemma']}* 🔄")
                else:
                    st.markdown(f"- {result['word']}")
        
        # Show lemmatized text (preserving punctuation and spacing)
        st.markdown("#### Lemmatized Text")
        lemmatized_text = " ".join([r['prefix'] + r['lemma'] + r['suffix'] for r in results])
        st.code(lemmatized_text, language=None)

# Information section
with st.expander("ℹ️ About this tool"):
    st.markdown("""
    **Note:** This is a simplified lemmatizer using basic rule-based approaches. 
    For more accurate results with complete Pali morphology, consider using:
    
    - Digital Pali Dictionary (DPD)
    - Pali Text Society resources
    - Academic NLP tools for Pali
    
    **Common Pali word endings handled:**
    - Nominative: -o, -ā, -aṃ
    - Instrumental: -ena
    - Genitive: -assa, -ānaṃ
    - Dative: -āya
    - Verb forms: -ti, -nti, -āmi, -si, -ati, -anti
    
    **Example words:**
    - buddho → buddha (the Buddha)
    - dhammo → dhamma (the teaching)
    - saṅgho → saṅgha (the community)
    """)
