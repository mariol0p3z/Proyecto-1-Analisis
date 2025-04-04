from flask import Flask, render_template, request, send_file, jsonify
import os
import pdfplumber
import docx
from gtts import gTTS
import pyttsx3
import threading
from werkzeug.utils import secure_filename
from threading import Lock
import sys
import re

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
AUDIO_FOLDER = os.path.join(BASE_DIR, "audios")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

class SpanishTTS:
    def __init__(self):
        self.engine = self._init_local_engine()
        self.gtts_fallback = False  

    def _init_local_engine(self):
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')

            spanish_patterns = [
                r'es(-|_)?(mx|es|ar|co|pe|ve|cl|ec|uy|py|bo|cr|do|pa|gt|hn|ni|sv|pr|cu)?',
                r'spanish',
                r'español',
                r'latino',
                r'mexican'
            ]
            
            spanish_voices = []
            for voice in voices:
                voice_id = voice.id.lower()
                voice_name = voice.name.lower()
                
                if any(re.search(pattern, voice_id) or re.search(pattern, voice_name) 
                      for pattern in spanish_patterns):
                    spanish_voices.append(voice)
            
            if spanish_voices:
                selected_voice = spanish_voices[0]
                engine.setProperty('voice', selected_voice.id)
                
                engine.setProperty('rate', 150)  
                engine.setProperty('volume', 0.9)  
                return engine
            else:
                self.gtts_fallback = True
                return None
                
        except Exception as e:
            self.gtts_fallback = True
            return None

    def _force_spanish_gtts(self, text, output_file):
        tld_options = ['com.mx', 'es', 'com.ar', 'com.co', 'com']
        
        for tld in tld_options:
            try:
                tts = gTTS(text=text, lang='es', tld=tld)
                tts.save(output_file)
                
                with open(output_file, 'rb') as f:
                    content = f.read(1000)
                    if b'lang: es' in content or b'lang:es' in content:
                        return True
                    elif b'lang: en' in content:
                        continue
                
                if os.path.getsize(output_file) > 1024: 
                    return True
                    
            except Exception as e:
                continue
                
        return False

    def convert_to_speech(self, text, output_file):
        if not text.strip():
            return False
            
        if self._force_spanish_gtts(text, output_file):
            return True
        
        if self.engine and not self.gtts_fallback:
            try:
                if os.path.exists(output_file):
                    os.remove(output_file)
                
                self.engine.save_to_file(text, output_file)
                self.engine.runAndWait()
                
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    return True
            except Exception as e:
                print(f"Error con motor local: {e}")
        
        return self._force_spanish_gtts(text, output_file)

    def _get_spanish_voice_id(self):
        voices = self.engine.getProperty('voices')
        for voice in voices:
            if 'spanish' in voice.name.lower() or 'español' in voice.name.lower() or 'es' in voice.id.lower():
                return voice.id
        return voices[0].id  

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
tts_engine = SpanishTTS()

def extraer_texto(archivo):
    try:
        texto = ""
        filename = secure_filename(archivo.filename)
        extension = filename.split('.')[-1].lower()
        temp_path = os.path.join(UPLOAD_FOLDER, filename)

        archivo.save(temp_path)

        if extension == 'pdf':
            with pdfplumber.open(temp_path) as pdf:
                for pagina in pdf.pages:
                    texto_extraido = pagina.extract_text(x_tolerance=1, y_tolerance=1)
                    if texto_extraido:
                        texto += "\n".join(
                            line for line in texto_extraido.split('\n')
                            if not (line.startswith('http') or line.startswith('www.'))
                        ) + "\n"

        elif extension == 'docx':
            doc = docx.Document(temp_path)
            for parrafo in doc.paragraphs:
                texto_parrafo = parrafo.text.strip()
                if texto_parrafo and not (
                    texto_parrafo.startswith('http') or
                    texto_parrafo.startswith('www.')
                ):
                    texto += texto_parrafo + "\n"

        if os.path.exists(temp_path):
            os.remove(temp_path)

        return texto.strip()

    except Exception as e:
        status.update(error=f"Error al extraer texto: {str(e)}")
        return ""

def convertir_texto_a_audio(texto, nombre_archivo):
    try:
        safe_name = secure_filename(nombre_archivo)
        output_path = os.path.join(AUDIO_FOLDER, safe_name)

        if os.path.exists(output_path):
            os.remove(output_path)

        max_chunk_size = 3000 
        chunks = [texto[i:i+max_chunk_size] for i in range(0, len(texto), max_chunk_size)]

        if len(chunks) > 1:
            temp_files = []
            for i, chunk in enumerate(chunks):
                temp_file = os.path.join(AUDIO_FOLDER, f"temp_{i}_{safe_name}")
                if not tts_engine.convert_to_speech(chunk, temp_file):
                    raise Exception(f"Error procesando parte {i+1}")
                temp_files.append(temp_file)
                status.update(progress=int((i + 1) / len(chunks) * 80))

            with open(output_path, 'wb') as outfile:
                for temp_file in temp_files:
                    with open(temp_file, 'rb') as infile:
                        outfile.write(infile.read())
                    os.remove(temp_file)
        else:
            if not tts_engine.convert_to_speech(texto, output_path):
                raise Exception("Error en conversión directa")

        status.update(progress=100, ready=True)
        return True

    except Exception as e:
        status.update(error=str(e), progress=0)
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
            status.update(progress=0, ready=False, error=None, filename=None)

            texto = extraer_texto(file)
            if not texto:
                return jsonify({'error': 'No se pudo extraer texto del archivo'}), 400

            output_name = f"{os.path.splitext(secure_filename(file.filename))[0]}.mp3"
            status.update(filename=output_name)

            thread = threading.Thread(
                target=convertir_texto_a_audio,
                args=(texto, output_name)
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
    app.run(debug=True)