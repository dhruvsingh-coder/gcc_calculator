import azure.functions as func
import json
import time
import logging

# Store OTPs in memory (use Azure Redis Cache in production)
otp_storage = {}

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        req_body = req.get_json()
        email = req_body.get('email', '').lower().strip()
        user_otp = req_body.get('otp', '').strip()

        if not email or not user_otp:
            return func.HttpResponse(
                json.dumps({"error": "Email and OTP are required"}),
                status_code=400,
                mimetype="application/json"
            )

        stored_data = otp_storage.get(email)
        
        if not stored_data:
            return func.HttpResponse(
                json.dumps({"verified": False, "error": "OTP not found or expired"}),
                status_code=400,
                mimetype="application/json"
            )

        # Check OTP expiration (10 minutes)
        if time.time() - stored_data['timestamp'] > 600:  # 10 minutes
            del otp_storage[email]
            return func.HttpResponse(
                json.dumps({"verified": False, "error": "OTP expired"}),
                status_code=400,
                mimetype="application/json"
            )

        # Check if OTP matches
        if stored_data['otp'] == user_otp:
            # OTP verified successfully
            del otp_storage[email]  # Remove used OTP
            return func.HttpResponse(
                json.dumps({"verified": True, "message": "OTP verified successfully"}),
                status_code=200,
                mimetype="application/json"
            )
        else:
            stored_data['attempts'] += 1
            # Remove OTP after 3 failed attempts
            if stored_data['attempts'] >= 3:
                del otp_storage[email]
                return func.HttpResponse(
                    json.dumps({"verified": False, "error": "Too many failed attempts"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"verified": False, "error": "Invalid OTP"}),
                status_code=400,
                mimetype="application/json"
            )

    except Exception as e:
        logging.error(f"Error verifying OTP: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Verification failed"}),
            status_code=500,
            mimetype="application/json"
        )