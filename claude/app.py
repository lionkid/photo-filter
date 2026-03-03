import os
import cv2
import json
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_file

app = Flask(__name__)

EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.heic')

# ── Job registry ─────────────────────────────────────────────────────────────
# job_id → {"event_queue": Queue, "cancel_flag": Event, "thread": Thread,
#            "state": dict}
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

# Directories the server has seen (used for thumbnail security check)
registered_dirs: set[str] = set()
registered_dirs_lock = threading.Lock()


def register_dir(path: str):
    with registered_dirs_lock:
        registered_dirs.add(os.path.realpath(path))


def is_allowed_path(path: str) -> bool:
    real = os.path.realpath(path)
    with registered_dirs_lock:
        return any(real.startswith(d) for d in registered_dirs)


# ── Image helpers ─────────────────────────────────────────────────────────────

def load_image_cv2(img_path: str):
    """Load image as cv2 BGR array; handles HEIC via Pillow."""
    if img_path.lower().endswith('.heic'):
        try:
            from pillow_heif import register_heif_opener
            from PIL import Image
            register_heif_opener()
            pil_img = Image.open(img_path).convert('RGB')
            return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    img = cv2.imread(img_path)
    return img


def count_images(directory: str) -> tuple[int, int]:
    """Return (image_count, folder_count) for a directory tree."""
    img_count = 0
    folder_set: set[str] = set()
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(EXTENSIONS):
                img_count += 1
                folder_set.add(root)
    return img_count, len(folder_set)


# ── InsightFace wrapper ───────────────────────────────────────────────────────

class FaceModel:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                from insightface.app import FaceAnalysis
                fa = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
                fa.prepare(ctx_id=-1, det_size=(640, 640))
                cls._instance = fa
            return cls._instance


def get_embedding(img_path: str, face_model):
    """Return normalized embedding of largest face, or None."""
    try:
        img = load_image_cv2(img_path)
        if img is None:
            return None
        faces = face_model.get(img)
        if not faces:
            return None
        faces = sorted(
            faces,
            key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]),
            reverse=True,
        )
        emb = faces[0].embedding
        return emb / np.linalg.norm(emb)
    except Exception:
        return None


# ── Face processing (runs in background thread) ───────────────────────────────

def run_filter_job(job_id: str, reference_dir: str, source_dir: str,
                   output_dir: str, threshold: float):
    job = jobs[job_id]
    q: queue.Queue = job['event_queue']
    cancel: threading.Event = job['cancel_flag']

    def emit(event: str, data: dict):
        q.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")

    try:
        # ── 1. Load model ──────────────────────────────────────────────────
        emit('status', {'phase': 'loading', 'message': 'Loading face recognition model (may download ~300 MB on first run)…'})
        face_model = FaceModel.get()

        if cancel.is_set():
            emit('status', {'phase': 'cancelled', 'message': 'Cancelled.'})
            return

        # ── 2. Build reference profile ─────────────────────────────────────
        emit('status', {'phase': 'reference', 'message': 'Analyzing reference photos…'})
        ref_images = [
            os.path.join(reference_dir, f)
            for f in os.listdir(reference_dir)
            if f.lower().endswith(EXTENSIONS)
        ]
        if not ref_images:
            emit('error', {'message': 'No images found in reference directory.'})
            return

        embeddings = []
        for path in ref_images:
            if cancel.is_set():
                emit('status', {'phase': 'cancelled', 'message': 'Cancelled.'})
                return
            emb = get_embedding(path, face_model)
            if emb is not None:
                embeddings.append(emb)

        if not embeddings:
            emit('error', {'message': 'No faces detected in reference photos. Please use clearer photos.'})
            return

        mean_emb = np.mean(embeddings, axis=0)
        target_embedding = mean_emb / np.linalg.norm(mean_emb)
        emit('status', {'phase': 'reference', 'message': f'Reference profile built from {len(embeddings)} face(s).'})

        if cancel.is_set():
            emit('status', {'phase': 'cancelled', 'message': 'Cancelled.'})
            return

        # ── 3. Collect source images ───────────────────────────────────────
        emit('status', {'phase': 'scanning', 'message': 'Scanning source directory…'})
        image_files = []
        for root, _dirs, files in os.walk(source_dir):
            for f in files:
                if f.lower().endswith(EXTENSIONS):
                    image_files.append(os.path.join(root, f))
        total = len(image_files)
        emit('status', {'phase': 'scanning', 'message': f'Found {total} images. Starting face matching…'})

        if total == 0:
            emit('error', {'message': 'No images found in source directory.'})
            return

        # ── 4. Process images ──────────────────────────────────────────────
        os.makedirs(output_dir, exist_ok=True)
        matched = 0
        start_time = time.time()

        for i, img_path in enumerate(image_files):
            if cancel.is_set():
                emit('status', {'phase': 'cancelled', 'message': 'Cancelled by user.'})
                return

            try:
                img = load_image_cv2(img_path)
                if img is None:
                    continue
                faces = face_model.get(img)
                for face in faces:
                    face_emb = face.embedding / np.linalg.norm(face.embedding)
                    sim = float(np.dot(face_emb, target_embedding))
                    if sim > threshold:
                        # Copy preserving subdirectory structure
                        rel = os.path.relpath(img_path, start=source_dir)
                        dest = os.path.join(output_dir, rel)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.copy2(img_path, dest)
                        matched += 1
                        break
            except Exception:
                pass

            # Emit progress every image (or at least every 10 to avoid flooding)
            done = i + 1
            if done % 1 == 0 or done == total:
                elapsed = time.time() - start_time
                eta = (elapsed / done) * (total - done) if done > 0 else 0
                emit('progress', {
                    'phase': 'processing',
                    'done': done,
                    'total': total,
                    'matched': matched,
                    'elapsed_sec': round(elapsed, 1),
                    'eta_sec': round(eta, 1),
                })

        elapsed = time.time() - start_time
        emit('complete', {
            'matched': matched,
            'total': total,
            'output_dir': output_dir,
            'elapsed_sec': round(elapsed, 1),
        })

    except Exception as e:
        emit('error', {'message': str(e)})
    finally:
        q.put(None)  # sentinel


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/validate-dir', methods=['POST'])
def validate_dir():
    data = request.get_json(force=True)
    path = data.get('path', '').strip()
    if not path or not os.path.isdir(path):
        return jsonify({'valid': False, 'error': 'Directory not found'})
    register_dir(path)
    img_count, folder_count = count_images(path)
    return jsonify({'valid': True, 'images': img_count, 'folders': folder_count})


