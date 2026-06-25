import re
import time
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
import serial
import streamlit as st
from google import genai
from serial.tools import list_ports


# ==========================================================
# App Streamlit: Monitor DHT11 + Tutor IA Gemini
# Autor: plantilla generada para lectura serial Arduino
# ==========================================================

st.set_page_config(
    page_title="Monitor DHT11 en tiempo real",
    page_icon="🌡️",
    layout="wide",
)

APP_CONTEXT = """
Esta aplicación Streamlit lee datos de temperatura y humedad enviados por Arduino
mediante el puerto serial. Está pensada para un sensor DHT11 cuyo Arduino imprime
líneas como:

Temperatura:25.0\tHumedad:60.0

También intenta interpretar formatos como:
Humedad: 60.0 %\tTemperatura: 25.0 °C
25.0,60.0
25.0 60.0

Componentes principales:
- Arduino UNO o compatible.
- Sensor DHT11 conectado al pin digital 2.
- Comunicación serial, típicamente a 9600 baudios.
- Python con Streamlit, pyserial, pandas y google-genai.
"""


def init_state() -> None:
    """Inicializa variables persistentes de la sesión."""
    defaults = {
        "serial_conn": None,
        "connected": False,
        "running": False,
        "data": [],
        "raw_lines": [],
        "t0": time.time(),
        "last_error": "",
        "chat_history": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def available_ports() -> list[str]:
    """Devuelve una lista de puertos seriales detectados."""
    ports = []
    for port in list_ports.comports():
        description = f"{port.device} — {port.description}"
        ports.append(description)
    return ports


def extract_port_device(port_label: str) -> str:
    """Extrae el nombre real del puerto desde la etiqueta mostrada en UI."""
    return port_label.split(" — ")[0].strip()


def to_float(value: str) -> float:
    """Convierte un texto numérico a float aceptando coma decimal."""
    return float(value.replace(",", "."))


def parse_dht_line(line: str) -> Optional[Tuple[float, float]]:
    """
    Interpreta una línea serial y regresa:
        (temperatura_C, humedad_pct)

    Soporta formatos etiquetados y formatos simples con dos números.
    """
    clean = line.strip()
    if not clean:
        return None

    number = r"[-+]?\d+(?:[\.,]\d+)?"

    temp_match = re.search(
        rf"(?:temperatura|temperature|temp|t)\s*[:=]\s*({number})",
        clean,
        flags=re.IGNORECASE,
    )
    hum_match = re.search(
        rf"(?:humedad|humidity|hum|h)\s*[:=]\s*({number})",
        clean,
        flags=re.IGNORECASE,
    )

    if temp_match and hum_match:
        temperatura = to_float(temp_match.group(1))
        humedad = to_float(hum_match.group(1))
        return temperatura, humedad

    # Formato alternativo: "25.0,60.0" o "25.0 60.0"
    values = re.findall(number, clean)
    if len(values) >= 2:
        temperatura = to_float(values[0])
        humedad = to_float(values[1])
        return temperatura, humedad

    return None


def connect_serial(port: str, baudrate: int) -> None:
    """Abre la conexión serial."""
    try:
        conn = serial.Serial(port=port, baudrate=baudrate, timeout=0.1)
        time.sleep(2)  # Arduino suele reiniciarse al abrir el puerto serial.
        conn.reset_input_buffer()

        st.session_state.serial_conn = conn
        st.session_state.connected = True
        st.session_state.running = True
        st.session_state.last_error = ""
        st.session_state.t0 = time.time()
    except Exception as exc:
        st.session_state.connected = False
        st.session_state.running = False
        st.session_state.serial_conn = None
        st.session_state.last_error = f"No se pudo abrir el puerto {port}: {exc}"


def disconnect_serial() -> None:
    """Cierra la conexión serial si está abierta."""
    conn = st.session_state.get("serial_conn")
    try:
        if conn is not None and conn.is_open:
            conn.close()
    except Exception:
        pass

    st.session_state.serial_conn = None
    st.session_state.connected = False
    st.session_state.running = False


def read_serial_data(max_lines: int, max_points: int) -> None:
    """Lee líneas disponibles del puerto serial y actualiza el historial."""
    conn = st.session_state.get("serial_conn")
    if conn is None or not st.session_state.connected:
        return

    if not conn.is_open:
        st.session_state.connected = False
        st.session_state.running = False
        st.session_state.last_error = "El puerto serial se cerró inesperadamente."
        return

    lines_read = 0
    while lines_read < max_lines:
        try:
            if conn.in_waiting <= 0:
                break

            raw = conn.readline()
            line = raw.decode("utf-8", errors="ignore").strip()
            lines_read += 1

            if not line:
                continue

            st.session_state.raw_lines.append(line)
            st.session_state.raw_lines = st.session_state.raw_lines[-10:]

            parsed = parse_dht_line(line)
            if parsed is None:
                continue

            temperatura, humedad = parsed
            now = datetime.now()
            elapsed = time.time() - st.session_state.t0

            st.session_state.data.append(
                {
                    "fecha_hora": now,
                    "tiempo_s": round(elapsed, 2),
                    "temperatura_C": round(temperatura, 2),
                    "humedad_pct": round(humedad, 2),
                    "linea_serial": line,
                }
            )
            st.session_state.data = st.session_state.data[-max_points:]
            st.session_state.last_error = ""

        except Exception as exc:
            st.session_state.last_error = f"Error leyendo el puerto serial: {exc}"
            break


def build_ai_prompt(user_question: str, df: pd.DataFrame) -> str:
    """Construye el prompt para el tutor IA."""
    if df.empty:
        last_data = "No hay datos válidos registrados todavía."
    else:
        last = df.iloc[-1]
        last_data = (
            f"Última lectura: temperatura={last['temperatura_C']} °C, "
            f"humedad={last['humedad_pct']} %, "
            f"tiempo={last['tiempo_s']} s."
        )

    return f"""
Eres un tutor de IA experto en este software de monitoreo ambiental con Arduino,
DHT11, comunicación serial, Python, Streamlit, pyserial y Gemini.

Objetivo del tutor:
- Ayudar al usuario a entender, depurar y mejorar la app.
- Explicar errores comunes de lectura serial, puertos COM, baudios, formato de datos y conexión del DHT11.
- Dar respuestas didácticas, claras y accionables.
- No inventar valores de medición. Usa únicamente los datos disponibles.
- No solicites ni repitas la API key del usuario.

Contexto técnico de la app:
{APP_CONTEXT}

Estado actual:
- Conectado: {st.session_state.connected}
- Adquisición activa: {st.session_state.running}
- Número de datos en memoria: {len(st.session_state.data)}
- {last_data}

Pregunta del usuario:
{user_question}
"""


init_state()

st.title("🌡️ Monitor DHT11 en tiempo real con Streamlit")
st.caption("Lectura de temperatura y humedad ambiental desde Arduino vía puerto serial.")

with st.sidebar:
    st.header("⚙️ Configuración serial")

    detected_ports = available_ports()
    port_options = detected_ports if detected_ports else ["No se detectaron puertos"]
    selected_label = st.selectbox("Puerto detectado", port_options)
    manual_port = st.text_input("Puerto manual opcional", placeholder="Ej. COM3, /dev/ttyUSB0, /dev/ttyACM0")

    baudrate = st.selectbox("Baudios", [9600, 19200, 38400, 57600, 115200], index=0)
    max_points = st.slider("Puntos máximos en memoria", min_value=50, max_value=2000, value=300, step=50)
    max_lines = st.slider("Líneas máximas por actualización", min_value=1, max_value=50, value=10)

    port_to_use = manual_port.strip() if manual_port.strip() else extract_port_device(selected_label)

    col_connect, col_disconnect = st.columns(2)
    with col_connect:
        if st.button("Conectar", use_container_width=True, disabled=st.session_state.connected):
            if port_to_use and port_to_use != "No se detectaron puertos":
                connect_serial(port_to_use, baudrate)
                st.rerun()
            else:
                st.session_state.last_error = "Selecciona o escribe un puerto serial válido."

    with col_disconnect:
        if st.button("Desconectar", use_container_width=True, disabled=not st.session_state.connected):
            disconnect_serial()
            st.rerun()

    if st.session_state.connected:
        st.success(f"Conectado a {port_to_use}")
    else:
        st.info("Sin conexión serial")

    st.divider()
    st.header("▶️ Adquisición")

    if st.session_state.connected:
        if st.button("Pausar/Reanudar", use_container_width=True):
            st.session_state.running = not st.session_state.running
            st.rerun()

    if st.button("Limpiar datos", use_container_width=True):
        st.session_state.data = []
        st.session_state.raw_lines = []
        st.session_state.t0 = time.time()
        st.rerun()

    st.write("Estado:", "🟢 Activa" if st.session_state.running else "⏸️ Pausada")

    st.divider()
    st.header("🤖 Tutor IA")
    ai_enabled = st.toggle("Activar tutor con Gemini", value=False)
    gemini_api_key = ""
    gemini_model = "gemini-2.5-flash"

    if ai_enabled:
        gemini_api_key = st.text_input("Gemini API key", type="password", help="La clave se usa solo durante esta sesión.")
        gemini_model = st.text_input("Modelo Gemini", value="gemini-2.5-flash")

if st.session_state.last_error:
    st.error(st.session_state.last_error)

status_col1, status_col2, status_col3 = st.columns(3)
with status_col1:
    st.metric("Conexión", "Activa" if st.session_state.connected else "Inactiva")
with status_col2:
    st.metric("Adquisición", "Corriendo" if st.session_state.running else "Pausada")
with status_col3:
    st.metric("Datos válidos", len(st.session_state.data))


@st.fragment(run_every="1s")
def live_panel(max_lines_fragment: int, max_points_fragment: int) -> None:
    """Panel que se actualiza automáticamente cada segundo."""
    if st.session_state.connected and st.session_state.running:
        read_serial_data(max_lines=max_lines_fragment, max_points=max_points_fragment)

    df = pd.DataFrame(st.session_state.data)

    if df.empty:
        st.warning("Aún no hay datos válidos. Verifica que Arduino esté enviando: Temperatura:25.0\\tHumedad:60.0")
    else:
        last = df.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("Temperatura", f"{last['temperatura_C']:.2f} °C")
        c2.metric("Humedad relativa", f"{last['humedad_pct']:.2f} %")
        c3.metric("Tiempo", f"{last['tiempo_s']:.1f} s")

        chart_df = df.set_index("tiempo_s")[["temperatura_C", "humedad_pct"]]
        st.subheader("Gráfica en tiempo real")
        st.line_chart(chart_df)

        with st.expander("Ver tabla de datos"):
            st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Descargar datos CSV",
            data=csv,
            file_name="datos_dht11.csv",
            mime="text/csv",
        )

    with st.expander("Últimas líneas seriales recibidas"):
        if st.session_state.raw_lines:
            st.code("\n".join(st.session_state.raw_lines), language="text")
        else:
            st.write("No se han recibido líneas seriales.")


