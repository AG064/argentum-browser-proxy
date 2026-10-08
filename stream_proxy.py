from resource_limits import JOB_BUDGET
#!/usr/bin/env python3
"""
Real-time video/audio transcoding proxy for PS4
Converts any video to HLS stream that PS4 can play
"""
import subprocess
import os
from pathlib import Path
from path_security import contained_file, remove_stream_directory
import signal
import uuid
import threading
import time
from flask import Flask, request, Response, send_file, redirect
from urllib.parse import unquote

app = Flask(__name__)

# FFmpeg settings for PS4 compatible output
FFMPEG_HLS = [
    'ffmpeg',
    '-re',  # Read at native frame rate
    '-i', '{input}',
    '-c:v', 'libx264',
    '-preset', 'ultrafast',
    '-tune', 'zerolatency',
    '-profile:v', 'main',
    '-level', '3.1',
    '-pix_fmt', 'yuv420p',
    '-b:v', '4000k',
    '-maxrate', '5000k',
    '-bufsize', '10000k',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-ar', '48000',
    '-ac', '2',
    '-f', 'hls',
    '-hls_time', '2',
    '-hls_list_size', '6',
    '-hls_flags', 'delete_segments',
    '-hls_segment_filename', '{segment_dir}/segment_%03d.ts',
    '{output}'
]

STREAMS = {}
JOB_BUDGET.install(app, ['stream', 'proxy'])
STREAM_DIR = str(JOB_BUDGET.database.parent / 'hls')

os.makedirs(STREAM_DIR, exist_ok=True)

def cleanup_stream(stream_id):
    JOB_BUDGET.stop(STREAMS, stream_id)

@app.route('/stream')
def stream():
    """
    Start a transcoding stream
    GET /stream?url=<video_url>
    Returns: JSON with stream_id and playlist URL
    """
    video_url = request.args.get('url', '')
    if not video_url:
        return {'error': 'No URL provided'}, 400
    
    video_url = unquote(video_url)
    stream_id = uuid.uuid4().hex[:16]
    segment_dir = f"{STREAM_DIR}/{uuid.uuid4().hex}"
    
    playlist_path = f"{segment_dir}/playlist.m3u8"
    
    cmd = [
        'ffmpeg',
        '-re',
        '-i', video_url,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-profile:v', 'main',
        '-level', '3.1',
        '-pix_fmt', 'yuv420p',
        '-b:v', '4000k',
        '-maxrate', '5000k',
        '-bufsize', '10000k',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ar', '48000',
        '-ac', '2',
        '-f', 'hls',
        '-hls_time', '2',
        '-hls_list_size', '6',
        '-hls_flags', 'delete_segments',
        '-hls_segment_filename', f'{segment_dir}/segment_%03d.ts',
        playlist_path
    ]
    
    try:
        proc = JOB_BUDGET.start(cmd, STREAMS, stream_id, segment_dir, STREAM_DIR, {'playlist': playlist_path, 'url': video_url})
        
        # Give ffmpeg a moment to start
        time.sleep(2)
        
        if proc.poll() is not None:
            # Process already finished (error)
            stderr = proc.stderr.read().decode('utf-8', errors='replace')
            return {'error': 'FFmpeg failed to start', 'details': stderr[:500]}, 500
        
        return {
            'stream_id': stream_id,
            'playlist_url': f'/hls/{stream_id}/playlist.m3u8',
            'status': 'started'
        }
        
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/hls/<stream_id>/<path:filename>')
def hls_files(stream_id, filename):
    return JOB_BUDGET.serve_hls(STREAMS, stream_id, filename)

@app.route('/status/<stream_id>')
def status(stream_id):
    """Check stream status"""
    info = JOB_BUDGET.snapshot(STREAMS, stream_id)
    if info is None:
        return {'error': 'Stream not found'}, 404

    proc = info.get('process')
    
    return {
        'stream_id': stream_id,
        'running': proc is not None and proc.poll() is None,
        'uptime': time.time() - info.get('started', 0),
        'url': info.get('url', '')
    }

@app.route('/stop/<stream_id>')
def stop(stream_id):
    """Stop a stream"""
    cleanup_stream(stream_id)
    return {'status': 'stopped'}

@app.route('/proxy')
def proxy():
    """
    Full proxy with real-time transcoding
    GET /proxy?url=<video_url>
    Returns HLS stream directly
    """
    video_url = request.args.get('url', '')
    if not video_url:
        return {'error': 'No URL provided'}, 400
    
    video_url = unquote(video_url)
    stream_id = 'direct'
    segment_dir = f"{STREAM_DIR}/{uuid.uuid4().hex}"
    
    playlist_path = f"{segment_dir}/playlist.m3u8"
    
    cmd = [
        'ffmpeg',
        '-re',
        '-i', video_url,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-profile:v', 'main',
        '-level', '3.1',
        '-pix_fmt', 'yuv420p',
        '-b:v', '4000k',
        '-maxrate', '5000k',
        '-bufsize', '10000k',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ar', '48000',
        '-ac', '2',
        '-f', 'hls',
        '-hls_time', '2',
        '-hls_list_size', '6',
        '-hls_flags', 'delete_segments',
        '-hls_segment_filename', f'{segment_dir}/segment_%03d.ts',
        playlist_path
    ]
    
    try:
        proc = JOB_BUDGET.start(cmd, STREAMS, stream_id, segment_dir, STREAM_DIR, {'playlist': playlist_path, 'url': video_url})
        
        time.sleep(2)
        
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode('utf-8', errors='replace')
            return {'error': 'FFmpeg failed', 'details': stderr[:500]}, 500
        
        # Redirect to HLS playlist
        return redirect(f'/hls/direct/playlist.m3u8')
        
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8788, debug=False)