@app.route('/api/scan-references', methods=['POST'])
def scan_references():
    data = request.get_json(force=True)
    path = data.get('path', '').strip()
    if not path or not os.path.isdir(path):
        return jsonify({'error': 'Directory not found'}), 400
    register_dir(path)
    images = [
        f for f in os.listdir(path) if f.lower().endswith(EXTENSIONS)
    ]
    thumbnails = [
        {'name': f, 'url': f'/api/thumbnail?path={os.path.join(path, f)}'}
        for f in sorted(images)
    ]
    return jsonify({'thumbnails': thumbnails, 'count': len(thumbnails)})


@app.route('/api/thumbnail')
def thumbnail():
    path = request.args.get('path', '')
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'File not found'}), 404
    if not is_allowed_path(path):
        return jsonify({'error': 'Access denied'}), 403

    try:
        if path.lower().endswith('.heic'):
            from pillow_heif import register_heif_opener
            from PIL import Image
            register_heif_opener()
            img = Image.open(path).convert('RGB')
        else:
            from PIL import Image
            img = Image.open(path).convert('RGB')

        img.thumbnail((200, 200))
        import io
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=80)
        buf.seek(0)
        return send_file(buf, mimetype='image/jpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reveal')
def reveal():
    path = request.args.get('path', '')
    if path and os.path.exists(path):
        os.system(f'open {repr(path)}')
        return jsonify({'ok': True})
    return jsonify({'error': 'Path not found'}), 404


@app.route('/api/start', methods=['POST'])
def start_job():
    data = request.get_json(force=True)
    reference_dir = data.get('reference_dir', '').strip()
    source_dir = data.get('source_dir', '').strip()
    output_dir = data.get('output_dir', '').strip()
    threshold = float(data.get('threshold', 0.55))

    for d in (reference_dir, source_dir):
        if not os.path.isdir(d):
            return jsonify({'error': f'Directory not found: {d}'}), 400
    if not output_dir:
        return jsonify({'error': 'Output directory required'}), 400

    job_id = str(uuid.uuid4())
    cancel_flag = threading.Event()
    event_queue: queue.Queue = queue.Queue()

    with jobs_lock:
        jobs[job_id] = {
            'event_queue': event_queue,
            'cancel_flag': cancel_flag,
            'thread': None,
        }

    t = threading.Thread(
        target=run_filter_job,
        args=(job_id, reference_dir, source_dir, output_dir, threshold),
        daemon=True,
    )
    jobs[job_id]['thread'] = t
    t.start()

    return jsonify({'job_id': job_id})


@app.route('/api/progress')
def progress():
    job_id = request.args.get('job_id', '')
    if not job_id or job_id not in jobs:
        return jsonify({'error': 'Unknown job'}), 404

    q = jobs[job_id]['event_queue']

    def generate():
        while True:
            try:
                msg = q.get(timeout=30)
            except queue.Empty:
                yield ': keepalive\n\n'
                continue
            if msg is None:
                return
            yield msg

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/cancel', methods=['POST'])
def cancel_job():
    data = request.get_json(force=True)
    job_id = data.get('job_id', '')
    if job_id in jobs:
        jobs[job_id]['cancel_flag'].set()
        return jsonify({'ok': True})
    return jsonify({'error': 'Unknown job'}), 404


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
