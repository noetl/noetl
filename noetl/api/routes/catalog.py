from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from noetl.util import setup_logger
from noetl.appctx.app_context import get_app_context, AppContext
from noetl.api.schemas.catalog import RegisterRequest
from noetl.api.services.catalog import CatalogService, create_catalog_entry
import base64
import json
import yaml

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
async def catalog_page(
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
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
                    <button onclick="window.open('/catalog/editor?type=content&resource_path={entry['id']}&resource_version={entry['version']}', '_blank')">View/Edit Content</button>
                </td>
                <td>
                    <button onclick="window.open('/catalog/editor?type=payload&resource_path={entry['id']}&resource_version={entry['version']}', '_blank')">View/Edit Payload</button>
                </td>
            </tr>
            """
            for entry in catalog_entries
        )

        return f"""
        <div>
            <h2>Catalog Page</h2>
            <p>Upload a playbook and view the catalog table to inspect or edit entries.</p>
            <form id="upload-form" hx-post="/catalog/upload" hx-target="#catalog-table" enctype="multipart/form-data">
                <label for="playbook-file">Upload Playbook:</label>
                <input type="file" name="playbook_file" id="playbook-file" required>
                <button type="submit">Upload</button>
            </form>
            <hr/>
            <div id="catalog-table">
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
            </div>
        </div>
        """
    except Exception as e:
        logger.error(f"Error displaying the catalog page: {e}")
        return f"<p>Error loading the catalog page. Please try again later.</p>"




@router.post("/upload", response_class=HTMLResponse)
async def upload_playbook(
        playbook_file: UploadFile = File(...),
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
        logger.info(f"Upload request file: {playbook_file.filename}")
        raw_content = await playbook_file.read()
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
                    <button onclick="window.open('/catalog/editor?type=content&id={entry['id']}', '_blank')">View/Edit Content</button>
                </td>
                <td>
                    <button onclick="window.open('/catalog/editor?type=payload&id={entry['id']}', '_blank')">View/Edit Payload</button>
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


@router.get("/editor", response_class=HTMLResponse)
async def editor(
        type: str,
        resource_path: str,
        resource_version: str,
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
        entry = await catalog_service.fetch_entry_path_version(
            context, resource_path, resource_version
        )
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Catalog entry for '{resource_path}' with version '{resource_version}' not found."
            )
        if type == "content":
            data = entry["content"]
            language = "yaml"
        elif type == "payload":
            data = json.dumps(entry["payload"], indent=2)
            language = "json"
        else:
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'content' or 'payload'.")

        return f"""
        <html>
            <head>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.9/codemirror.min.js"></script>
                <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.9/codemirror.min.css">
                <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.9/mode/{language}/{language}.min.js"></script>
                <style>
                    .CodeMirror {{ border: 1px solid #ddd; height: auto; }}
                    button {{ margin: 5px; }}
                </style>
            </head>
            <body>
                <h3>Editing {type.capitalize()} for '{resource_path}' (Version: {resource_version})</h3>
                <form method="POST" action="/catalog/save">
                    <!-- Save and Close buttons -->
                    <div>
                        <button type="submit">Save</button>
                        <button type="button" onclick="window.location='/';">Close Without Saving</button>
                    </div>
                    <textarea id="editor" name="data" style="width:100%; height:300px;">{data}</textarea>
                    <input type="hidden" name="type" value="{type}">
                    <input type="hidden" name="resource_path" value="{resource_path}">
                    <input type="hidden" name="resource_version" value="{resource_version}">
                </form>
                <script>
                    var editor = CodeMirror.fromTextArea(document.getElementById("editor"), {{
                        lineNumbers: true,
                        mode: "{language}"
                    }});
                </script>
            </body>
        </html>
        """
    except Exception as e:
        logger.error(f"Error opening editor: {e}")
        return f"<p>Error opening editor for '{resource_path}' (version '{resource_version}'): {e}</p>"


from deepdiff import DeepDiff

@router.post("/save", response_class=RedirectResponse)
async def save_editor(
        resource_path: str = Form(...),
        resource_version: str = Form(...),
        type: str = Form(...),
        data: str = Form(...),
        catalog_service: CatalogService = Depends(get_catalog_service),
        context: AppContext = Depends(get_app_context)
):
    try:
        logger.info(f"Attempting to save {type} for resource_path='{resource_path}' (version='{resource_version}').")

        async with context.postgres.get_session() as session:
            current_entry = await catalog_service.fetch_entry_path_version(
                    context, resource_path, resource_version
                )

        if not current_entry:
            raise HTTPException(
                status_code=404,
                detail=f"No matching entry found for '{resource_path}' version '{resource_version}'."
            )

        existing_content = current_entry["content"].strip()
        existing_payload = current_entry["payload"]

        if type == "content":
            new_content = data.strip()
            try:
                new_payload = yaml.safe_load(new_content)
            except yaml.YAMLError as e:
                raise HTTPException(status_code=400, detail=f"Invalid YAML format: {e}")
        elif type == "payload":
            try:
                new_payload = json.loads(data)
                new_content = yaml.dump(new_payload, default_flow_style=False).strip()
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")
        else:
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'content' or 'payload'.")

        existing_content_normalized = yaml.dump(
            yaml.safe_load(existing_content),
            default_flow_style=False
        ).strip()
        new_content_normalized = yaml.dump(
            yaml.safe_load(new_content),
            default_flow_style=False
        ).strip()

        if existing_content_normalized == new_content_normalized and DeepDiff(existing_payload, new_payload) == {}:
            logger.info(f"No changes detected for '{resource_path}' (version='{resource_version}').")
            return RedirectResponse(url="/", status_code=303)

        updated_entry = await create_catalog_entry(session, new_content_normalized, new_payload, resource_version)
        logger.info(f"Saved new version '{updated_entry.resource_version}' for '{resource_path}'.")

        return RedirectResponse(url="/", status_code=303)

    except Exception as e:
        logger.error(f"Error saving {type} for {resource_path} (version={resource_version}): {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error saving {type} for '{resource_path}' (version '{resource_version}'): {e}"
        )





