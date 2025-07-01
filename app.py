import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import sqlite3
import os
import webbrowser
import csv
import datetime
from urllib.parse import quote
import threading # For running LLM calls in a separate thread to keep UI responsive
import re # For simple keyword extraction

# --- Attempt to import optional libraries ---
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("ReportLab not found. PDF export will be disabled. Install with 'pip install reportlab'")

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    print("PyPDF2 not found. PDF import functionality will be limited. Install with 'pip install PyPDF2'")

# --- Gemini AI Integration ---
import base64 # base64 is a standard library, no need for try-except here
try:
    from Crypto.Cipher import AES # Import AES for decryption
    AES_AVAILABLE = True
except ImportError:
    AES_AVAILABLE = False
    print("PyCryptodome library not found. Secure API key loading will be disabled. Install with 'pip install pycryptodome'")

try:
    import google.generativeai as genai
    GEMINI_API_KEY_LOADED = False # Flag to track if API key was loaded successfully
    if AES_AVAILABLE:
        try:
            # Key for AES encryption (must be 16 bytes for AES-128, 24 for AES-192, 32 for AES-256)
            # This secret must match the one used in encrypt_key.py
            SECRET_KEY = b'mysecretaeskey12'

            def unpad(s): return s.rstrip(b' ') # Define unpad function

            def load_encrypted_api_key():
                with open("encrypted_key.txt", "r") as f:
                    encrypted = base64.b64decode(f.read())
                cipher = AES.new(SECRET_KEY, AES.MODE_ECB)
                decrypted = unpad(cipher.decrypt(encrypted))
                return decrypted.decode()

            gemini_api_key = load_encrypted_api_key()
            genai.configure(api_key=gemini_api_key)
            GEMINI_AVAILABLE = True
            GEMINI_API_KEY_LOADED = True
            print("Gemini AI API configured securely from encrypted_key.txt.")
        except FileNotFoundError:
            GEMINI_AVAILABLE = False
            print("encrypted_key.txt not found. Please run encrypt_key.py first.")
        except Exception as e:
            GEMINI_AVAILABLE = False
            print(f"Error loading Gemini API key from file: {e}")
    else:
        GEMINI_AVAILABLE = False
        print("PyCryptodome is not available, cannot load encrypted API key.")

except ImportError:
    GEMINI_AVAILABLE = False
    print("Google Generative AI library not found. Gemini AI features will be disabled. Install with 'pip install google-generativeai'")
except Exception as e:
    # This catches errors from genai.configure if key is invalid even if loaded from file
    GEMINI_AVAILABLE = False
    print(f"Error configuring Gemini AI: {e}. Gemini AI features will be disabled.")


def get_gemini_model():
    """Returns a configured Gemini GenerativeModel if available."""
    if not GEMINI_AVAILABLE or not GEMINI_API_KEY_LOADED:
        return None
    try:
        return genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        # Using print for console output, as messagebox might block in a thread
        print(f"Gemini AI Error: Failed to load Gemini model: {e}")
        return None

# Removed gemini_web_search as it's no longer used for direct browser opening
# The functions that previously called it will now use webbrowser directly.

def gemini_chat_response(user_query, context):
    """
    Generates a chatbot response using Gemini AI, based on user query and provided context.
    If the answer is not in context, it will suggest a web search with a special tag.
    """
    model = get_gemini_model()
    if not model:
        return "Chatbot is currently unavailable: Gemini AI not configured."

    try:
        # Prompt for Retrieval Augmented Generation (RAG)
        # Instruct the LLM to provide a web search suggestion if context is insufficient.
        prompt = f"You are a helpful assistant providing information about global energy data. " \
                 f"Answer the following question concisely based ONLY on the provided context about producers. " \
                 f"If the answer is not available in the context, respond with: " \
                 f"'I don't have that specific information in my database. You might find it by searching online. [WEB_SEARCH_SUGGESTION: {user_query} global energy]' " \
                 f"Otherwise, provide the answer directly from the context. " \
                 f"\n\nContext:\n{context}\n\nQuestion: {user_query}"

        chat = model.start_chat(history=[])
        response = chat.send_message(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini AI Error in chatbot response: {e}")
        return "I'm sorry, I encountered an error while processing your request. Please try again."


# --- Database Setup ---
DB_FILE = "global_energy_db.sqlite"

def create_db_and_table():
    """Creates the database file and the 'producers' table if it doesn't exist."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS producers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact TEXT,
                address TEXT,
                products TEXT,
                category TEXT
            )
        """)
        conn.commit()
    except sqlite3.Error as e:
        messagebox.showerror("Database Error", f"Failed to create database/tables: {e}")
    finally:
        if conn:
            conn.close()

# Ensure DB and tables exist on startup
create_db_and_table()

# Connect to database (This connection will be used throughout the app)
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# --- Functions for Producer CRUD Operations ---

def clear_producer_fields():
    """Clears all input entry fields for producers."""
    entry_name.delete(0, tk.END)
    entry_contact.delete(0, tk.END)
    entry_address.delete(0, tk.END)
    entry_products.delete(0, tk.END)
    entry_category.delete(0, tk.END)
    for item in tree_producers.selection():
        tree_producers.selection_remove(item)

def load_producers_data(search_term="", search_by=""):
    """
    Loads data from the 'producers' table into the Treeview,
    with optional search filtering.
    """
    for item in tree_producers.get_children():
        tree_producers.delete(item)

    query = "SELECT * FROM producers"
    params = []

    if search_term and search_by:
        if search_by == "Name":
            query += " WHERE name LIKE ?"
            params.append(f"%{search_term}%")
        elif search_by == "Category":
            query += " WHERE category LIKE ?"
            params.append(f"%{search_term}%")

    try:
        cursor.execute(query, params)
        for row in cursor.fetchall():
            tree_producers.insert("", "end", values=row)
    except sqlite3.Error as e:
        messagebox.showerror("Database Error", f"Failed to load producer data: {e}")

