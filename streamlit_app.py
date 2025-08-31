import re
import pdfplumber
import streamlit as st
import pandas as pd
from fpdf import FPDF
import io

# ---------------- STEP 1: Extract Complete Questions + Year ----------------
def extract_questions_with_year(pdf_file):
    """Extract complete questions with all content (text, options, marks) between question markers"""
    questions_data = []
    current_year = None
    all_text = ""
    page_breaks = {}

    # First, extract all text and track page breaks
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text:
                continue
            
            page_breaks[len(all_text)] = page_num
            all_text += f"\n--- PAGE {page_num} ---\n" + text

    # Enhanced year extraction for IAI format
    year_patterns = [
        r"(\d{1,2})\s*(?:st|nd|rd|th)\s+\w+\s+(20\d{2})",  # "28th May 2024"
        r"(20\d{2})",  # Simple year
        r"Year\s*:?\s*(20\d{2})",  # "Year: 2024"
        r"Session\s*:?\s*(20\d{2})",  # "Session: 2024"
    ]
    
    for pattern in year_patterns:
        year_match = re.search(pattern, all_text, re.IGNORECASE)
        if year_match:
            if "st|nd|rd|th" in pattern:
                current_year = year_match.group(2)
            else:
                groups = year_match.groups()
                current_year = groups[-1]  # Take the last group (year)
            break

    # Enhanced question detection for IAI format
    question_pattern = r"Q\.\s*(\d+)\)"  # Specifically "Q. 1)" format used in IAI papers
    
    question_positions = []
    for match in re.finditer(question_pattern, all_text, re.MULTILINE):
        q_num = int(match.group(1))
        start_pos = match.start()
        
        # Find which page this question is on
        page_num = 1
        for pos, page in page_breaks.items():
            if start_pos >= pos:
                page_num = page
        
        question_positions.append({
            "number": q_num,
            "start": start_pos,
            "match": match,
            "page": page_num
        })

    # Sort by question number to ensure correct order
    question_positions.sort(key=lambda x: x["number"])

    # Extract complete content between questions
    for i, q_pos in enumerate(question_positions):
        # Determine end position (start of next question or special markers)
        if i + 1 < len(question_positions):
            end_pos = question_positions[i + 1]["start"]
        else:
            # Look for end markers like "************************" or document end
            end_markers = list(re.finditer(r'\*{10,}', all_text[q_pos["start"]:]))
            if end_markers:
                end_pos = q_pos["start"] + end_markers[0].start()
            else:
                end_pos = len(all_text)

        # Extract complete question content
        complete_content = all_text[q_pos["start"]:end_pos].strip()
        
        # Clean up page markers and extra whitespace
        complete_content = re.sub(r'\n--- PAGE \d+ ---\n', '\n', complete_content)
        complete_content = re.sub(r'\n\s*\n\s*\n', '\n\n', complete_content)  # Clean multiple newlines
        complete_content = complete_content.strip()

        # Extract marks if present (look for [2], [4], etc. at the end)
        marks_pattern = r'\[(\d+)\]\s*$'
        marks_match = re.search(marks_pattern, complete_content)
        marks = marks_match.group(1) if marks_match else "Unknown"

        # Skip if content is too short
        if len(complete_content) > 20:
            # Create preview text (first meaningful line after Q. X))
            lines = complete_content.split('\n')
            preview_text = ""
            for line in lines:
                clean_line = re.sub(r'Q\.\s*\d+\)', '', line).strip()
                if clean_line and len(clean_line) > 10:
                    preview_text = clean_line
                    break
            
            if not preview_text:
                preview_text = lines[0] if lines else complete_content

            questions_data.append({
                "question_number": q_pos["number"],
                "question_preview": preview_text[:150] + "..." if len(preview_text) > 150 else preview_text,
                "complete_content": complete_content,
                "marks": marks,
                "chapter": None,
                "year": current_year or "Unknown",
                "page": q_pos["page"]
            })

    return questions_data


