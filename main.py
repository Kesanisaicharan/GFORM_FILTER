from src.answer_retrever import rag_pipeline_with_refresh 
from src.selenium_filler import fill_google_form


if __name__ == "__main__":

    FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScP8ZvKzWqo496iHhBYp99ygcSEGADD4LOJAaXjspkYvfRBnw/viewform?usp=header"
    DOCUMENTS = [r"test_files\Kesani_Sai_Charan_resume.pdf"]  
    # DOCUMENTS = [r"test_files\GFF_sample_context_text_file_2.pdf", r"test_files\GFF_sample_context_text_file.docx"]  # Add your files

    print("🚀 Starting the Google Form Auto-filler Process...")
    print(f"📄 Using document(s): {', '.join(DOCUMENTS)}")

    print("\n🧠 Generating answers from documents... Please wait.")
    filled_form_data = rag_pipeline_with_refresh(
        FORM_URL, 
        DOCUMENTS,
        top_k=3,
        context_refresh_interval=5
    )
    
    # ---  Verify the Generated Answers  ---

    print("\n✅ Answers generated successfully. Here's what will be filled in:")
    print("-" * 70)
    for q in filled_form_data:
        print(f"❓ Question: {q['question']}")
        print(f"✔️ Answer:   {q.get('answer', 'No answer found')}") # Use .get() for safety
        print("-" * 70)

    # ---  Automatically Fill the Google Form ---

    print("\n🤖 Now launching browser to auto-fill the form...")
    fill_google_form(FORM_URL, filled_form_data)

    print("\n🎉 Process complete! The browser window has been left open for your review.")