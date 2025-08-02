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
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Accept-Encoding': 'gzip,deflate',
            'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['dash', 'hls'],
                'player_skip': ['configs', 'webpage']
            }
        }
    }
    
    if download:
        opts.update({
            'ignoreerrors': True,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True
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
    """Video indirme"""
    try:
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', '720p')
        
        if not url:
            return jsonify({"error": "URL gerekli"}), 400
        
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({"error": "Geçersiz YouTube URL"}), 400
        
        # Format seçimi
        if quality == 'audio':
            format_selector = 'bestaudio[ext=m4a]/bestaudio'
            ext = 'mp3'
        elif quality == 'highest':
            format_selector = 'best[height<=1080][ext=mp4]/best[height<=1080]/best'
            ext = 'mp4'
        elif quality == '1080p':
            format_selector = 'best[height<=1080][ext=mp4]/best[height<=1080]/best'
            ext = 'mp4'
        elif quality == '720p':
            format_selector = 'best[height<=720][ext=mp4]/best[height<=720]/best'
            ext = 'mp4'
        elif quality == '480p':
            format_selector = 'best[height<=480][ext=mp4]/best[height<=480]/best'
            ext = 'mp4'
        else:  # 360p
            format_selector = 'best[height<=360][ext=mp4]/best[height<=360]/best'
            ext = 'mp4'
        
        # Güvenli dosya adı
        safe_filename = f"video_{video_id}_{quality}_{int(time.time())}.{ext}"
        output_path = os.path.join(TEMP_DIR, safe_filename)
        
        # Bot koruması bypass eden ayarlar
        ydl_opts = get_ydl_opts(download=True)
        ydl_opts.update({
            'format': format_selector,
            'outtmpl': output_path,
        })
        
        # Ses için özel işlem
        if quality == 'audio':
            ydl_opts.update({
                'format': 'bestaudio',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'prefer_ffmpeg': True,
            })
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Önce bilgi al
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("Video bilgisi alınamadı")
                
                title = info.get('title', 'video')
                safe_title = re.sub(r'[^\w\-_\.]', '_', title[:50])
                final_filename = f"{safe_title}_{quality}.{ext}"
                final_path = os.path.join(TEMP_DIR, final_filename)
                
                # Çıktı dosyasını güncelle
                ydl_opts['outtmpl'] = final_path
                ydl.params.update(ydl_opts)
                
                # Video indir
                ydl.download([url])
                
                # Dosya kontrolü
                downloaded_file = None
                if os.path.exists(final_path) and os.path.getsize(final_path) > 1000:
                    downloaded_file = final_path
                else:
                    # Alternatif dosya adlarını kontrol et
                    for file in os.listdir(TEMP_DIR):
                        file_path = os.path.join(TEMP_DIR, file)
                        if (video_id in file or safe_title[:20] in file) and os.path.getsize(file_path) > 1000:
                            downloaded_file = file_path
                            final_filename = file
                            break
                
                if not downloaded_file:
                    raise Exception("İndirme tamamlanamadı - dosya bulunamadı")
                
                file_size = os.path.getsize(downloaded_file)
                
                # Eski dosyaları temizle
                threading.Thread(target=cleanup_old_files, daemon=True).start()
                
                return jsonify({
                    "success": True,
                    "message": "Video başarıyla indirildi",
                    "download_url": f"/api/file/{os.path.basename(downloaded_file)}",
                    "file_size": file_size,
                    "filename": os.path.basename(downloaded_file)
                })
                
        except Exception as download_error:
            print(f"Download error: {download_error}")
            raise Exception(f"İndirme hatası: {str(download_error)}")
        
    except Exception as e:
        print(f"General error in download_video: {e}")
        return jsonify({"error": f"İndirme hatası: {str(e)}"}), 500

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