def producer_exists(name):
    cursor.execute("SELECT 1 FROM producers WHERE name = ?", (name,))
    return cursor.fetchone() is not None

def add_producer():
    """Adds a new producer record to the database with optional AI suggestions."""
    name = entry_name.get().strip()
    contact = entry_contact.get().strip()
    address = entry_address.get().strip()
    products = entry_products.get().strip()
    category = entry_category.get().strip()

    if not name:
        messagebox.showwarning("Input Error", "Producer Name cannot be empty.")
        return

    if producer_exists(name):
        messagebox.showwarning("Duplicate Entry", f"A producer with the name '{name}' already exists.")
        return

    # AI suggestion for category/products
    if GEMINI_AVAILABLE and (not category or not products):
        model = get_gemini_model()
        if model:
            try:
                # Prompt to get suggestions for category and products based on name/contact/address
                ai_prompt = f"Given the producer name '{name}', contact '{contact}', and address '{address}', " \
                            f"suggest a suitable category (e.g., 'Solar', 'Wind', 'Hydro', 'Biofuel', 'Geothermal', 'Nuclear', 'Fossil Fuel') " \
                            f"and representative products. Format as 'Category: [category], Products: [product1, product2]'. If no information is sufficient, state 'Category: Unknown, Products: None'."
                response = model.start_chat(history=[]).send_message(ai_prompt)
                suggestion_text = response.text.strip()
                print(f"AI Suggestion: {suggestion_text}") # For debugging

                # Parse the suggestion
                suggested_category = "Unknown"
                suggested_products = "None"

                if "Category:" in suggestion_text and "Products:" in suggestion_text:
                    parts = suggestion_text.split("Category:")
                    if len(parts) > 1:
                        category_part = parts[1].split("Products:")[0].strip().replace(",", "")
                        suggested_category = category_part.strip()

                        products_part = suggestion_text.split("Products:")[1].strip()
                        suggested_products = products_part.strip()


                if suggested_category != "Unknown" or suggested_products != "None":
                    if messagebox.askyesno("AI Suggestion",
                                            f"AI suggests:\nCategory: {suggested_category}\nProducts: {suggested_products}\n\nDo you want to apply these suggestions?"):
                        if not category and suggested_category != "Unknown":
                            category = suggested_category
                        if not products and suggested_products != "None":
                            products = suggested_products

            except Exception as e:
                messagebox.showwarning("AI Suggestion Error", f"Failed to get AI suggestions: {e}")

    try:
        cursor.execute("INSERT INTO producers (name, contact, address, products, category) VALUES (?, ?, ?, ?, ?)",
                       (name, contact, address, products, category))
        conn.commit()
        messagebox.showinfo("Success", "Producer added successfully!")
        clear_producer_fields()
        load_producers_data()
    except sqlite3.Error as e:
        messagebox.showerror("Database Error", f"Failed to add producer: {e}")

def update_producer():
    """Updates the selected producer record in the database."""
    selected_item = tree_producers.selection()
    if not selected_item:
        messagebox.showwarning("Selection Error", "Please select a producer to update.")
        return

    producer_id = tree_producers.item(selected_item, 'values')[0]

    name = entry_name.get().strip()
    contact = entry_contact.get().strip()
    address = entry_address.get().strip()
    products = entry_products.get().strip()
    category = entry_category.get().strip()

    if not name:
        messagebox.showwarning("Input Error", "Producer Name cannot be empty.")
        return

    original_name = tree_producers.item(selected_item, 'values')[1]
    if name != original_name and producer_exists(name):
        messagebox.showwarning("Duplicate Entry", f"A producer with the name '{name}' already exists. Cannot update to a duplicate name.")
        return

    # Optional: AI validation/enrichment for updates
    if GEMINI_AVAILABLE:
        model = get_gemini_model()
        if model:
            try:
                # Simple AI validation/suggestion for updated fields
                ai_prompt = f"Review the following producer data for potential issues or suggestions: " \
                            f"Name: {name}, Contact: {contact}, Address: {address}, Products: {products}, Category: {category}. " \
                            f"Provide a brief assessment or suggest improvements if any. If no issues, state 'No issues found'."
                response = model.start_chat(history=[]).send_message(ai_prompt)
                ai_assessment = response.text.strip()
                if ai_assessment and ai_assessment != "No issues found.":
                    messagebox.showinfo("AI Assessment", f"AI reviewed the update:\n\n{ai_assessment}")
            except Exception as e:
                messagebox.showwarning("AI Assessment Error", f"Failed to get AI assessment: {e}")

    try:
        cursor.execute("UPDATE producers SET name=?, contact=?, address=?, products=?, category=? WHERE id=?",
                       (name, contact, address, products, category, producer_id))
        conn.commit()
        messagebox.showinfo("Success", "Producer updated successfully!")
        clear_producer_fields()
        load_producers_data()
    except sqlite3.Error as e:
        messagebox.showerror("Database Error", f"Failed to update producer: {e}")

