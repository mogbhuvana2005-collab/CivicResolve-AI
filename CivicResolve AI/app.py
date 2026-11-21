
import os
import json
import sqlite3
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI


# ==========================================
# 1. PROJECT SETTINGS
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
CORS(app)

DB_FILE = os.path.join(BASE_DIR, "database.db")
DATA_FILE = os.path.join(BASE_DIR, "complaints.json")

MODEL_NAME = "nova-micro"


# ==========================================
# 2. NEXUS AI SETTINGS
# ==========================================

api_key = os.getenv("NEXUS_API_KEY")
base_url = os.getenv("NEXUS_BASE_URL")

client = None

if api_key and base_url:
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )


# ==========================================
# 3. DATABASE CONNECTION
# ==========================================

def get_db_connection():

    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row

    return connection


# ==========================================
# 4. CREATE DATABASE TABLE
# ==========================================

def initialize_database():

    connection = get_db_connection()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            complaint_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            ai_analysis TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)

    connection.commit()
    connection.close()

    # Migrate previously saved JSON complaints

    if os.path.exists(DATA_FILE):

        try:

            with open(DATA_FILE, "r", encoding="utf-8") as file:
                records = json.load(file)

            if isinstance(records, list):

                connection = get_db_connection()

                for record in records:

                    if not isinstance(record, dict):
                        continue

                    complaint_id = record.get("complaint_id")

                    if not complaint_id:
                        continue

                    connection.execute("""
                        INSERT OR IGNORE INTO complaints
                        (
                            complaint_id, name, mobile, category,
                            location, description, ai_analysis,
                            status, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        complaint_id,
                        record.get("name", ""),
                        record.get("mobile", ""),
                        record.get("category", ""),
                        record.get("location", ""),
                        record.get("description", ""),
                        record.get("ai_analysis", ""),
                        record.get("status", "Pending"),
                        record.get("created_at", "")
                    ))

                connection.commit()
                connection.close()

        except (json.JSONDecodeError, OSError) as error:

            print("JSON migration warning:", error)


# ==========================================
# 5. AI COMPLAINT ANALYSIS
# ==========================================

def analyse_complaint(category, location, description):

    if client is None:

        raise ValueError(
            "Check your Nexus API settings in the .env file."
        )

    response = client.chat.completions.create(

        model=MODEL_NAME,

        messages=[
            {
                "role": "system",
                "content": (
                    "You are CivicResolve AI. Analyse civic complaints "
                    "and suggest practical solutions."
                )
            },
            {
                "role": "user",
                "content": f"""
Category: {category}
Location: {location}
Complaint: {description}

Provide:
1. Problem summary
2. Suggested solution
3. Responsible government department
4. Recommended priority (Low, Medium, High)
"""
            }
        ]
    )

    return response.choices[0].message.content


# ==========================================
# 6. SAVE COMPLAINT INTO SQLITE
# ==========================================

def save_complaint(record):

    connection = get_db_connection()

    connection.execute("""
        INSERT INTO complaints (
            complaint_id, name, mobile, category,
            location, description, ai_analysis,
            status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record["complaint_id"],
        record["name"],
        record["mobile"],
        record["category"],
        record["location"],
        record["description"],
        record["ai_analysis"],
        record["status"],
        record["created_at"]
    ))

    connection.commit()
    connection.close()


# ==========================================
# 7. HOME PAGE
# ==========================================

@app.route("/", methods=["GET"])
def home():

    return "CivicResolve AI Backend is Running!"


# ==========================================
# 8. TEST AI
# ==========================================

