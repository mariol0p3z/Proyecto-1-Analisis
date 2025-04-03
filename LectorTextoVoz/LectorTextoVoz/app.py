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

# Configuración de directorios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
AUDIO_FOLDER = os.path.join(BASE_DIR, "audios")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

class SpanishTTS:
    def __init__(self):
        self.engine = self._init_local_engine()
        self.gtts_fallback = False  # Bandera para usar gTTS como fallback

    def _init_local_engine(self):
        """Configura específicamente una voz en español para pyttsx3 con más opciones"""
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            
            # Patrones para identificar voces en español
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
                
                # Verificar si la voz es en español
                if any(re.search(pattern, voice_id) or re.search(pattern, voice_name) 
                      for pattern in spanish_patterns):
                    spanish_voices.append(voice)
                    print(f"Voz en español encontrada: {voice.name} - ID: {voice.id}")
            
            if spanish_voices:
                # Seleccionar la primera voz en español encontrada
                selected_voice = spanish_voices[0]
                engine.setProperty('voice', selected_voice.id)
                print(f"Voz seleccionada: {selected_voice.name}")
                
                # Configurar parámetros para mejor calidad
                engine.setProperty('rate', 150)  # Velocidad moderada
                engine.setProperty('volume', 0.9)  # Volumen alto
                return engine
            else:
                print("No se encontraron voces en español. Se usará gTTS como fallback.")
                self.gtts_fallback = True
                return None
                
        except Exception as e:
            print(f"No se pudo inicializar el motor local: {e}")
            self.gtts_fallback = True
            return None

    def _force_spanish_gtts(self, text, output_file):
        """Método reforzado para gTTS en español con múltiples intentos"""
        # Lista de dominios regionales para español
        tld_options = ['com.mx', 'es', 'com.ar', 'com.co', 'com']
        
        for tld in tld_options:
            try:
                tts = gTTS(text=text, lang='es', tld=tld)
                tts.save(output_file)
                
                # Verificación adicional del archivo generado
                with open(output_file, 'rb') as f:
                    content = f.read(1000)
                    if b'lang: es' in content or b'lang:es' in content:
                        return True
                    elif b'lang: en' in content:
                        print(f"gTTS generó inglés con tld={tld}, intentando siguiente opción...")
                        continue
                
                # Si el archivo tiene contenido válido
                if os.path.getsize(output_file) > 1024:  # Tamaño mínimo razonable
                    return True
                    
            except Exception as e:
                print(f"Error con gTTS (tld={tld}): {e}")
                continue
                
        return False

    def convert_to_speech(self, text, output_file):
        """Conversión a audio EN ESPAÑOL con múltiples estrategias"""
        if not text.strip():
            print("Texto vacío, no se puede convertir")
            return False
            
        # Primero intentar con gTTS (mejor calidad en español)
        print("Intentando con gTTS...")
        if self._force_spanish_gtts(text, output_file):
            print("gTTS generó archivo en español correctamente")
            return True
        
        # Si gTTS falla, intentar con motor local si está disponible
        if self.engine and not self.gtts_fallback:
            print("Fallo con gTTS, intentando con motor local...")
            try:
                # Limpiar archivo de salida por si acaso
                if os.path.exists(output_file):
                    os.remove(output_file)
                
                self.engine.save_to_file(text, output_file)
                self.engine.runAndWait()
                
                # Verificar que se creó el archivo
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    return True
            except Exception as e:
                print(f"Error con motor local: {e}")
        
        # Último recurso: forzar gTTS aunque haya fallado antes
        print("Intentando forzar gTTS como último recurso...")
        return self._force_spanish_gtts(text, output_file)

    def _get_spanish_voice_id(self):
        """Obtiene la primera voz en español disponible"""
        voices = self.engine.getProperty('voices')
        for voice in voices:
            if 'spanish' in voice.name.lower() or 'español' in voice.name.lower() or 'es' in voice.id.lower():
                return voice.id
        return voices[0].id  # Si no encuentra, usa la primera disponible

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
tts_engine = SpanishTTS()

def extraer_texto(archivo):
    try:
        texto = ""
        filename = secure_filename(archivo.filename)
        extension = filename.split('.')[-1].lower()
        temp_path = os.path.join(UPLOAD_FOLDER, filename)

        # Guardar archivo temporalmente
        archivo.save(temp_path)

        if extension == 'pdf':
            with pdfplumber.open(temp_path) as pdf:
                for pagina in pdf.pages:
                    texto_extraido = pagina.extract_text(x_tolerance=1, y_tolerance=1)
                    if texto_extraido:
                        # Filtrar líneas que parecen URLs
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

        # Limpiar archivo temporal
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

        # Dividir texto en partes más pequeñas para mejor manejo
        max_chunk_size = 3000  # gTTS tiene límite de ~5000 caracteres
        chunks = [texto[i:i+max_chunk_size] for i in range(0, len(texto), max_chunk_size)]

        if len(chunks) > 1:
            # Procesar cada chunk por separado
            temp_files = []
            for i, chunk in enumerate(chunks):
                temp_file = os.path.join(AUDIO_FOLDER, f"temp_{i}_{safe_name}")
                if not tts_engine.convert_to_speech(chunk, temp_file):
                    raise Exception(f"Error procesando parte {i+1}")
                temp_files.append(temp_file)
                status.update(progress=int((i + 1) / len(chunks) * 80))

            # Combinar archivos
            with open(output_path, 'wb') as outfile:
                for temp_file in temp_files:
                    with open(temp_file, 'rb') as infile:
                        outfile.write(infile.read())
                    os.remove(temp_file)
        else:
            # Texto pequeño, procesar directamente
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
            # Reiniciar estado
            status.update(progress=0, ready=False, error=None, filename=None)

            # Extraer texto
            texto = extraer_texto(file)
            if not texto:
                return jsonify({'error': 'No se pudo extraer texto del archivo'}), 400

            # Preparar nombre de archivo de salida
            output_name = f"{os.path.splitext(secure_filename(file.filename))[0]}.mp3"
            status.update(filename=output_name)

            # Iniciar conversión en segundo plano
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
    # Verificación de voces al iniciar
    print("=== Verificación de voz en español ===")
    test_text = "Esta es una prueba de voz en español"
    test_file = os.path.join(AUDIO_FOLDER, "test_spanish.mp3")

    # Asegurar que el directorio de audios existe
    os.makedirs(AUDIO_FOLDER, exist_ok=True)

    if tts_engine.convert_to_speech(test_text, test_file):
        print(f"✓ Voz en español configurada correctamente. Archivo de prueba en: {test_file}")
    else:
        print("✗ No se pudo configurar voz en español. Revise los requisitos.")

    app.run(debug=True)