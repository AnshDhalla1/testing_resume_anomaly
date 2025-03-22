import os
import subprocess
from docling.document_converter import DocumentConverter

def convert_doc_to_pdf(doc_path, output_dir="output_pdfs"):

    if not os.path.exists(doc_path):
        raise FileNotFoundError(f"Input file not found: {doc_path}")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    doc_name = os.path.basename(doc_path)
    
    if doc_name.endswith(".doc"):
        pdf_name = doc_name.replace(".doc", ".pdf")
    elif doc_name.endswith(".docx"):
        pdf_name = doc_name.replace(".docx", ".pdf")
    else:
        raise ValueError(f"Unsupported file type: {doc_name}. Expected .doc or .docx")

    pdf_path = os.path.join(output_dir, pdf_name)

    if not os.path.exists(pdf_path):   
        try:
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf", doc_path, "--outdir", output_dir],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            print(f"LibreOffice output: {result.stdout}")
            if result.stderr:
                print(f"LibreOffice warnings/errors: {result.stderr}")
        except subprocess.CalledProcessError as e:
            raise FileNotFoundError(f"Conversion failed: {e.stderr}")

    if os.path.exists(pdf_path):
        print(f"Conversion successful: {pdf_path}")
        return pdf_path
    else:
        raise FileNotFoundError(f"Failed to convert {doc_path} to .pdf")

def extract_text_and_tables(doc_path, output_dir="output_pdfs"):
    pdf_path = convert_doc_to_pdf(doc_path, output_dir)
    try:
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        parsed_data = result.document.export_to_markdown()
        return parsed_data
    except Exception as e:
        print(f"Error during extraction: {str(e)}")
        raise
