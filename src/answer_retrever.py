
import os
import time
import random
# import google.generativeai as genai
import traceback
import requests

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
# from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, PyPDFLoader, Docx2txtLoader
# from langchain_huggingface import HuggingFaceEmbeddings

# Import your question extractor
from src.question_retrever import extract_questions_from_google_form


# --------------------------------------------------------------------------
# Environment Setup
# --------------------------------------------------------------------------
load_dotenv()

# genai will be configured dynamically when answer generation functions are executed.


# --------------------------------------------------------------------------
# Document Loading and Vector Store
# --------------------------------------------------------------------------
def load_documents(file_paths):
    """Loads multiple documents (PDF, DOCX, or TXT)."""
    docs = []
    for path in file_paths:
        try:
            if not os.path.exists(path):
                print(f"⚠️  Warning: File not found at {path}, skipping.")
                continue

            if path.endswith(".pdf"):
                loader = PyPDFLoader(path)
            elif path.endswith(".docx"):
                loader = Docx2txtLoader(path)
            else:
                loader = TextLoader(path)

            docs.extend(loader.load())

        except Exception as e:
            print(f"⚠️  Error loading {path}: {e}")
            traceback.print_exc()

    return docs


def create_vector_store(docs):
    """Creates FAISS vector store from document embeddings."""
    if not docs:
        print("⚠️  No documents loaded. Skipping FAISS vector creation.")
        return None

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    split_docs = splitter.split_documents(docs)

    print("🔹 Initializing Gemini embedding model...")
    from langchain_google_genai import GoogleGenAIEmbeddings
    embeddings = GoogleGenAIEmbeddings(model="models/text-embedding-004")

    print("🔹 Creating vector store...")
    vector_store = FAISS.from_documents(split_docs, embeddings)
    print("✅ Vector store created successfully.")
    return vector_store


# --------------------------------------------------------------------------
# Safe Gemini Generation with Retry Logic
# --------------------------------------------------------------------------
def safe_generate_content(client, prompt, model_name="gemini-2.5-flash", retries=3, delay=2):
    """Calls Gemini API safely with retry logic. Logs each retry. Returns (response_text, failed_flag)."""
    last_error = "Unknown error"
    from google.genai import types
    
    # Configure safety settings for the new google-genai SDK
    config = types.GenerateContentConfig(
        safety_settings=[
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_NONE",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_NONE",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_NONE",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_NONE",
            ),
        ]
    )

    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            if response.text:
                return response.text.strip(), False

            print(f"⚠️  Attempt {attempt}: Gemini returned empty response, retrying...")
            last_error = "Empty response returned by Gemini"

        except Exception as e:
            print(f"⚠️  Attempt {attempt} failed with error: {e}")
            last_error = str(e)
            print("🔁 Retrying...")

        time.sleep(delay + random.uniform(0, 1))

    print("❌ All retry attempts failed. Marking as failed.")
    return f"No answer generated (Gemini failure: {last_error})", True