# ---------------- STEP 2: Generate Workbook PDF ----------------
def generate_workbook(questions, output_path="chapter_wise_workbook.pdf"):
    """Generate chapter-wise organized workbook"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=16)
    pdf.cell(0, 15, "Chapter-wise Question Workbook", ln=True, align="C")
    pdf.ln(10)

    # Filter out unassigned questions
    assigned_questions = [q for q in questions if q["chapter"] and q["chapter"] != "-- Select Chapter --"]
    
    if not assigned_questions:
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 10, "No questions have been assigned to chapters yet.", ln=True)
        pdf.output(output_path)
        return

    # Group by chapter
    chapters = {}
    for q in assigned_questions:
        chapter = q["chapter"]
        if chapter not in chapters:
            chapters[chapter] = []
        chapters[chapter].append(q)

    # Sort chapters naturally
    def chapter_sort_key(chapter_name):
        match = re.search(r'(\d+)', chapter_name)
        return int(match.group(1)) if match else float('inf')
    
    sorted_chapters = sorted(chapters.keys(), key=chapter_sort_key)

    for chapter in sorted_chapters:
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 12, f"{chapter}", ln=True)
        pdf.ln(5)
        
        for i, q in enumerate(chapters[chapter], 1):
            # Add question header with marks
            pdf.set_font("Arial", "B", 12)
            header_text = f"Question {q['question_number']} (Year: {q['year']}) - [{q['marks']} marks]"
            pdf.cell(0, 8, header_text, ln=True)
            pdf.ln(3)
            
            # Add complete question content
            pdf.set_font("Arial", size=10)
            
            # Process the complete content line by line
            content_lines = q['complete_content'].split('\n')
            for line in content_lines:
                line = line.strip()
                if line:
                    # Handle different types of content
                    if re.match(r'[ABCD]\.', line):  # Options A. B. C. D.
                        pdf.set_font("Arial", size=10)
                        pdf.cell(5, 5, "", ln=False)  # Indent options
                    elif re.match(r'[IVX]+\.', line):  # Roman numerals I. II. III. IV.
                        pdf.set_font("Arial", size=10)
                        pdf.cell(5, 5, "", ln=False)  # Indent roman options
                    elif re.match(r'[a-d]\.', line):  # Lower case options a. b. c. d.
                        pdf.set_font("Arial", size=10)
                        pdf.cell(5, 5, "", ln=False)  # Indent lower options
                    elif re.match(r'i+\)', line):  # Sub-questions i) ii) iii)
                        pdf.set_font("Arial", "B", 10)
                    else:
                        pdf.set_font("Arial", size=10)
                    
                    # Handle long lines by wrapping
                    try:
                        # Try to encode in latin-1, fallback to UTF-8 handling
                        encoded_line = line.encode('latin-1', 'replace').decode('latin-1')
                        pdf.multi_cell(0, 5, encoded_line)
                    except:
                        # If encoding fails, use a simplified version
                        clean_line = ''.join(char if ord(char) < 128 else '?' for char in line)
                        pdf.multi_cell(0, 5, clean_line)
                else:
                    pdf.ln(2)  # Empty line spacing
            
            pdf.ln(10)  # Space between questions
        
        pdf.ln(10)  # Space between chapters

    pdf.output(output_path)


# ---------------- STEP 3: Bulk Assignment Helper ----------------
def bulk_assign_by_keywords(questions, keyword_mapping):
    """Assign chapters based on keywords in questions"""
    for q in questions:
        question_lower = q["question_preview"].lower()
        for chapter, keywords in keyword_mapping.items():
            if any(keyword.lower() in question_lower for keyword in keywords):
                q["chapter"] = chapter
                break
    return questions


# ---------------- STREAMLIT APP ----------------
def main():
    st.set_page_config(page_title="PYQ Chapter Labeler", page_icon="📘", layout="wide")
    
    st.title("📘 PYQ to Chapter-wise Workbook Generator")
    st.markdown("Upload your question paper PDF and organize questions by chapters!")

    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        num_chapters = st.number_input("Number of chapters:", min_value=1, max_value=50, value=12, step=1)
        
        # Chapter naming option
        chapter_naming = st.selectbox(
            "Chapter naming style:",
            ["Chapter 1, Chapter 2, ...", "Custom names", "Subject-wise"]
        )
        
        if chapter_naming == "Custom names":
            st.write("Enter chapter names (one per line):")
            chapter_names_input = st.text_area(
                "Chapter names:",
                placeholder="Introduction\nBasic Concepts\nAdvanced Topics\n...",
                height=150
            )
            chapter_names = [name.strip() for name in chapter_names_input.split('\n') if name.strip()]
        elif chapter_naming == "Subject-wise":
            # Common actuarial subjects
            chapter_names = [
                "Portfolio Theory", "CAPM & Asset Pricing", "Options & Derivatives", 
                "Fixed Income", "Risk Management", "Efficient Market Hypothesis",
                "Credit Risk", "Claims Reserving", "Stochastic Processes",
                "Loss Distributions", "Ruin Theory", "Financial Engineering"
            ]
        else:
            chapter_names = [f"Chapter {i}" for i in range(1, num_chapters + 1)]

    # Main content area
    uploaded_file = st.file_uploader("📁 Upload PYQ PDF", type=["pdf"])

    if uploaded_file:
        # Process button
        if st.button("🔍 Extract Questions", type="primary"):
            with st.spinner("Extracting questions from PDF..."):
                questions = extract_questions_with_year(uploaded_file)
            
            if questions:
                st.success(f"✅ Successfully extracted {len(questions)} questions!")
                
                # Store in session state
                st.session_state.questions = questions
                st.session_state.chapter_names = chapter_names
                
                # Show preview
                preview_data = []
                for q in questions:
                    preview_data.append({
                        "Q#": q["question_number"],
                        "Preview": q["question_preview"],
                        "Marks": q["marks"],
                        "Year": q["year"],
                        "Page": q["page"],
                        "Chapter": q["chapter"] or "Unassigned"
                    })
                
                preview_df = pd.DataFrame(preview_data)
                st.write("### 📋 Extracted Questions Preview")
                st.dataframe(preview_df, use_container_width=True)
                
                # Show sample complete content
                if questions:
                    with st.expander("🔍 View Sample Complete Question Content"):
                        sample_q = questions[0]
                        st.write(f"**Question {sample_q['question_number']} - Complete Content:**")
                        st.text_area("", value=sample_q["complete_content"], height=200, disabled=True)
                
            else:
                st.error("❌ No questions found in the PDF. Please check the format.")

        # Question labeling section
        if 'questions' in st.session_state:
            questions = st.session_state.questions
            chapter_names = st.session_state.chapter_names
            
            st.write("---")
            st.write("### 🏷️ Assign Questions to Chapters")
            
            # Bulk assignment option
            with st.expander("🚀 Bulk Assignment (Optional)"):
                st.write("Define keywords for automatic chapter assignment:")
                keyword_mapping = {}
                
                cols = st.columns(2)
                for i, chapter in enumerate(chapter_names):
                    col = cols[i % 2]
                    with col:
                        keywords = st.text_input(
                            f"Keywords for {chapter}:",
                            placeholder="keyword1, keyword2, keyword3",
                            key=f"keywords_{chapter}"
                        )
                        if keywords:
                            keyword_mapping[chapter] = [k.strip() for k in keywords.split(',')]
                
                if st.button("🎯 Apply Bulk Assignment") and keyword_mapping:
                    questions = bulk_assign_by_keywords(questions, keyword_mapping)
                    st.session_state.questions = questions
                    st.success("Bulk assignment completed!")
                    st.rerun()

            # Individual question assignment
            st.write("#### Individual Question Assignment")
            
            # Filter options
            col1, col2, col3 = st.columns(3)
            with col1:
                filter_chapter = st.selectbox(
                    "Filter by chapter:",
                    ["All"] + ["Unassigned"] + chapter_names,
                    key="filter_chapter"
                )
            with col2:
                filter_year = st.selectbox(
                    "Filter by year:",
                    ["All"] + sorted(set(q["year"] for q in questions)),
                    key="filter_year"
                )
            with col3:
                questions_per_page = st.selectbox(
                    "Questions per page:",
                    [5, 10, 20],
                    index=1
                )

            # Apply filters
            filtered_questions = questions.copy()
            if filter_chapter == "Unassigned":
                filtered_questions = [q for q in questions if not q["chapter"] or q["chapter"] == "-- Select Chapter --"]
            elif filter_chapter != "All":
                filtered_questions = [q for q in questions if q["chapter"] == filter_chapter]
            
            if filter_year != "All":
                filtered_questions = [q for q in filtered_questions if q["year"] == filter_year]

            # Pagination
            total_questions = len(filtered_questions)
            total_pages = (total_questions - 1) // questions_per_page + 1 if total_questions > 0 else 0
            
            if total_pages > 1:
                page_num = st.selectbox(f"Page (showing {questions_per_page} questions per page):", 
                                      range(1, total_pages + 1)) - 1
            else:
                page_num = 0

            start_idx = page_num * questions_per_page
            end_idx = min(start_idx + questions_per_page, total_questions)
            page_questions = filtered_questions[start_idx:end_idx]

            # Display questions for assignment
            if page_questions:
                st.write(f"Showing questions {start_idx + 1}-{end_idx} of {total_questions}")
                
                for i, q in enumerate(page_questions):
                    with st.container():
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.write(f"**Q{q['question_number']}** ({q['year']}) - Page {q['page']} - **[{q['marks']} marks]**")
                            
                            # Show preview with option to view complete content
                            st.write(f"**Preview:** {q['question_preview']}")
                            
                            # Expandable section for complete content
                            with st.expander(f"🔍 View Complete Question {q['question_number']} (with options & marks)"):
                                st.text_area(
                                    "Complete Content:",
                                    value=q["complete_content"],
                                    height=400,
                                    disabled=True,
                                    key=f"content_view_{i}_{page_num}"
                                )
                        
                        with col2:
                            # Find the question in the original list
                            original_idx = next(idx for idx, orig_q in enumerate(questions) 
                                              if orig_q["question_number"] == q["question_number"] and orig_q["page"] == q["page"])
                            
                            current_chapter = questions[original_idx].get("chapter", "-- Select Chapter --")
                            if current_chapter is None:
                                current_chapter = "-- Select Chapter --"
                            
                            try:
                                if current_chapter in chapter_names:
                                    current_index = chapter_names.index(current_chapter) + 1
                                else:
                                    current_index = 0
                            except ValueError:
                                current_index = 0
                            
                            selected_chapter = st.selectbox(
                                "Chapter:",
                                ["-- Select Chapter --"] + chapter_names,
                                index=current_index,
                                key=f"chapter_select_{original_idx}_{page_num}"
                            )
                            
                            # Update the question's chapter
                            questions[original_idx]["chapter"] = selected_chapter

                # Save changes to session state
                st.session_state.questions = questions
            else:
                st.info("No questions match the current filters.")

            # Progress tracking
            assigned_count = len([q for q in questions if q["chapter"] and q["chapter"] != "-- Select Chapter --"])
            progress = assigned_count / len(questions) if questions else 0
            
            st.write("### 📊 Assignment Progress")
            st.progress(progress)
            st.write(f"✅ {assigned_count}/{len(questions)} questions assigned ({progress:.1%})")

            # Generate workbook section
            st.write("---")
            st.write("### 📘 Generate Workbook")
            
            if assigned_count > 0:
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("📄 Generate Chapter-wise Workbook", type="primary"):
                        with st.spinner("Generating workbook PDF..."):
                            output_buffer = io.BytesIO()
                            generate_workbook(questions, "temp_workbook.pdf")
                            
                            with open("temp_workbook.pdf", "rb") as f:
                                output_buffer.write(f.read())
                            output_buffer.seek(0)
                            
                            st.download_button(
                                "📥 Download Workbook PDF",
                                data=output_buffer.getvalue(),
                                file_name="chapter_wise_workbook.pdf",
                                mime="application/pdf"
                            )
                
                with col2:
                    if st.button("💾 Export Assignment Data"):
                        # Create CSV with all assignment data
                        df = pd.DataFrame(questions)
                        csv_buffer = io.StringIO()
                        df.to_csv(csv_buffer, index=False)
                        
                        st.download_button(
                            "📥 Download CSV Data",
                            data=csv_buffer.getvalue(),
                            file_name="question_assignments.csv",
                            mime="text/csv"
                        )
            else:
                st.info("⚠️ Please assign at least one question to a chapter before generating the workbook.")

            # Summary statistics
            if assigned_count > 0:
                st.write("### 📈 Assignment Summary")
                
                # Create summary dataframe
                assigned_questions = [q for q in questions if q["chapter"] and q["chapter"] != "-- Select Chapter --"]
                summary_data = {}
                
                for q in assigned_questions:
                    chapter = q["chapter"]
                    year = q["year"]
                    
                    if chapter not in summary_data:
                        summary_data[chapter] = {}
                    if year not in summary_data[chapter]:
                        summary_data[chapter][year] = 0
                    summary_data[chapter][year] += 1

                # Display summary
                def chapter_sort_key(chapter_name):
                    match = re.search(r'(\d+)', chapter_name)
                    return int(match.group(1)) if match else float('inf')
                
                for chapter in sorted(summary_data.keys(), key=chapter_sort_key):
                    with st.expander(f"{chapter} ({sum(summary_data[chapter].values())} questions)"):
                        for year, count in sorted(summary_data[chapter].items()):
                            st.write(f"• {year}: {count} questions")


# ---------------- UTILITY FUNCTIONS ----------------
def reset_assignments():
    """Reset all chapter assignments"""
    if 'questions' in st.session_state:
        for q in st.session_state.questions:
            q["chapter"] = None
        st.success("All assignments reset!")
        st.rerun()


# ---------------- MAIN APP ----------------
if __name__ == "__main__":
    # Add reset button in sidebar
    with st.sidebar:
        st.write("---")
        if st.button("🔄 Reset All Assignments", type="secondary"):
            reset_assignments()
        
        if 'questions' in st.session_state:
            st.write("---")
            st.write("### 📊 Quick Stats")
            total = len(st.session_state.questions)
            assigned = len([q for q in st.session_state.questions 
                          if q["chapter"] and q["chapter"] != "-- Select Chapter --"])
            st.metric("Total Questions", total)
            st.metric("Assigned", assigned)
            st.metric("Remaining", total - assigned)

    main()