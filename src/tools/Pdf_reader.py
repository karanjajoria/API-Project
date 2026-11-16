import os
import csv
import glob
from docling.document_converter import DocumentConverter
# Native fallback fallback tool just in case it has hidden digital text layout stream
from pypdf import PdfReader 

def extract_fallback_text(pdf_path):
    """Fallback parser if the advanced AI layout engine returns nothing."""
    try:
        reader = PdfReader(pdf_path)
        text_slices = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_slices.append(text)
        return "\n".join(text_slices).strip()
    except Exception:
        return ""

def process_pdfs_to_csv(input_dir, output_csv_path):
    # Initialize Docling
    converter = DocumentConverter()
    
    headers = ["file_name", "markdown_content", "extraction_status"]
    
    with open(output_csv_path, mode="w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        
        pdf_pattern = os.path.join(input_dir, "*.pdf")
        pdf_files = glob.glob(pdf_pattern)
        
        if not pdf_files:
            print(f"No PDF files found in directory: {input_dir}")
            return
            
        print(f"Found {len(pdf_files)} PDFs to process.")
        
        for pdf_path in pdf_files:
            file_name = os.path.basename(pdf_path)
            print(f"Processing: {file_name}...")
            
            md_content = ""
            status = "Success"
            
            try:
                # 1. Main Docling Core execution
                result = converter.convert(pdf_path)
                md_content = result.document.export_to_markdown().strip()
                
                # 2. Check if Docling/RapidOCR came up completely empty
                if not md_content or "RapidOCR returned empty" in md_content:
                    print(f"  [Notice] Docling returned empty text for {file_name}. Trying quick local digital fallback...")
                    fallback_text = extract_fallback_text(pdf_path)
                    
                    if fallback_text:
                        md_content = fallback_text
                        status = "Fallback (Digital Text Layer)"
                    else:
                        md_content = "[No text or structural elements detected on image pages]"
                        status = "Empty/Scanned Page Warning"
                        
            except Exception as e:
                print(f"  [Error] Failed parsing {file_name}: {e}")
                status = f"Error: {str(e)}"
                md_content = "[Extraction Failed]"
                
            # Save the row to CSV cleanly
            writer.writerow({
                "file_name": file_name,
                "markdown_content": md_content,
                "extraction_status": status
            })
                
    print(f"\nAll datasets processed. View metrics summary inside: {output_csv_path}")

# Run within your active environment folder structure
pdf_folder_path = r"C:\Users\USER\Desktop\drive-download-20261104T070854Z-1-001"
destination_csv = "./extracted_data3.csv"

process_pdfs_to_csv(pdf_folder_path, destination_csv)
