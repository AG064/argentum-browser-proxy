#!/usr/bin/env python3
"""
Argentum Browser - Full browser interface for PS4
Features:
- URL bar with navigation
- Video detection and transcoding
- Cloudflare bypass
- Keyboard support for PS4
- Gamepad navigation
"""
from flask import Flask, request, Response, render_template_string, redirect
from urllib.parse import quote, unquote
import os
import uuid
import time
import subprocess
import signal

app = Flask(__name__)

STREAM_DIR = '/tmp/hls_browser'
os.makedirs(STREAM_DIR, exist_ok=True)
STREAMS = {}

MAIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Argentum Browser</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { 
            height: 100%; 
            background: #0a0a0a; 
            color: #fff; 
            font-family: 'Segoe UI', Arial, sans-serif; 
            overflow: hidden;
        }
        
        /* Header / URL Bar */
        .header {
            background: #1a1a1a;
            padding: 12px;
            border-bottom: 2px solid #333;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .nav-btn {
            background: #2a2a2a;
            border: 1px solid #444;
            color: #fff;
            width: 44px;
            height: 44px;
            font-size: 18px;
            cursor: pointer;
            border-radius: 6px;
        }
        .nav-btn:hover { background: #3a3a3a; }
        .nav-btn:active { background: #555; }
        
        .url-bar {
            flex: 1;
            background: #2a2a2a;
            border: 1px solid #444;
            color: #fff;
            padding: 12px 16px;
            font-size: 16px;
            border-radius: 6px;
            outline: none;
        }
        .url-bar:focus { border-color: #f0a500; }
        
        .go-btn {
            background: #f0a500;
            border: none;
            color: #000;
            padding: 12px 20px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            border-radius: 6px;
        }
        .go-btn:hover { background: #ffb520; }
        
        /* Main content area */
        .content {
            height: calc(100% - 68px);
            display: flex;
            flex-direction: column;
        }
        
        iframe {
            flex: 1;
            border: none;
            background: #fff;
        }
        
        /* Video player overlay */
        .video-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: #000;
            z-index: 9999;
            display: none;
        }
        .video-overlay.active { display: flex; flex-direction: column; }
        
        .video-header {
            background: #1a1a1a;
            padding: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .video-title {
            color: #f0a500;
            font-size: 16px;
            max-width: 70%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .close-btn {
            background: #d32f2f;
            border: none;
            color: #fff;
            width: 44px;
            height: 44px;
            font-size: 24px;
            cursor: pointer;
            border-radius: 6px;
        }
        
        .video-container {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #000;
        }
        .video-container video {
            max-width: 100%;
            max-height: 100%;
        }
        
        .video-controls {
            background: #1a1a1a;
            padding: 12px;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .ctrl-btn {
            background: #333;
            border: 1px solid #555;
            color: #fff;
            padding: 10px 16px;
            font-size: 14px;
            cursor: pointer;
            border-radius: 6px;
        }
        .ctrl-btn:hover { background: #444; }
        .ctrl-btn.active { background: #f0a500; color: #000; }
        
        .progress-bar {
            flex: 1;
            height: 8px;
            background: #333;
            border-radius: 4px;
            cursor: pointer;
        }
        .progress-fill {
            height: 100%;
            background: #f0a500;
            border-radius: 4px;
            width: 0%;
            transition: width 0.1s;
        }
        
        /* Transcoding status */
        .transcode-status {
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(26, 26, 26, 0.95);
            border: 2px solid #f0a500;
            padding: 20px 40px;
            border-radius: 12px;
            text-align: center;
            z-index: 10000;
            display: none;
        }
        .transcode-status.active { display: block; }
        .transcode-status h3 { color: #f0a500; margin-bottom: 10px; }
        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid #333;
            border-top-color: #f0a500;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        /* PS4 controller hints */
        .controller-hints {
            position: fixed;
            bottom: 10px;
            left: 10px;
            background: rgba(0,0,0,0.8);
            padding: 10px 15px;
            border-radius: 8px;
            font-size: 12px;
            color: #888;
            z-index: 100;
        }
        .controller-hints span { color: #f0a500; }
        
        /* Loading screen */
        .loading {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: #0a0a0a;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 99999;
        }
        .loading.hidden { display: none; }
        .loading h1 { color: #f0a500; font-size: 32px; margin-bottom: 30px; }
        .loading .spinner {
            width: 60px;
            height: 60px;
            border-width: 6px;
        }
    </style>
</head>
<body>
    <div class="loading" id="loading">
        <h1>Argentum Browser</h1>
        <div class="spinner"></div>
        <p>Loading...</p>
    </div>

    <div class="header">
        <button class="nav-btn" onclick="goBack()" title="Back">←</button>
        <button class="nav-btn" onclick="goForward()" title="Forward">→</button>
        <button class="nav-btn" onclick="goHome()" title="Home">⌂</button>
        <input type="text" class="url-bar" id="urlBar" placeholder="Enter URL or search..." value="{{ home_url }}">
        <button class="go-btn" onclick="navigate()">Go</button>
    </div>
    
    <div class="content">
        <iframe id="browserFrame" src="{{ home_url }}"></iframe>
    </div>
    
    <div class="video-overlay" id="videoOverlay">
        <div class="video-header">
            <span class="video-title" id="videoTitle">Video</span>
            <button class="close-btn" onclick="closeVideo()">×</button>
        </div>
        <div class="video-container">
            <video id="videoPlayer" controls autoplay>
                <source id="videoSource" type="application/vnd.apple.mpegurl">
            </video>
        </div>
        <div class="video-controls">
            <button class="ctrl-btn" onclick="togglePlay()">▶</button>
            <div class="progress-bar" id="progressBar">
                <div class="progress-fill" id="progressFill"></div>
            </div>
            <button class="ctrl-btn" onclick="toggleFullscreen()">⛶</button>
            <button class="ctrl-btn active" id="qualityBtn" onclick="toggleQuality()">Auto</button>
        </div>
    </div>
    
    <div class="transcode-status" id="transcodeStatus">
        <div class="spinner"></div>
        <h3>Transcoding for PS4...</h3>
        <p id="transcodeInfo">Preparing video</p>
    </div>
    
    <div class="controller-hints">
        <span>PS Button</span> Menu | <span>L1/R1</span> Back/Forward | <span>Share</span> Reload
    </div>

    <script>
        var currentUrl = '{{ home_url }}';
        var history = [currentUrl];
        var historyIndex = 0;
        var currentStreamId = null;
        var isTranscoding = false;
        
        // Initialize
        window.onload = function() {
            setTimeout(() => {
                document.getElementById('loading').classList.add('hidden');
            }, 1000);
            
            document.getElementById('urlBar').value = currentUrl;
            detectVideos();
        };
        
        function navigate() {
            var url = document.getElementById('urlBar').value.trim();
            if (!url) return;
            
            // Add protocol if missing
            if (!url.startsWith('http://') && !url.startsWith('https://')) {
                if (url.includes('.') && !url.includes(' ')) {
                    url = 'https://' + url;
                } else {
                    // Treat as search
                    url = 'https://www.google.com/search?q=' + encodeURIComponent(url);
                }
            }
            
            loadURL(url);
        }
        
        function loadURL(url) {
            document.getElementById('loading').style.display = 'flex';
            document.getElementById('loading').classList.remove('hidden');
            
            // Proxy through our server
            var proxyUrl = '/browse?url=' + encodeURIComponent(url);
            document.getElementById('browserFrame').src = proxyUrl;
            currentUrl = url;
            document.getElementById('urlBar').value = url;
            
            // Add to history
            if (historyIndex < history.length - 1) {
                history = history.slice(0, historyIndex + 1);
            }
            history.push(url);
            historyIndex = history.length - 1;
            
            // Detect videos after load
            setTimeout(() => {
                document.getElementById('loading').classList.add('hidden');
                detectVideos();
            }, 2000);
        }
        
        function goBack() {
            if (historyIndex > 0) {
                historyIndex--;
                loadURL(history[historyIndex]);
            }
        }
        
        function goForward() {
            if (historyIndex < history.length - 1) {
                historyIndex++;
                loadURL(history[historyIndex]);
            }
        }
        
        function goHome() {
            loadURL('{{ home_url }}');
        }
        
        // Video detection and handling
        function detectVideos() {
            try {
                var frame = document.getElementById('browserFrame');
                var frameDoc = frame.contentDocument || frame.contentWindow.document;
                
                // Look for video elements
                var videos = frameDoc.querySelectorAll('video');
                var iframes = frameDoc.querySelectorAll('iframe');
                var embeds = frameDoc.querySelectorAll('embed');
                
                console.log('Found:', videos.length, 'videos,', iframes.length, 'iframes,', embeds.length, 'embeds');
                
                // Add click handlers to videos
                videos.forEach(function(video) {
                    video.style.cursor = 'pointer';
                    video.addEventListener('click', function() {
                        playVideo(video.src || video.currentSrc);
                    });
                });
                
                // Check for iframe video players (common)
                iframes.forEach(function(iframe) {
                    var src = iframe.src || '';
                    if (src && !src.includes('youtube.com') && !src.includes('vk.com') && !src.includes('player.vimeo')) {
                        iframe.style.cursor = 'pointer';
                        iframe.addEventListener('click', function() {
                            // Try to detect video URL from iframe
                            var videoUrl = detectVideoFromIframe(iframe);
                            if (videoUrl) {
                                playVideo(videoUrl);
                            }
                        });
                    }
                });
                
            } catch (e) {
                console.log('Cannot access frame content:', e);
            }
        }
        
        function detectVideoFromIframe(iframe) {
            var src = iframe.src || '';
            return src;
        }
        
        function playVideo(videoUrl) {
            if (!videoUrl) return;
            
            showTranscodeStatus('Starting transcoding...');
            
            // Start transcoding stream
            fetch('/browser/stream/start?url=' + encodeURIComponent(videoUrl))
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        hideTranscodeStatus();
                        alert('Error: ' + data.error);
                        return;
                    }
                    
                    currentStreamId = data.stream_id;
                    var hlsUrl = '/browser/hls/' + data.stream_id + '/playlist.m3u8';
                    
                    // Show video player
                    document.getElementById('videoTitle').textContent = videoUrl.split('/').pop();
                    document.getElementById('videoSource').src = hlsUrl;
                    document.getElementById('videoPlayer').load();
                    document.getElementById('videoOverlay').classList.add('active');
                    
                    hideTranscodeStatus();
                    
                    // Start progress monitoring
                    startProgressMonitor();
                })
                .catch(err => {
                    hideTranscodeStatus();
                    alert('Failed to start stream: ' + err);
                });
        }
        
        function closeVideo() {
            var player = document.getElementById('videoPlayer');
            player.pause();
            document.getElementById('videoOverlay').classList.remove('active');
            
            if (currentStreamId) {
                fetch('/browser/stream/stop/' + currentStreamId);
                currentStreamId = null;
            }
        }
        
        function togglePlay() {
            var player = document.getElementById('videoPlayer');
            if (player.paused) {
                player.play();
            } else {
                player.pause();
            }
        }
        
        function toggleFullscreen() {
            var player = document.getElementById('videoPlayer');
            if (player.requestFullscreen) {
                player.requestFullscreen();
            }
        }
        
        function toggleQuality() {
            // Placeholder for quality switching
            alert('Quality: Auto (transcoding)');
        }
        
        function startProgressMonitor() {
            var player = document.getElementById('videoPlayer');
            var progressFill = document.getElementById('progressFill');
            
            player.ontimeupdate = function() {
                if (player.duration) {
                    var percent = (player.currentTime / player.duration) * 100;
                    progressFill.style.width = percent + '%';
                }
            };
        }
        
        function showTranscodeStatus(info) {
            document.getElementById('transcodeInfo').textContent = info;
            document.getElementById('transcodeStatus').classList.add('active');
            isTranscoding = true;
        }
        
        function hideTranscodeStatus() {
            document.getElementById('transcodeStatus').classList.remove('active');
            isTranscoding = false;
        }
        
        // Handle URL bar Enter key
        document.getElementById('urlBar').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                navigate();
            }
        });
        
        // Reload on share button (PS4)
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Share') {
                location.reload();
            }
        });
        
        // Auto-detect videos periodically
        setInterval(detectVideos, 5000);
    </script>
</body>
</html>
'''

@app.route('/browser')
def browser():
    """Main browser interface"""
    home = request.args.get('home', 'https://www.google.com')
    return render_template_string(MAIN_TEMPLATE, home_url=home)

@app.route('/browser/stream/start')
def stream_start():
    """Start a transcoding stream for video"""
    video_url = request.args.get('url', '')
    if not video_url:
        return {'error': 'No URL provided'}, 400
    
    video_url = unquote(video_url)
    stream_id = str(uuid.uuid4())[:8]
    segment_dir = f"{STREAM_DIR}/{stream_id}"
    os.makedirs(segment_dir, exist_ok=True)
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
        '-b:v', '5000k',
        '-maxrate', '6000k',
        '-bufsize', '12000k',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ar', '48000',
        '-ac', '2',
        '-f', 'hls',
        '-hls_time', '2',
        '-hls_list_size', '10',
        '-hls_flags', 'delete_segments',
        '-hls_segment_filename', f'{segment_dir}/segment_%03d.ts',
        playlist_path
    ]
    
    try:
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        
        STREAMS[stream_id] = {
            'process': proc,
            'segment_dir': segment_dir,
            'started': time.time()
        }
        
        time.sleep(2)
        
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode('utf-8', errors='replace')
            return {'error': 'FFmpeg failed', 'details': stderr[:500]}, 500
        
        return {
            'stream_id': stream_id,
            'status': 'started'
        }
        
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/browser/hls/<stream_id>/<path:filename>')
def serve_hls(stream_id, filename):
    """Serve HLS segments"""
    if stream_id not in STREAMS:
        return 'Stream not found', 404
    
    segment_dir = STREAMS[stream_id]['segment_dir']
    file_path = os.path.join(segment_dir, filename)
    
    if not os.path.exists(file_path):
        return 'File not found', 404
    
    if filename.endswith('.m3u8'):
        return Response(
            open(file_path).read(),
            mimetype='application/vnd.apple.mpegurl',
            headers={'Cache-Control': 'no-cache'}
        )
    else:
        return Response(
            open(file_path, 'rb').read(),
            mimetype='video/mp2t'
        )

@app.route('/browser/stream/stop/<stream_id>')
def stream_stop(stream_id):
    """Stop a stream"""
    if stream_id in STREAMS:
        proc = STREAMS[stream_id].get('process')
        if proc:
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except:
                pass
        del STREAMS[stream_id]
    return {'status': 'stopped'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8765, debug=False)
