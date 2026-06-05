import streamlit as st
import pandas as pd
import pdfplumber
import json
import io
import os
import requests
import re

from dotenv import load_dotenv

from google import genai
from groq import Groq
from supabase import create_client, Client
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# =========================
# ENV
# =========================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# =========================
# CLIENTS
# =========================
client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash-lite"

groq_client = Groq(api_key=GROQ_API_KEY)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# STREAMLIT
# =========================
st.set_page_config(page_title="SmartHire AI", page_icon="📄", layout="wide")

# =========================
# SIDEBAR (NEW)
# =========================
with st.sidebar:
    st.title("📊 SmartHire Panel")
    st.markdown("### About")
    st.write("AI-powered Resume Ranking + Job Matching System")

    st.markdown("### Features")
    st.write("✔ Resume Parsing")
    st.write("✔ ATS Scoring")
    st.write("✔ Skill Extraction")
    st.write("✔ Interview Questions")
    st.write("✔ Job Search (JSearch)")

    st.markdown("### Tips")
    st.info("Enter Job Role + Upload resumes for best results")

# =========================
# HELPERS
# =========================
def safe_json(text):
    try:
        return json.loads(text)
    except:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group())
        raise


def extract_pdf_text(uploaded_file):
    text = ""
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        st.error(f"PDF Error: {e}")
    return text


# =========================
# GEMINI CALL
# =========================
def gemini_call(prompt):
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )
    return response.text


# =========================
# JSEARCH (NEW - FIXED)
# =========================
def get_jobs(job_title):
    if not JSEARCH_API_KEY:
        return {"data": []}

    url = "https://jsearch.p.rapidapi.com/search"

    headers = {
        "X-RapidAPI-Key": JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }

    params = {
        "query": job_title,
        "page": "1",
        "num_pages": "1"
    }

    response = requests.get(url, headers=headers, params=params)

    return response.json()


# =========================
# RESUME ANALYSIS
# =========================
def analyze_resume(resume_text):

    prompt = f"""
Return ONLY valid JSON.

{{
"name": "",
"skills": [],
"experience": "",
"summary": ""
}}

Resume:
{resume_text}
"""

    try:
        output = gemini_call(prompt)

        cleaned = output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.replace("```json", "").replace("```", "")

        data = safe_json(cleaned)
        return data

    except Exception as e:
        st.error(f"Gemini Error: {e}")
        return {
            "name": "Unknown",
            "skills": [],
            "experience": "",
            "summary": ""
        }


# =========================
# ATS SCORE
# =========================
def calculate_ats_score(candidate_skills, required_skills):

    candidate_set = set([s.lower().strip() for s in candidate_skills])
    required_set = set([s.lower().strip() for s in required_skills])

    matched = candidate_set.intersection(required_set)

    score = (len(matched) / max(len(required_set), 1)) * 100
    missing = list(required_set - candidate_set)

    return round(score), missing


# =========================
# INTERVIEW QUESTIONS
# =========================
def generate_questions(profile):

    prompt = f"""
Generate 5 Technical Questions and 5 HR Questions.

Candidate Profile:
{profile}
"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"Groq Error: {e}"


# =========================
# PDF REPORT
# =========================
def create_pdf_report(name, ats_score, summary, missing_skills):

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)

    pdf.drawString(100, 750, f"Candidate: {name}")
    pdf.drawString(100, 720, f"ATS Score: {ats_score}%")
    pdf.drawString(100, 690, "Summary:")
    pdf.drawString(100, 670, summary[:400])
    pdf.drawString(100, 630, "Missing Skills:")
    pdf.drawString(100, 610, ", ".join(missing_skills))

    pdf.save()
    buffer.seek(0)
    return buffer


# =========================
# SUPABASE SAVE
# =========================
def save_candidate(name, skills, ats_score, missing_skills):

    try:
        supabase.table("candidates").insert({
            "name": name,
            "skills": ", ".join(skills),
            "ats_score": int(ats_score),
            "missing_skills": ", ".join(list(map(str, missing_skills)))
        }).execute()

    except Exception as e:
        st.error(f"Supabase Error: {e}")


# =========================
# UI
# =========================
st.title("📄 SmartHire AI")
st.subheader("AI Candidate Ranking System")

job_role = st.text_input("Enter Job Role")
job_description = st.text_area("Paste Job Description", height=300)

# =========================
# JOB SEARCH OUTPUT (NEW INSERTION)
# =========================
if job_role:
    jobs = get_jobs(job_role)

    st.subheader("🔥 Live Job Listings")

    for job in jobs.get("data", [])[:5]:
        st.markdown(f"### {job.get('job_title')}")
        st.write("🏢", job.get("employer_name"))
        st.write("📍", job.get("job_city"))
        st.write("🔗", job.get("job_apply_link"))
        st.markdown("---")


# =========================
# SKILL EXTRACTION
# =========================
required_skills = []

if job_description:

    skill_prompt = f"""
Extract only skills as JSON:

{{
"skills":[]
}}

Job Description:
{job_description}
"""

    try:
        output = gemini_call(skill_prompt)

        cleaned = output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.replace("```json", "").replace("```", "")

        skill_data = safe_json(cleaned)
        required_skills = skill_data["skills"]

        st.success(f"Skills: {', '.join(required_skills)}")

    except:
        st.warning("Skill extraction failed")


# =========================
# UPLOAD
# =========================
uploaded_files = st.file_uploader(
    "Upload Resumes",
    type=["pdf"],
    accept_multiple_files=True
)

results = []

# =========================
# ANALYZE BUTTON
# =========================
if st.button("Analyze Candidates"):

    if not uploaded_files or not job_description:
        st.warning("Upload resumes + job description")
    else:

        progress = st.progress(0)

        for i, file in enumerate(uploaded_files):

            text = extract_pdf_text(file)
            analysis = analyze_resume(text)

            ats_score, missing = calculate_ats_score(
                analysis["skills"],
                required_skills
            )

            questions = generate_questions(analysis)

            results.append({
                "Name": analysis["name"],
                "Skills": ", ".join(analysis["skills"]),
                "Experience": analysis["experience"],
                "ATS Score": ats_score,
                "Missing Skills": ", ".join(missing),
                "Summary": analysis["summary"],
                "Questions": questions
            })

            progress.progress((i + 1) / len(uploaded_files))

        df = pd.DataFrame(results).sort_values("ATS Score", ascending=False)

        st.session_state["results"] = df
        st.success("Analysis Complete")


# =========================
# RESULTS
# =========================
if "results" in st.session_state:

    df = st.session_state["results"]

    st.header("📊 Ranking")
    st.dataframe(df, use_container_width=True)

    selected = st.selectbox("Select Candidate", df["Name"])

    cand = df[df["Name"] == selected].iloc[0]

    st.subheader(selected)

    st.write("ATS:", cand["ATS Score"])
    st.write("Skills:", cand["Skills"])
    st.write("Missing:", cand["Missing Skills"])
    st.write("Summary:", cand["Summary"])

    st.text_area("Questions", cand["Questions"], height=250)

    if st.button("Save to DB"):
        save_candidate(
            cand["Name"],
            cand["Skills"].split(", "),
            cand["ATS Score"],
            cand["Missing Skills"].split(", ")
        )
        st.success("Saved")

    pdf = create_pdf_report(
        cand["Name"],
        cand["ATS Score"],
        cand["Summary"],
        cand["Missing Skills"].split(", ")
    )

    st.download_button(
        "Download PDF",
        data=pdf,
        file_name=f"{cand['Name']}.pdf",
        mime="application/pdf"
    )