import os
import io
import csv
from datetime import datetime, timezone
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, Response)
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'ganpati-aagman-secret-2026')
app.config['MAX_CONTENT_LENGTH'] = 1100 * 1024 * 1024  # 1.1 GB max upload (1 GB video / 512 MB photo)

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


@app.route('/api/submit', methods=['POST'])
def api_submit():
    try:
        entry_id = request.form.get('id')
        file = request.files.get('media')

        if not file or not entry_id:
            return jsonify({'success': False, 'error': 'Missing file or id'}), 400

        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'bin'
        filename = f"{entry_id}.{ext}"
        file_bytes = file.read()

        # Upload to Supabase Storage
        supabase.storage.from_('uploads').upload(
            filename,
            file_bytes,
            {'content-type': file.content_type or 'application/octet-stream', 'upsert': 'true'}
        )
        public_url = supabase.storage.from_('uploads').get_public_url(filename)

        # Update DB row
        supabase.table('entries').update({
            'status':         'submitted',
            'media_url':      public_url,
            'media_filename': file.filename,
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
