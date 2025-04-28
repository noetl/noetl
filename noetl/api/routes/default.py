from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
def health_check():
    return {"status": "ok"}


@router.get("/health-dashboard", response_class=HTMLResponse)
async def health_dashboard():
    return """
    <div class="health-status-container">
        <span class="health-indicator"></span>
        <span class="health-text">Service is healthy</span>
    </div>
    """

@router.get("/", response_class=HTMLResponse)
async def main_page():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NoETL Main Page</title>
        <script src="https://unpkg.com/htmx.org"></script>
        <link rel="stylesheet" href="/static/styles.css">
        <style>
            body {
                font-family: Arial, sans-serif;
            }
            .health-status-container {
                display: flex;
                align-items: center;
                padding: 1em;
                background-color: #f7f9fa;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
            .health-indicator {
                width: 16px;
                height: 16px;
                border-radius: 50%;
                background-color: green;
                margin-right: 0.5em;
                display: inline-block;
            }
            .health-text {
                font-size: 1em;
                vertical-align: middle;
                color: #333;
            }
            nav ul {
                list-style: none;
                padding: 0;
            }
            nav ul li {
                display: inline;
                margin-right: 10px;
            }
            #content {
                margin-top: 20px;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: #f9f9f9;
                min-height: 100px;
            }
        </style>
    </head>
    <body>
        <h1>NoETL Dashboard</h1>
        <nav>
            <ul>
                <li><button hx-get="/catalog" hx-trigger="click" hx-target="#content">Catalog</button></li>
                <li><button hx-get="/events" hx-trigger="click" hx-target="#content">Events</button></li>
                <li><button hx-get="/jobs" hx-trigger="click" hx-target="#content">Jobs</button></li>
                <li><button hx-get="/health-dashboard" hx-trigger="click" hx-target="#content">Health Dashboard</button></li>
                <li><button onclick="location.href='/docs'">Docs</button></li>
            </ul>
        </nav>
        <div id="content">
            <p>Select a tab to view details.</p>
        </div>
    </body>
    </html>
    """