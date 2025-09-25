"""
flask_server.py

Provides a generic web interface for viewing multiple camera streams.
This has been refactored to be data-driven, based on the global state.

Responsibilities:
- Defines Flask routes for the web UI (/)
- Defines dynamic routes for streaming (/stream/<stream_id>)
- Defines a powerful, multi-stream recording endpoint (/record/start)
- Defines a feeder thread to populate the web view data from the pipelines.
"""

from flask import Flask, Response, render_template, jsonify, request
import threading
import time
import queue
import cv2

# Import the new, generic shared state and recorder API
import shared_state
from recorder import start_recording, get_status

app = Flask(__name__)


# --- Generic Stream Feeder ---
def stream_feeder():
    """Pulls the latest processed frame from each pipeline for web display."""
    while not shared_state.shutdown_requested.is_set():
        # 1. Pull from camera pipelines
        for cam_id, pipeline in shared_state.pipelines.items():
            view_queue_name = f"{cam_id}_process_contours_out"
            if view_queue_name in pipeline.queues:
                view_queue = pipeline.queues[view_queue_name]
                if not view_queue.empty():
                    try:
                        data = view_queue.get_nowait()
                        with shared_state.stream_data_lock:
                            shared_state.stream_data[cam_id] = data
                    except queue.Empty:
                        pass

        # 2. Pull from the fusion worker's final output queue
        if not shared_state.fusion_view_queue.empty():
            try:
                data = shared_state.fusion_view_queue.get_nowait()
                with shared_state.stream_data_lock:
                    shared_state.stream_data['fusion'] = data
            except queue.Empty:
                pass

        time.sleep(0.01)

def start_stream_feeder():
    """Starts the stream_feeder in a background thread."""
    threading.Thread(target=stream_feeder, daemon=True).start()


# --- Web Routes ---

@app.route('/')
def index():
    """Renders the main page, passing the list of available stream IDs."""
    stream_ids = sorted(list(shared_state.pipelines.keys()))
    if hasattr(shared_state, 'fusion_worker') and shared_state.fusion_worker:
        stream_ids.append('fusion')
    
    return render_template('index.html', stream_ids=stream_ids)


@app.route('/stream/<stream_id>')
def stream(stream_id):
    """A dynamic route to serve the video stream for any given camera ID."""
    def gen():
        while not shared_state.shutdown_requested.is_set():
            frame_to_stream = None
            with shared_state.stream_data_lock:
                stream_packet = shared_state.stream_data.get(stream_id)
                if stream_packet:
                    frame_to_stream = stream_packet.get('outlined')
            
            if frame_to_stream is not None:
                ret, jpeg = cv2.imencode('.jpg', frame_to_stream)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            time.sleep(0.01)

    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')


# --- Recording Routes ---

@app.route('/record/start', methods=['POST'])
def start_multiple_recordings():
    """
    Starts recordings for a list of stream IDs provided in a JSON payload.
    Payload format: {"streams": ["cam1", "cam2"], "frame_type": "raw_frame"}
    """
    data = request.get_json()
    if not data or 'streams' not in data:
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    stream_ids = data.get('streams', [])
    frame_type = data.get('frame_type', 'outlined') # Default to 'outlined'
    
    started_count = 0
    for stream_id in stream_ids:
        success = start_recording(stream_id, frame_type=frame_type, duration_s=10.0)
        if success:
            started_count += 1
            
    return jsonify({'status': 'success', 'message': f'Started {started_count} new recordings.'})


@app.route('/record_status')
def record_status():
    """Returns the status of all active recordings."""
    return jsonify(get_status())


__all__ = ['app', 'start_stream_feeder']
