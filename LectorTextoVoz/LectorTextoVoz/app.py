from flask import Flask, render_template, request, send_file, jsonify
import os
import pdfplumber
import docx
import pyttsx3
import threading
import time
from werkzeug.utils import secure_filename
from threading import Lock

app = Flask(__name__)

# Configuración de directorios (usa rutas absolutas para evitar problemas)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
AUDIO_FOLDER = os.path.join(BASE_DIR, "audios")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

def init_tts_engine():
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 0.9)

    # Configuración específica para sistemas en inglés
    if os.name == 'nt':  # Windows
        # IDs directos de voces en español en Windows
        spanish_voices = [
            'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_ES-ES_HELENA_11.0',  # Español (España)
            'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_ES-MX_HILDA_11.0'    # Español (México)
        ]
        
        for voice_id in spanish_voices:
            try:
                engine.setProperty('voice', voice_id)
                break  # Si funciona, salimos del bucle
            except:
                continue
    
    # Para Linux/Mac (espeak)
    else:
        voices = engine.getProperty('voices')
        for voice in voices:
            langs = getattr(voice, 'languages', [])
            if any(b'es' in lang for lang in langs) or any('es' in str(lang) for lang in langs):
                engine.setProperty('voice', voice.id)
                break

    return engine

engine = init_tts_engine()

# Sistema de estado
class ConversionStatus:
    def __init__(self):
        self.lock = Lock()
        self.status = {
            'progress': 0,
            'filename': None,
            'ready': False,
            'error': None
        }
    
    def update(self, **kwargs):
        with self.lock:
            self.status.update(kwargs)
    
    def get_status(self):
        with self.lock:
            return self.status.copy()

status = ConversionStatus()

def text_to_speech(text, filename):
    try:
        safe_name = secure_filename(filename)
        output_path = os.path.join(AUDIO_FOLDER, safe_name)
        
        # Limpiar archivo existente si lo hay
        if os.path.exists(output_path):
            os.remove(output_path)
        
        # Asegurar que el directorio existe
        os.makedirs(AUDIO_FOLDER, exist_ok=True)
        
        # Dividir texto en partes
        parts = [text[i:i+2000] for i in range(0, len(text), 2000)]
        
        for i, part in enumerate(parts):
            temp_file = os.path.join(AUDIO_FOLDER, f'temp_{i}_{safe_name}')
            engine.save_to_file(part, temp_file)
            engine.runAndWait()
            
            # Actualizar progreso
            progress = min(100, int((i + 1) / len(parts) * 100))
            status.update(progress=progress)
        
        # Combinar partes si es necesario
        if len(parts) > 1:
            from pydub import AudioSegment
            combined = AudioSegment.empty()
            for i in range(len(parts)):
                temp_file = os.path.join(AUDIO_FOLDER, f'temp_{i}_{safe_name}')
                combined += AudioSegment.from_mp3(temp_file)
                os.remove(temp_file)
            combined.export(output_path, format='mp3')
        else:
            os.rename(os.path.join(AUDIO_FOLDER, f'temp_0_{safe_name}'), output_path)
        
        status.update(progress=100, ready=True)
        return True
    
    except Exception as e:
        status.update(error=str(e), progress=0)
        print(f"Error en text_to_speech: {str(e)}")
        return False

@app.route('/progress')
def progress():
    return jsonify(status.get_status())

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'archivo' not in request.files:
            return jsonify({'error': 'No se subió ningún archivo'}), 400
            
        file = request.files['archivo']
        if not file.filename:
            return jsonify({'error': 'Nombre de archivo vacío'}), 400
        
        try:
            status.update(progress=0, ready=False, error=None)
            
            # Extraer texto
            text = ''
            if file.filename.lower().endswith('.pdf'):
                with pdfplumber.open(file.stream) as pdf:
                    text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
            elif file.filename.lower().endswith('.docx'):
                doc = docx.Document(file.stream)
                text = '\n'.join(p.text for p in doc.paragraphs)
            
            if not text.strip():
                return jsonify({'error': 'No se pudo extraer texto'}), 400
            
            # Iniciar conversión
            output_name = f"{os.path.splitext(secure_filename(file.filename))[0]}.mp3"
            status.update(filename=output_name)
            
            thread = threading.Thread(
                target=text_to_speech,
                args=(text, output_name)
            )
            thread.start()
            
            return jsonify({
                'status': 'processing',
                'filename': output_name
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return render_template('index.html')

@app.route('/download/<filename>')
def download(filename):
    safe_name = secure_filename(filename)
    filepath = os.path.join(AUDIO_FOLDER, safe_name)
    
    # Verificar existencia del archivo
    if not os.path.exists(filepath):
        return jsonify({'error': 'Archivo no encontrado'}), 404
    
    try:
        return send_file(
            filepath,
            as_attachment=True,
            download_name=safe_name,
            mimetype='audio/mpeg'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Verificar voces disponibles
    print("Voces disponibles:")
    for voice in engine.getProperty('voices'):
        print(f"- {voice.name} (Id: {voice.id}, Idiomas: {getattr(voice, 'languages', 'Desconocido')}")
    
    app.run(debug=True)