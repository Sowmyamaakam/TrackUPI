from flask import Flask, request, jsonify, send_from_directory
from PIL import Image
import pytesseract
import re
from datetime import datetime
from pymongo import MongoClient
import os
import urllib.parse
from bson.objectid import ObjectId

app = Flask(__name__)

# MongoDB Atlas setup
username = urllib.parse.quote_plus("sowmya21")
password = urllib.parse.quote_plus("sowmya05")
client = MongoClient(f"mongodb+srv://{username}:{password}@cluster0.1r3xc.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client["transaction_db"]
collection = db["transactions"]

def preprocess_image(image_path):
    image = Image.open(image_path)
    image = image.convert('L')  # Convert to grayscale
    image = image.point(lambda x: 0 if x < 150 else 255)  # Increase contrast
    return image

def convert_to_12_hour_format(time_str):
    try:
        if ':' in time_str and len(time_str.split(':')[0]) == 2:
            time_obj = datetime.strptime(time_str, '%H:%M')  # Parse as 24-hour time
            return time_obj.strftime('%I:%M %p')  # Convert to 12-hour with AM/PM
    except ValueError:
        return time_str  # If parsing fails, return the original

def extract_transaction_details(image_path):
    image = preprocess_image(image_path)
    custom_config = r'--oem 3 --psm 6'
    text = pytesseract.image_to_string(image, config=custom_config)
    
    # Print the raw extracted text
    print("Extracted Text:")
    print(text)  # This will print all the extracted text

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

@app.route('/')
def index():
    return send_from_directory('', 'tpg.html')

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

@app.route('/save', methods=['POST'])
def save_edited_transaction():
    data = request.json
    if not data.get('Date') or not data.get('Time') or not data.get('Receiver') or not data.get('Amount') or not data.get('Category'):
        return jsonify({'error': 'Missing required fields'}), 400

    result = collection.insert_one(data)
    return jsonify({'message': 'Transaction details saved successfully', '_id': str(result.inserted_id)})

if __name__ == '__main__':
    app.run(debug=True, port=5001)