@app.route("/api/test-ai", methods=["POST"])
def test_ai():

    try:

        data = request.get_json(silent=True) or {}

        complaint = data.get("complaint", "")

        if not isinstance(complaint, str):
            complaint = ""

        complaint = complaint.strip()

        if not complaint:

            return jsonify({
                "success": False,
                "error": "Please enter a complaint."
            }), 400

        answer = analyse_complaint(
            "General",
            "Not specified",
            complaint
        )

        return jsonify({
            "success": True,
            "ai_response": answer
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==========================================
# 9. REGISTER COMPLAINT
# ==========================================

@app.route("/api/register-complaint", methods=["POST"])
def register_complaint():

    try:

        data = request.get_json(silent=True) or {}

        name = data.get("name", "")
        mobile = data.get("mobile", "")
        category = data.get("category", "")
        location = data.get("location", "")
        description = data.get("description", "")

        fields = [name, mobile, category, location, description]

        if not all(isinstance(value, str) for value in fields):

            return jsonify({
                "success": False,
                "error": "Invalid input format."
            }), 400

        name = name.strip()
        mobile = mobile.strip()
        category = category.strip()
        location = location.strip()
        description = description.strip()

        if not all([name, mobile, category, location, description]):

            return jsonify({
                "success": False,
                "error": "Please fill in all fields."
            }), 400

        # Generate AI analysis

        ai_answer = analyse_complaint(
            category,
            location,
            description
        )

        # Generate unique complaint ID

        connection = get_db_connection()

        while True:

            complaint_id = "CR" + datetime.now().strftime(
                "%Y%m%d%H%M%S%f"
            )

            existing = connection.execute(
                "SELECT complaint_id FROM complaints WHERE complaint_id = ?",
                (complaint_id,)
            ).fetchone()

            if existing is None:
                break

        connection.close()

        # Create complaint record

        record = {
            "complaint_id": complaint_id,
            "name": name,
            "mobile": mobile,
            "category": category,
            "location": location,
            "description": description,
            "ai_analysis": ai_answer,
            "status": "Pending",
            "created_at": datetime.now().isoformat()
        }

        save_complaint(record)

        return jsonify({
            "success": True,
            "complaint_id": complaint_id,
            "ai_analysis": ai_answer,
            "status": "Pending"
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==========================================
# 10. TRACK COMPLAINT
# ==========================================

@app.route("/api/track-complaint/<complaint_id>", methods=["GET"])
def track_complaint(complaint_id):

    try:

        connection = get_db_connection()

        record = connection.execute(
            "SELECT * FROM complaints WHERE complaint_id = ?",
            (complaint_id,)
        ).fetchone()

        connection.close()

        if record is None:

            return jsonify({
                "success": False,
                "error": "Complaint not found."
            }), 404

        return jsonify({
            "success": True,
            "complaint": {
                "complaint_id": record["complaint_id"],
                "name": record["name"],
                "category": record["category"],
                "location": record["location"],
                "description": record["description"],
                "ai_analysis": record["ai_analysis"],
                "status": record["status"],
                "created_at": record["created_at"]
            }
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==========================================
# 11. ADMIN DASHBOARD - GET ALL COMPLAINTS
# ==========================================

@app.route("/api/admin/complaints", methods=["GET"])
def admin_complaints():

    try:

        connection = get_db_connection()

        complaints = connection.execute(
            "SELECT * FROM complaints ORDER BY created_at DESC"
        ).fetchall()

        total = connection.execute(
            "SELECT COUNT(*) FROM complaints"
        ).fetchone()[0]

        pending = connection.execute(
            "SELECT COUNT(*) FROM complaints WHERE status = 'Pending'"
        ).fetchone()[0]

        progress = connection.execute(
            "SELECT COUNT(*) FROM complaints WHERE status = 'In Progress'"
        ).fetchone()[0]

        resolved = connection.execute(
            "SELECT COUNT(*) FROM complaints WHERE status = 'Resolved'"
        ).fetchone()[0]

        connection.close()

       
        complaint_list = []

        for record in complaints:

            complaint_list.append({
                "complaint_id": record["complaint_id"],
                "name": record["name"],
                "mobile": record["mobile"],
                "category": record["category"],
                "location": record["location"],
                "description": record["description"],
                "ai_analysis": record["ai_analysis"],
                "status": record["status"],
                "created_at": record["created_at"]
            })



        return jsonify({
            "success": True,

            "statistics": {
                "total": total,
                "pending": pending,
                "progress": progress,
                "resolved": resolved
            },

            "complaints": complaint_list
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==========================================
# 12. ADMIN - UPDATE COMPLAINT STATUS
# ==========================================

@app.route(
    "/api/admin/update-status/<complaint_id>",
    methods=["PUT"]
)
def update_complaint_status(complaint_id):

    try:

        data = request.get_json(silent=True) or {}

        new_status = data.get("status", "")

        if not isinstance(new_status, str):
            new_status = ""

        new_status = new_status.strip()

        allowed_statuses = [
            "Pending",
            "In Progress",
            "Resolved"
        ]

        if new_status not in allowed_statuses:

            return jsonify({
                "success": False,
                "error": "Invalid complaint status."
            }), 400

        connection = get_db_connection()

        existing = connection.execute(
            "SELECT complaint_id FROM complaints WHERE complaint_id = ?",
            (complaint_id,)
        ).fetchone()

        if existing is None:

            connection.close()

            return jsonify({
                "success": False,
                "error": "Complaint not found."
            }), 404

        connection.execute(
            """
            UPDATE complaints
            SET status = ?
            WHERE complaint_id = ?
            """,
            (new_status, complaint_id)
        )

        connection.commit()
        connection.close()

        return jsonify({
            "success": True,
            "message": "Complaint status updated successfully.",
            "status": new_status
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==========================================
# 13. START FLASK APPLICATION
# ==========================================

if __name__ == "__main__":

    initialize_database()

    print("CivicResolve AI Database Initialized!")

    print("Starting CivicResolve AI Backend...")

    app.run(
        debug=True,
        port=5000
    )
