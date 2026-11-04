import os
import csv
import glob
from docling.document_converter import DocumentConverter

def process_pdfs_to_csv(input_dir, output_csv_path):
    # Initialize the Docling document converter
    converter = DocumentConverter()
    
    # Define the CSV headers
    headers = ["file_name", "markdown_content"]
    
    # Open the CSV file for writing text layout rows safely
    with open(output_csv_path, mode="w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        
        # Find all PDF files in the specified directory
        pdf_pattern = os.path.join(input_dir, "*.pdf")
        pdf_files = glob.glob(pdf_pattern)
        
        if not pdf_files:
            print(f"No PDF files found in directory: {input_dir}")
            return
            
        print(f"Found {len(pdf_files)} PDFs to process.")
        
        for pdf_path in pdf_files:
            file_name = os.path.basename(pdf_path)
            print(f"Processing: {file_name}...")
            
            try:
                # Convert the PDF using Docling
                result = converter.convert(pdf_path)
                
                # Export structural data to Markdown text (ideal for structured CSV blocks)
                md_content = result.document.export_to_markdown()
                
                # Write file tracking metrics and data rows
                writer.writerow({
                    "file_name": file_name,
                    "markdown_content": md_content
                })
                
            except Exception as e:
                print(f"Error parsing {file_name}: {e}")
                writer.writerow({
                    "file_name": file_name,
                    "markdown_content": f"Extraction failed: {str(e)}"
                })
                
    print(f"All datasets successfully saved to {output_csv_path}")

# Run the batch conversion
pdf_folder_path = "./my_pdf_directory"  # Replace with your actual directory path
destination_csv = "extracted_data.csv"

process_pdfs_to_csv(pdf_folder_path, destination_csv)
