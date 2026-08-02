"""AWS Lambda entrypoint: wraps the FastAPI app with Mangum (ASGI adapter).

The Lambda Function URL invokes `backend.lambda_handler.handler`; Mangum
translates the Function URL event into an ASGI request and back, including
base64-encoding binary responses (PWA icons).
"""
from mangum import Mangum

from backend.main import app

handler = Mangum(app)
