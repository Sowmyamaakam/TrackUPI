from flask import Flask, request, jsonify, render_template, send_from_directory
from PIL import Image
import pytesseract
import re
from datetime import datetime
from pymongo import MongoClient
import os
import urllib.parse
from bson.objectid import ObjectId
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path='.env.txt')

app = Flask(__name__)

# MongoDB credentials
username = os.getenv("DB_USERNAME")
password = os.getenv("DB_PASSWORD")

# Test MongoDB connection
try:
    client = MongoClient(f"mongodb+srv://{username}:{password}@cluster0.1r3xc.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
    client.admin.command('ping')  # Test the connection
    print("MongoDB connection successful")
except Exception as e:
    print(f"MongoDB connection failed: {e}")

db = client["transaction_db"]
credit_collection = db["credited"]  # Collection for credited transactions
debit_collection = db["debited"]  # Collection for debited transactions
collection = db["transactions"]  # Common collection

# Image Preprocessing
def preprocess_image(image_path):
    image = Image.open(image_path)
    image = image.convert('L')  # Convert to grayscale
    image = image.point(lambda x: 0 if x < 150 else 255)  # Increase contrast
    return image

# Convert time to 12-hour format
def convert_to_12_hour_format(time_str):
    try:
        if ':' in time_str and len(time_str.split(':')[0]) == 2:
            time_obj = datetime.strptime(time_str, '%H:%M')  # Parse as 24-hour time
            return time_obj.strftime('%I:%M %p')  # Convert to 12-hour with AM/PM
    except ValueError:
        return time_str  # If parsing fails, return the original

# Extract transaction details from image
def extract_transaction_details(image_path):
    image = preprocess_image(image_path)
    custom_config = r'--oem 3 --psm 6'
    text = pytesseract.image_to_string(image, config=custom_config)
    
    print("Extracted Text:")
    print(text)  # Print extracted text for debugging

    corrected_text = re.sub(r'[^\w\s₹.,:am|pm]', '', text)
    corrected_text = re.sub(r'(?<=\d)3(?=\d)', '₹', corrected_text)
    corrected_text = re.sub(r'%', '₹', corrected_text)

    transaction_status = "Unknown"
    if "credited" in corrected_text.lower():
        transaction_status = "Credited"
    elif "debited" in corrected_text.lower():
        transaction_status = "Debited"

    details = {'Status': transaction_status}

    # Extract date and time
    date_time = re.search(r'(\d{1,2}:\d{2}\s*[APap][Mm])\s*on\s*(\d{1,2}\s\w+\s\d{4})', corrected_text)
    if date_time:
        time_str = date_time.group(1).strip().replace(' pm', '').replace(' am', '')
        date_str = date_time.group(2).strip()
        try:
            datetime_obj = datetime.strptime(date_str, '%d %b %Y')  # Input format
            details['Date'] = datetime_obj.strftime('%Y-%m-%d')  # Output format
        except ValueError:
            details['Date'] = date_str  # Fallback for unparsed dates
        details['Time'] = time_str

    # Extract sender or receiver
    if transaction_status == "Credited":
        sender_name = re.search(r'Received from\s*\n*([^\d\n]+)', corrected_text)
        if sender_name:
            details['Sender'] = sender_name.group(1).strip()
    elif transaction_status == "Debited":
        receiver_name = re.search(r'Paid to\s*\n*([^\d\n]+)', corrected_text)
        if receiver_name:
            details['Receiver'] = receiver_name.group(1).strip()

    # Extract amount
    amount_line = re.search(r'(?:Paid to|Received from)\s*\n*([^\n]+)', text)
    if amount_line:
        amount_text = amount_line.group(1).strip()
        amount = re.search(r'(\d{1,3}(?:,\d{3})*)', amount_text)
        if amount:
            details['Amount'] = amount.group(1).strip().replace(',', '')  # Remove commas for consistency

    return details

# Flask route for the landing page (HTML)
@app.route('/')
def index():
    return send_from_directory('', 'upi form.html')

# Flask route for uploading an image and extracting transaction details
@app.route('/upload', methods=['POST'])
def upload_image():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image uploaded'}), 400

        image_file = request.files['image']
        if image_file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        if not os.path.exists('uploads'):
            os.makedirs('uploads')

        image_path = os.path.join('uploads', image_file.filename)
        image_file.save(image_path)
        
        details = extract_transaction_details(image_path)
        details['_id'] = str(ObjectId())  # Create a new unique ID for the transaction
        return jsonify(details)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Flask route for submitting transaction data to MongoDB
@app.route('/submit', methods=['POST'])
def submit_transaction():
    try:
        # Extract data from the form
        name = request.form.get('name')
        transaction_id = request.form.get('transaction_id')
        date = request.form.get('date')
        time = request.form.get('time')
        amount = request.form.get('amount')
        payment_type = request.form.get('payment_type')
        payee_type = request.form.get('payee_type')
        personal_reference = request.form.get('personal_reference')
        transaction_rating = request.form.get('transaction_rating')

        # Prepare the transaction data
        transaction_data = {
            'name': name,
            'transaction_id': transaction_id,
            'date': date,
            'time': time,
            'amount': float(amount) if amount else 0.0,
            'payee_type': payee_type,
            'personal_reference': personal_reference,
            'transaction_rating': transaction_rating
        }

        # Insert transaction into the respective collection based on payment type
        if payment_type == 'Credited':
            credit_collection.insert_one(transaction_data)
        else:
            debit_collection.insert_one(transaction_data)

        return jsonify({'message': 'Transaction data stored successfully', 'status': 'success'}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500
if __name__ == '__main__':
    app.run(debug=True)