live_panel(max_lines, max_points)

st.divider()
st.subheader("Formato recomendado del código Arduino")
st.code(
    'Serial.print("Temperatura:");\n'
    'Serial.print(temperatura);\n'
    'Serial.print("\\t");\n'
    'Serial.print("Humedad:");\n'
    'Serial.println(humedad);',
    language="cpp",
)

if ai_enabled:
    st.divider()
    st.subheader("🤖 Tutor IA experto en el software")

    if not gemini_api_key:
        st.info("Ingresa tu Gemini API key en la barra lateral para activar el tutor.")
    else:
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        user_question = st.chat_input("Pregúntale al tutor sobre Arduino, DHT11, Streamlit, errores seriales o mejoras del software...")

        if user_question:
            st.session_state.chat_history.append({"role": "user", "content": user_question})
            with st.chat_message("user"):
                st.markdown(user_question)

            with st.chat_message("assistant"):
                with st.spinner("Consultando a Gemini..."):
                    try:
                        client = genai.Client(api_key=gemini_api_key)
                        df_current = pd.DataFrame(st.session_state.data)
                        prompt = build_ai_prompt(user_question, df_current)
                        response = client.models.generate_content(
                            model=gemini_model,
                            contents=prompt,
                        )
                        answer = response.text or "No se recibió respuesta del modelo."
                    except Exception as exc:
                        answer = f"Ocurrió un error al consultar Gemini: {exc}"

                    st.markdown(answer)
                    st.session_state.chat_history.append({"role": "assistant", "content": answer})

st.divider()
st.caption(
    "Sugerencia: cierra el Monitor Serial o Serial Plotter del IDE de Arduino antes de conectar esta app, "
    "porque dos programas no pueden usar el mismo puerto serial al mismo tiempo."
)
