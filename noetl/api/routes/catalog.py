import base64
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from noetl.util import setup_logger
from noetl.appctx.app_context import get_app_context, AppContext
from noetl.api.schemas.catalog import RegisterRequest
from noetl.api.services.catalog import CatalogService

logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix="/catalog")

def get_catalog_service():
    return CatalogService()

@router.post("/register")
async def register_resource(
        request: RegisterRequest,
        context: AppContext = Depends(get_app_context)
):
    content_base64 = request.content_base64
    logger.info(f"Received request to register resource.", extra={"content_base64": content_base64})
    return await CatalogService.register_entry(
        content_base64=content_base64,
        event_type="REGISTERED",
        context=context
    )


@router.get("/", response_class=HTMLResponse)
async def catalog_page():
    return """
    <div>
        <h2>Catalog Page</h2>
        <p>Catalog content. You can upload a playbook and view the catalog table.</p>
        <form id="upload-form" hx-post="/catalog/upload" hx-target="#catalog-table" enctype="multipart/form-data">
            <label for="playbook-file">Upload Playbook:</label>
            <input type="file" name="playbook_file" id="playbook-file" required>
            <button type="submit">Upload</button>
        </form>
        <hr/>
        <div id="catalog-table">
            <p>Catalog table will be displayed after playbook is uploaded.</p>
        </div>
        <div id="details">
            <h3>Details</h3>
            <p>Select a playbook to view content or payload.</p>
        </div>
    </div>
    """


@router.post("/upload", response_class=HTMLResponse)
async def upload_playbook(
        playbook_file: UploadFile = File(...),
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
        logger.info(f"Upload request file: {playbook_file.filename}")
        raw_content = await playbook_file.read()
        logger.debug(f"File content: {raw_content[:200]}")
        base64_content = base64.b64encode(raw_content).decode("utf-8")
        response = await catalog_service.register_entry(
            content_base64=base64_content,
            event_type="REGISTERED",
            context=context
        )
        catalog_entries = await catalog_service.fetch_all_entries(context)
        table_rows = "".join(
            f"""
            <tr>
                <td>{entry['id']}</td>
                <td>{entry['name']}</td>
                <td>{entry['event_type']}</td>
                <td>{entry['version']}</td>
                <td>{entry['timestamp']}</td>
                <td>
                    <button hx-get="/catalog/content?id={entry['id']}" hx-target="#details">View Content</button>
                </td>
                <td>
                    <button hx-get="/catalog/payload?id={entry['id']}" hx-target="#details">View Payload</button>
                </td>
            </tr>
            """
            for entry in catalog_entries
        )

        message_html = f"<p><strong>Status:</strong> {response['message']}</p>"
        return f"""
        {message_html}
        <h3>Catalog Table</h3>
        <table border="1">
            <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Event Type</th>
                <th>Version</th>
                <th>Timestamp</th>
                <th>Content</th>
                <th>Payload</th>
            </tr>
            {table_rows}
        </table>
        """
    except Exception as e:
        logger.error(f"Error uploading playbook: {e}")
        return f"<p>Error processing the uploaded file: {e}</p>"


@router.get("/content", response_class=HTMLResponse)
async def get_content(
        id: str,
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
        entry = await catalog_service.fetch_entry_id(context, id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Catalog entry with ID '{id}' not found.")
        return f"""
        <h4>Content for '{id}':</h4>
        <pre>{entry.get('content', 'No content available')}</pre>
        """
    except Exception as e:
        logger.error(f"Error fetching content: {e}")
        return f"<p>Error fetching content for entry '{id}': {e}</p>"


@router.get("/payload", response_class=HTMLResponse)
async def get_payload(
        id: str,
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
        entry = await catalog_service.fetch_entry_id(context, id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Catalog entry with ID '{id}' not found.")
        return f"""
        <h4>Payload for '{id}':</h4>
        <pre>{entry.get('payload', 'No payload available')}</pre>
        """
    except Exception as e:
        logger.error(f"Error fetching payload: {e}")
        return f"<p>Error fetching payload for entry '{id}': {e}</p>"
