from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import threading
import time
from urllib.parse import urlparse, parse_qs
import re

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Geçici dosyalar için dizin
TEMP_DIR = tempfile.mkdtemp()

def clean_filename(filename):
    """Dosya adını temizle"""
    # Özel karakterleri kaldır
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Uzunluğu sınırla
    if len(filename) > 100:
        filename = filename[:100]
    return filename

def extract_video_id(url):
    """YouTube URL'den video ID'sini çıkar"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([^&\n?#]+)',
        r'youtube\.com\/watch\?.*v=([^&\n?#]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def cleanup_old_files():
    """Eski dosyaları temizle (1 saat sonra)"""
    try:
        for filename in os.listdir(TEMP_DIR):
            filepath = os.path.join(TEMP_DIR, filename)
            if os.path.isfile(filepath):
                # 1 saatten eski dosyaları sil
                if time.time() - os.path.getctime(filepath) > 3600:
                    os.remove(filepath)
    except Exception as e:
        print(f"Cleanup error: {e}")

def get_ydl_opts(download=False):
    """Bot koruması bypass eden yt-dlp ayarları"""
    import random
    
    # Farklı user agent'lar rotasyonu
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
    ]
    
    selected_ua = random.choice(user_agents)
    
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'user_agent': selected_ua,
        'referer': 'https://www.youtube.com/',
        'sleep_interval': 2,  # İstekler arası bekleme
        'max_sleep_interval': 5,
        'http_headers': {
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android_creator', 'android', 'web'],
                'skip': ['dash', 'hls'],
                'player_skip': ['configs', 'webpage'],
                'innertube_host': 'studio.youtube.com',
                'innertube_key': 'AIzaSyBUPetSUmoZL-OhlxA7wSac5XinrygCqMo'
            }
        },
        'geo_bypass': True,
        'geo_bypass_country': 'US'
    }
    
    if download:
        opts.update({
            'ignoreerrors': True,
            'retries': 5,
            'fragment_retries': 5,
            'skip_unavailable_fragments': True,
            'keep_video': False,
            'embed_chapters': False,
            'embed_info_json': False
        })
    
    return opts

@app.route('/')
def home():
    return jsonify({
        "message": "YouTube İndirici API",
        "version": "1.0",
        "endpoints": {
            "/api/info": "Video bilgilerini al",
            "/api/download": "Video indir",
            "/api/formats": "Mevcut formatları listele"
        }
    })

@app.route('/api/info', methods=['POST'])
def get_video_info():
    """Video bilgilerini al"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "URL gerekli"}), 400
        
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({"error": "Geçersiz YouTube URL"}), 400
        
        # Bot koruması bypass eden ayarlar
        ydl_opts = get_ydl_opts(download=False)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    raise Exception("Video bilgileri alınamadı")
                
                # Mevcut formatları al
                formats = []
                if 'formats' in info and info['formats']:
                    seen_qualities = set()
                    for fmt in info['formats']:
                        if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                            height = fmt.get('height')
                            if height and height not in seen_qualities and height >= 240:
                                formats.append({
                                    'quality': f"{height}p",
                                    'format_id': fmt['format_id'],
                                    'ext': fmt.get('ext', 'mp4'),
                                    'filesize': fmt.get('filesize')
                                })
                                seen_qualities.add(height)
                    
                    # Sadece ses için format ekle
                    for fmt in info['formats']:
                        if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none':
                            formats.append({
                                'quality': 'audio',
                                'format_id': fmt['format_id'],
                                'ext': fmt.get('ext', 'mp3'),
                                'filesize': fmt.get('filesize')
                            })
                            break
                
                # Süreyi formatla
                duration = info.get('duration', 0)
                duration_str = "Bilinmiyor"
                if duration:
                    hours = duration // 3600
                    minutes = (duration % 3600) // 60
                    seconds = duration % 60
                    if hours > 0:
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration_str = f"{minutes:02d}:{seconds:02d}"
                
                return jsonify({
                    "success": True,
                    "video": {
                        "id": video_id,
                        "title": info.get('title', 'Bilinmeyen Video'),
                        "channel": info.get('uploader', 'Bilinmeyen Kanal'),
                        "duration": duration_str,
                        "views": info.get('view_count', 0),
                        "thumbnail": info.get('thumbnail', f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'),
                        "description": (info.get('description', '') or '')[:200] + '...' if info.get('description') else 'Açıklama yok',
                        "upload_date": info.get('upload_date', ''),
                        "formats": formats[:10]
                    }
                })
                
            except Exception as extract_error:
                print(f"Extract error: {extract_error}")
                raise Exception(f"Video bilgisi çıkarılamadı: {str(extract_error)}")
            
    except Exception as e:
        print(f"General error in get_video_info: {e}")
        return jsonify({"error": f"Video bilgisi alınamadı: {str(e)}"}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    """Video indirme - External site yönlendirmesi"""
    try:
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', '720p')
        
        if not url:
            return jsonify({"error": "URL gerekli"}), 400
        
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({"error": "Geçersiz YouTube URL"}), 400
        
        # External download services
        external_services = {
            'highest': f'https://www.y2mate.com/youtube/{video_id}',
            '1080p': f'https://www.y2mate.com/youtube/{video_id}',
            '720p': f'https://www.y2mate.com/youtube/{video_id}',
            '480p': f'https://www.y2mate.com/youtube/{video_id}',
            '360p': f'https://www.y2mate.com/youtube/{video_id}',
            'audio': f'https://ytmp3.cc/en13/{video_id}/'
        }
        
        download_url = external_services.get(quality, external_services['720p'])
        
        return jsonify({
            "success": True,
            "message": "İndirme sitesine yönlendiriliyorsunuz",
            "external_url": download_url,
            "quality": quality,
            "instructions": "Yeni sekmede açılan siteden videonuzu indirebilirsiniz."
        })
        
    except Exception as e:
        print(f"Download redirect error: {e}")
        return jsonify({"error": f"Yönlendirme hatası: {str(e)}"}), 500

@app.route('/api/file/<filename>')
def download_file(filename):
    """Dosyayı indir"""
    try:
        file_path = os.path.join(TEMP_DIR, filename)
        
        if not os.path.exists(file_path):
            return jsonify({"error": "Dosya bulunamadı"}), 404
        
        # Güvenlik kontrolü
        if not os.path.commonpath([file_path, TEMP_DIR]) == TEMP_DIR:
            return jsonify({"error": "Geçersiz dosya yolu"}), 403
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"File download error: {e}")
        return jsonify({"error": f"Dosya indirme hatası: {str(e)}"}), 500

@app.route('/api/formats', methods=['POST'])
def get_available_formats():
    """Mevcut formatları listele"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "URL gerekli"}), 400
        
        ydl_opts = get_ydl_opts(download=False)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            if 'formats' in info:
                for fmt in info['formats']:
                    formats.append({
                        'format_id': fmt['format_id'],
                        'ext': fmt.get('ext'),
                        'quality': fmt.get('format_note'),
                        'height': fmt.get('height'),
                        'width': fmt.get('width'),
                        'filesize': fmt.get('filesize'),
                        'vcodec': fmt.get('vcodec'),
                        'acodec': fmt.get('acodec')
                    })
            
            return jsonify({
                "success": True,
                "formats": formats
            })
            
    except Exception as e:
        print(f"Formats error: {e}")
        return jsonify({"error": f"Format listesi alınamadı: {str(e)}"}), 500

@app.route('/health')
def health_check():
    """Sağlık kontrolü"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time()
    })

if __name__ == '__main__':
    # Geliştirme ortamında çalıştır
    app.run(debug=True, host='0.0.0.0', port=5000)
