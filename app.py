from flask import Flask, request, jsonify, render_template
from datetime import datetime
import os
import uuid
import json
import fitz  # PyMuPDF
import google.generativeai as genai
from werkzeug.utils import secure_filename

# Configure Gemini API Key
genai.configure(api_key="your gemini api key")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
CHAT_LOG_DIR = "chat_logs"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(CHAT_LOG_DIR, exist_ok=True)

# ---------- Helper: Extract Text from PDF ----------
def extract_text_from_pdf(file_path):
    try:
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        return f"Error reading PDF: {e}"


# ---------- Home Page ----------
@app.route("/")
def index():
    chat_id = request.args.get("chat_id")
    chats = []

    for filename in os.listdir(CHAT_LOG_DIR):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(CHAT_LOG_DIR, filename)) as f:
                    data = json.load(f)
                    chats.append({"id": data["id"], "title": data["title"], "timestamp": data["timestamp"]})
            except (json.JSONDecodeError, KeyError):
                # Skip corrupted files
                continue

    # Sort chats by timestamp (newest first)
    chats.sort(key=lambda x: x["timestamp"], reverse=True)

    messages = []
    if chat_id:
        path = os.path.join(CHAT_LOG_DIR, f"{chat_id}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    messages = json.load(f)["messages"]
            except (json.JSONDecodeError, KeyError):
                messages = []

    return render_template("index.html", chats=chats, messages=messages, current_chat_id=chat_id)


# ---------- Chat Route ----------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message")
    chat_id = data.get("chat_id") or str(uuid.uuid4())

    if not user_message or not user_message.strip():
        return jsonify({"error": "Message cannot be empty"}), 400

    filepath = os.path.join(CHAT_LOG_DIR, f"{chat_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                chat_data = json.load(f)
        except (json.JSONDecodeError, KeyError):
            # If file is corrupted, create new chat data
            chat_data = {
                "id": chat_id,
                "title": user_message[:30] + ("..." if len(user_message) > 30 else ""),
                "timestamp": datetime.utcnow().isoformat(),
                "messages": []
            }
    else:
        chat_data = {
            "id": chat_id,
            "title": user_message[:30] + ("..." if len(user_message) > 30 else ""),
            "timestamp": datetime.utcnow().isoformat(),
            "messages": []
        }

    chat_data["messages"].append({"role": "user", "content": user_message})

    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        response = model.generate_content(user_message)
        reply = response.text.strip()
    except Exception as e:
        reply = f"Error: {str(e)}"

    chat_data["messages"].append({"role": "assistant", "content": reply})

    # Update timestamp when chat is modified
    chat_data["timestamp"] = datetime.utcnow().isoformat()

    try:
        with open(filepath, "w") as f:
            json.dump(chat_data, f, indent=2)
    except Exception as e:
        return jsonify({"error": f"Failed to save chat: {str(e)}"}), 500

    return jsonify({"reply": reply, "chat_id": chat_id})


# ---------- Delete Chat Route ----------
@app.route("/delete_chat/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    try:
        filepath = os.path.join(CHAT_LOG_DIR, f"{chat_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({"success": True, "message": "Chat deleted successfully"})
        else:
            return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to delete chat: {str(e)}"}), 500


# ---------- New Chat Route ----------
@app.route("/new_chat", methods=["POST"])
def new_chat():
    try:
        new_chat_id = str(uuid.uuid4())
        return jsonify({"chat_id": new_chat_id, "success": True})
    except Exception as e:
        return jsonify({"error": f"Failed to create new chat: {str(e)}"}), 500


# ---------- PDF Upload Route ----------
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    
    if not file or not file.filename:
        return jsonify({"reply": "No file selected."})
    
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"reply": "Invalid file type. Only PDF files are supported."})

    try:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        extracted_text = extract_text_from_pdf(file_path)
        
        if extracted_text.startswith("Error"):
            return jsonify({"reply": extracted_text})

        # Clean up uploaded file after processing
        os.remove(file_path)

        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        response = model.generate_content(f"Summarize this PDF content:\n\n{extracted_text[:3000]}")
        reply = response.text.strip()
        
    except Exception as e:
        reply = f"Error processing PDF: {str(e)}"
        # Clean up file if it exists
        try:
            if 'file_path' in locals() and os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

    return jsonify({"reply": reply})


# ---------- Error Handlers ----------
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


# ---------- Run App ----------
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)