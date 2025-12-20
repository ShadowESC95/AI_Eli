```python
import os
from PyPDF2 import PdfReader
from pdfminer.high_level import extract_text
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - 
%(message)s')

def process_pdf(file_path):
    try:
        # Using PyPDF2 for extraction
        reader = PdfReader(file_path)
        num_pages = len(reader.pages)
        text = "".join([page.extract_text() or "" for page in reader.pages])

        if not text:
            # Fallback to pdfminer.six if no text was extracted by PyPDF2
            logging.warning(f"PyPDF2 failed to extract text from {file_path}. 
Attempting with pdfminer.")
            text = extract_text(file_path)

        return text, num_pages

    except Exception as e:
        logging.error(f"Error processing file {file_path}: {e}")
        return None, 0


def main():
    directory = "/home/jay/Desktop/AI_Eli/data/input"

    if not os.path.exists(directory):
        logging.critical("Directory does not exist.")
        return
    
    files = [f for f in os.listdir(directory) if f.endswith('.pdf')]
    
    if not files:
        logging.warning(f"No PDF files found in {directory}")
        return
    
    for file_name in files:
        file_path = os.path.join(directory, file_name)
        
        text, num_pages = process_pdf(file_path)

        if text is None or num_pages == 0:
            continue

        logging.info(f"File: {file_name} with {num_pages} pages")
        logging.debug(f"Extracted Text Preview:\n{repr(text[:100])}\n")  # Use repr to 
show non-printable characters


if __name__ == "__main__":
    main()
```
