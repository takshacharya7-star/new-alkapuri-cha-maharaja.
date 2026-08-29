import os
import io
import csv
import json
from datetime import datetime, timezone
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, Response)
from supabase import create_client, Client
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'ganpati-aagman-secret-2026')
app.config['MAX_CONTENT_LENGTH'] = 1100 * 1024 * 1024  # 1.1 GB max upload

# ─── Google Drive Setup ───────────────────────────────────────────────────────
GOOGLE_DRIVE_FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service():
    # Read credentials from environment variable (works on Vercel)
    sa_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # Fallback: read from local file (for local development)
        sa_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'ganpati2026')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── Public Pages ────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/registration')
def registration():
    return render_template('registration.html')

@app.route('/upload')
def upload():
    return render_template('upload.html')

@app.route('/success')
def success():
    return render_template('success.html')

# ─── API Routes ──────────────────────────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        entry = {
            'id':          data['id'],
            'name':        data['name'],
            'mobile':      data['mobile'],
            'email':       data['email'],
            'instagram':   data['instagram'],
            'competition': data['competition'],
            'captured':    data['captured'],
            'status':      'registered',
            'created_at':  datetime.now(timezone.utc).isoformat(),
        }
        supabase.table('entries').insert(entry).execute()
        return jsonify({'success': True, 'id': data['id']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/lookup', methods=['POST'])
def api_lookup():
    try:
        data = request.get_json() or {}
        query = str(data.get('query', '')).strip()
        if not query:
            return jsonify({'success': False, 'error': 'Mobile number or ID is required'}), 400

        # Clean digits for mobile query
        clean_digits = ''.join(c for c in query if c.isdigit())
        if len(clean_digits) >= 10:
            clean_mobile = clean_digits[-10:]
        else:
            clean_mobile = query

        # Search by mobile or submission ID in Supabase
        result = (
            supabase.table('entries')
            .select('*')
            .or_(f"mobile.eq.{clean_mobile},mobile.eq.{query},id.eq.{query}")
            .order('created_at', desc=True)
            .limit(1)
            .execute()
        )

        if not result.data or len(result.data) == 0:
            return jsonify({
                'success': False,
                'not_found': True,
                'error': 'No registration found with this mobile number. Please do a new registration.'
            }), 404

        entry = result.data[0]
        return jsonify({'success': True, 'entry': entry})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/update-entry', methods=['POST'])
def api_update_entry():
    try:
        data = request.get_json() or {}
        entry_id = data.get('id')
        competition = data.get('competition')
        captured = data.get('captured')

        if not entry_id:
            return jsonify({'success': False, 'error': 'Entry ID is required'}), 400

        update_payload = {}
        if competition in ['Photo', 'Video']:
            update_payload['competition'] = competition
        if captured in ['Mobile', 'Camera']:
            update_payload['captured'] = captured

        if update_payload:
            supabase.table('entries').update(update_payload).eq('id', entry_id).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/get-upload-url', methods=['POST'])
def api_get_upload_url():
    """Step 1: Generate a Google Drive resumable upload URL.
    Browser uploads directly to Google Drive — bypasses Vercel 4.5 MB limit.
    """
    try:
        data       = request.get_json() or {}
        entry_id   = data.get('id')
        filename   = data.get('filename', 'upload.bin')
        mimetype   = data.get('mimetype', 'application/octet-stream')
        filesize   = data.get('filesize', 0)
        orig_name  = data.get('original_filename', filename)

        if not entry_id:
            return jsonify({'success': False, 'error': 'Missing entry id'}), 400

        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
        drive_filename = f"{entry_id}.{ext}"

        import googleapiclient.http as ghttp
        import urllib.request

        drive_service = get_drive_service()

        # Build a resumable upload request manually to get the upload URL
        file_metadata = {'name': drive_filename, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}

        # Use the files().create() to initiate but get the resumable URI
        request_obj = drive_service.files().create(
            body=file_metadata,
            media_body=ghttp.MediaIoBaseUpload(
                io.BytesIO(b''),
                mimetype=mimetype,
                resumable=True
            ),
            fields='id,webViewLink'
        )

        # Manually initiate resumable session to get the upload URL
        import httplib2
        from googleapiclient.http import _retry_request
        http = drive_service._http

        # Use the Drive API resumable upload endpoint directly
        import google.auth.transport.requests
        creds = service_account.Credentials.from_service_account_info(
            json.loads(os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '{}')),
            scopes=SCOPES
        ) if os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON') else \
            service_account.Credentials.from_service_account_file(
                os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json'),
                scopes=SCOPES
            )

        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        token = creds.token

        import urllib.request as urlreq
        import urllib.error

        meta_json = json.dumps({'name': drive_filename, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}).encode()
        req = urlreq.Request(
            f'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
            data=meta_json,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json; charset=UTF-8',
                'X-Upload-Content-Type': mimetype,
                'X-Upload-Content-Length': str(filesize),
            },
            method='POST'
        )
        with urlreq.urlopen(req) as resp:
            upload_url = resp.headers.get('Location')

        # Pre-create DB entry as 'uploading'
        supabase.table('entries').update({
            'status':         'uploading',
            'media_filename': orig_name,
        }).eq('id', entry_id).execute()

        return jsonify({
            'success':    True,
            'upload_url': upload_url,
            'filename':   drive_filename,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/submit-link', methods=['POST'])
def api_submit_link():
    try:
        data = request.get_json() or {}
        entry_id = data.get('id')
        instagram_link = data.get('instagram_link', '').strip()

        if not entry_id or not instagram_link:
            return jsonify({'success': False, 'error': 'Missing registration ID or Instagram Link'}), 400

        if 'instagram.com' not in instagram_link.lower():
            return jsonify({'success': False, 'error': 'Please enter a valid Instagram Link'}), 400

        supabase.table('entries').update({
            'status':         'submitted',
            'media_url':      instagram_link,
            'media_filename': 'Instagram Link',
            'submitted_at':   datetime.now(timezone.utc).isoformat(),
        }).eq('id', entry_id).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/complete-upload', methods=['POST'])
def api_complete_upload():
    """Step 2: After browser uploads directly to Drive, make file public & update DB."""
    try:
        data      = request.get_json() or {}
        entry_id  = data.get('id')
        file_id   = data.get('file_id')
        orig_name = data.get('original_filename', '')

        if not entry_id or not file_id:
            return jsonify({'success': False, 'error': 'Missing id or file_id'}), 400

        drive_service = get_drive_service()

        # Make file publicly readable
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        file_info = drive_service.files().get(
            fileId=file_id, fields='webViewLink'
        ).execute()
        public_url = file_info.get('webViewLink', '')

        supabase.table('entries').update({
            'status':         'submitted',
            'media_url':      public_url,
            'media_filename': orig_name,
            'submitted_at':   datetime.now(timezone.utc).isoformat(),
        }).eq('id', entry_id).execute()

        return jsonify({'success': True, 'media_url': public_url})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.route('/admin')
def admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='❌ Wrong password. Try again.')
    return render_template('admin_login.html', error=None)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('admin.html')


@app.route('/admin/data')
def admin_data():
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    result = supabase.table('entries').select('*').order('created_at', desc=True).execute()
    return jsonify(result.data)


@app.route('/admin/export')
def admin_export():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    result = supabase.table('entries').select('*').order('created_at', desc=True).execute()
    entries = result.data

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Mobile', 'Email', 'Instagram',
                     'Competition', 'Captured', 'Status',
                     'Media URL', 'Registered At', 'Submitted At'])
    for e in entries:
        writer.writerow([e.get(k, '') for k in [
            'id', 'name', 'mobile', 'email', 'instagram',
            'competition', 'captured', 'status',
            'media_url', 'created_at', 'submitted_at'
        ]])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=ganpati_entries.csv'}
    )


if __name__ == '__main__':
    app.run(debug=True)
