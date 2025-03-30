# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, send_file
import os
import pdfplumber
import docx
from gtts import gTTS

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "audios"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

def convertir_texto_a_audio(texto, nombre_archivo):
    tts = gTTS(texto, lang="es")
    ruta_audio = os.path.join(AUDIO_FOLDER, nombre_archivo)
    tts.save(ruta_audio)
    return ruta_audio

def extraer_texto(archivo):
    extension = archivo.filename.split(".")[-1].lower()
    ruta_archivo = os.path.join(UPLOAD_FOLDER, archivo.filename)
    archivo.save(ruta_archivo)

    texto = ""
    if extension == "pdf":
        with pdfplumber.open(ruta_archivo) as pdf:
            for pagina in pdf.pages:
                # Extraer texto línea por línea para evitar que solo se lean enlaces
                texto_extraido = pagina.extract_text(x_tolerance=1, y_tolerance=1)
                if texto_extraido:
                    texto += "\n".join([line for line in texto_extraido.split("\n") if not line.startswith("http")]) + "\n"
    elif extension == "docx":
        doc = docx.Document(ruta_archivo)
        for parrafo in doc.paragraphs:
            if not parrafo.text.startswith("http"):
                texto += parrafo.text + "\n"

    return texto.strip()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        archivo = request.files["archivo"]
        if archivo:
            texto = extraer_texto(archivo)
            if texto:
                nombre_audio = archivo.filename.split(".")[0] + ".mp3"
                ruta_audio = convertir_texto_a_audio(texto, nombre_audio)
                return send_file(ruta_audio, as_attachment=True)
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)



 