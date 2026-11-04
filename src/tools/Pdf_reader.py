from docling.document_converter import DocumentConverter

converter = DocumentConverter()
result = converter.convert(r"C:\Users\USER\Desktop\drive-download-20261030T104538Z-1-001\ACCURIS Mini Lab Balances W4000.pdf")

# Output the document structure as Markdown
print(result.document.export_to_html())