# --------------------------------------------------------------------------
# Generate Answers using RAG
# --------------------------------------------------------------------------
def generate_answers_rag_with_refresh(form_data, vector_store, top_k=3, context_refresh_interval=5):
    """Generates answers for each form question using Gemini RAG."""
    # Configure Gemini dynamically using environment key
    api_key = os.getenv("GFF_key")
    if not api_key:
        raise ValueError("Gemini API key ('GFF_key') not found. Please set it in your .env file or as a Streamlit Secret.")
    
    from google import genai
    client = genai.Client(api_key=api_key)
    PLACEHOLDER_FLAG = "DATA_NOT_FOUND"

    retriever = None
    if vector_store:
        retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": top_k})

    answered = []
    last_context_text = ""

    for i, q in enumerate(form_data, start=1):
        question_text = q.get("question", "")
        options = q.get("options", [])
        options_str = "\n".join([f"- {opt}" for opt in options]) if options else "None"

        print(f"\n🧠 Processing Q{i}: {question_text[:80]}...")

        context_text = ""
        source = "general knowledge"

        if retriever:
            try:
                relevant_docs = retriever.invoke(question_text)
                if relevant_docs:
                    context_text = "\n\n".join([doc.page_content for doc in relevant_docs])
                    source = "from context"
            except Exception as e:
                print(f"⚠️  Context retrieval failed for Q{i}: {e}")
                traceback.print_exc()

        # Context refresh mechanism
        if i % context_refresh_interval == 0 and last_context_text:
            context_text = last_context_text
        if context_text:
            last_context_text = context_text

        context_prompt = f"Use the following context to answer the question:\n{context_text}" if context_text else "No relevant context found."
        prompt = f"""
You are an intelligent assistant filling a Google Form.

Question: {question_text}
Options (if any):
{options_str}

{context_prompt}
CRITICAL: If you could not answer using context or general_knowledge then return "{PLACEHOLDER_FLAG}" and source "not_found". Never invent personal data.

Generate only the final answer (no explanation).
"""

        # Using gemini-2.5-flash which is native and fully supported in the new SDK
        answer_text, failed_flag = safe_generate_content(client, prompt, model_name="gemini-2.5-flash")
        if answer_text.strip() == PLACEHOLDER_FLAG:
            answer_text = ""
        q["answer"] = answer_text
        q["answer_source"] = source
        q["failed"] = failed_flag

        print(f"{'❌ Failed' if failed_flag else '✅ Success'} for Q{i}")
        answered.append(q)

    return answered

# --------------------------------------------------------------------------
# Safe Question Extraction
# --------------------------------------------------------------------------
def safe_extract_questions(form_url):
    """Safely extract questions from a Google Form, handling connection errors."""
    try:
        return extract_questions_from_google_form(form_url)
    except (requests.exceptions.RequestException, Exception) as e:
        print("⚠️  Error fetching Google Form questions:")
        print(f"➡️  {e}")
        traceback.print_exc()
        # Return placeholder failed entry if form couldn’t be fetched
        return [{"question": "Form fetch failed due to network error.", "options": [], "answer": "", "failed": True}]


# --------------------------------------------------------------------------
# Full Pipeline
# --------------------------------------------------------------------------
def rag_pipeline_with_refresh(form_url, doc_paths, top_k=3, context_refresh_interval=5):
    """Main RAG pipeline with full fault tolerance."""
    api_key = os.getenv("GFF_key")
    if not api_key:
        raise ValueError("Gemini API key ('GFF_key') not found. Please set it in your .env file or as a Streamlit Secret.")
    os.environ["GOOGLE_API_KEY"] = api_key

    print("🔹 Extracting questions from Google Form...")
    questions = safe_extract_questions(form_url)
    print(f"✅ Extracted {len(questions)} questions (including failed placeholders if any).")

    docs = load_documents(doc_paths)
    vector_store = create_vector_store(docs)

    print("🔹 Generating answers using RAG...")
    filled_form = generate_answers_rag_with_refresh(
        questions,
        vector_store,
        top_k=top_k,
        context_refresh_interval=context_refresh_interval,
    )

    return filled_form




# -------------------------------
# Example usage
# -------------------------------



# if __name__ == "__main__":
#     FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScP8ZvKzWqo496iHhBYp99ygcSEGADD4LOJAaXjspkYvfRBnw/viewform?usp=header"
#     DOCUMENTS = [r"test_files\Kesani_Sai_Charan_resume.pdf"]  # Add your files
#     # DOCUMENTS = [r"C:\Users\rav29\Desktop\Kesani_Sai_Charan_resume.pdf"]  # Add your files
#     # DOCUMENTS = [r"test_files\GFF_sample_context_text_file_2.pdf", r"test_files\GFF_sample_context_text_file.docx",]  # Add your files

#     filled_form = rag_pipeline_with_refresh(
#         FORM_URL, DOCUMENTS,
#         top_k=3,
#         context_refresh_interval=5  # Refresh context every 5 questions
#     )
    
#     print("\n--- Final Answers ---")
#     for q in filled_form:
#         print(q)
#         print(f"Q: {q['question']}")
#         print(f"A: {q['answer']} (Source: {q['answer_source']})")
#         print("-" * 60)