def delete_producer():
    """Deletes the selected producer record from the database with AI confirmation."""
    selected_item = tree_producers.selection()
    print(f"Delete function - selected_item: {selected_item}") # Debugging print
    if not selected_item:
        messagebox.showwarning("Selection Error", "Please select a producer to delete.")
        return

    producer_id = tree_producers.item(selected_item, 'values')[0]
    producer_name = tree_producers.item(selected_item, 'values')[1]

    ai_confirmation_message = ""
    if GEMINI_AVAILABLE:
        model = get_gemini_model()
        if model:
            try:
                # Ask AI for a more 'intelligent' confirmation prompt
                ai_prompt = f"Generate a brief confirmation message for deleting the producer '{producer_name}' (ID: {producer_id}). " \
                            f"Emphasize that the action is irreversible. Keep it concise, around one sentence."
                response = model.start_chat(history=[]).send_message(ai_prompt)
                ai_confirmation_message = response.text.strip()
            except Exception as e:
                print(f"AI confirmation prompt failed: {e}") # Log error, proceed with default confirmation
                ai_confirmation_message = ""

    if not ai_confirmation_message:
        ai_confirmation_message = f"Are you sure you want to delete producer '{producer_name}' (ID: {producer_id})?"

    if messagebox.askyesno("Confirm Delete", ai_confirmation_message + "\n\nThis action cannot be undone."):
        try:
            cursor.execute("DELETE FROM producers WHERE id=?", (producer_id,))
            conn.commit()
            messagebox.showinfo("Success", "Producer deleted successfully!")
            clear_producer_fields()
            load_producers_data()
        except sqlite3.Error as e:
            messagebox.showerror("Database Error", f"Failed to delete producer: {e}")


def on_producer_tree_select(event):
    """Populates input fields when a row in the Producer Treeview is selected."""
    selected_item = tree_producers.selection()
    print(f"Treeview selection event - selected_item: {selected_item}") # Debugging print
    if selected_item:
        values = tree_producers.item(selected_item, 'values')
        # IMPORTANT: Removed clear_producer_fields() from here to prevent immediate deselection
        entry_name.delete(0, tk.END)
        entry_contact.delete(0, tk.END)
        entry_address.delete(0, tk.END)
        entry_products.delete(0, tk.END)
        entry_category.delete(0, tk.END)
        entry_name.insert(0, values[1])
        entry_contact.insert(0, values[2])
        entry_address.insert(0, values[3])
        entry_products.insert(0, values[4])
        entry_category.insert(0, values[5])

def search_producers():
    """Triggers data loading with search filters for producers."""
    search_term = entry_search.get().strip()
    search_by = search_by_combobox.get()
    load_producers_data(search_term, search_by)

def show_all_producers():
    """Resets search fields and loads all producer data."""
    entry_search.delete(0, tk.END)
    search_by_combobox.set("Name")
    load_producers_data()

def web_search_producer():
    """Opens a Google search for the selected producer's product name."""
    selected_item = tree_producers.selection()
    if not selected_item:
        messagebox.showwarning("Selection Error", "Please select a producer to perform a web search.")
        return

    product_name = tree_producers.item(selected_item, 'values')[4]

    if product_name:
        search_query = f"{product_name} energy product"
        # Using webbrowser for this specific action as it's a direct external link
        webbrowser.open_new_tab(f"https://www.google.com/search?q={quote(search_query)}")
    else:
        messagebox.showinfo("Web Search", "No product name found for web search for the selected producer.")

def web_search_product_keyword():
    """
    Performs a general web search for companies producing a given product keyword
    by opening a new browser tab with a Google search.
    """
    keyword = entry_web_search_keyword.get().strip()
    if not keyword:
        messagebox.showwarning("Input Error", "Please enter a keyword for product web search.")
        return

    search_query = f"companies producing {keyword} energy"
    webbrowser.open_new_tab(f"https://www.google.com/search?q={quote(search_query)}")
    messagebox.showinfo("Web Search Initiated", f"Opening web search for '{search_query}' in your browser.")


def export_to_csv():
    """Exports current Producer Treeview data to a CSV file."""
    filepath = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    if not filepath:
        return

    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["ID", "Name", "Contact", "Address", "Products", "Category"])
            cursor.execute("SELECT * FROM producers")
            for row in cursor.fetchall():
                writer.writerow(row)
        messagebox.showinfo("Export Success", f"Producer data successfully exported to {filepath}")
    except Exception as e:
        messagebox.showerror("Export Error", f"Failed to export producer data to CSV: {e}")

def export_to_pdf():
    """Exports current Producer Treeview data to a PDF file using ReportLab."""
    if not REPORTLAB_AVAILABLE:
        messagebox.showerror("Error", "ReportLab library not found. PDF export is disabled. Please install it using 'pip install reportlab'.")
        return

    filepath = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
    )
    if not filepath:
        return

    try:
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph("Global Energy Producers Database", styles['h1']))
        elements.append(Spacer(1, 0.2 * inch))

        data = [["ID", "Name", "Contact", "Address", "Products", "Category"]]
        cursor.execute("SELECT * FROM producers")
        for row in cursor.fetchall():
            data.append(list(row))

        table = Table(data)

        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.2 * inch))

        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        elements.append(Paragraph(f"Exported on: {current_time}", styles['Normal']))

        doc.build(elements)
        messagebox.showinfo("Export Success", f"Producer data successfully exported to {filepath}")

    except Exception as e:
        messagebox.showerror("Export Error", f"Failed to export producer data to PDF: {e}")

