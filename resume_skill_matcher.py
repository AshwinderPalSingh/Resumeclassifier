import spacy
import sqlite3
import os
import shutil
import fitz  ]
import pytesseract
from PIL import Image
from sentence_transformers import SentenceTransformer, util
from typing import List, Tuple
import uuid

from skills_list import skills_list
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"


nlp = spacy.load("en_core_web_sm")
model = SentenceTransformer('all-MiniLM-L6-v2')

# SQLite database setup
def init_db():
    conn = sqlite3.connect('resume_matcher.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            resume_id TEXT,
            job_id TEXT,
            compatibility_score REAL,
            matched_skills TEXT,
            resume_path TEXT
        )
    ''')
    conn.commit()
    return conn

def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception:
        return ""

def extract_text_from_png(png_path: str) -> str:
    try:
        image = Image.open(png_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception:
        return ""

def extract_skills(text: str) -> List[str]:
    if not text:
        return []
    text_lower = text.lower()
    skills = []
    for skill in skills_list:
        if skill.lower() in text_lower:
            skills.append(skill)
    return list(set(skills))  # Remove duplicates

def calculate_compatibility(resume_text: str, job_skills: List[str]) -> Tuple[float, List[str]]:
    resume_skills = extract_skills(resume_text)
    if not resume_skills or not job_skills:
        return 0.0, []
    resume_embeddings = model.encode(resume_skills, convert_to_tensor=True)
    job_embeddings = model.encode(job_skills, convert_to_tensor=True)
    cosine_scores = util.cos_sim(resume_embeddings, job_embeddings)
    avg_score = cosine_scores.mean().item() if cosine_scores.size else 0.0
    matched_skills = [skill for skill in resume_skills if skill.lower() in [s.lower() for s in job_skills]]
    return avg_score, matched_skills

def store_results(conn, resume_id: str, job_id: str, score: float, matched_skills: List[str], resume_path: str):
    c = conn.cursor()
    match_id = str(uuid.uuid4())
    c.execute('''
        INSERT INTO matches (id, resume_id, job_id, compatibility_score, matched_skills, resume_path)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (match_id, resume_id, job_id, score, ", ".join(matched_skills), resume_path))
    conn.commit()

def clear_table(conn):
    c = conn.cursor()
    c.execute('DELETE FROM matches')
    conn.commit()

def process_resumes(folder_path: str, job_skills: List[str], output_folder: str, conn):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    results = []
    for filename in os.listdir(folder_path):
        if filename.lower().endswith(('.pdf', '.png')):
            file_path = os.path.join(folder_path, filename)
            resume_text = extract_text_from_pdf(file_path) if filename.lower().endswith('.pdf') else extract_text_from_png(file_path)
            if resume_text:
                score, matched_skills = calculate_compatibility(resume_text, job_skills)
                resume_id = str(uuid.uuid4())
                job_id = str(uuid.uuid4())
                
                # Check if at least one requested skill is present
                resume_skills = extract_skills(resume_text)
                if any(skill.lower() in [s.lower() for s in resume_skills] for skill in job_skills):
                    store_results(conn, resume_id, job_id, score, matched_skills, file_path)
                    output_path = os.path.join(output_folder, filename)
                    shutil.copy(file_path, output_path)
                    extra_skills_count = len([skill for skill in resume_skills if skill.lower() not in [s.lower() for s in job_skills]])
                    total_skills_count = len(resume_skills)
                    results.append({
                        'filename': filename,
                        'score': score + (extra_skills_count * 0.1),  # Boost score by 0.1 per extra skill
                        'matched_skills': matched_skills,
                        'total_skills_count': total_skills_count,
                        'extra_skills_count': extra_skills_count,
                        'resume_path': output_path
                    })
    
    results.sort(key=lambda x: (x['extra_skills_count'], x['score']), reverse=True)
    return results


if __name__ == "__main__":
    conn = init_db()
    
  
    clear_choice = input("\nWould you like to clear the existing matches table? (yes/no): ").lower()
    if clear_choice == 'yes':
        clear_table(conn)
        print("\nMatches table has been cleared.\n")

    print("Welcome to Resume Skill Matcher!")
    print("----------------------------------")
    folder_path = input("Please enter the path to your resume folder (e.g., ./resumes): ")
    job_skills_input = input("Please enter the skills to match (e.g., Creo, Python, Java), separated by commas: ")
    job_skills = [skill.strip().capitalize() for skill in job_skills_input.split(',')]
    output_folder = os.path.join(folder_path, "selected")
    

    results = process_resumes(folder_path, job_skills, output_folder, conn)

    if results:
        print("\nMatching Resumes Found:")
        print("-----------------------")
        for result in results:
            print(f"Filename: {result['filename']}")
            print(f"Compatibility Score: {result['score']:.2f}")
            print(f"Total Number of Skills: {result['total_skills_count']}")
            print(f"Extra Skills Count: {result['extra_skills_count']}")
            print("-----------------------")
        print(f"\nSelected resumes have been saved in: {output_folder}\n")
    else:
        print("\nNo resumes match any of the specified skills.\n")
    
    conn.close()