# --- Import from File Functions ---
def import_producers_from_file():
    """
    Imports data from a selected CSV or TXT file into the 'producers' table.
    For TXT files, assumes comma-separated values.
    Checks for and skips duplicate producer names.
    """
    filepath = filedialog.askopenfilename(
        title="Select File to Import (Producers)",
        filetypes=[("CSV files", "*.csv"), ("Text files", "*.txt"), ("All files", "*.*")]
    )
    if not filepath:
        return

    if not (filepath.lower().endswith(".csv") or filepath.lower().endswith(".txt")):
        messagebox.showwarning("Unsupported Format", "Only CSV and TXT files are supported for data import.")
        return

    try:
        with open(filepath, 'r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            header = next(reader)

            header_map = {col.strip().lower(): i for i, col in enumerate(header)}

            name_idx = header_map.get('name')
            contact_idx = header_map.get('contact')
            address_idx = header_map.get('address')
            products_idx = header_map.get('products')
            category_idx = header_map.get('category')

            if None in [name_idx, contact_idx, address_idx, products_idx, category_idx]:
                messagebox.showerror("Import Error", "CSV/TXT header must contain 'Name', 'Contact', 'Address', 'Products', and 'Category' columns.")
                return

            imported_count = 0
            skipped_duplicates = 0
            skipped_malformed = 0

            for i, row in enumerate(reader):
                if len(row) > max(name_idx, contact_idx, address_idx, products_idx, category_idx):
                    name = row[name_idx].strip()
                    contact = row[contact_idx].strip()
                    address = row[address_idx].strip()
                    products = row[products_idx].strip()
                    category = row[category_idx].strip()

                    if producer_exists(name):
                        skipped_duplicates += 1
                    else:
                        cursor.execute("INSERT INTO producers (name, contact, address, products, category) VALUES (?, ?, ?, ?, ?)",
                                       (name, contact, address, products, category))
                        imported_count += 1
                else:
                    skipped_malformed += 1
        conn.commit()

        summary_message = f"Producer import complete:\n" \
                          f"  - Successfully imported: {imported_count} records.\n" \
                          f"  - Skipped (Duplicates): {skipped_duplicates} records.\n" \
                          f"  - Skipped (Malformed rows): {skipped_malformed} records."
        messagebox.showinfo("Import Summary", summary_message)

        load_producers_data()
    except Exception as e:
        conn.rollback()
        messagebox.showerror("Import Error", f"Failed to import producer file: {e}")

# --- PDF Search Functionality ---

def extract_text_from_pdf(filepath):
    """Extracts text from a given PDF file."""
    if not PYPDF2_AVAILABLE:
        messagebox.showerror("Error", "PyPDF2 library not found. PDF text extraction is disabled.")
        return None
    text = ""
    try:
        with open(filepath, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text += page.extract_text() or ""
        return text
    except Exception as e:
        messagebox.showerror("PDF Error", f"Failed to read PDF: {e}")
        return None

def identify_product_keywords(text):
    """A very basic function to identify potential product-related keywords from text."""
    potential_keywords = []
    lines = text.split('\n')
    for line in lines:
        if "Model:" in line or "Product:" in line or "Type:" in line:
            parts = line.split(':')
            if len(parts) > 1:
                potential_keywords.append(parts[1].strip().split(',')[0].split('(')[0].strip())

        words = line.split()
        for word in words:
            if len(word) > 2 and word[0].isupper() and word.lower() not in ["the", "a", "an", "and", "or", "for", "with", "from", "to", "in"]:
                potential_keywords.append(word)

    filtered_keywords = list(set([kw.strip(".,:;'\"") for kw in potential_keywords if kw and len(kw) > 2]))
    return filtered_keywords[:20]

def search_for_suppliers(product_keyword):
    """Opens a Google search for suppliers of the given product keyword."""
    if product_keyword:
        search_query = f"{product_keyword} energy suppliers"
        # Keeping this as a direct webbrowser open as it's an immediate external link
        webbrowser.open_new_tab(f"https://www.google.com/search?q={quote(search_query)}")
    else:
        messagebox.showinfo("Web Search", "No product keyword provided for supplier search.")

def upload_pdf_and_search():
    """Handles PDF upload, extracts text, identifies keywords, and prompts user to search."""
    if not PYPDF2_AVAILABLE:
        messagebox.showerror("Error", "PyPDF2 library not found. PDF upload and search is disabled.")
        return

    filepath = filedialog.askopenfilename(
        title="Select PDF File for Product Search",
        filetypes=[("PDF files", "*.pdf")]
    )
    if not filepath:
        return

    extracted_text = extract_text_from_pdf(filepath)
    if extracted_text:
        potential_product_keywords = identify_product_keywords(extracted_text)

        if potential_product_keywords:
            keyword_dialog = tk.Toplevel(root)
            keyword_dialog.title("Confirm Product Keyword for Supplier Search")
            keyword_dialog.transient(root)
            keyword_dialog.grab_set()

            tk.Label(keyword_dialog, text="Identified potential keywords (select or refine):").pack(padx=20, pady=10)

            keyword_var = tk.StringVar(keyword_dialog)
            keyword_var.set(potential_product_keywords[0])

            keyword_combobox = ttk.Combobox(keyword_dialog, textvariable=keyword_var, values=potential_product_keywords, width=50)
            keyword_combobox.pack(padx=20, pady=5)

            tk.Label(keyword_dialog, text="Or enter a custom keyword:").pack(padx=20, pady=5)
            custom_keyword_entry = tk.Entry(keyword_dialog, width=50)
            custom_keyword_entry.pack(padx=20, pady=5)

            def perform_search_from_dialog():
                final_keyword = custom_keyword_entry.get().strip() or keyword_var.get().strip()
                if final_keyword:
                    search_for_suppliers(final_keyword)
                else:
                    messagebox.showwarning("Input Error", "Please enter or select a keyword to search.")
                keyword_dialog.destroy()

            tk.Button(keyword_dialog, text="Search Suppliers on Web", command=perform_search_from_dialog).pack(pady=10)

            keyword_dialog.update_idletasks()
            x = root.winfo_x() + (root.winfo_width() // 2) - (keyword_dialog.winfo_width() // 2)
            y = root.winfo_y() + (root.winfo_height() // 2) - (keyword_dialog.winfo_height() // 2)
            keyword_dialog.geometry(f"+{x}+{y}")
        else:
            messagebox.showinfo("Product Search", "Could not identify clear product keywords from the PDF text.")
    else:
        messagebox.showerror("PDF Processing", "No text could be extracted from the PDF.")

def upload_and_scan_file_for_energy_products():
    """
    Scans any supported file for keywords and performs an AI-powered search online.
    """
    file_path = filedialog.askopenfilename(
        title="Select File to Scan for Energy Products",
        filetypes=[("Supported Files", "*.pdf *.txt *.csv"), ("All files", "*.*")]
    )
    if not file_path:
        return

    extracted_text = ""
    try:
        if file_path.lower().endswith(".pdf"):
            if not PYPDF2_AVAILABLE:
                messagebox.showerror("Missing Library", "PyPDF2 is required to read PDF files.")
                return
            extracted_text = extract_text_from_pdf(file_path)
        elif file_path.lower().endswith((".txt", ".csv")):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                extracted_text = f.read()
        else:
            messagebox.showwarning("Unsupported Format", f"File type for '{os.path.basename(file_path)}' is not supported for keyword scanning.")
            return
    except Exception as e:
        messagebox.showerror("File Error", f"Error reading file: {e}")
        return

    if not extracted_text.strip():
        messagebox.showinfo("No Content", "No text could be extracted from the file.")
        return

    potential_keywords = identify_product_keywords(extracted_text)
    if not potential_keywords:
        messagebox.showinfo("No Keywords", "No relevant global energy keywords were found.")
        return

    keyword_dialog = tk.Toplevel(root)
    keyword_dialog.title("Select Keyword to Search (Google Search)") # Updated title
    keyword_dialog.transient(root)
    keyword_dialog.grab_set()
    keyword_dialog.geometry("400x200")

    tk.Label(keyword_dialog, text="Select or refine an energy-related keyword:").pack(pady=10)
    keyword_var = tk.StringVar(keyword_dialog)
    keyword_var.set(potential_keywords[0])
    keyword_dropdown = ttk.Combobox(keyword_dialog, textvariable=keyword_var, values=potential_keywords, width=45)
    keyword_dropdown.pack(pady=5, padx=10)

    tk.Label(keyword_dialog, text="Or enter a custom keyword:").pack(pady=5)
    entry_custom_keyword = tk.Entry(keyword_dialog, width=48)
    entry_custom_keyword.pack(pady=5, padx=10)

    def confirm_and_search():
        final_keyword = entry_custom_keyword.get().strip() or keyword_var.get().strip()
        if final_keyword:
            search_query = f"{final_keyword} global energy product suppliers" # Refined query for AI search
            webbrowser.open_new_tab(f"https://www.google.com/search?q={quote(search_query)}")
            messagebox.showinfo("Web Search Initiated", f"Opening web search for '{search_query}' in your browser.", parent=keyword_dialog)
            keyword_dialog.destroy()
        else:
            messagebox.showwarning("Input Required", "Please enter or select a keyword to search.", parent=keyword_dialog)

    tk.Button(keyword_dialog, text="Search Online (Google Search)", command=confirm_and_search).pack(pady=15) # Updated button text

    keyword_dialog.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() // 2) - (keyword_dialog.winfo_width() // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (keyword_dialog.winfo_height() // 2)
    keyword_dialog.geometry(f"+{x}+{y}")


# --- AI Database Query Function ---
def ai_database_query():
    """Allows user to query the database using natural language via Gemini AI."""
    model = get_gemini_model()
    if not model:
        messagebox.showerror("Gemini AI Error", "Gemini AI library not available or configured.")
        return

    query_dialog = tk.Toplevel(root)
    query_dialog.title("AI Database Query")
    query_dialog.transient(root)
    query_dialog.grab_set()
    query_dialog.geometry("600x400")

    tk.Label(query_dialog, text="Enter your natural language query about producers:").pack(padx=20, pady=10)
    query_entry = tk.Entry(query_dialog, width=80)
    query_entry.pack(padx=20, pady=5)

    result_text = tk.Text(query_dialog, height=10, width=75, state='disabled', wrap='word')
    result_text.pack(padx=20, pady=10)
    result_scroll = tk.Scrollbar(query_dialog, command=result_text.yview)
    result_scroll.pack(side="right", fill="y")
    result_text.config(yscrollcommand=result_scroll.set)

    # Define table schema for AI
    db_schema = {
        "producers": {
            "columns": ["id", "name", "contact", "address", "products", "category"],
            "description": "Stores information about global energy producers including their name, contact details, address, products they offer, and their energy category (e.g., Solar, Wind, Hydro, Biofuel, Geothermal, Nuclear, Fossil Fuel)."
        }
    }

    def execute_ai_query():
        user_query = query_entry.get().strip()
        if not user_query:
            messagebox.showwarning("Input Error", "Please enter a query.")
            return

        result_text.config(state='normal')
        result_text.delete(1.0, tk.END)
        result_text.insert(tk.END, "Thinking...\n")
        result_text.config(state='disabled')
        query_dialog.update_idletasks()

        def run_query_in_thread():
            try:
                # Step 1: Use AI to generate SQL
                prompt = f"Given the SQLite database schema:\n\n" \
                         f"CREATE TABLE producers (\n" \
                         f"    id INTEGER PRIMARY KEY AUTOINCREMENT,\n" \
                         f"    name TEXT NOT NULL UNIQUE,\n" \
                         f"    contact TEXT,\n" \
                         f"    address TEXT,\n" \
                         f"    products TEXT,\n" \
                         f"    category TEXT\n" \
                         f");\n\n" \
                         f"Table description: {db_schema['producers']['description']}\n\n" \
                         f"Convert the following natural language query into a valid SQLite SQL SELECT statement. " \
                         f"Only provide the SQL query, nothing else. Do not add any backticks or extra formatting. " \
                         f"If the query cannot be translated to a SELECT statement, respond with 'INVALID_QUERY'.\n\n" \
                         f"Natural language query: '{user_query}'\n\nSQL:"

                response = model.start_chat(history=[]).send_message(prompt)
                sql_query_raw = response.text.strip()
                print(f"Generated SQL (raw): {sql_query_raw}") # For debugging

                if sql_query_raw.upper().startswith("SELECT"):
                    generated_sql = sql_query_raw
                else:
                    generated_sql = "INVALID_QUERY"

                if generated_sql == "INVALID_QUERY":
                    root.after(0, lambda: (
                        result_text.config(state='normal'),
                        result_text.delete(1.0, tk.END),
                        result_text.insert(tk.END, "AI could not generate a valid SQL SELECT query from your input or it's not a SELECT query.\n"),
                        result_text.config(state='disabled')
                    ))
                    return

                # Step 2: Execute SQL query
                temp_conn = sqlite3.connect(DB_FILE) # Use a new connection for the thread
                temp_cursor = temp_conn.cursor()
                temp_cursor.execute(generated_sql)
                rows = temp_cursor.fetchall()
                columns = [description[0] for description in temp_cursor.description]
                temp_conn.close()

                root.after(0, lambda: (
                    result_text.config(state='normal'),
                    result_text.delete(1.0, tk.END),
                    result_text.insert(tk.END, "Query Results:\n"),
                    result_text.insert(tk.END, "-" * 50 + "\n"),
                    result_text.insert(tk.END, "\t".join(columns) + "\n"),
                    result_text.insert(tk.END, "-" * 50 + "\n"),
                    *(result_text.insert(tk.END, "\t".join(map(str, row)) + "\n") for row in rows),
                    result_text.config(state='disabled')
                ) if rows else (
                    result_text.config(state='normal'),
                    result_text.delete(1.0, tk.END),
                    result_text.insert(tk.END, "No results found for your query.\n"),
                    result_text.config(state='disabled')
                ))

            except sqlite3.Error as se:
                root.after(0, lambda: (
                    result_text.config(state='normal'),
                    result_text.delete(1.0, tk.END),
                    result_text.insert(tk.END, f"Database Error executing SQL: {se}\nGenerated SQL: {generated_sql}\n"),
                    result_text.config(state='disabled')
                ))
            except Exception as e:
                root.after(0, lambda: (
                    result_text.config(state='normal'),
                    result_text.delete(1.0, tk.END),
                    result_text.insert(tk.END, f"AI/Execution Error: {e}\n"),
                    result_text.config(state='disabled')
                ))

        # Run the AI query in a separate thread to prevent UI freezing
        threading.Thread(target=run_query_in_thread).start()


    tk.Button(query_dialog, text="Execute AI Query", command=execute_ai_query).pack(pady=10)

    query_dialog.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() // 2) - (query_dialog.winfo_width() // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (query_dialog.winfo_height() // 2)
    query_dialog.geometry(f"+{x}+{y}")


# --- Chatbot Window Function ---
def open_chatbot_window():
    """Opens a new Toplevel window for the chatbot interface."""
    chatbot_window = tk.Toplevel(root)
    chatbot_window.title("GlobalEnergyDB Chatbot")
    chatbot_window.geometry("500x600")
    chatbot_window.transient(root) # Make it appear on top of the main window
    chatbot_window.grab_set() # Make it modal (user must interact with it)

    # Chat display area
    chat_display = tk.Text(chatbot_window, wrap='word', state='disabled', font=("Arial", 10), bd=2, relief="groove")
    chat_display.pack(padx=10, pady=10, fill="both", expand=True)

    # Scrollbar for chat display
    chat_scrollbar = tk.Scrollbar(chat_display, command=chat_display.yview)
    chat_display.config(yscrollcommand=chat_scrollbar.set)
    chat_scrollbar.pack(side="right", fill="y")

    # Input frame
    input_frame = tk.Frame(chatbot_window)
    input_frame.pack(padx=10, pady=(0, 10), fill="x")

    user_input = tk.Entry(input_frame, font=("Arial", 10), relief="solid", bd=1)
    user_input.pack(side="left", fill="x", expand=True, padx=(0, 5))

    send_button = tk.Button(input_frame, text="Send", font=("Arial", 10, "bold"), bg="#4CAF50", fg="white")
    send_button.pack(side="right")

    # Loading indicator
    loading_label = tk.Label(chatbot_window, text="AI is thinking...", fg="gray", font=("Arial", 9, "italic"))
    loading_label.pack(pady=5)
    loading_label.pack_forget() # Hide initially

    def display_message(sender, message, is_link=False, link_url=None):
        chat_display.config(state='normal')
        if is_link:
            chat_display.insert(tk.END, f"{sender}: {message}\n")
            chat_display.insert(tk.END, f"🔗 {link_url}\n", "link")
            chat_display.tag_config("link", foreground="blue", underline=True)
            chat_display.tag_bind("link", "<Button-1>", lambda e: webbrowser.open_new_tab(link_url))
            chat_display.insert(tk.END, "\n") # Add extra newline after link
        else:
            chat_display.insert(tk.END, f"{sender}: {message}\n\n")
        chat_display.yview(tk.END) # Scroll to bottom
        chat_display.config(state='disabled')

    def retrieve_context(query):
        """
        Retrieves relevant context from the producers database based on keywords in the query.
        This simulates the "learning from stored data" aspect.
        """
        # Simple keyword extraction (can be enhanced with NLP libraries)
        keywords = re.findall(r'\b\w+\b', query.lower())
        # Filter out common stop words if necessary for more precise search
        stop_words = {"what", "is", "are", "tell", "me", "about", "who", "which", "show", "list", "of", "the", "a", "an", "find"}
        filtered_keywords = [word for word in keywords if word not in stop_words and len(word) > 2]

        context_data = []
        try:
            temp_conn = sqlite3.connect(DB_FILE)
            temp_cursor = temp_conn.cursor()

            # Build a dynamic query to search across relevant columns
            sql_parts = []
            params = []
            for kw in filtered_keywords:
                sql_parts.append("name LIKE ? OR products LIKE ? OR category LIKE ?")
                params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])

            if sql_parts:
                query_sql = "SELECT name, products, category FROM producers WHERE " + " OR ".join(sql_parts) + " LIMIT 5" # Limit results for concise context
                temp_cursor.execute(query_sql, params)
                rows = temp_cursor.fetchall()
                
                if rows:
                    context_data.append("Relevant producer information from the database:")
                    for row in rows:
                        # Format each relevant row into a readable string
                        context_data.append(f"- Name: {row[0]}, Products: {row[1] if row[1] else 'N/A'}, Category: {row[2] if row[2] else 'N/A'}")
                
            temp_conn.close()

        except Exception as e:
            print(f"Error fetching producer data for context: {e}")
            context_data.append("An error occurred while trying to retrieve information from the database.")

        # Always include some general information about the DB if no specific data is found
        if not context_data or len(context_data) == 0: # Ensure context_data is not empty
            context_data.append("No specific producer data found in the database for your query.")
        
        context_data.append("\nGeneral information about GlobalEnergyDB: This project aims to centralize data on global energy production, consumption, and reserves. It includes details on producers and their products (e.g., solar, wind, oil, gas).")
        
        # Conceptual placeholder for "learning from searches"
        # Removed the "Note on learning from past searches" as it's not a core function for the chatbot's direct response.

        return "\n".join(context_data)


    def send_chat_message_thread():
        query = user_input.get().strip()
        if not query:
            return

        display_message("You", query)
        user_input.delete(0, tk.END)
        loading_label.pack() # Show loading indicator
        send_button.config(state='disabled') # Disable button

        def process_chat_response():
            try:
                context = retrieve_context(query)
                print(f"Context provided to LLM:\n{context}\n---") # For debugging
                response_text = gemini_chat_response(query, context)

                # Check for web search suggestion tag
                match = re.search(r'\[WEB_SEARCH_SUGGESTION:\s*(.*?)\s*\]', response_text)
                if match:
                    suggested_query = match.group(1).strip()
                    google_url = f"https://www.google.com/search?q={quote(suggested_query)}"
                    
                    # Clean the response text by removing the tag
                    clean_response_text = response_text.replace(match.group(0), "").strip()
                    if not clean_response_text:
                        clean_response_text = f"I couldn't find a direct answer, but I've opened a web search for '{suggested_query}' for you."
                    
                    display_message("Bot", clean_response_text, is_link=True, link_url=google_url)
                    webbrowser.open_new_tab(google_url)
                else:
                    display_message("Bot", response_text)

            except Exception as e:
                display_message("Bot", f"An error occurred: {e}")
            finally:
                loading_label.pack_forget() # Hide loading indicator
                send_button.config(state='normal') # Re-enable button

        # Run the AI call in a separate thread
        threading.Thread(target=process_chat_response).start()

    send_button.config(command=send_chat_message_thread)
    user_input.bind("<Return>", lambda event: send_chat_message_thread()) # Allow Enter key to send

    # Initial bot message
    display_message("Bot", "Hello! I'm your GlobalEnergyDB chatbot. I can answer questions based on the producers data stored in this application. If I can't find it, I might suggest an online search. How can I assist you today?")

    # Center the chatbot window
    chatbot_window.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() // 2) - (chatbot_window.winfo_width() // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (chatbot_window.winfo_height() // 2)
    chatbot_window.geometry(f"+{x}+{y}")


# --- GUI Layout ---

root = tk.Tk()
root.title("Global Energy Producers Database") # Updated title
root.geometry("1200x700") # Adjusted size to accommodate new button

# Create a main frame to hold everything
main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True)

# Top frame for producers
producers_section = tk.Frame(main_frame)
producers_section.pack(fill="both", expand=True, padx=10, pady=10)

# --- Producers Section ---
input_frame_producers = tk.LabelFrame(producers_section, text="Producer Details", padx=10, pady=10)
input_frame_producers.pack(pady=10, padx=10, fill="x")

# Producer input fields...
tk.Label(input_frame_producers, text="Name:").grid(row=0, column=0, sticky="w", pady=2)
entry_name = tk.Entry(input_frame_producers, width=50)
entry_name.grid(row=0, column=1, pady=2, padx=5)
# ... other producer fields

tk.Label(input_frame_producers, text="Contact:").grid(row=1, column=0, sticky="w", pady=2)
entry_contact = tk.Entry(input_frame_producers, width=50)
entry_contact.grid(row=1, column=1, pady=2, padx=5)

tk.Label(input_frame_producers, text="Address:").grid(row=0, column=2, sticky="w", pady=2, padx=(10,0))
entry_address = tk.Entry(input_frame_producers, width=50)
entry_address.grid(row=0, column=3, pady=2, padx=5)

tk.Label(input_frame_producers, text="Products:").grid(row=1, column=2, sticky="w", pady=2, padx=(10,0))
entry_products = tk.Entry(input_frame_producers, width=50)
entry_products.grid(row=1, column=3, pady=2, padx=5)

tk.Label(input_frame_producers, text="Category:").grid(row=2, column=0, sticky="w", pady=2)
entry_category = tk.Entry(input_frame_producers, width=50)
entry_category.grid(row=2, column=1, pady=2, padx=5)

button_frame_producers = tk.Frame(producers_section, padx=10)
button_frame_producers.pack(pady=5, fill="x")

# ... Producer buttons
btn_add = tk.Button(button_frame_producers, text="Add Producer", command=add_producer)
btn_add.pack(side="left", padx=5)
btn_update = tk.Button(button_frame_producers, text="Update Selected", command=update_producer)
btn_update.pack(side="left", padx=5)
btn_delete = tk.Button(button_frame_producers, text="Delete Selected (AI Confirm)", command=delete_producer) # Updated button
btn_delete.pack(side="left", padx=5)
btn_clear = tk.Button(button_frame_producers, text="Clear Fields", command=clear_producer_fields)
btn_clear.pack(side="left", padx=5)
btn_web_search_producer = tk.Button(button_frame_producers, text="Web Search Selected Producer", command=web_search_producer)
btn_web_search_producer.pack(side="left", padx=5)


search_frame_producers = tk.LabelFrame(producers_section, text="Search & Import Producers", padx=10, pady=5)
search_frame_producers.pack(pady=5, padx=10, fill="x")

# ... Producer search and import
tk.Label(search_frame_producers, text="Search:").pack(side="left", padx=(0,5))
entry_search = tk.Entry(search_frame_producers, width=40)
entry_search.pack(side="left", padx=5)
tk.Label(search_frame_producers, text="By:").pack(side="left", padx=(0,5))
search_by_combobox = ttk.Combobox(search_frame_producers, values=["Name", "Category"], state="readonly", width=10)
search_by_combobox.pack(side="left", padx=5)
btn_search = tk.Button(search_frame_producers, text="Search", command=search_producers)
btn_search.pack(side="left", padx=5)
btn_show_all = tk.Button(search_frame_producers, text="Show All", command=show_all_producers)
btn_show_all.pack(side="left", padx=5)
btn_import_producers = tk.Button(search_frame_producers, text="Import Producers from File", command=import_producers_from_file)
btn_import_producers.pack(side="left", padx=5)


tree_frame_producers = tk.Frame(producers_section)
tree_frame_producers.pack(fill="both", expand=True, padx=10, pady=10)
# ... Producer treeview setup

tree_scroll_producers = ttk.Scrollbar(tree_frame_producers)
tree_scroll_producers.pack(side="right", fill="y")
tree_producers = ttk.Treeview(tree_frame_producers, columns=("ID", "Name", "Contact", "Address", "Products", "Category"), show="headings", yscrollcommand=tree_scroll_producers.set, selectmode="browse") # Added selectmode
tree_scroll_producers.config(command=tree_producers.yview)
columns_producers = {"ID": 40, "Name": 150, "Contact": 120, "Address": 200, "Products": 150, "Category": 100}
for col, width in columns_producers.items():
    tree_producers.heading(col, text=col, anchor="w")
    tree_producers.column(col, width=width, minwidth=40, stretch=True)
tree_producers.pack(fill="both", expand=True)
tree_producers.bind("<<TreeviewSelect>>", on_producer_tree_select)


# --- Global Web and File Search Frame ---
global_search_frame = tk.LabelFrame(main_frame, text="Global Search Tools", padx=10, pady=10)
global_search_frame.pack(fill="x", padx=10, pady=(0,10))

# Web Search (now uses Gemini AI)
tk.Label(global_search_frame, text="AI Web Search Keyword:").pack(side="left", padx=(0,5))
entry_web_search_keyword = tk.Entry(global_search_frame, width=30)
entry_web_search_keyword.pack(side="left", padx=5)
btn_web_search_keyword_general = tk.Button(global_search_frame, text="Search Companies (Google)", command=web_search_product_keyword)
btn_web_search_keyword_general.pack(side="left", padx=5)

# Separator
ttk.Separator(global_search_frame, orient='vertical').pack(side='left', fill='y', padx=20)

# File Scan (now integrates AI search)
tk.Label(global_search_frame, text="File Content Search:").pack(side="left", padx=(0,5))
btn_upload_pdf = tk.Button(global_search_frame, text="Scan PDF for Suppliers", command=upload_pdf_and_search)
btn_upload_pdf.pack(side="left", padx=5)
btn_upload_and_search_any_file = tk.Button(global_search_frame, text="Scan Any File for Products (Google)", command=upload_and_scan_file_for_energy_products)
btn_upload_and_search_any_file.pack(side="left", padx=5)

# AI Database Query Button
btn_ai_db_query = tk.Button(global_search_frame, text="AI Database Query", command=ai_database_query)
btn_ai_db_query.pack(side="left", padx=(20,5)) # Add some padding from previous group

# NEW: Chatbot Button
btn_open_chatbot = tk.Button(global_search_frame, text="Open Chatbot", command=open_chatbot_window)
btn_open_chatbot.pack(side="left", padx=5)


# --- Load initial data ---
load_producers_data()

# Start GUI loop
root.mainloop()

# Close database connection when the app closes
conn.close()
